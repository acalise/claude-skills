# Claude Skills

Custom Claude Code skills I use in my daily workflows.

## Skills

### [kinetic-lyrics](./kinetic-lyrics)

Generate kinetic typography lyric videos from any MP3. Whisper for timestamps, Claude for lyric alignment, renders 9:16 Shorts-ready videos.

- Works with just an MP3 or MP3 + lyrics file
- Wikipedia artist backgrounds with Ken Burns effect
- Glowing text, particles, smooth transitions
- YouTube Shorts and TikTok ready
- Live example: <https://youtu.be/WnLsf9lLhKs>

### [health-detective](./health-detective)

Point Claude at an Apple Health `export.zip` and get back a short investigation report — anomalies, asymmetries, behavior shifts, cross-metric correlations. Runs fully local (Python stdlib only).

- Parses 25+ HealthKit metrics + sleep stages + workouts into compact CSVs
- Pre-flags anomalous weeks with a rolling z-score baseline
- Optional `--focus sleep|injury|social|music|workouts|stress` to narrow the investigation

### [tiktok-slideshow](./tiktok-slideshow)

Turn one sentence into a ready-to-post 5-slide vertical slideshow. Claude drafts the copy, Gemini renders the images with text baked in, optional MP4 assembly via ffmpeg. Bring your own `GEMINI_API_KEY`.

- 1080×1920 JPG output per slide, optional 1080×1920 MP4 with crossfades
- `minimal` and `cartoon` style presets
- Live examples: <https://acalise.com/tiktok-slideshow/>

## Installing a skill

Copy the skill folder to your project's `.claude/skills/` folder (or to `~/.claude/skills/` for user-scope):

```bash
mkdir -p .claude/skills
cp -r kinetic-lyrics .claude/skills/
cp -r tiktok-slideshow .claude/skills/
```

Then run them in Claude Code with `/kinetic-short` or `/tiktok-slideshow`.

## License

[MIT](./LICENSE) — use, fork, remix freely.
