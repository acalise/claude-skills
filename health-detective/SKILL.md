---
name: health-detective
description: Investigate an Apple Health export like a detective. Parses export.zip into compact CSV summaries, then reads them to surface anomalies, behavior shifts, asymmetries, and narrative correlations. BYO export.zip from iPhone Health app.
user_invocable: true
---

# Health Detective

Turn an Apple Health export into a short, specific investigation report — anomalies, asymmetries, behavior shifts, and cross-metric correlations. The goal is to surface **things the user did not realize were in their data**, not to restate obvious totals.

## Arguments

- Required: path to an Apple Health `export.zip` (or unzipped `export.xml`) as a quoted string.
- Optional `--since YYYY-MM-DD`: only analyze records on/after this date.
- Optional `--out <dir>`: output directory for the parsed summaries (default `./health-detective-out`).
- Optional `--focus <theme>`: narrow the investigation. Examples: `sleep`, `social`, `injury`, `music`, `workouts`, `stress`.
- Optional `--site`: also build a self-contained HTML dashboard with graphs (activities by year, workout types, weekly steps/HR/energy, sleep stages, body mass, anomalies) and open it in the browser.

## How to export from iPhone

Tell the user, if they haven't already: Health app → profile icon (top right) → *Export All Health Data* → AirDrop/save the resulting `export.zip`.

## Steps

### 1. Parse the export

Run the parser to produce compact CSVs Claude can read:

```bash
python3 parse.py --input "<path to export.zip>" --out ./health-detective-out
```

Add `--since 2024-01-01` if the export is huge and you only want recent data.

If `--site` was requested, also run:

```bash
python3 build_site.py --data ./health-detective-out --open
```

This writes a single self-contained `index.html` (Chart.js from CDN, data inlined) and opens it in the default browser. No server, no npm. Tell the user where the file landed so they can bookmark it.

The parser writes:
- `index.json` — date range, metrics available, pre-flagged z-score anomalies, top data sources.
- `daily/<metric>.csv` — one row per day: `date, value, samples, min, max`.
- `weekly/<metric>.csv` — one row per ISO week: `week, mean, median, min, max, std, n_days`.
- `sleep.csv` — per-day sleep stage minutes.
- `workouts.csv` — every workout with activity, duration, distance, energy, source.

### 2. Read the index first

Read `index.json` to learn the date range, which metrics exist, and which weeks the parser pre-flagged (z-score ≥ 2 vs trailing 12-week baseline). The anomaly list is a starting point — do not just parrot it back.

### 2.5. Audit data provenance before building any narrative

The index contains `primary_activity_source`, `primary_activity_class`, `metric_sources_top` (top 3 sources per metric with sample counts), and `low_confidence_metrics`.

- If `low_confidence_metrics` is non-empty, **do not build findings on those metrics.** They've already been stripped from the pre-flagged anomaly list. Mention in the report only if the user would care (e.g., "Gait metrics are phone-derived and noisy for you since your primary tracker is Garmin — skipping.").
- When `primary_activity_source` is a third-party wearable (Garmin `Connect`, Fitbit, Whoop, Oura, etc.), trust it for steps, heart rate, energy, and workouts. Phone-only metrics (iPhone-derived walking gait, environmental audio) are unreliable unless sample counts show the user still carries the phone consistently.
- Beware junk sources: cheap Bluetooth bands (`HeroBandⅢ`, generic `Bluetooth Device`) can dump millions of noisy records. If a metric's top source is one of these and values look wild (100% asymmetry, HR of 2 bpm), call it a data artifact, not a finding.
- Cross-check any striking weekly value by looking at the daily CSV before writing it into the report. A single bad day can move a weekly mean by several sigma.

### 3. Investigate like a detective

You are looking for **stories**, not statistics. Work through these lenses, picking the 3–5 most interesting threads to actually write up:

**Behavior shifts** — did a metric suddenly start or stop?
- `headphone_audio` dropping to near zero for a stretch → they stopped listening to music/podcasts. Ask *why then*.
- `env_audio` collapse or spike → change in social environment (WFH, moved, new job, went on retreat).
- `mindful_minutes` appearing then vanishing → tried meditation, dropped it.
- A workout type appearing once and never again → tried something new.

**Asymmetries and mechanics** — the injury tells.
- Weeks where `walking_asymmetry` or `walking_double_support` spiked → likely pain or limp. Cross-reference with a drop in `steps` or `walking_speed` or disappearance of running workouts.
- `walking_step_length` dropping is a subtle injury signal.

**Stress / recovery signatures**
- `resting_hr` trending up while `hrv` trending down over a span → accumulating load, illness, or stress.
- `respiratory_rate` elevation overnight is a known sickness early-warning.

**Social proxies**
- `env_audio` loudness patterns by day of week → weekday vs weekend social shape.
- Weeks of unusually low `env_audio` diversity → isolation, travel to quiet places, sick at home.

**Sleep narrative**
- Shifts in `asleep_deep` or `asleep_rem` ratios, not just total sleep.
- Bedtime drift (derive from sleep.csv start times if useful).
- Correlation between workout days and next-night deep sleep.

**Cross-metric correlations** — only call these out when they hold visibly in the data.
- Workout intensity vs next-day `hrv`.
- `headphone_audio` (proxy for solo time) vs `env_audio` (proxy for social time) — inverse patterns are interesting.
- Big step days followed by resting HR dips.

**Origin stories**
- When did they first get an Apple Watch? (first week `walking_hr` appears).
- When did they start strength training? (first `FunctionalStrengthTraining` workout).
- Longest active streak, longest gap.

### 4. Verify before claiming

Before writing any observation, spot-check it by reading the actual CSV rows. Do not claim a trend you haven't seen. If `--focus` was provided, anchor the investigation around that theme but still report any striking finding outside it.

### 5. Write the report

Output a short markdown report directly to the user (do not write a file unless they ask). Structure:

- **Data range:** dates covered, metrics available.
- **3–5 findings**, each as its own section with:
  - A one-line headline that reads like a detective's observation ("You stopped listening to music in March 2025.").
  - 2–4 sentences of supporting evidence with specific numbers and dates.
  - One open question back to the user ("Did something change that month?"). The user closing the loop is half the fun.
- **Things worth a closer look** — a short bullet list of leads you didn't fully chase.

Tone: curious, specific, slightly understated. Never generic wellness advice. Never "keep it up!" Never a summary of totals the user already knows.

## Privacy

Everything runs locally. The export and parsed CSVs never leave the user's machine unless they paste them somewhere. Remind the user of this if they hesitate.

## Example invocations

```
/health-detective "~/Downloads/export.zip"
/health-detective "~/Downloads/export.zip" --since 2024-01-01
/health-detective "~/Downloads/export.zip" --focus sleep
/health-detective "~/Downloads/export.zip" --focus injury --since 2024-06-01
```
