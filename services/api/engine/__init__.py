"""Universal Converter conversion engine."""

from __future__ import annotations

import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def child_cmd(job_dir: Path) -> list[str]:
    """Command that runs one job inside the sandbox.

    `-I` keeps the (attacker-influenced) working directory and env vars off
    sys.path; the trusted code directory is added explicitly instead.
    """
    boot = f"import sys; sys.path.insert(0, {str(API_DIR)!r}); from engine.child import main; sys.exit(main(sys.argv[1]))"
    return [sys.executable, "-I", "-c", boot, str(job_dir)]
