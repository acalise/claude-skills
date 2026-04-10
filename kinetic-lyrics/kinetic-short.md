---
name: kinetic-short
description: Generate a kinetic typography lyric video from an MP3 file. Uses Whisper for timestamps and Claude for lyric alignment.
user_invocable: true
---

# Kinetic Typography Video Generator

Generate a kinetic typography lyric video from an MP3 file. Works with just an MP3 (Whisper + Claude cleanup) or MP3 + lyrics text file for perfect accuracy.

## Arguments

- Required: path to an MP3 file (e.g., `/kinetic-short song.mp3`)
- Optional: path to a lyrics text file for perfect accuracy
- Optional: artist name for Wikipedia background image

## Steps

### 1. Locate the files

Confirm the MP3 file exists. If a lyrics file was provided, read it. If an artist name was given, note it for the background image step.

### 2. Pick the best clip window

If the song is longer than 60 seconds, choose the most compelling 55-60 second section for a Short. Typically Verse 1 + Chorus. Consider:
- Start at a natural musical phrase
- End at a natural break
- Prefer sections with emotional impact or a strong hook

### 3. Trim the audio

```python
from moviepy import AudioFileClip
clip = AudioFileClip(audio_path).subclipped(start_time, end_time)
clip.write_audiofile("/tmp/kinetic_trim.mp3", logger=None)
clip.close()
```

### 4. Fetch artist background image (optional)

If an artist name was provided, grab their Wikipedia photo:

```python
from fetch_artist_image import fetch_artist_image
bg_path = fetch_artist_image(artist_name, "output/artist_bg.jpg")
```

Falls back to a dark background if no image is found.

### 5. Transcribe with Whisper

```python
import whisper
model = whisper.load_model("small")
result = model.transcribe("/tmp/kinetic_trim.mp3", word_timestamps=True, language="en")
```

Print the segments for review.

### 6. Align lyrics to timestamps (CRITICAL STEP)

This is where Claude's judgment is essential.

**If a lyrics file was provided:**
- Compare Whisper's transcription against the actual lyrics line by line
- Use the REAL lyrics, not Whisper's text
- Map each lyric line to the correct segment timestamps

**If no lyrics file (MP3 only):**
- Use Whisper's transcription as the starting point
- Fix obvious mishearings using context (e.g., "I'm a noodle" is probably "ramen noodles")
- Clean up grammar and punctuation
- Use your knowledge of common phrases, slang, and song conventions

**For both modes:**
- Merge segments that Whisper split incorrectly
- Handle gaps between segments (instrumental breaks)
- Build a `phrases` list: `{"text": "lyric line", "start": float, "end": float}`
- Extend each phrase's `end` to the next phrase's `start` (no dead air) unless there's an instrumental gap > 2 seconds

**IMPORTANT: No trailing commas.** Never end a phrase with a hanging comma. Break the line differently or drop it.

**IMPORTANT: Natural line breaks.** Never split related words across lines. Break at natural phrase boundaries.

### 7. Render the video

```python
import sys
sys.path.insert(0, '<path-to-kinetic-lyrics-folder>')
from kinetic import render_video, parse_color_list

colors = parse_color_list('#FFD700')  # gold, or any hex color

render_video(
    phrases=phrases,
    audio_path="/tmp/kinetic_trim.mp3",
    output_path="output/kinetic_short.mp4",
    colors=colors,
    width=1080,
    height=1920,
    bg_image_path=bg_path,  # artist image, or None for dark background
    font_size_base=95,
    text_position="upper",  # keeps text above YouTube Shorts UI buttons
)
```

### 8. Report result

Print the output file path, file size, number of phrases rendered, and clip window used.

## Render Options

- `text_position="upper"` places text at ~30% from top (safe zone for YouTube Shorts)
- `text_position="center"` centers text vertically (default, good for YouTube/TikTok long-form)
- `pop_words=3` splits phrases into 3-word chunks with pop animation (experimental)
- `colors` accepts comma-separated hex colors that cycle per phrase

## Requirements

- Python 3.9+
- ffmpeg (`brew install ffmpeg`)
- `pip install openai-whisper moviepy pillow numpy`
- Optional: `pip install certifi` (for SSL on some systems)

## Installation

1. Copy `kinetic-short.md` to your project's `.claude/skills/` folder
2. Copy `kinetic.py` and `fetch_artist_image.py` to your project
3. Update the `sys.path.insert` line in step 7 to point to where you put `kinetic.py`
4. Run `/kinetic-short path/to/song.mp3`
