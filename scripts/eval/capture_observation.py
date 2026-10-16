"""Archive an allowlisted collection snapshot; no provider calls or collection POST."""

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

URL = "https://signal-desk-demo.onrender.com/api/admin/sync/observation?days=7"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("redirect_refused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    envelope = {"schema": "collection-capture-v1", "captured_at": datetime.now(UTC).isoformat(),
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                "workflow_commit": os.environ.get("GITHUB_SHA"), "status": "failure"}
    try:
        token = os.environ.get("SYNC_TRIGGER_TOKEN", "")
        if len(token) < 32:
            raise RuntimeError("missing_sync_token")
        request = urllib.request.Request(URL, headers={"X-Sync-Token": token})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise RuntimeError("snapshot_too_large")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != "collection-observation-v1":
            raise RuntimeError("unexpected_snapshot_schema")
        envelope.update(status="success", snapshot=data, response_sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        # No raw response, exception text or headers in public workflow artifacts.
        envelope["error_type"] = type(exc).__name__
        if isinstance(exc, urllib.error.HTTPError):
            envelope["http_status"] = exc.code
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
    print("Collection evidence capture:", envelope["status"])
    if envelope["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
