# TikTok Slideshow — Claude Code Skill

Generate a ready-to-post 5-slide TikTok/Reels slideshow from a single sentence.

You type one idea. Claude writes the hook and slide copy. Gemini renders each slide as a 1080×1920 vertical JPG with the text baked in.

Bring your own `GEMINI_API_KEY`.

## Examples

Live gallery: <https://acalise.com/tiktok-slideshow/>

## Install

1. Copy the `tiktok-slideshow/` folder into your Claude Code skills directory. Either:
   - User-scope: `~/.claude/skills/tiktok-slideshow/`
   - Project-scope: `<your-project>/.claude/skills/tiktok-slideshow/`
2. Install the two Python deps:
   ```bash
   pip install google-genai pillow
   ```
3. Get a Gemini API key from <https://aistudio.google.com/apikey> and drop it in a `.env` file next to `generate.py`:
   ```bash
   cp .env.example .env
   # edit .env and paste your key
   ```

## Usage

From a Claude Code session:

```
/tiktok-slideshow "why octopuses taste with their arms"
/tiktok-slideshow "the 20-mile march of a Roman legion" --style minimal
/tiktok-slideshow "how bees pick a new hive location" --style cartoon --slides 5
/tiktok-slideshow "why your coffee tastes burnt" --video
```

Output lands in `./tiktok-slideshow-out/slide-1.jpg` … `slide-5.jpg` by default. Override with `--out <dir>`.

Add `--video` to also assemble the slides into a 1080×1920 MP4 (3 seconds per slide, 0.5s crossfades) at `<out>/slideshow.mp4`. Requires `ffmpeg` on PATH. Tune with `--slide-seconds` and `--crossfade`.

## Styles

- **`minimal`** (default) — cinematic, photographic scene imagery. No character. Works for any topic: history, science, food, engineering, culture.
- **`cartoon`** — one friendly 3D cartoon mascot that recurs across all slides. Best for topics that benefit from a character guide (animals, kid-friendly explainers, whimsical takes).

Photoreal humans are intentionally not a preset — multi-slide consistency is unreliable with today's image models. If you need a persistent human character, fork the skill and lock in the character description yourself.

## How it works

1. `SKILL.md` tells Claude how to draft a 5-slide arc: hook → payoff → close, with tight copy and a scene description per slide.
2. Claude passes the drafted copy as JSON to `generate.py`.
3. `generate.py` builds a structured prompt per slide, calls Gemini 3.1 Flash Image with a 9:16 aspect ratio, retries on transient 5xx errors, and saves each slide as a JPG.

The skill stops at the file output. You move the JPGs to your phone and post them yourself.

## Why not just ask an image model directly?

Three recurring problems that `generate.py` handles:
- Image models often bake in the app's search bar, status bar, or "Search" field when you mention TikTok. The prompt explicitly forbids UI chrome in the top 15%.
- Models sometimes duplicate lines or invent extra text. The prompt enforces "render only the exact lines provided, verbatim."
- Text that centers vertically ends up hidden behind the TikTok UI. The prompt pins text between 22%–42% from the top.

## License

MIT. Have fun.
