#!/usr/bin/env python3
"""
TikTok Slideshow Generator — generic public version.

Usage:
  python3 generate.py --topic "your idea" --style minimal --slides 5 \
                      --out ./out --slide-copy '<JSON>'

Claude Code drives this via SKILL.md: Claude drafts the slide copy + image
descriptions and passes them in as --slide-copy. The script handles Gemini
generation only.

Requires:
  GEMINI_API_KEY in env or in a .env file next to this script.
  pip install google-genai pillow
"""

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv(Path(__file__).resolve().parent / ".env")

IMAGE_MODEL = "gemini-3.1-flash-image-preview"

STYLE_PREAMBLES = {
    "minimal": (
        "Cinematic, photographic scene. No people as primary subject unless the topic "
        "explicitly requires one. Natural lighting, shallow depth of field, rich color, "
        "editorial composition."
    ),
    "cartoon": (
        "Warm, friendly 3D cartoon illustration in a Pixar-adjacent style. Soft shading, "
        "saturated but not neon colors, clean shapes, expressive and readable."
    ),
}


def build_prompt(text_lines: str, scene: str, style: str) -> str:
    preamble = STYLE_PREAMBLES.get(style, STYLE_PREAMBLES["minimal"])
    return f"""Full 9:16 vertical image, 1080x1920, fills the entire frame edge to edge. No letterboxing, no black bars.

{preamble}

Scene: {scene}

The main subject must sit in the lower 55-70% of the frame. Keep the upper portion uncluttered for text.

Text overlay placed between 22% and 42% from the top edge. NEVER in the top 15% (keep that area pure background). NEVER in the dead center. NEVER in the lower half. Multi-line layout, clean modern bold sans-serif, solid white, no gradients, no outlines other than a subtle soft shadow for legibility, normal sentence capitalization.

Do NOT draw a search bar, magnifying glass, status bar, app UI chrome, logos, watermarks, or any graphic element in the top 15% of the image. That area must be pure scene background only.

Render ONLY the exact text lines below, verbatim, in order, one line per provided line, with no additions, no repetitions, and no extra text anywhere else in the image:

{text_lines}
"""


def generate_image(client, prompt: str, output_path: Path) -> bool:
    from google.genai import types

    max_retries = 6
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["Text", "Image"],
                    image_config=types.ImageConfig(aspect_ratio="9:16"),
                ),
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    from PIL import Image
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                    img.save(str(output_path), "JPEG", quality=95)
                    return True
            return False
        except Exception as e:
            transient = any(s in str(e) for s in ("503", "500", "UNAVAILABLE", "INTERNAL"))
            if attempt < max_retries and transient:
                wait = 10 * attempt
                print(f"  {type(e).__name__} on attempt {attempt}/{max_retries}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    return False


def assemble_video(
    slide_paths: list,
    out_path: Path,
    slide_seconds: float,
    crossfade: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> None:
    """Render slide JPGs into an MP4 with crossfades using ffmpeg's xfade filter."""
    if not slide_paths:
        raise ValueError("no slides to assemble")

    # Build filter graph: each input is a looped still image for slide_seconds; chain via xfade.
    n = len(slide_paths)
    inputs = []
    for p in slide_paths:
        inputs += ["-loop", "1", "-t", f"{slide_seconds}", "-i", str(p)]

    # Normalize each input to target resolution/fps, then chain xfade transitions.
    filter_parts = []
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[v{i}]"
        )

    # xfade chain
    prev = "v0"
    for i in range(1, n):
        offset = slide_seconds * i - crossfade * i
        out_label = f"x{i}" if i < n - 1 else "vout"
        filter_parts.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={crossfade}:offset={offset}[{out_label}]"
        )
        prev = out_label if i < n - 1 else "vout"

    if n == 1:
        filter_complex = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[vout]"
    else:
        filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "23",
        "-movflags", "+faststart",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-1500:]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True, help="The user's topic/idea (for logging)")
    p.add_argument("--style", default="minimal", choices=["minimal", "cartoon"])
    p.add_argument("--slides", type=int, default=5)
    p.add_argument("--out", default="./tiktok-slideshow-out")
    p.add_argument(
        "--slide-copy",
        required=True,
        help="JSON array: [{'text': 'Line 1\\nLine 2', 'description': 'scene'}]",
    )
    p.add_argument("--video", action="store_true", help="Also assemble slides into an MP4 via ffmpeg")
    p.add_argument("--slide-seconds", type=float, default=3.0, help="Seconds per slide when --video (default 3)")
    p.add_argument("--crossfade", type=float, default=0.5, help="Crossfade duration in seconds (default 0.5)")
    args = p.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Put it in .env next to generate.py or export it.", file=sys.stderr)
        sys.exit(2)

    try:
        slide_copy = json.loads(args.slide_copy)
    except json.JSONDecodeError as e:
        print(f"ERROR: --slide-copy is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(slide_copy, list) or not slide_copy:
        print("ERROR: --slide-copy must be a non-empty JSON array.", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    from google import genai
    client = genai.Client(api_key=api_key)

    print(f'Topic : "{args.topic}"')
    print(f"Style : {args.style}")
    print(f"Out   : {out_dir}")
    print()

    paths = []
    for i, slide in enumerate(slide_copy, 1):
        text = slide.get("text", "").strip()
        desc = slide.get("description", "").strip()
        if not text or not desc:
            print(f"ERROR: slide {i} missing 'text' or 'description'.", file=sys.stderr)
            sys.exit(2)

        text_lines = "\n".join(f'"{line}"' for line in text.split("\n"))
        prompt = build_prompt(text_lines, desc, args.style)

        out_path = out_dir / f"slide-{i}.jpg"
        preview = text.replace("\n", " | ")[:70]
        print(f"[Slide {i}/{len(slide_copy)}] {preview}")
        print(f"  -> {IMAGE_MODEL} ...", end=" ", flush=True)

        ok = generate_image(client, prompt, out_path)
        if not ok:
            print("FAIL")
            sys.exit(1)

        kb = out_path.stat().st_size // 1024
        print(f"OK ({kb} KB) -> {out_path.name}")
        paths.append(out_path)

    print()
    print("Done. Files:")
    for p_ in paths:
        print(f"  {p_}")

    if args.video:
        video_path = out_dir / "slideshow.mp4"
        total = args.slide_seconds * len(paths) - args.crossfade * (len(paths) - 1)
        print(f"\nAssembling video ({total:.1f}s) -> {video_path.name} ...", flush=True)
        assemble_video(paths, video_path, args.slide_seconds, args.crossfade)
        mb = video_path.stat().st_size / (1024 * 1024)
        print(f"  OK ({mb:.1f} MB) -> {video_path}")


if __name__ == "__main__":
    main()
