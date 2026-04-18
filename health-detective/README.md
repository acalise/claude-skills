# health-detective

A Claude Code skill that investigates an Apple Health export like a detective — surfacing anomalies, behavior shifts, asymmetries, and correlations you didn't know were in your data.

Inspired by [@localghost's tweet](https://x.com/localghost/status/2044897124081643564) about Opus 4.7 noticing a walking asymmetry during a week of knee pain, guessing social activity from noise levels, and asking why they stopped listening to music one month.

**Live example dashboard (my own 9½ years of Apple Health data):** <https://acalise.com/health-detective/>

## What it does

1. Parses your Apple Health `export.zip` into compact CSVs (one per metric, daily + weekly).
2. Dedupes multi-tracker double-counting (Garmin + iPhone + etc.) by picking one preferred source per metric.
3. Flags iPhone-derived gait metrics as low-confidence when a dedicated wearable dominates (they're phone-carry noise, not biomechanics).
4. Pre-flags anomalous weeks using a trailing 12-week z-score baseline, filtered to ≥20% real-world changes in physiologically sane ranges.
5. Claude reads the summaries and writes a short investigation report: 3–5 specific observations, each with evidence and an open question back to you.
6. Optional `--site` flag: builds a single self-contained HTML dashboard with charts (steps, HR, sleep stages, activity by year, workout types, body mass, anomalies) and opens it in your browser. No server, no npm.

Everything runs locally. Nothing is uploaded.

## Install

```bash
mkdir -p ~/.claude/skills
cp -r health-detective ~/.claude/skills/
```

Or project-scoped: `cp -r health-detective .claude/skills/`.

## Export your data

On iPhone: Health app → profile icon (top right) → **Export All Health Data** → AirDrop the `export.zip` to your Mac.

## Run

```
/health-detective "~/Downloads/export.zip"
/health-detective "~/Downloads/export.zip" --since 2024-01-01
/health-detective "~/Downloads/export.zip" --focus sleep
/health-detective "~/Downloads/export.zip" --focus injury
/health-detective "~/Downloads/export.zip" --site
```

## Requirements

- Python 3.9+ (standard library only — no pip installs).
- Claude Code.

## What gets parsed

Steps, distance, flights, active + basal energy, heart rate, resting HR, HRV, walking HR, exercise time, stand time, walking asymmetry / double-support / step length / speed, six-minute walk, headphone audio exposure, environmental audio exposure, mindful minutes, body mass, body fat, VO2 max, respiratory rate, SpO2, blood pressure, sleep stages, and every workout.

## License

MIT.
