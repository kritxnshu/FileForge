"""Shared test infrastructure.

* Isolated Redis + storage per test session.
* `convert(...)`: run one operation through the real sandboxed job process.
* `live_api`: real uvicorn + real arq worker processes for HTTP-level tests.
* The `verifies(*keys)` marker records outcomes into engine/verified.json —
  that file is what decides which pairs the API advertises (DECISIONS D7).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2] / "services" / "api"
TMP = Path(tempfile.mkdtemp(prefix="uc-test-")).resolve()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


REDIS_PORT = free_port()
os.environ.update(
    STORAGE_DIR=str(TMP / "storage"),
    REDIS_URL=f"redis://127.0.0.1:{REDIS_PORT}/0",
    COOKIE_SECURE="false",
    LOG_LEVEL="WARNING",
)
os.environ.setdefault("ENABLE_EXPERIMENTAL", "true")  # experimental ops are tested too; flags only hide them in the UI

sys.path.insert(0, str(API_DIR))

from engine import child_cmd, registry, sandbox  # noqa: E402
from engine.formats import FORMATS  # noqa: E402

# ---------------------------------------------------------------------------
# verification recording

_results: dict[str, list[str]] = {}


def pytest_configure(config):
    config.addinivalue_line("markers", "verifies(*keys): record this test's outcome as evidence for these registry keys")
    config.addinivalue_line("markers", "live: needs the live API + workers")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    m = item.get_closest_marker("verifies")
    if not m:
        return
    if rep.when == "call" or (rep.when == "setup" and (rep.failed or rep.skipped)):
        status = "passed" if rep.passed else "skipped" if rep.skipped else "failed"
        for key in m.args:
            _results.setdefault(key, []).append(status)


def pytest_sessionfinish(session, exitstatus):
    if not _results or os.environ.get("UC_NO_RECORD") == "1":
        return
    path = registry.VERIFIED_PATH
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        data = {"pairs": {}}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for key, statuses in _results.items():
        st = "failed" if "failed" in statuses else "skipped" if "skipped" in statuses else "passed"
        data["pairs"][key] = {"status": st, "at": now, "tests": len(statuses)}
    data["pairs"] = dict(sorted(data["pairs"].items()))
    data["generated_by"] = "pytest (tests/api/conftest.py)"
    path.write_text(json.dumps(data, indent=1) + "\n")


def pytest_unconfigure(config):
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------------------
# direct conversion through the sandboxed job process


@dataclass
class Converted:
    ok: bool
    outputs: list[tuple[Path, str]] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: dict | None = None
    info: dict = field(default_factory=dict)
    progress: list[dict] = field(default_factory=list)
    job_dir: Path | None = None

    @property
    def out(self) -> Path:
        assert self.ok, f"conversion failed: {self.error}"
        return self.outputs[0][0]


def detect_format(p: Path) -> str:
    from engine.detect import detect

    det = detect(p, p.name, probe_dir=TMP / "probe")
    assert det.format, f"fixture {p.name} not detected: {det.error}"
    return det.format


def convert(op_id: str, inputs: list[Path] | Path, target: str | None = None, options: dict | None = None,
            timeout: float = 120, formats: list[str] | None = None) -> Converted:
    if isinstance(inputs, Path):
        inputs = [inputs]
    op = registry.get(op_id)
    assert op, op_id
    job = TMP / "jobs" / f"{op_id}-{time.monotonic_ns()}"
    (job / "in").mkdir(parents=True)
    specs = []
    for n, src in enumerate(inputs):
        fmt = formats[n] if formats else detect_format(src)
        dst = job / "in" / f"{n}.{FORMATS[fmt].ext}"
        shutil.copyfile(src, dst)
        specs.append({"path": str(dst), "format": fmt, "size": dst.stat().st_size,
                      "stem": "output" if len(inputs) == 1 else f"file{n + 1}"})
    tgt = target or specs[0]["format"]
    (job / "spec.json").write_text(json.dumps({"operation": op_id, "target": tgt, "options": options or {},
                                               "inputs": specs, "timeout_s": timeout,
                                               "limits": {"max_image_pixels": 100_000_000}}))
    progress: list[dict] = []

    def line(b: bytes) -> None:
        try:
            progress.append(json.loads(b))
        except ValueError:
            pass

    res = sandbox.run_sync(child_cmd(job), job_dir=job, limits=sandbox.Limits(timeout_s=timeout, memory_mb=op.memory_mb if op.memory_mb != -1 else 4096),
                           on_stdout_line=line)
    if res.timed_out:
        return Converted(False, error={"code": "timeout"}, progress=progress, job_dir=job)
    if res.returncode == 0:
        r = json.loads((job / "result.json").read_text())
        return Converted(True, [(job / o["path"], o["format"]) for o in r["outputs"]], r["notices"], r["warnings"],
                         None, r.get("info", {}), progress, job)
    err = json.loads((job / "error.json").read_text()) if (job / "error.json").exists() else \
        {"code": "crash", "message": res.stderr_tail[-2000:]}
    return Converted(False, error=err, progress=progress, job_dir=job)


def pairs_of(op_id: str, only_available: bool = True):
    """pytest params for every (src, dst) pair of an operation, each marked as evidence for its key."""
    op = registry.get(op_id)
    assert op, op_id
    out = []
    for s, d in op.pairs():
        marks = [pytest.mark.verifies(op.key(s, d))]
        missing = registry.missing_engines(op, s, d)
        if missing and only_available:
            marks.append(pytest.mark.skip(reason=f"engine missing: {missing}"))
        out.append(pytest.param(s, d, marks=marks, id=f"{s}->{d}"))
    return out


# ---------------------------------------------------------------------------
# live API


def _wait(url: str, timeout: float = 30) -> None:
    import httpx

    end = time.time() + timeout
    while time.time() < end:
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code == 200 and all(r.json()["workers"].values()):
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"service at {url} did not become healthy")


@pytest.fixture(scope="session")
def redis_server():
    exe = shutil.which("redis-server")
    if not exe:
        pytest.skip("redis-server not installed")
    p = subprocess.Popen([exe, "--port", str(REDIS_PORT), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import redis as _r

    for _ in range(100):
        try:
            if _r.Redis(port=REDIS_PORT).ping():
                break
        except Exception:
            time.sleep(0.05)
    yield f"redis://127.0.0.1:{REDIS_PORT}/0"
    p.terminate()
    p.wait()


@dataclass
class Live:
    base: str
    env: dict
    procs: dict

    def client(self):
        import httpx

        return httpx.Client(base_url=self.base, timeout=60)


def start_live(env_overrides: dict | None = None, name: str = "main"):
    port = free_port()
    storage = TMP / f"storage-{name}"
    env = {**os.environ, "STORAGE_DIR": str(storage), "PYTHONPATH": str(API_DIR), **(env_overrides or {})}
    logs = TMP / f"logs-{name}"
    logs.mkdir(exist_ok=True)
    py = sys.executable
    procs = {
        "api": subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--port", str(port), "--host", "127.0.0.1"],
                                cwd=API_DIR, env=env, stdout=open(logs / "api.log", "w"), stderr=subprocess.STDOUT),
        "fast": subprocess.Popen([py, "-m", "arq", "worker.FastWorker"], cwd=API_DIR, env=env,
                                 stdout=open(logs / "fast.log", "w"), stderr=subprocess.STDOUT),
        "heavy": subprocess.Popen([py, "-m", "arq", "worker.HeavyWorker"], cwd=API_DIR, env=env,
                                  stdout=open(logs / "heavy.log", "w"), stderr=subprocess.STDOUT),
    }
    base = f"http://127.0.0.1:{port}"
    try:
        _wait(base + "/api/health", 60)
    except RuntimeError:
        for n, p in procs.items():
            p.terminate()
        raise RuntimeError("live API failed to start:\n" + "\n".join(
            f"--- {f.name}\n{f.read_text()[-3000:]}" for f in logs.iterdir()))
    return Live(base, env, procs)


def stop_live(live: Live) -> None:
    for p in live.procs.values():
        p.terminate()
    for p in live.procs.values():
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


@pytest.fixture(scope="session")
def live(redis_server):
    lv = start_live()
    yield lv
    stop_live(lv)


@pytest.fixture
def client(live):
    with live.client() as c:
        yield c


def upload(client, *paths: Path, names: list[str] | None = None):
    files = [("files", ((names[i] if names else p.name), p.read_bytes(), "application/octet-stream"))
             for i, p in enumerate(paths)]
    return client.post("/api/uploads", files=files)


def wait_job(client, job_id: str, timeout: float = 120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed", "cancelled", "expired"):
            return j
        time.sleep(0.1)
    raise TimeoutError(job_id)
