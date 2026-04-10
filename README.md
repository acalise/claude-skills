# Claude Skills

Custom Claude Code skills I use in my daily workflows.

## Skills

### [kinetic-lyrics](./kinetic-lyrics)

Generate kinetic typography lyric videos from any MP3. Whisper for timestamps, Claude for lyric alignment, renders 9:16 Shorts-ready videos.

- Works with just an MP3 or MP3 + lyrics file
- Wikipedia artist backgrounds with Ken Burns effect
- Glowing text, particles, smooth transitions
- YouTube Shorts and TikTok ready

## Installing a skill

Copy the `.md` skill file to your project's `.claude/skills/` folder:

```bash
mkdir -p .claude/skills
cp kinetic-lyrics/kinetic-short.md .claude/skills/
```

Then run it in Claude Code with `/kinetic-short`.
