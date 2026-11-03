"""Merge Vitest results into services/api/engine/verified.json (client-side tools' evidence).

Test titles start with registry keys, e.g. "dev.data_convert:json->yaml preserves content" or
"neg:dev.base64 rejects invalid input". A key passes only if every test naming it passed.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / ".data" / "vitest-results.json"
VERIFIED = ROOT / "services" / "api" / "engine" / "verified.json"
KEY = re.compile(r"(neg:[a-z0-9_]+\.[a-z0-9_]+|[a-z0-9_]+\.[a-z0-9_]+:[a-z0-9]+->[a-z0-9]+)")


def main() -> int:
    report = json.loads(REPORT.read_text())
    results: dict[str, list[str]] = {}
    for f in report.get("testResults", []):
        for a in f.get("assertionResults", []):
            for key in KEY.findall(a.get("title", "")):
                results.setdefault(key, []).append(a.get("status", "failed"))
    data = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {"pairs": {}}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for key, sts in results.items():
        st = "failed" if any(s not in ("passed", "skipped", "pending", "todo") for s in sts) else (
            "passed" if "passed" in sts else "skipped")
        data["pairs"][key] = {"status": st, "at": now, "tests": len(sts), "by": "vitest"}
    data["pairs"] = dict(sorted(data["pairs"].items()))
    VERIFIED.write_text(json.dumps(data, indent=1) + "\n")
    print(f"merged {len(results)} client-side keys from Vitest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
