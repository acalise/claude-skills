#!/usr/bin/env python3
"""
Kinetic Typography Lyrics Video Generator

Takes an MP3 file, transcribes it with Whisper, and renders a kinetic
typography video with text effects, particles, glow, and optional
background image.

Usage:
    python kinetic.py song.mp3
    python kinetic.py song.mp3 --colors "#fff,#ff6b35,#5b9cf5"
    python kinetic.py song.mp3 --resolution youtube --bg cover.jpg
"""

import os
import sys
import math
import random
import argparse
import textwrap
import re
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# -- Resolution presets --------------------------------------------------------

RESOLUTIONS = {
    "tiktok": (1080, 1920),
    "youtube": (1920, 1080),
    "square": (1080, 1080),
}

FPS = 30


# -- Font discovery ------------------------------------------------------------

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Impact.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def find_font():
    """Return the first available font path from our candidate list."""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    # Last resort: let Pillow try a default
    return "arial"


MAIN_FONT = find_font()


# -- Color parsing -------------------------------------------------------------

def parse_hex_color(hex_str):
    """Parse a hex color string like '#fff' or '#ff6b35' into an RGB tuple."""
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_str}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def parse_color_list(color_str):
    """Parse a comma-separated list of hex colors."""
    parts = [c.strip() for c in color_str.split(",") if c.strip()]
    return [parse_hex_color(c) for c in parts]


# -- Whisper transcription (Step 1) -------------------------------------------

def transcribe_audio(audio_path, model_name="base"):
    """Transcribe audio using Whisper and return word-level timestamps."""
    print(f"  Step 1/4: Loading Whisper ({model_name})...")
    import whisper
    model = whisper.load_model(model_name)

    print(f"  Step 1/4: Transcribing...")
    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
    )

    # Flatten all word-level data from segments
    words = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            words.append({
                "word": word_info["word"].strip(),
                "start": word_info["start"],
                "end": word_info["end"],
            })

    print(f"  Step 1/4: Done - {len(words)} words detected.")
    return words


# -- Phrase grouping (Step 2) --------------------------------------------------

# Punctuation that triggers a phrase break when it appears at the end of a word
PHRASE_BREAK_PUNCT = re.compile(r"[.!?,;:]$")

# Minimum gap between words (in seconds) that triggers a new phrase
PAUSE_THRESHOLD = 0.25

# Maximum words per phrase
MAX_WORDS_PER_PHRASE = 4

# Minimum phrase duration in seconds
MIN_PHRASE_DURATION = 0.5


def group_words_into_phrases(words):
    """
    Group transcribed words into display phrases based on pauses,
    punctuation, and max word count. Each phrase gets timing that
    extends to fill the gap before the next phrase.
    """
    if not words:
        return []

    # Build raw phrase groups
    raw_phrases = []
    current_group = [words[0]]

    for i in range(1, len(words)):
        prev = words[i - 1]
        curr = words[i]

        gap = curr["start"] - prev["end"]
        ends_with_punct = bool(PHRASE_BREAK_PUNCT.search(prev["word"]))
        group_full = len(current_group) >= MAX_WORDS_PER_PHRASE

        if gap > PAUSE_THRESHOLD or ends_with_punct or group_full:
            raw_phrases.append(current_group)
            current_group = [curr]
        else:
            current_group.append(curr)

    if current_group:
        raw_phrases.append(current_group)

    # Convert groups into timed phrases, extending each to fill dead time
    phrases = []
    for idx, group in enumerate(raw_phrases):
        text = " ".join(w["word"] for w in group)
        start = group[0]["start"]
        natural_end = group[-1]["end"]

        # Extend to the start of the next phrase (no dead time)
        if idx < len(raw_phrases) - 1:
            next_start = raw_phrases[idx + 1][0]["start"]
            end = next_start
        else:
            end = natural_end

        # Enforce minimum duration
        if end - start < MIN_PHRASE_DURATION:
            end = start + MIN_PHRASE_DURATION

        phrases.append({
            "text": text,
            "start": start,
            "end": end,
        })

    print(f"  Step 2/4: Grouped into {len(phrases)} phrases.")
    return phrases


# -- Background builder --------------------------------------------------------

def load_bg_image(path, width, height):
    """Load and scale a single background image to fill the frame."""
    img = Image.open(path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = width / height
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_h = height
        new_w = int(src_w * height / src_h)
    else:
        new_w = width
        new_h = int(src_h * width / src_w)
    # Scale up a bit extra for Ken Burns headroom
    new_w = int(new_w * 1.15)
    new_h = int(new_h * 1.15)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    return img


def apply_ken_burns(img, width, height, t_frac, image_index):
    """
    Apply Ken Burns effect: slow zoom + slight pan.
    t_frac is 0-1 progress through this image's display time.
    Each image gets a different pan direction based on its index.
    """
    src_w, src_h = img.size
    # Zoom from 1.0 to 1.08
    zoom = 1.0 + 0.08 * t_frac
    crop_w = int(width / zoom)
    crop_h = int(height / zoom)

    # Pan direction varies per image
    directions = [(0.3, 0.3), (-0.3, 0.3), (0.3, -0.3), (-0.3, -0.3)]
    dx_dir, dy_dir = directions[image_index % len(directions)]

    cx = src_w // 2 + int(dx_dir * (src_w - crop_w) * t_frac)
    cy = src_h // 2 + int(dy_dir * (src_h - crop_h) * t_frac)

    left = max(0, cx - crop_w // 2)
    top = max(0, cy - crop_h // 2)
    right = min(src_w, left + crop_w)
    bottom = min(src_h, top + crop_h)

    cropped = img.crop((left, top, right, bottom))
    return cropped.resize((width, height), Image.BILINEAR)


def build_vignette(width, height):
    """Build a reusable vignette mask as a float array."""
    vignette = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vignette)
    cx, cy = width // 2, height // 2
    steps = 80
    for i in range(steps, 0, -1):
        frac = i / steps
        rx = int(cx * 2 * frac)
        ry = int(cy * 2 * frac)
        brightness = int(255 * (1 - frac ** 1.4))
        vdraw.ellipse([cx - rx // 2, cy - ry // 2, cx + rx // 2, cy + ry // 2], fill=brightness)

    vig_arr = np.array(vignette, dtype=np.float32) / 255.0
    # 3-channel version
    vig_3 = np.stack([vig_arr] * 3, axis=-1)
    return 0.45 + 0.55 * vig_3


def build_bg_frame_at_time(t, duration, bg_images, width, height, vignette_factor):
    """
    Build a background frame at time t. Handles multiple images with
    Ken Burns zoom/pan and cross-dissolve transitions.
    """
    if not bg_images:
        return np.zeros((height, width, 3), dtype=np.uint8)

    n = len(bg_images)
    seg_dur = duration / n
    dissolve_dur = min(1.0, seg_dur * 0.15)  # 15% of segment or 1s max

    # Which image segment are we in?
    seg_idx = min(int(t / seg_dur), n - 1)
    seg_t = t - seg_idx * seg_dur
    seg_frac = seg_t / seg_dur

    # Render current image with Ken Burns
    current = apply_ken_burns(bg_images[seg_idx], width, height, seg_frac, seg_idx)

    # Cross-dissolve into next image near the end of segment
    if seg_idx < n - 1 and seg_t > seg_dur - dissolve_dur:
        next_idx = seg_idx + 1
        next_frac = 0.0  # start of next image
        next_img = apply_ken_burns(bg_images[next_idx], width, height, next_frac, next_idx)
        blend_t = (seg_t - (seg_dur - dissolve_dur)) / dissolve_dur
        current = Image.blend(current, next_img, alpha=blend_t)

    # Darken
    overlay = Image.new("RGB", (width, height), (0, 0, 0))
    current = Image.blend(current, overlay, alpha=0.6)

    # Apply vignette
    arr = np.array(current, dtype=np.float32)
    arr = np.clip(arr * vignette_factor, 0, 255).astype(np.uint8)

    return arr


# -- Particle system -----------------------------------------------------------

class Particle:
    """A small floating particle that drifts upward."""

    def __init__(self, width, height, rng):
        self.width = width
        self.height = height
        self.rng = rng
        self.reset()

    def reset(self):
        self.x = self.rng.uniform(0, self.width)
        self.y = self.rng.uniform(0, self.height)
        self.vx = self.rng.uniform(-0.3, 0.3)
        self.vy = self.rng.uniform(-0.6, -0.2)
        self.size = self.rng.uniform(1.0, 3.0)
        self.alpha = self.rng.uniform(0.1, 0.4)
        self.life = self.rng.uniform(0.0, 1.0)

    def update(self, dt=1.0 / FPS):
        self.x += self.vx
        self.y += self.vy
        self.life += dt * 0.15
        if self.y < -10 or self.life > 1.0:
            self.reset()
            self.y = self.height + 5


# -- Easing functions ----------------------------------------------------------

def ease_out_cubic(t):
    """Cubic ease-out: fast start, smooth stop."""
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    """Cubic ease-in: smooth start, fast stop."""
    return t ** 3


# -- Text rendering helpers ----------------------------------------------------

def word_wrap_text(text, font, max_width):
    """
    Wrap text so each line fits within max_width pixels.
    Returns a list of lines.
    """
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test = (current_line + " " + word).strip() if current_line else word
        bb = font.getbbox(test)
        w = bb[2] - bb[0]
        if w > max_width and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def fit_font_size(lines, font_path, max_size, max_width):
    """
    Find the largest font size (up to max_size) where no line exceeds max_width.
    Returns (font, line_widths, line_heights).
    """
    size = max_size
    while size >= 24:
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            size -= 4
            continue
        widths = []
        heights = []
        ok = True
        for ln in lines:
            bb = font.getbbox(ln)
            w = bb[2] - bb[0]
            h = bb[3] - bb[1]
            if w > max_width:
                ok = False
                break
            widths.append(w)
            heights.append(h)
        if ok:
            return font, widths, heights
        size -= 4

    # Fallback to minimum size
    font = ImageFont.truetype(font_path, 24)
    widths, heights = [], []
    for ln in lines:
        bb = font.getbbox(ln)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    return font, widths, heights


def draw_glow_fast(img, lines_data, font, color, alpha, glow_radius=18, width=1080, height=1920):
    """
    Draw a glow behind text using a blur approach (much faster than offset copies).
    Renders all text lines to a separate layer, blurs it, then composites.
    lines_data is a list of (text, x, y) tuples.
    """
    r, g, b = color
    glow_color = (min(255, r + 60), min(255, g + 60), min(255, b + 60))
    bright = int(255 * min(1.0, alpha * 0.9))

    # Render text to a separate RGBA layer
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    for text, x, y in lines_data:
        glow_draw.text((x, y), text, font=font, fill=(glow_color[0], glow_color[1], glow_color[2], bright))

    # Blur the layer
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=glow_radius))

    # Composite onto the main image
    img.paste(Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 0)), glow_layer), (0, 0), glow_layer)


# -- Main video renderer -------------------------------------------------------

def render_video(phrases, audio_path, output_path, colors, width, height,
                 bg_image_path, font_size_base, text_position="center",
                 pop_words=0):
    """
    Render the kinetic typography video using MoviePy with a per-frame callback.

    text_position: "center", "upper", or a float 0.0-1.0 for vertical position.
                   "upper" places text at ~30% from top (safe zone above YT Shorts buttons).
    pop_words: if > 0, splits each phrase into chunks of N words that pop on screen
               one group at a time with a scale animation. 0 = classic full-phrase mode.
    """
    from moviepy import AudioFileClip, VideoClip

    print(f"  Step 3/4: Loading audio...")
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Load background images
    bg_images = []
    if bg_image_path:
        paths = [p.strip() for p in bg_image_path.split(",") if p.strip()]
        for p in paths:
            if os.path.isfile(p):
                print(f"  Step 3/4: Loading background: {os.path.basename(p)}")
                bg_images.append(load_bg_image(p, width, height))
            else:
                print(f"  Warning: Background image not found: {p}")

    has_bg = len(bg_images) > 0
    vignette_factor = build_vignette(width, height)

    # For no-bg mode, pre-build a static black frame with vignette
    if not has_bg:
        black = np.zeros((height, width, 3), dtype=np.float32)
        static_bg = np.clip(black * vignette_factor, 0, 255).astype(np.uint8)

    # Initialize particles
    rng = random.Random(42)
    particles = [Particle(width, height, rng) for _ in range(60)]

    # Compute safe text area (82% of frame width)
    margin = int(width * 0.09)
    max_text_width = width - margin * 2

    # Scale glow radius based on resolution
    base_glow = int(24 * (width / 1080))

    # Map font_size_base (default 100) to actual pixel size.
    # 100 maps to roughly 120px at 1080 width, scale proportionally.
    actual_font_max = int(font_size_base * 1.2 * (width / 1080))

    # Timing constants for fade
    FADE_DURATION = 0.15

    # Resolve text vertical position
    if text_position == "center":
        text_y_frac = 0.5
    elif text_position == "upper":
        text_y_frac = 0.30
    elif isinstance(text_position, (int, float)):
        text_y_frac = float(text_position)
    else:
        text_y_frac = 0.5

    # Pre-split phrases into word-pop sub-phrases if pop_words > 0
    if pop_words > 0:
        pop_phrases = []
        for phrase in phrases:
            words = phrase["text"].split()
            n_chunks = max(1, math.ceil(len(words) / pop_words))
            chunk_dur = (phrase["end"] - phrase["start"]) / n_chunks
            for ci in range(n_chunks):
                chunk_words = words[ci * pop_words : (ci + 1) * pop_words]
                pop_phrases.append({
                    "text": " ".join(chunk_words),
                    "start": phrase["start"] + ci * chunk_dur,
                    "end": phrase["start"] + (ci + 1) * chunk_dur,
                })
        phrases = pop_phrases
        print(f"  Pop-words mode: {len(phrases)} sub-phrases ({pop_words} words each)")

    # Track frame count for progress display
    total_frames = int(duration * FPS)
    render_start = [None]
    last_pct = [-1]

    def get_current_phrase(t):
        """Find the active phrase at time t."""
        for phrase in phrases:
            if phrase["start"] <= t < phrase["end"]:
                return phrase
        return None

    def make_frame(t):
        """Render a single frame at time t."""
        if render_start[0] is None:
            render_start[0] = time.time()

        frame_num = int(t * FPS)
        pct = int(100 * frame_num / max(total_frames, 1))
        if pct != last_pct[0]:
            last_pct[0] = pct
            elapsed_s = time.time() - render_start[0]
            if pct > 0:
                eta_s = elapsed_s / pct * (100 - pct)
                eta_m, eta_sec = int(eta_s // 60), int(eta_s % 60)
                bar = "=" * (pct // 4) + ">" + " " * (25 - pct // 4)
                print(f"\r  [{bar}] {pct}%  ETA {eta_m}:{eta_sec:02d}  ", end="", flush=True)

        # -- Background --
        if has_bg:
            frame_base = build_bg_frame_at_time(t, duration, bg_images, width, height, vignette_factor)
        else:
            frame_base = static_bg.copy()

        img = Image.fromarray(frame_base).convert("RGBA")
        draw = ImageDraw.Draw(img)

        # -- Particles --
        current_phrase = get_current_phrase(t)
        phrase_color = (255, 255, 255)
        if current_phrase is not None:
            phrase_idx = phrases.index(current_phrase)
            phrase_color = colors[phrase_idx % len(colors)]

        for p in particles:
            p.update()
            fade = 1 - p.life
            pr = int(phrase_color[0] * p.alpha * fade)
            pg = int(phrase_color[1] * p.alpha * fade)
            pb = int(phrase_color[2] * p.alpha * fade)
            pr = max(0, min(255, pr))
            pg = max(0, min(255, pg))
            pb = max(0, min(255, pb))
            ix, iy = int(p.x), int(p.y)
            s = max(1, int(p.size))
            draw.ellipse([ix - s, iy - s, ix + s, iy + s], fill=(pr, pg, pb))

        # -- Text rendering --
        if current_phrase is not None:
            phrase_idx = phrases.index(current_phrase)
            color = colors[phrase_idx % len(colors)]
            text = current_phrase["text"].rstrip(",").upper()
            start = current_phrase["start"]
            end = current_phrase["end"]
            phrase_dur = end - start
            elapsed = t - start

            # Get a font at the target size for word wrapping
            try:
                wrap_font = ImageFont.truetype(MAIN_FONT, actual_font_max)
            except Exception:
                wrap_font = ImageFont.load_default()

            lines = word_wrap_text(text, wrap_font, max_text_width)

            # Fit font to ensure all lines stay within bounds
            font, line_widths, line_heights = fit_font_size(
                lines, MAIN_FONT, actual_font_max, max_text_width
            )

            # -- Compute fade alpha --
            pop_scale = 1.0
            if pop_words > 0:
                # Pop mode: fast scale-up from 0.5 to 1.0 in first 20% of duration
                pop_t = min(elapsed / max(phrase_dur * 0.2, 0.05), 1.0)
                pop_scale = 0.5 + 0.5 * ease_out_cubic(pop_t)
                # Fade out in last 10%
                if elapsed > phrase_dur * 0.9:
                    fade_t = (elapsed - phrase_dur * 0.9) / (phrase_dur * 0.1)
                    alpha = 1.0 - ease_in_cubic(min(fade_t, 1.0))
                elif elapsed < 0.05:
                    alpha = ease_out_cubic(elapsed / 0.05)
                else:
                    alpha = 1.0
            elif phrase_dur < 0.5:
                # Very short phrase: no fade, just show it
                alpha = 1.0
            elif elapsed < FADE_DURATION:
                # Fade in: cubic ease-out on opacity
                local = elapsed / FADE_DURATION
                alpha = ease_out_cubic(local)
            elif elapsed > phrase_dur - FADE_DURATION:
                # Fade out: cubic ease-in on opacity
                local = (elapsed - (phrase_dur - FADE_DURATION)) / FADE_DURATION
                alpha = 1.0 - ease_in_cubic(local)
            else:
                alpha = 1.0

            alpha = max(0.0, min(1.0, alpha))

            # -- Layout: center the text block vertically and horizontally --
            line_spacing_factor = 1.2
            single_lh = line_heights[0] if line_heights else 40
            gap = int(single_lh * (line_spacing_factor - 1.0))
            block_h = sum(line_heights) + gap * (len(lines) - 1)

            center_x = width // 2
            center_y = int(height * text_y_frac)

            y_cursor = center_y - block_h // 2

            # Collect line positions for batch glow
            line_positions = []
            y_tmp = y_cursor
            for i, (ln, lw, lh) in enumerate(zip(lines, line_widths, line_heights)):
                draw_x = center_x - lw // 2
                draw_x = max(margin, min(draw_x, width - margin - lw))
                line_positions.append((ln, draw_x, y_tmp))
                y_tmp += int(lh * line_spacing_factor)

            # 1. Glow layer (single blur pass for all lines)
            if alpha > 0.05:
                draw_glow_fast(
                    img, line_positions, font,
                    color, alpha * 0.8, glow_radius=base_glow,
                    width=width, height=height
                )
                # Re-create draw after composite
                draw = ImageDraw.Draw(img)

            # 2. Drop shadow + clean text for each line
            shadow_off = max(2, int(3 * width / 1080))

            if pop_words > 0 and pop_scale < 0.99:
                # Pop-scale mode: render text to temp layer, scale it, composite
                text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                text_draw = ImageDraw.Draw(text_layer)
                for ln, draw_x, draw_y in line_positions:
                    text_draw.text(
                        (draw_x + shadow_off, draw_y + shadow_off),
                        ln, font=font, fill=(0, 0, 0, int(255 * alpha))
                    )
                    r, g, b = color
                    fr = int(r * alpha)
                    fg = int(g * alpha)
                    fb = int(b * alpha)
                    text_draw.text((draw_x, draw_y), ln, font=font,
                                  fill=(fr, fg, fb, int(255 * alpha)))

                # Scale around center of text block
                scaled_w = int(width * pop_scale)
                scaled_h = int(height * pop_scale)
                text_layer = text_layer.resize((scaled_w, scaled_h), Image.LANCZOS)
                paste_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                paste_x = (width - scaled_w) // 2
                paste_y = (height - scaled_h) // 2
                paste_layer.paste(text_layer, (paste_x, paste_y))
                img = Image.alpha_composite(img, paste_layer)
            else:
                for ln, draw_x, draw_y in line_positions:
                    draw.text(
                        (draw_x + shadow_off, draw_y + shadow_off),
                        ln, font=font, fill=(0, 0, 0)
                    )
                    draw.text(
                        (draw_x + shadow_off * 2, draw_y + shadow_off * 2),
                        ln, font=font, fill=(10, 10, 15)
                    )
                    r, g, b = color
                    fr = int(r * alpha)
                    fg = int(g * alpha)
                    fb = int(b * alpha)
                    draw.text((draw_x, draw_y), ln, font=font, fill=(fr, fg, fb))

        return np.array(img.convert("RGB"))

    # -- Build and write the video --
    dur_m, dur_s = int(duration // 60), int(duration % 60)
    print(f"  Step 3/4: Rendering {total_frames} frames ({dur_m}:{dur_s:02d} at {FPS}fps)")
    video = VideoClip(make_frame, duration=duration)
    video = video.with_fps(FPS)
    video = video.with_audio(audio)

    try:
        video.write_videofile(
            output_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile="/tmp/kinetic_audio_temp.m4a",
            remove_temp=True,
            preset="medium",
            ffmpeg_params=["-crf", "23", "-movflags", "+faststart"],
            logger="bar",
        )
    except Exception as e:
        err_msg = str(e).lower()
        if "ffmpeg" in err_msg or "not found" in err_msg or "no such file" in err_msg:
            print(
                "\nError: ffmpeg was not found. Please install it:\n"
                "  macOS:  brew install ffmpeg\n"
                "  Ubuntu: sudo apt install ffmpeg\n"
                "  Windows: download from https://ffmpeg.org/download.html"
            )
            sys.exit(1)
        raise

    print("")  # newline after progress
    video.close()
    audio.close()


# -- CLI -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a kinetic typography lyrics video from an audio file."
    )
    parser.add_argument(
        "audio",
        help="Path to the audio file (MP3, WAV, etc.)",
    )
    parser.add_argument(
        "--colors",
        default="#ffffff",
        help='Comma-separated hex colors, cycles per phrase. Default: "#ffffff"',
    )
    parser.add_argument(
        "--resolution",
        default="tiktok",
        choices=["tiktok", "youtube", "square"],
        help='Video resolution preset. Default: "tiktok" (1080x1920)',
    )
    parser.add_argument(
        "--bg",
        default=None,
        help="Background image(s). Comma-separated for multiple. Ken Burns zoom/pan with dissolve transitions.",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=100,
        help="Relative font size (default 100). Maps to actual pixels based on resolution.",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium"],
        help='Whisper model to use for transcription. Default: "base"',
    )
    parser.add_argument(
        "--no-edit",
        action="store_true",
        help="Skip the lyrics editing step and render immediately.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Default: same directory as input, named inputname_kinetic.mp4",
    )

    args = parser.parse_args()

    # Validate audio file
    audio_path = os.path.abspath(args.audio)
    if not os.path.isfile(audio_path):
        print(f"Error: Audio file not found: {audio_path}")
        sys.exit(1)

    # Parse colors
    try:
        colors = parse_color_list(args.colors)
    except ValueError as e:
        print(f"Error parsing colors: {e}")
        sys.exit(1)

    # Resolution
    width, height = RESOLUTIONS[args.resolution]

    # Background image(s) - pass through as comma-separated string
    bg_path = None
    if args.bg:
        # Resolve each path
        parts = [p.strip() for p in args.bg.split(",") if p.strip()]
        resolved = [os.path.abspath(p) for p in parts]
        bg_path = ",".join(resolved)

    # Output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        audio_dir = os.path.dirname(audio_path)
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        output_path = os.path.join(audio_dir, f"{audio_name}_kinetic.mp4")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    print()
    print("  Kinetic Lyrics")
    print("  " + "-" * 40)
    print(f"  Audio:      {os.path.basename(audio_path)}")
    print(f"  Resolution: {args.resolution} ({width}x{height})")
    print(f"  Colors:     {[f'#{r:02x}{g:02x}{b:02x}' for r, g, b in colors]}")
    print(f"  Font size:  {args.font_size}")
    print(f"  Whisper:    {args.whisper_model}")
    print(f"  Output:     {output_path}")
    if bg_path:
        print(f"  Background: {bg_path}")
    print("  " + "-" * 40)
    print()

    # Step 1: Transcribe
    words = transcribe_audio(audio_path, model_name=args.whisper_model)

    if not words:
        print("Error: No words detected in the audio. Check the file and try again.")
        sys.exit(1)

    # Step 2: Group into phrases
    phrases = group_words_into_phrases(words)

    if not phrases:
        print("Error: Could not form any phrases from the transcription.")
        sys.exit(1)

    # Write lyrics file for editing (unless --no-edit)
    lyrics_path = os.path.join(os.path.dirname(output_path) or ".", "lyrics.txt")

    if not args.no_edit:
        with open(lyrics_path, "w") as f:
            f.write("# Kinetic Lyrics - Edit the text below, one phrase per line.\n")
            f.write("# Keep the same number of lines. Timestamps are preserved.\n")
            f.write("# Lines starting with # are ignored.\n\n")
            for p in phrases:
                f.write(p["text"] + "\n")

        print()
        print(f"  Lyrics saved to: {lyrics_path}")
        print(f"  Open it, make any edits, save, then come back here.")
        print()
        try:
            input("  Press Enter to continue (or Ctrl+C to cancel)... ")
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            sys.exit(0)

        # Re-read edited lyrics
        with open(lyrics_path, "r") as f:
            edited_lines = [
                ln.strip() for ln in f.readlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]

        # Update phrase text from edited file (keep original timestamps)
        if len(edited_lines) == len(phrases):
            for i, line in enumerate(edited_lines):
                phrases[i]["text"] = line
            print(f"  Lyrics updated from {lyrics_path}")
        elif len(edited_lines) > 0 and len(edited_lines) != len(phrases):
            print(f"  Warning: lyrics.txt has {len(edited_lines)} lines but expected {len(phrases)}.")
            print(f"  Using first {min(len(edited_lines), len(phrases))} lines with original timestamps.")
            for i in range(min(len(edited_lines), len(phrases))):
                phrases[i]["text"] = edited_lines[i]
        print()

    # Step 3: Render video
    render_video(
        phrases=phrases,
        audio_path=audio_path,
        output_path=output_path,
        colors=colors,
        width=width,
        height=height,
        bg_image_path=bg_path,
        font_size_base=args.font_size,
    )

    # Step 4: Done
    print()
    print(f"  Step 4/4: Done!")
    file_size = os.path.getsize(output_path) / 1024 / 1024
    print(f"  Output: {output_path} ({file_size:.1f} MB)")
    print()


if __name__ == "__main__":
    main()
