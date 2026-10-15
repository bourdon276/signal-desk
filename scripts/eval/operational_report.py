"""Read-only, reproducible summary of exported run JSON; never calls providers."""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def distribution(values):
    values = sorted(values)
    return {"n": len(values), "p50": values[math.ceil(len(values) * .5) - 1] if values else None,
            "p95": values[math.ceil(len(values) * .95) - 1] if values else None,
            "sum": round(sum(values), 6) if values else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    export = json.loads(raw)
    runs = export.get("runs") if isinstance(export, dict) else export
    if not isinstance(runs, list) or any(not isinstance(row, dict) or not row.get("id") for row in runs):
        raise SystemExit("Expected exported runs array with an id on every record")
    seen, repeated = {}, 0
    for row in runs:
        if row["id"] in seen:
            if row != seen[row["id"]]:
                raise SystemExit("Conflicting snapshots for one run id; choose one export")
            repeated += 1
        seen[row["id"]] = row
    groups = {}
    for kind in sorted({row.get("kind", "unknown") for row in seen.values()}):
        rows = [row for row in seen.values() if row.get("kind", "unknown") == kind]
        statuses = Counter(row.get("status", "unknown") for row in rows)
        terminal = sum(statuses.get(status, 0) for status in ("success", "failure", "partial"))
        durations, costs, tools, errors = [], [], Counter(), Counter()
        for row in rows:
            duration = row.get("duration_ms")
            if not finite(duration) and row.get("started_at") and row.get("finished_at"):
                try:
                    start = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(row["finished_at"].replace("Z", "+00:00"))
                    # Unknown timezone is not silently assumed.
                    if start.tzinfo and end.tzinfo:
                        duration = (end - start).total_seconds() * 1000
                except (ValueError, TypeError):
                    pass
            if finite(duration) and row.get("status") in {"success", "failure", "partial"}:
                durations.append(round(duration, 3))
            trace = row.get("trace") or {}
            if not isinstance(trace, dict):
                continue
            cost = trace.get("estimated_cost_cny")
            if finite(cost) and not trace.get("usage_unknown"):
                costs.append(cost)
            for tool in trace.get("tools", []):
                if isinstance(tool, dict):
                    tools[str(tool.get("status", "unknown"))] += 1
            # Only fixed error codes, never raw prompts, bodies or account data.
            reason = trace.get("fallback_reason") or trace.get("error")
            if isinstance(reason, str) and len(reason) <= 60 and all(c.isalnum() or c == '_' for c in reason):
                errors[reason] += 1
        groups[kind] = {
            "runs": len(rows), "status_counts": dict(statuses), "terminal_runs": terminal,
            "execution_success_fraction": {"numerator": statuses.get("success", 0), "denominator": terminal},
            "terminal_duration_ms_nearest_rank": distribution(durations),
            "duration_missing_or_not_terminal": len(rows) - len(durations),
            "estimated_cost_cny": distribution(costs), "cost_missing_or_usage_unknown": len(rows) - len(costs),
            "tool_status_counts": dict(tools), "recorded_failure_codes": dict(errors),
        }
    result = {
        "schema": "operational-report-v1", "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": export.get("scope", "provided_export_only") if isinstance(export, dict) else "provided_export_only",
        "unique_runs": len(seen), "duplicate_rows_removed": repeated,
        "run_ids": sorted(seen), "by_kind": groups,
        "limitations": [
            "Provided export only: latest-50 exports cannot establish all-site uptime or retention.",
            "Execution success does not establish factual accuracy or citation entailment.",
            "Estimated model cost is configuration-derived, not a reconciled provider bill.",
            "Cold starts are not separated unless recorded by the source. Small-sample p95 is unstable.",
            "SHA256 detects changes; it does not prove authenticity. Corroborate with deployment/provider records.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Report written: {len(seen)} unique runs; no provider requests made.")


if __name__ == "__main__":
    main()
