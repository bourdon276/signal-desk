"""Combine overlapping collection captures by run id for an explicit time window."""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return result.astimezone(UTC)


def distribution(values):
    values = sorted(values)
    return {"n": len(values), "p50": values[math.ceil(len(values) * .5) - 1] if values else None,
            "p95": values[math.ceil(len(values) * .95) - 1] if values else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start, end = timestamp(args.start), timestamp(args.end)
    if start >= end:
        raise SystemExit("start must precede end")
    captures, hashes, failures, truncated, seen, unique_hashes = [], [], [], [], {}, set()
    for path in args.input:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in unique_hashes:
            continue
        unique_hashes.add(digest)
        data = json.loads(raw)
        if data.get("schema") != "collection-capture-v1":
            raise SystemExit("Unexpected capture schema")
        hashes.append(digest)
        captures.append(data)
    for data in sorted(captures, key=lambda row: timestamp(row["captured_at"])):
        if data.get("status") != "success":
            failures.append({key: data.get(key) for key in ("captured_at", "error_type", "http_status")})
            continue
        snapshot = data["snapshot"]
        if snapshot.get("schema") != "collection-observation-v1":
            raise SystemExit("Unexpected snapshot schema")
        if snapshot.get("runs_truncated"):
            truncated.append(data["captured_at"])
        for run in snapshot["runs"]:
            if start <= timestamp(run["started_at"]) < end:
                # The same running job can appear in many snapshots; retain its newest state.
                seen[run["id"]] = run
    statuses = Counter(row["status"] for row in seen.values())
    daily = Counter(timestamp(row["started_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    for row in seen.values())
    sources, durations = {}, []
    for run in seen.values():
        duration = run.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration):
            if duration >= 0 and run["status"] in {"success", "partial", "failure"}:
                durations.append(duration)
        for name, value in run.get("sources", {}).items():
            target = sources.setdefault(name, {"reported_rounds": 0, "status_counts": {}, "counters": {}})
            target["reported_rounds"] += 1
            state = value.get("status", "unknown")
            target["status_counts"][state] = target["status_counts"].get(state, 0) + 1
            for key, count in value.items():
                if type(count) is int and count >= 0:
                    metric = target["counters"].setdefault(key, {"sum": 0, "recorded_rounds": 0})
                    metric["sum"] += count
                    metric["recorded_rounds"] += 1
    dates = []
    day = start.astimezone(ZoneInfo("Asia/Shanghai")).date()
    while day <= (end - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Shanghai")).date():
        dates.append(day.isoformat())
        day += timedelta(days=1)
    result = {
        "schema": "collection-report-v1", "generated_at": datetime.now(UTC).isoformat(),
        "window_start_inclusive": start.isoformat(), "window_end_exclusive": end.isoformat(),
        "window_has_ended": datetime.now(UTC) >= end, "input_sha256": sorted(hashes),
        "capture_count": len(captures), "capture_failures": failures, "truncated_captures": truncated,
        "unique_collection_runs": len(seen), "status_counts": dict(statuses),
        "run_deployment_counts": dict(Counter(row.get("deployed_commit") or "unknown" for row in seen.values())),
        "terminal_duration_ms_nearest_rank": distribution(durations),
        "duration_missing_or_not_terminal": len(seen) - len(durations),
        "beijing_daily_run_counts": {date: daily.get(date, 0) for date in dates},
        "dates_without_observed_runs": [date for date in dates if date not in daily],
        "sources": sources,
        "limitations": [
            "An observed run is not proof that all scheduled jobs ran or that the site was available.",
            "Empty dates can be future dates, missing evidence or missing jobs; do not silently discard them.",
            "Partial, cached, unconfigured and quota-skipped sources remain separate from success.",
            "Inventory windows overlap and are deliberately not summed; no whole-web recall is claimed.",
            "Counts are execution evidence, not useful-news counts, factual accuracy or actual billing.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved observation report: {len(seen)} distinct collection runs from {len(captures)} captures.")


if __name__ == "__main__":
    main()
