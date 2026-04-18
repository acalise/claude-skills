#!/usr/bin/env python3
"""
Parse an Apple Health export.zip (or export.xml) into compact CSV summaries
that Claude can read and reason over.

Usage:
  python3 parse.py --input /path/to/export.zip --out ./health-summary
  python3 parse.py --input /path/to/export.xml --out ./health-summary --since 2024-01-01
"""

import argparse
import csv
import io
import json
import math
import os
import statistics
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, date
from xml.etree import ElementTree as ET

# Metrics we care about. Maps HealthKit identifier suffix -> short name.
QUANTITY_METRICS = {
    "StepCount": "steps",
    "DistanceWalkingRunning": "distance_walk_run",
    "FlightsClimbed": "flights_climbed",
    "ActiveEnergyBurned": "active_energy",
    "BasalEnergyBurned": "basal_energy",
    "HeartRate": "heart_rate",
    "RestingHeartRate": "resting_hr",
    "HeartRateVariabilitySDNN": "hrv",
    "WalkingHeartRateAverage": "walking_hr",
    "AppleExerciseTime": "exercise_time",
    "AppleStandTime": "stand_time",
    "WalkingAsymmetryPercentage": "walking_asymmetry",
    "WalkingDoubleSupportPercentage": "walking_double_support",
    "WalkingStepLength": "walking_step_length",
    "WalkingSpeed": "walking_speed",
    "SixMinuteWalkTestDistance": "six_min_walk",
    "HeadphoneAudioExposure": "headphone_audio",
    "EnvironmentalAudioExposure": "env_audio",
    "MindfulSession": "mindful_minutes",
    "BodyMass": "body_mass",
    "BodyFatPercentage": "body_fat",
    "VO2Max": "vo2_max",
    "RespiratoryRate": "respiratory_rate",
    "OxygenSaturation": "spo2",
    "BloodPressureSystolic": "bp_systolic",
    "BloodPressureDiastolic": "bp_diastolic",
}

# Metrics where daily value should be summed vs averaged.
SUM_METRICS = {
    "steps", "distance_walk_run", "flights_climbed",
    "active_energy", "basal_energy", "exercise_time", "stand_time",
    "mindful_minutes",
}


def parse_ts(s):
    # Apple Health format: "2024-01-15 08:32:00 -0500"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def open_xml(input_path):
    """Return a file-like object for export.xml. Accepts zip or raw xml."""
    if input_path.endswith(".zip"):
        zf = zipfile.ZipFile(input_path)
        # Typical path: apple_health_export/export.xml
        candidates = [n for n in zf.namelist() if n.endswith("export.xml")]
        if not candidates:
            sys.exit("export.xml not found inside zip")
        return zf.open(candidates[0])
    return open(input_path, "rb")


def iso_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to export.zip or export.xml")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--since", default=None, help="Only include records on/after YYYY-MM-DD")
    args = ap.parse_args()

    since = datetime.fromisoformat(args.since).date() if args.since else None
    out = args.out
    os.makedirs(os.path.join(out, "daily"), exist_ok=True)
    os.makedirs(os.path.join(out, "weekly"), exist_ok=True)

    # daily_by_source[metric][source][date] = [values...]
    # We keep source dimension so we can dedupe after parsing — multiple
    # trackers (Garmin + iPhone + HeroBand) often all report the same metric
    # and naive summing inflates totals (e.g., 4000+ kcal basal energy).
    daily_by_source = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    workouts = []
    sleep_records = []  # (date, stage, minutes)
    sources = defaultdict(int)
    # metric_sources[metric_short][source_name] = count
    metric_sources = defaultdict(lambda: defaultdict(int))

    min_date = None
    max_date = None

    stream = open_xml(args.input)
    context = ET.iterparse(stream, events=("end",))

    for event, elem in context:
        tag = elem.tag
        if tag == "Record":
            rtype = elem.attrib.get("type", "")
            start = elem.attrib.get("startDate")
            if not start:
                elem.clear(); continue
            try:
                start_dt = parse_ts(start)
            except Exception:
                elem.clear(); continue
            d = start_dt.date()
            if since and d < since:
                elem.clear(); continue
            if min_date is None or d < min_date: min_date = d
            if max_date is None or d > max_date: max_date = d

            sources[elem.attrib.get("sourceName", "")] += 1

            # Sleep is a category record
            if rtype.endswith("SleepAnalysis"):
                end = elem.attrib.get("endDate")
                try:
                    end_dt = parse_ts(end)
                except Exception:
                    elem.clear(); continue
                minutes = (end_dt - start_dt).total_seconds() / 60.0
                stage = elem.attrib.get("value", "").replace("HKCategoryValueSleepAnalysis", "")
                sleep_records.append((d.isoformat(), stage, round(minutes, 1)))
                elem.clear(); continue

            # Mindful sessions are category records too (no value)
            if rtype.endswith("MindfulSession"):
                end = elem.attrib.get("endDate")
                try:
                    end_dt = parse_ts(end)
                except Exception:
                    elem.clear(); continue
                minutes = (end_dt - start_dt).total_seconds() / 60.0
                src = elem.attrib.get("sourceName", "")
                daily_by_source["mindful_minutes"][src][d.isoformat()].append(minutes)
                metric_sources["mindful_minutes"][src] += 1
                elem.clear(); continue

            # Quantity records
            for suffix, short in QUANTITY_METRICS.items():
                if rtype.endswith(suffix):
                    val = elem.attrib.get("value")
                    if val is None:
                        break
                    try:
                        v = float(val)
                    except ValueError:
                        break
                    src = elem.attrib.get("sourceName", "")
                    daily_by_source[short][src][d.isoformat()].append(v)
                    metric_sources[short][src] += 1
                    break
            elem.clear()

        elif tag == "Workout":
            start = elem.attrib.get("startDate")
            if not start:
                elem.clear(); continue
            try:
                start_dt = parse_ts(start)
            except Exception:
                elem.clear(); continue
            d = start_dt.date()
            if since and d < since:
                elem.clear(); continue
            if min_date is None or d < min_date: min_date = d
            if max_date is None or d > max_date: max_date = d
            workouts.append({
                "date": d.isoformat(),
                "activity": elem.attrib.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
                "duration_min": float(elem.attrib.get("duration", 0) or 0),
                "distance": float(elem.attrib.get("totalDistance", 0) or 0),
                "distance_unit": elem.attrib.get("totalDistanceUnit", ""),
                "energy_kcal": float(elem.attrib.get("totalEnergyBurned", 0) or 0),
                "source": elem.attrib.get("sourceName", ""),
            })
            elem.clear()

    # Dedupe: collapse daily_by_source -> daily_values by picking the preferred
    # source per metric (most records overall) and falling back to the next-best
    # source on days the preferred one has no data. This prevents multi-tracker
    # double counting (Garmin + iPhone + HeroBand all reporting the same metric).
    preferred_source_per_metric = {}
    daily_values = defaultdict(dict)
    for metric, by_src in daily_by_source.items():
        # Rank sources by total record count.
        ranked = sorted(by_src.keys(),
                        key=lambda s: -sum(len(v) for v in by_src[s].values()))
        preferred_source_per_metric[metric] = ranked[0] if ranked else None
        # Collect every date across any source, pick values from highest-ranked
        # source that has data that day.
        all_dates = set()
        for s in ranked:
            all_dates.update(by_src[s].keys())
        for d_iso in all_dates:
            for s in ranked:
                vals = by_src[s].get(d_iso)
                if vals:
                    daily_values[metric][d_iso] = vals
                    break

    # Write daily CSVs
    daily_summary = {}
    for metric, days in daily_values.items():
        rows = []
        for d_iso in sorted(days):
            vals = days[d_iso]
            if not vals:
                continue
            if metric in SUM_METRICS:
                agg = sum(vals)
            else:
                agg = statistics.mean(vals)
            rows.append({
                "date": d_iso,
                "value": round(agg, 3),
                "samples": len(vals),
                "min": round(min(vals), 3),
                "max": round(max(vals), 3),
            })
        path = os.path.join(out, "daily", f"{metric}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "value", "samples", "min", "max"])
            w.writeheader()
            w.writerows(rows)
        daily_summary[metric] = len(rows)

    # Write weekly rollups
    for metric, days in daily_values.items():
        weekly = defaultdict(list)
        for d_iso, vals in days.items():
            d = date.fromisoformat(d_iso)
            if metric in SUM_METRICS:
                weekly[iso_week(d)].append(sum(vals))
            else:
                weekly[iso_week(d)].extend(vals)
        rows = []
        for wk in sorted(weekly):
            vs = weekly[wk]
            if not vs:
                continue
            rows.append({
                "week": wk,
                "mean": round(statistics.mean(vs), 3),
                "median": round(statistics.median(vs), 3),
                "min": round(min(vs), 3),
                "max": round(max(vs), 3),
                "std": round(statistics.pstdev(vs), 3) if len(vs) > 1 else 0,
                "n_days": len(vs),
            })
        path = os.path.join(out, "weekly", f"{metric}.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["week", "mean", "median", "min", "max", "std", "n_days"])
            w.writeheader()
            w.writerows(rows)

    # Sleep
    sleep_daily = defaultdict(lambda: defaultdict(float))
    for d_iso, stage, minutes in sleep_records:
        sleep_daily[d_iso][stage] += minutes
    with open(os.path.join(out, "sleep.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "asleep_core", "asleep_deep", "asleep_rem", "asleep_unspecified", "awake", "inbed", "total_asleep_min"])
        for d_iso in sorted(sleep_daily):
            s = sleep_daily[d_iso]
            asleep_total = s.get("AsleepCore", 0) + s.get("AsleepDeep", 0) + s.get("AsleepREM", 0) + s.get("AsleepUnspecified", 0) + s.get("Asleep", 0)
            w.writerow([
                d_iso,
                round(s.get("AsleepCore", 0), 1),
                round(s.get("AsleepDeep", 0), 1),
                round(s.get("AsleepREM", 0), 1),
                round(s.get("AsleepUnspecified", 0) + s.get("Asleep", 0), 1),
                round(s.get("Awake", 0), 1),
                round(s.get("InBed", 0), 1),
                round(asleep_total, 1),
            ])

    # Workouts
    with open(os.path.join(out, "workouts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "activity", "duration_min", "distance", "distance_unit", "energy_kcal", "source"])
        w.writeheader()
        for wk in sorted(workouts, key=lambda x: x["date"]):
            w.writerow(wk)

    # Anomaly pre-pass: z-score weeks vs rolling trailing-12-week mean/std.
    anomalies = []
    for metric in daily_values:
        path = os.path.join(out, "weekly", f"{metric}.csv")
        with open(path) as f:
            rows = list(csv.DictReader(f))
        means = [float(r["mean"]) for r in rows]
        for i, r in enumerate(rows):
            window = means[max(0, i - 12):i]
            if len(window) < 4:
                continue
            mu = statistics.mean(window)
            sd = statistics.pstdev(window) or 1e-9
            z = (float(r["mean"]) - mu) / sd
            if abs(z) >= 2.0:
                anomalies.append({
                    "metric": metric,
                    "week": r["week"],
                    "value": float(r["mean"]),
                    "baseline_mean": round(mu, 3),
                    "z_score": round(z, 2),
                    "direction": "high" if z > 0 else "low",
                })
    anomalies.sort(key=lambda a: (a["week"], -abs(a["z_score"])))

    # Classify data sources to detect primary tracker.
    # Apple Watch = first-party wearable. Garmin "Connect", Fitbit, Whoop, Oura,
    # Polar, Wahoo, Coros, Suunto = third-party wearables. iPhone / bare names =
    # phone-only (gait metrics from phone are noisy because they depend on pocket carry).
    WEARABLE_MARKERS = ("Apple Watch", "Connect", "Fitbit", "Whoop", "Oura",
                        "Polar", "Wahoo", "Coros", "Suunto", "Garmin")
    PHONE_ONLY_GAIT = {"walking_asymmetry", "walking_double_support",
                       "walking_step_length", "walking_speed", "six_min_walk"}

    def classify(name):
        for m in WEARABLE_MARKERS:
            if m.lower() in name.lower():
                return "wearable"
        if "iphone" in name.lower():
            return "phone"
        return "other"  # could be a scale, BP cuff, cheap BT band, manual

    # Primary activity source = which source has the most step records.
    step_sources = sorted(metric_sources.get("steps", {}).items(), key=lambda x: -x[1])
    primary_activity_source = step_sources[0][0] if step_sources else None
    primary_class = classify(primary_activity_source) if primary_activity_source else None

    # Detect any dedicated third-party wearable anywhere in the source pool with
    # meaningful volume (>= 5000 records across all metrics). If one exists, the
    # user has a real tracker and any iPhone-derived gait metrics are phone-carry
    # noise — they're not coming from the wearable.
    wearable_present = None
    wearable_markers_third_party = ("Connect", "Garmin", "Fitbit", "Whoop",
                                     "Oura", "Polar", "Wahoo", "Coros", "Suunto")
    for src_name, total in sorted(sources.items(), key=lambda x: -x[1]):
        if total < 5000:
            break
        if any(m.lower() in src_name.lower() for m in wearable_markers_third_party):
            wearable_present = src_name
            break

    low_confidence = []
    if wearable_present:
        for m in PHONE_ONLY_GAIT:
            if m in daily_values:
                low_confidence.append({
                    "metric": m,
                    "reason": f"iPhone-derived gait metric; user's primary wearable is '{wearable_present}' which does not report gait. Values reflect phone-carry, not biomechanics — do not build injury narratives from this.",
                })

    # Drop anomalies on low-confidence metrics so Claude doesn't lead with them.
    low_conf_set = {lc["metric"] for lc in low_confidence}
    anomalies_filtered = [a for a in anomalies if a["metric"] not in low_conf_set]

    # Top 3 sources per metric (so Claude can audit provenance).
    metric_sources_top = {
        m: sorted(src.items(), key=lambda x: -x[1])[:3]
        for m, src in metric_sources.items()
    }

    # Index
    index = {
        "date_range": {
            "start": min_date.isoformat() if min_date else None,
            "end": max_date.isoformat() if max_date else None,
        },
        "metrics_available": sorted(daily_values.keys()),
        "days_per_metric": daily_summary,
        "n_workouts": len(workouts),
        "n_sleep_days": len(sleep_daily),
        "top_sources": sorted(sources.items(), key=lambda x: -x[1])[:10],
        "primary_activity_source": primary_activity_source,
        "primary_activity_class": primary_class,
        "metric_sources_top": metric_sources_top,
        "preferred_source_per_metric": preferred_source_per_metric,
        "low_confidence_metrics": low_confidence,
        "anomalies": anomalies_filtered,
        "anomalies_suppressed_low_confidence": len(anomalies) - len(anomalies_filtered),
    }
    with open(os.path.join(out, "index.json"), "w") as f:
        json.dump(index, f, indent=2, default=str)

    print(f"Parsed {sum(len(v) for v in daily_values.values())} daily metric points across {len(daily_values)} metrics.")
    print(f"Workouts: {len(workouts)}. Sleep days: {len(sleep_daily)}. Anomalies flagged: {len(anomalies)}.")
    print(f"Output: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
