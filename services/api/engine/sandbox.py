"""The one subprocess runner. Every engine process starts here.

Guarantees for each child:
  * its own session / process group, killed as a whole on timeout or cancel
  * rlimits: CPU seconds, output file size, open files, core dumps off, and
    address space where the kernel enforces it (Linux; see DECISIONS D5)
  * no network and no writes outside the job directory, via
      - macOS: Seatbelt (sandbox-exec) profile           (DECISIONS D4)
      - Linux: bubblewrap when installed (--unshare-net, read-only root)
      - otherwise limits + timeouts only (reported by /api/health)
  * a non-root uid when the service itself runs as root
  * a scrubbed environment (HOME/TMPDIR point into the job directory)
"""

from __future__ import annotations

import asyncio
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
SANDBOX_UID = int(os.environ.get("SANDBOX_UID", "65534"))
_ISOLATION_DISABLED = os.environ.get("SANDBOX_ISOLATION", "auto") == "off"


@dataclass
class Limits:
    timeout_s: float = 60
    memory_mb: int | None = 2048  # None = no address-space limit (e.g. Chromium reserves huge VA)
    cpu_s: int | None = None  # defaults to timeout*2
    fsize_mb: int = 2048
    nofile: int = 512


@dataclass
class Result:
    returncode: int
    timed_out: bool = False
    cancelled: bool = False
    stdout: bytes = b""
    stderr_tail: str = ""
    duration_s: float = 0.0
    signal: int | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


@dataclass
class Isolation:
    kind: str  # seatbelt | bwrap | limits-only | inherited
    detail: str = ""
    extra_read_roots: list[str] = field(default_factory=list)


def isolation_mode() -> Isolation:
    if os.environ.get("UC_IN_SANDBOX") == "1":
        return Isolation("inherited", "already inside a sandboxed job process")
    if _ISOLATION_DISABLED:
        return Isolation("limits-only", "SANDBOX_ISOLATION=off")
    if IS_MAC and shutil.which("sandbox-exec"):
        return Isolation("seatbelt", "macOS sandbox-exec: no network, writes confined to job dir, home dir unreadable")
    if IS_LINUX and shutil.which("bwrap"):
        return Isolation("bwrap", "bubblewrap: --unshare-net, read-only root, job dir writable")
    return Isolation("limits-only", "no bubblewrap/seatbelt available; rlimits + timeouts only")


# ---------------------------------------------------------------------------
# isolation wrappers


def _sb_quote(p: str) -> str:
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _read_roots() -> list[str]:
    """Paths under $HOME that a job process legitimately needs to read."""
    roots = {
        os.path.realpath(sys.prefix),
        os.path.realpath(sys.base_prefix),
        os.path.realpath(Path(__file__).resolve().parents[1]),  # services/api (engine code)
    }
    pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / "Library/Caches/ms-playwright")
    roots.add(os.path.realpath(pw))
    roots.add(os.path.realpath(Path.home() / "Library/Fonts"))
    roots.add(os.path.realpath(Path.home() / ".local/share/uv/python"))
    for extra in os.environ.get("SANDBOX_EXTRA_READ", "").split(os.pathsep):
        if extra:
            roots.add(os.path.realpath(extra))
    return sorted(roots)


def _seatbelt_profile(job_dir: str) -> str:
    home = os.path.realpath(Path.home())
    job = os.path.realpath(job_dir)
    reads = " ".join(f"(subpath {_sb_quote(r)})" for r in [*_read_roots(), job])
    return f"""(version 1)
(allow default)
(deny network*)
(allow network* (remote unix-socket (path-regex #"^{job}/")))
(allow network* (local unix-socket (path-regex #"^{job}/")))
(allow network* (remote unix-socket (path-regex #"^/private/tmp/OSL_PIPE_") (path-regex #"^/tmp/OSL_PIPE_")))
(allow network* (local unix-socket (path-regex #"^/private/tmp/OSL_PIPE_") (path-regex #"^/tmp/OSL_PIPE_")))
(deny file-write*)
(allow file-write* (subpath {_sb_quote(job)}) (literal "/dev/null") (literal "/dev/zero")
       (literal "/dev/stdout") (literal "/dev/stderr") (literal "/dev/dtracehelper") (regex #"^/dev/fd/") (regex #"^/dev/tty"))
(allow file-write* (regex #"^/private/var/folders/.*/(T|C)/"))
; LibreOffice's single-instance pipe lives in a hard-coded /tmp; it also touches the /tmp directory entry itself
; (root-owned + sticky, so this grants no way to alter other files there).
(allow file-write* (regex #"^/private/tmp/OSL_PIPE_") (regex #"^/tmp/OSL_PIPE_") (literal "/private/tmp"))
(deny file-read* (subpath {_sb_quote(home)}))
(allow file-read* {reads})
(allow file-read-metadata)
"""


def _wrap(cmd: Sequence[str], job_dir: Path) -> list[str]:
    iso = isolation_mode()
    if iso.kind == "seatbelt":
        return ["sandbox-exec", "-p", _seatbelt_profile(str(job_dir)), *cmd]
    if iso.kind == "bwrap":
        j = str(job_dir.resolve())
        return [
            "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/root",
            "--bind", j, j, "--unshare-net", "--unshare-ipc", "--die-with-parent", "--new-session",
            *cmd,
        ]
    return list(cmd)


def _preexec(limits: Limits) -> Callable[[], None]:
    cpu = limits.cpu_s or int(limits.timeout_s * 2) + 5

    def fn() -> None:
        def setl(res: int, val: int) -> None:
            try:
                soft, hard = resource.getrlimit(res)
                if hard != resource.RLIM_INFINITY:
                    val = min(val, hard)
                resource.setrlimit(res, (val, val if hard == resource.RLIM_INFINITY else hard))
            except (ValueError, OSError):
                pass  # not enforceable on this platform (DECISIONS D5)

        setl(resource.RLIMIT_CORE, 0)
        setl(resource.RLIMIT_CPU, cpu)
        setl(resource.RLIMIT_FSIZE, limits.fsize_mb * 1024 * 1024)
        setl(resource.RLIMIT_NOFILE, limits.nofile)
        if limits.memory_mb and IS_LINUX:
            setl(resource.RLIMIT_AS, limits.memory_mb * 1024 * 1024)
        if os.geteuid() == 0:
            os.setgid(SANDBOX_UID)
            os.setuid(SANDBOX_UID)

    return fn


def _env(job_dir: Path, extra: dict[str, str] | None) -> dict[str, str]:
    keep = ("PATH", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "SANDBOX_ISOLATION", "SANDBOX_UID",
            "SANDBOX_EXTRA_READ", "UC_FFMPEG", "UC_FFPROBE", "UC_SOFFICE", "UC_PANDOC")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    if IS_MAC and "/opt/homebrew/bin" not in env["PATH"]:
        env["PATH"] = "/opt/homebrew/bin:" + env["PATH"]
    home = job_dir / "home"
    tmp = job_dir / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp), UC_IN_SANDBOX="1",
               PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", LANG=env.get("LANG", "C.UTF-8"))
    env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "Library/Caches/ms-playwright") if IS_MAC else "/ms-playwright")
    if extra:
        env.update(extra)
    return env


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# ---------------------------------------------------------------------------
# async runner (used by the worker)


async def run(
    cmd: Sequence[str],
    *,
    job_dir: Path,
    limits: Limits,
    on_stdout_line: Callable[[bytes], Awaitable[None] | None] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> Result:
    job_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *_wrap(cmd, job_dir),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd or job_dir),
        env=_env(job_dir, env),
        start_new_session=True,
        preexec_fn=_preexec(limits),
        limit=1024 * 1024,
    )
    stderr_buf = bytearray()
    stdout_buf = bytearray()

    async def pump_stdout() -> None:
        assert proc.stdout
        while line := await proc.stdout.readline():
            if on_stdout_line:
                r = on_stdout_line(line)
                if asyncio.iscoroutine(r):
                    await r
            elif len(stdout_buf) < 4 * 1024 * 1024:
                stdout_buf.extend(line)

    async def pump_stderr() -> None:
        assert proc.stderr
        while chunk := await proc.stderr.read(65536):
            stderr_buf.extend(chunk)
            if len(stderr_buf) > 256 * 1024:
                del stderr_buf[: len(stderr_buf) - 64 * 1024]

    pumps = asyncio.gather(pump_stdout(), pump_stderr())
    timed_out = cancelled = False
    deadline = started + limits.timeout_s
    try:
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=0.25)
                break
            except TimeoutError:
                pass
            if time.monotonic() > deadline:
                timed_out = True
                _kill_group(proc.pid)
                break
            if cancel_check and await cancel_check():
                cancelled = True
                _kill_group(proc.pid)
                break
    except asyncio.CancelledError:
        _kill_group(proc.pid)
        raise
    finally:
        # The child may have left grandchildren in its group; clean them all.
        _kill_group(proc.pid)
    await proc.wait()
    try:
        await asyncio.wait_for(pumps, timeout=5)
    except TimeoutError:
        pass
    rc = proc.returncode if proc.returncode is not None else -9
    return Result(
        returncode=rc,
        timed_out=timed_out,
        cancelled=cancelled,
        stdout=bytes(stdout_buf),
        stderr_tail=bytes(stderr_buf[-8192:]).decode("utf-8", "replace"),
        duration_s=time.monotonic() - started,
        signal=-rc if rc < 0 else None,
    )


# ---------------------------------------------------------------------------
# sync runner (used inside job processes for nested engines, and for ffprobe
# during upload detection)


def run_sync(
    cmd: Sequence[str],
    *,
    job_dir: Path,
    limits: Limits,
    on_stdout_line: Callable[[bytes], None] | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    capture_stdout: bool = True,
) -> Result:
    job_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Nested engines (inside a job process) stay in the job's process group so the
    # worker's killpg() on cancel/timeout takes them down too.
    nested = os.environ.get("UC_IN_SANDBOX") == "1"
    proc = subprocess.Popen(
        _wrap(cmd, job_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd or job_dir),
        env={**os.environ, **(env or {})} if nested else _env(job_dir, env),
        start_new_session=not nested,
        preexec_fn=_preexec(limits),
    )
    import threading

    stderr_buf = bytearray()
    stdout_buf = bytearray()

    def pump_err() -> None:
        assert proc.stderr
        for chunk in iter(lambda: proc.stderr.read(65536), b""):
            stderr_buf.extend(chunk)
            if len(stderr_buf) > 256 * 1024:
                del stderr_buf[: len(stderr_buf) - 64 * 1024]

    def pump_out() -> None:
        assert proc.stdout
        for line in iter(proc.stdout.readline, b""):
            if on_stdout_line:
                on_stdout_line(line)
            if capture_stdout and len(stdout_buf) < 64 * 1024 * 1024:
                stdout_buf.extend(line)

    threads = [threading.Thread(target=pump_err, daemon=True), threading.Thread(target=pump_out, daemon=True)]
    for t in threads:
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=limits.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if nested:
            if proc.poll() is None:
                proc.kill()
        else:
            _kill_group(proc.pid)
        proc.wait()
    for t in threads:
        t.join(timeout=5)
    rc = proc.returncode
    return Result(
        returncode=rc,
        timed_out=timed_out,
        stdout=bytes(stdout_buf),
        stderr_tail=bytes(stderr_buf[-8192:]).decode("utf-8", "replace"),
        duration_s=time.monotonic() - started,
        signal=-rc if rc < 0 else None,
    )
