---
name: tiktok-slideshow
description: Generate a 5-slide TikTok/Reels slideshow (1080x1920 JPGs) from a single idea. Claude writes the hook + slide copy; Gemini renders the images with baked-in text. BYO GEMINI_API_KEY.
user_invocable: true
---

# TikTok Slideshow Generator

Turn one idea into a ready-to-post 5-slide vertical slideshow. You write one sentence describing the topic; Claude expands it into slide copy; Gemini renders each slide as a 9:16 image with the text baked in.

## Arguments

- Required: a topic/idea as a quoted string (e.g., `/tiktok-slideshow "why octopuses taste with their arms"`)
- Optional `--style <preset>`: `minimal` (default) or `cartoon`
- Optional `--slides <N>`: number of slides, 3–7 (default 5)
- Optional `--out <dir>`: output directory (default `./tiktok-slideshow-out`)
- Optional `--video`: also assemble the slides into a 9:16 MP4 (3s per slide, 0.5s crossfades) at `<out>/slideshow.mp4`. Requires `ffmpeg` on PATH.

## Prerequisites

- `GEMINI_API_KEY` set in the environment or in a `.env` file next to `generate.py`
- Python 3.9+ with `google-genai` and `pillow` installed

## Steps

### 1. Parse the request

Extract the topic, style preset (default `minimal`), slide count (default 5), and output dir.

### 2. Draft slide copy

Given the topic, write a 5-slide arc:

- **Slide 1 (hook):** A bold, curiosity-driven opener. One short sentence. Ends with an implicit promise that the next slide delivers a payoff.
- **Slides 2 to N-1 (payoff):** Each delivers ONE concrete, surprising fact or step. Keep each slide to 1–3 short lines. Use natural phrase breaks for line wraps, never mid-word.
- **Slide N (close):** A clean takeaway or memorable line. Not a CTA.

Rules for copy:
- Normal sentence capitalization. No all-caps.
- No emoji. No hashtags. No em dashes (use periods or commas).
- Each slide is self-contained readable in under 3 seconds.

### 3. Draft image descriptions

For each slide, write a one-sentence image description that fits the `--style` preset. These are passed to Gemini along with the slide text.

**Style presets** (handled by `generate.py`; you just write a plain scene description):

- `minimal` — Evocative, cinematic scene imagery relevant to the slide topic. No character. Examples: "a Roman soldier's sandaled feet on a dusty road at dawn", "a cracked coffee bean under a harsh overhead light", "sonar rings spreading across dark ocean water".
- `cartoon` — A single friendly 3D cartoon mascot that appears on every slide, doing something relevant. Pick the mascot ONCE (e.g., "a curious cartoon octopus with big eyes") and reuse the exact same description on every slide so Gemini keeps it consistent. Vary only the action/setting.

### 4. Generate the images

Call `generate.py`:

```bash
python3 generate.py \
  --topic "the exact user topic" \
  --style minimal \
  --slides 5 \
  --out ./tiktok-slideshow-out \
  --slide-copy '[JSON array of {"text": "...", "description": "..."} per slide]'
```

The script handles the Gemini API call, aspect ratio, retries on 503s, and writes `slide-1.jpg` through `slide-N.jpg` in the output directory.

### 5. Report

Print the absolute path to the output folder and list the generated files. Don't post or upload anything — the user takes the JPGs into their phone and posts themselves.

## Style preset details (for reference)

The actual Gemini prompt is built inside `generate.py`. Both presets:
- Produce 1080×1920 vertical JPGs
- Bake the text overlay into the image itself (white, bold, sentence case)
- Place text in the upper third so TikTok/Reels UI chrome doesn't overlap
- Explicitly tell Gemini NOT to render search bars, icons, logos, or UI elements

## Example invocations

```
/tiktok-slideshow "why octopuses taste with their arms"
/tiktok-slideshow "the 20-mile march of a Roman legion" --style minimal
/tiktok-slideshow "how bees decide where to build a hive" --style cartoon --slides 5
/tiktok-slideshow "why your coffee tastes burnt" --video
```
