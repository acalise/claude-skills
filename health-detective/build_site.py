#!/usr/bin/env python3
"""
Build a single self-contained HTML dashboard from the parsed CSVs.

Usage:
  python3 build_site.py --data ./health-detective-out --out ./health-detective-out/index.html
  python3 build_site.py --data ./health-detective-out --open
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date


import re

def humanize_activity(a):
    if not a:
        return "Unknown"
    # Split CamelCase → "Traditional Strength Training"
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", a).strip()
    return s

# Human-readable metric names + what the metric actually is.
METRIC_LABELS = {
    "steps": ("Steps", "Daily step count."),
    "distance_walk_run": ("Walking + running distance", "Miles walked/run per day."),
    "flights_climbed": ("Flights of stairs", "Flights of stairs climbed per day."),
    "active_energy": ("Active calories", "Calories burned from movement (on top of resting)."),
    "basal_energy": ("Resting calories", "Calories your body burns just existing (BMR). Changes with body mass, muscle, and tracker calibration — big jumps often mean a new device, not a metabolic event."),
    "heart_rate": ("Heart rate", "Average heart rate throughout the day."),
    "resting_hr": ("Resting heart rate", "Heart rate at rest. Rising trends can signal illness or accumulated stress."),
    "hrv": ("Heart rate variability", "Beat-to-beat variation. Higher is generally better recovery."),
    "walking_hr": ("Walking heart rate", "Average HR while walking."),
    "exercise_time": ("Exercise minutes", "Minutes of brisk activity."),
    "stand_time": ("Stand minutes", "Minutes upright each hour."),
    "mindful_minutes": ("Mindful minutes", "Meditation time."),
    "body_mass": ("Body mass", "Weight."),
    "body_fat": ("Body fat %", "Percent body fat."),
    "vo2_max": ("VO2 max", "Cardiorespiratory fitness."),
    "respiratory_rate": ("Respiratory rate", "Breaths per minute overnight. Elevation often precedes illness by a day or two."),
    "spo2": ("Blood oxygen", "SpO2."),
    "headphone_audio": ("Headphone audio exposure", "Sound level through headphones — a proxy for solo/music/podcast time."),
    "env_audio": ("Environmental audio exposure", "Ambient sound — proxy for how loud your surroundings are, indirectly for social time."),
    "walking_asymmetry": ("Walking asymmetry", "Difference between left/right leg gait."),
    "walking_double_support": ("Walking double-support", "Percent of time both feet are on the ground."),
    "walking_step_length": ("Walking step length", "Length of each stride."),
    "walking_speed": ("Walking speed", "Average walking speed."),
    "bp_systolic": ("BP (systolic)", "Systolic blood pressure."),
    "bp_diastolic": ("BP (diastolic)", "Diastolic blood pressure."),
}

# Physiologically plausible weekly-mean ranges. Weekly rows or anomalies outside
# these are treated as device/data artifacts and dropped from display.
SANE_RANGES = {
    "heart_rate": (35, 180),
    "resting_hr": (30, 130),
    "walking_hr": (50, 180),
    "hrv": (5, 250),
    "body_mass": (60, 500),
    "body_fat": (3, 60),
    "spo2": (0.70, 1.0),
    "respiratory_rate": (6, 30),
    "bp_systolic": (70, 220),
    "bp_diastolic": (40, 140),
    "vo2_max": (15, 80),
    # Energy metrics: multiple sources often double-report, inflating totals.
    # BMR >3500/day or active >3000/day are almost always double-counted.
    "basal_energy": (800, 3500),
    "active_energy": (0, 3000),
    # Steps likewise — single-digit-thousands realistic upper bound per day.
    "steps": (0, 60000),
    "flights_climbed": (0, 150),
    "distance_walk_run": (0, 35),
}


def in_range(metric, value):
    lo_hi = SANE_RANGES.get(metric)
    if not lo_hi:
        return True
    lo, hi = lo_hi
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return lo <= v <= hi


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def weekly(data_dir, metric):
    return read_csv(os.path.join(data_dir, "weekly", f"{metric}.csv"))


def daily(data_dir, metric):
    return read_csv(os.path.join(data_dir, "daily", f"{metric}.csv"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="Parsed data directory (from parse.py)")
    ap.add_argument("--out", default=None, help="Output HTML path (default <data>/index.html)")
    ap.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    args = ap.parse_args()

    data_dir = args.data
    out_path = args.out or os.path.join(data_dir, "index.html")

    with open(os.path.join(data_dir, "index.json")) as f:
        index = json.load(f)

    workouts_all = read_csv(os.path.join(data_dir, "workouts.csv"))
    # Drop sub-5-minute entries. Garmin auto-detects short movement blips
    # (often as "Other") and logs each as a workout — real workouts are longer.
    def _dur(w):
        try: return float(w.get("duration_min") or 0)
        except ValueError: return 0
    workouts = [w for w in workouts_all if _dur(w) >= 10]
    sleep = read_csv(os.path.join(data_dir, "sleep.csv"))

    # Low-confidence metrics — don't chart them.
    low_conf = {lc["metric"] for lc in index.get("low_confidence_metrics", [])}

    # Activities by year
    by_year = Counter(w["date"][:4] for w in workouts)
    by_year_data = sorted(by_year.items())

    # Workout type breakdown — humanize CamelCase
    raw_types = Counter(w["activity"] for w in workouts)
    by_type = Counter()
    for k, v in raw_types.items():
        by_type[humanize_activity(k)] += v

    # Monthly workout frequency (for last 36 months)
    by_month = Counter(w["date"][:7] for w in workouts)
    months_sorted = sorted(by_month.keys())[-36:]
    monthly_workouts = [(m, by_month[m]) for m in months_sorted]

    # Activity duration by type
    duration_by_type = defaultdict(float)
    for w in workouts:
        try:
            duration_by_type[w["activity"]] += float(w.get("duration_min") or 0)
        except ValueError:
            pass

    # Headline stats
    total_steps = 0
    for r in daily(data_dir, "steps"):
        try:
            total_steps += float(r["value"])
        except ValueError:
            pass
    total_energy = 0
    for r in daily(data_dir, "active_energy"):
        try:
            total_energy += float(r["value"])
        except ValueError:
            pass
    total_sleep_hours = 0
    for r in sleep:
        try:
            total_sleep_hours += float(r["total_asleep_min"]) / 60.0
        except ValueError:
            pass

    # Weekly series — filter out weeks whose mean falls outside physiological range
    def weekly_series(metric):
        out = []
        for r in weekly(data_dir, metric):
            try:
                m = float(r["mean"])
            except ValueError:
                continue
            if not in_range(metric, m):
                continue
            out.append({"week": r["week"], "mean": m})
        return out

    # Daily body mass
    body_mass = [{"date": r["date"], "value": float(r["value"])} for r in daily(data_dir, "body_mass")]

    # Weekly sleep stacked
    from collections import defaultdict as _dd
    week_sleep = _dd(lambda: {"core": 0.0, "deep": 0.0, "rem": 0.0, "awake": 0.0, "n": 0})
    for r in sleep:
        d = date.fromisoformat(r["date"])
        y, w, _ = d.isocalendar()
        key = f"{y}-W{w:02d}"
        ws = week_sleep[key]
        ws["core"] += float(r.get("asleep_core") or 0)
        ws["deep"] += float(r.get("asleep_deep") or 0)
        ws["rem"] += float(r.get("asleep_rem") or 0)
        ws["awake"] += float(r.get("awake") or 0)
        ws["n"] += 1
    sleep_weekly = []
    for key in sorted(week_sleep):
        ws = week_sleep[key]
        # Require at least 3 nights in the week AND non-trivial total sleep,
        # otherwise the row is a tracking artifact (e.g., first week of owning
        # the watch) and will look like an empty gap on the chart.
        if ws["n"] < 3:
            continue
        total_min = ws["core"] + ws["deep"] + ws["rem"]
        if total_min < 60:  # < 1 hour avg per night is nonsense
            continue
        n = max(ws["n"], 1)
        sleep_weekly.append({
            "week": key,
            "core": round(ws["core"] / n / 60, 2),
            "deep": round(ws["deep"] / n / 60, 2),
            "rem": round(ws["rem"] / n / 60, 2),
            "awake": round(ws["awake"] / n / 60, 2),
        })

    # Anomaly highlights — keep only ones a human would notice:
    # 1. Value must be physiologically plausible.
    # 2. Relative change from baseline must be >= 20% (z-score alone is misleading
    #    when the baseline has very low variance).
    # 3. Attach human-readable labels + descriptions.
    cleaned_anoms = []
    for a in index.get("anomalies", []):
        m = a["metric"]
        if not in_range(m, a["value"]):
            continue
        base = a.get("baseline_mean") or 0
        if base == 0:
            continue
        rel = abs(a["value"] - base) / abs(base)
        if rel < 0.20:
            continue
        label, desc = METRIC_LABELS.get(m, (m.replace("_", " ").title(), ""))
        cleaned_anoms.append({**a, "label": label, "description": desc,
                              "pct_change": round(rel * 100, 0)})
    # Take top 10 by magnitude, then reorder chronologically (most recent first).
    top = sorted(cleaned_anoms, key=lambda a: -abs(a["z_score"]))[:10]
    anomalies = sorted(top, key=lambda a: a["week"], reverse=True)

    payload = {
        "meta": {
            "date_range": index.get("date_range"),
            "metrics_available": index.get("metrics_available"),
            "primary_activity_source": index.get("primary_activity_source"),
            "low_confidence_metrics": index.get("low_confidence_metrics", []),
            "top_sources": index.get("top_sources"),
        },
        "headline": {
            "n_workouts": len(workouts),
            "total_steps": int(total_steps),
            "total_energy_kcal": int(total_energy),
            "total_sleep_hours": round(total_sleep_hours, 1),
            "n_sleep_days": len(sleep),
        },
        "activities_by_year": by_year_data,
        "workouts_by_type": by_type.most_common(),
        "duration_by_type": sorted(duration_by_type.items(), key=lambda x: -x[1])[:12],
        "monthly_workouts": monthly_workouts,
        "weekly": {
            m: weekly_series(m)
            for m in ("steps", "heart_rate", "resting_hr", "active_energy",
                      "hrv", "flights_climbed", "distance_walk_run",
                      "headphone_audio", "env_audio")
            if m in (index.get("metrics_available") or [])
        },
        "body_mass": body_mass,
        "sleep_weekly": sleep_weekly,
        "anomalies": anomalies,
        "low_conf": sorted(low_conf),
    }

    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Wrote dashboard: {os.path.abspath(out_path)}")

    if args.open:
        if sys.platform == "darwin":
            subprocess.run(["open", out_path])
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", out_path])
        elif sys.platform == "win32":
            os.startfile(out_path)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Health Detective — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0b0d10; --panel: #14171c; --panel2: #1b1f26;
    --text: #e6e9ef; --muted: #8a94a6; --accent: #7bd88f; --warn: #f2b866; --bad: #f27878;
    --grid: #2a2f38;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 32px 20px 80px; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  h2 { font-size: 15px; margin: 0 0 4px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .range { font-size: 11px; color: var(--muted); margin-bottom: 12px; font-variant-numeric: tabular-nums; }
  .sub { color: var(--muted); margin-bottom: 28px; font-size: 13px; }
  .grid { display: grid; gap: 16px; }
  .cards { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 20px; }
  .card { background: var(--panel); border: 1px solid var(--grid); border-radius: 10px; padding: 16px; }
  .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; }
  .stat-value { font-size: 24px; font-weight: 600; margin-top: 6px; letter-spacing: -0.01em; }
  .stat-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .panels { grid-template-columns: repeat(auto-fit, minmax(440px, 1fr)); }
  .panel { background: var(--panel); border: 1px solid var(--grid); border-radius: 10px; padding: 18px; }
  .panel.full { grid-column: 1 / -1; }
  canvas { max-width: 100%; }
  .anomaly-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
  .anomaly-list li { background: var(--panel2); border: 1px solid var(--grid); border-radius: 8px; padding: 14px 16px; }
  .anom-top { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
  .anom-title { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
  .anom-week { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .anom-compare { display: flex; align-items: center; gap: 14px; margin-bottom: 8px; font-variant-numeric: tabular-nums; flex-wrap: wrap; }
  .anom-value { font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  .anom-sep { color: var(--muted); font-size: 12px; }
  .anom-baseline { font-size: 13px; color: var(--muted); }
  .anom-z { font-size: 11px; color: var(--muted); margin-left: auto; padding: 2px 8px; border: 1px solid var(--grid); border-radius: 999px; }
  .anom-desc { font-size: 12px; color: var(--muted); line-height: 1.5; }
  .tag { display: inline-block; font-size: 10px; padding: 3px 8px; border-radius: 4px; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; }
  .tag.good { background: rgba(123, 216, 143, 0.15); color: var(--accent); }
  .tag.bad { background: rgba(242, 120, 120, 0.15); color: var(--bad); }
  .tag.neutral { background: rgba(242, 184, 102, 0.15); color: var(--warn); }
  .muted { color: var(--muted); }
  .warn-banner { background: rgba(242, 120, 120, 0.08); border: 1px solid rgba(242, 120, 120, 0.2); color: var(--bad); padding: 10px 14px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Health Detective</h1>
  <div class="sub" id="sub"></div>

  <div class="grid cards" id="cards"></div>

  <div class="grid panels">
    <div class="panel"><h2>Workouts by year</h2><div class="range" id="yearRange"></div><canvas id="yearChart"></canvas></div>
    <div class="panel"><h2>Workout types (all time)</h2><div class="range" id="typeRange"></div><canvas id="typeChart"></canvas></div>
    <div class="panel full"><h2>Monthly workouts</h2><div class="range" id="monthRange"></div><canvas id="monthChart"></canvas></div>
    <div class="panel full"><h2>Weekly steps</h2><div class="range" id="stepsRange"></div><canvas id="stepsChart"></canvas></div>
    <div class="panel"><h2>Weekly heart rate</h2><div class="range" id="hrRange"></div><canvas id="hrChart"></canvas></div>
    <div class="panel"><h2>Weekly active calories</h2><div class="range" id="energyRange"></div><canvas id="energyChart"></canvas></div>
    <div class="panel full"><h2>Weekly sleep (avg hours per night, by stage)</h2><div class="range" id="sleepRange"></div><canvas id="sleepChart"></canvas></div>
    <div class="panel full"><h2>Body mass over time</h2><div class="range" id="bodyRange"></div><canvas id="bodyChart"></canvas></div>
    <div class="panel full">
      <h2>Notable anomalies</h2>
      <div class="range">Weeks that differ by ≥20% from your trailing 12-week average for that metric. "Typical" below is that rolling average — not an all-time number.</div>
      <ul class="anomaly-list" id="anomList"></ul>
    </div>
  </div>
</div>

<script>
const DATA = __PAYLOAD__;
Chart.defaults.color = '#8a94a6';
Chart.defaults.borderColor = '#2a2f38';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif';

function fmt(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtWeek(s) { return s || ''; }
// Long form for the anomaly list where we have horizontal room.
function fmtWeekLong(s) {
  if (!s) return '';
  const m = /^(\d{4})-W(\d{1,2})$/.exec(s);
  return m ? `Week ${parseInt(m[2], 10)}, ${m[1]}` : s;
}

// Header
const r = DATA.meta.date_range || {};
document.getElementById('sub').textContent = `${r.start || '?'} → ${r.end || '?'}`;

// Cards
const cards = [
  { label: 'Workouts', value: fmt(DATA.headline.n_workouts) },
  { label: 'Steps', value: fmt(DATA.headline.total_steps) },
  { label: 'Active kcal', value: fmt(DATA.headline.total_energy_kcal) },
  { label: 'Sleep hours', value: fmt(DATA.headline.total_sleep_hours), sub: `${fmt(DATA.headline.n_sleep_days)} nights` },
  { label: 'Metrics tracked', value: (DATA.meta.metrics_available || []).length },
];
document.getElementById('cards').innerHTML = cards.map(c => `
  <div class="card">
    <div class="stat-label">${c.label}</div>
    <div class="stat-value">${c.value}</div>
    ${c.sub ? `<div class="stat-sub">${c.sub}</div>` : ''}
  </div>
`).join('');

function lineChart(id, labels, data, label, color) {
  new Chart(document.getElementById(id), {
    type: 'line',
    data: { labels, datasets: [{ label, data, borderColor: color, backgroundColor: color + '33', tension: 0.2, pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 20, borderWidth: 1.5 }] },
    options: {
      responsive: true, animation: false,
      interaction: { mode: 'index', intersect: false, axis: 'x' },
      scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { beginAtZero: false } },
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } }
    }
  });
}

function barChart(id, labels, data, color) {
  new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color }] },
    options: { responsive: true, animation: false, plugins: { legend: { display: false } } }
  });
}

function rangeText(items, keyStart, keyEnd) {
  if (!items || !items.length) return '';
  const first = keyStart ? items[0][keyStart] : items[0][0];
  const last = keyEnd ? items[items.length-1][keyEnd] : items[items.length-1][0];
  return `${first} → ${last}`;
}

// Yearly
barChart('yearChart', DATA.activities_by_year.map(d => d[0]), DATA.activities_by_year.map(d => d[1]), '#7bd88f');
document.getElementById('yearRange').textContent = rangeText(DATA.activities_by_year);
document.getElementById('typeRange').textContent = `${DATA.headline.n_workouts.toLocaleString()} workouts tracked`;

// Types
const typeLabels = DATA.workouts_by_type.slice(0, 10).map(d => d[0] || 'Unknown');
const typeData = DATA.workouts_by_type.slice(0, 10).map(d => d[1]);
new Chart(document.getElementById('typeChart'), {
  type: 'doughnut',
  data: { labels: typeLabels, datasets: [{ data: typeData, backgroundColor: ['#7bd88f','#f2b866','#78c2f2','#c978f2','#f27878','#a7f278','#f2e878','#78f2d4','#b0b0b0','#e078f2'] }] },
  options: { responsive: true, animation: false, plugins: { legend: { position: 'right', labels: { font: { size: 11 } } } } }
});

// Monthly
barChart('monthChart', DATA.monthly_workouts.map(d => d[0]), DATA.monthly_workouts.map(d => d[1]), '#78c2f2');
document.getElementById('monthRange').textContent = rangeText(DATA.monthly_workouts);

// Weekly lines
function setWeeklyRange(id, series) {
  const el = document.getElementById(id);
  if (!series || !series.length) { el.textContent = 'No data'; return; }
  el.textContent = `${fmtWeek(series[0].week)} → ${fmtWeek(series[series.length-1].week)}  (${series.length} weeks)`;
}
if (DATA.weekly.steps) { lineChart('stepsChart', DATA.weekly.steps.map(r => fmtWeek(r.week)), DATA.weekly.steps.map(r => r.mean), 'Steps', '#7bd88f'); setWeeklyRange('stepsRange', DATA.weekly.steps); }
if (DATA.weekly.heart_rate) { lineChart('hrChart', DATA.weekly.heart_rate.map(r => fmtWeek(r.week)), DATA.weekly.heart_rate.map(r => r.mean), 'HR', '#f27878'); setWeeklyRange('hrRange', DATA.weekly.heart_rate); }
if (DATA.weekly.active_energy) { lineChart('energyChart', DATA.weekly.active_energy.map(r => fmtWeek(r.week)), DATA.weekly.active_energy.map(r => r.mean), 'Active kcal', '#f2b866'); setWeeklyRange('energyRange', DATA.weekly.active_energy); }

// Sleep stacked
new Chart(document.getElementById('sleepChart'), {
  type: 'bar',
  data: {
    labels: DATA.sleep_weekly.map(r => fmtWeek(r.week)),
    datasets: [
      { label: 'Deep', data: DATA.sleep_weekly.map(r => r.deep), backgroundColor: '#4a6fa5' },
      { label: 'Core', data: DATA.sleep_weekly.map(r => r.core), backgroundColor: '#78c2f2' },
      { label: 'REM', data: DATA.sleep_weekly.map(r => r.rem), backgroundColor: '#c978f2' },
      { label: 'Awake', data: DATA.sleep_weekly.map(r => r.awake), backgroundColor: '#f27878' },
    ]
  },
  options: {
    responsive: true, animation: false,
    interaction: { mode: 'index', intersect: false, axis: 'x' },
    scales: { x: { stacked: true, ticks: { maxTicksLimit: 12 } }, y: { stacked: true, title: { display: true, text: 'hours' } } },
    plugins: { legend: { position: 'bottom' }, tooltip: { mode: 'index', intersect: false } }
  }
});
setWeeklyRange('sleepRange', DATA.sleep_weekly);

// Body mass
lineChart('bodyChart', DATA.body_mass.map(r => r.date), DATA.body_mass.map(r => r.value), 'Body mass', '#f2e878');
if (DATA.body_mass && DATA.body_mass.length) {
  const bm = DATA.body_mass;
  document.getElementById('bodyRange').textContent = `${bm[0].date} → ${bm[bm.length-1].date}  (${bm.length} readings)`;
}

// Format anomaly values: big numbers as integers, small as 1 decimal.
function fmtVal(n) {
  const v = Number(n);
  if (!isFinite(v)) return '—';
  if (Math.abs(v) >= 100) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

// Semantic valence per metric+direction. Determines tag color:
//   good   = green   (this is a positive reading)
//   bad    = red     (this is a concerning reading)
//   neutral= amber   (notable but not clearly good or bad)
const VALENCE = {
  resting_hr: { high: 'bad', low: 'good' },
  heart_rate: { high: 'bad', low: 'neutral' },
  hrv: { high: 'good', low: 'bad' },
  spo2: { high: 'good', low: 'bad' },
  respiratory_rate: { high: 'bad', low: 'neutral' },
  body_fat: { high: 'bad', low: 'good' },
  vo2_max: { high: 'good', low: 'bad' },
  steps: { high: 'good', low: 'bad' },
  flights_climbed: { high: 'good', low: 'bad' },
  distance_walk_run: { high: 'good', low: 'bad' },
  active_energy: { high: 'good', low: 'bad' },
  exercise_time: { high: 'good', low: 'bad' },
  stand_time: { high: 'good', low: 'bad' },
  walking_speed: { high: 'good', low: 'bad' },
  walking_hr: { high: 'bad', low: 'good' },
  mindful_minutes: { high: 'good', low: 'neutral' },
  // basal_energy, body_mass, headphone_audio, env_audio, bp_*: neutral by default
};
function valence(metric, direction) {
  return (VALENCE[metric] && VALENCE[metric][direction]) || 'neutral';
}
function valenceLabel(v, direction) {
  if (v === 'good') return 'looking good';
  if (v === 'bad')  return 'worth a look';
  return direction === 'high' ? 'higher than usual' : 'lower than usual';
}

document.getElementById('anomList').innerHTML = DATA.anomalies.map(a => {
  const v = valence(a.metric, a.direction);
  return `
  <li>
    <div class="anom-top">
      <div>
        <span class="tag ${v}">${valenceLabel(v, a.direction)}</span>
        <span class="anom-title" style="margin-left:8px">${a.label}</span>
      </div>
      <div class="anom-week">${fmtWeekLong(a.week)}</div>
    </div>
    <div class="anom-compare">
      <div class="anom-value">${fmtVal(a.value)}</div>
      <div class="anom-sep">vs typical</div>
      <div class="anom-baseline">${fmtVal(a.baseline_mean)}</div>
      <div class="anom-z">${a.value > a.baseline_mean ? '+' : '-'}${Math.round(a.pct_change)}%</div>
    </div>
    ${a.description ? `<div class="anom-desc">${a.description}</div>` : ''}
  </li>`;
}).join('') || '<li class="muted">No notable anomalies.</li>';
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
