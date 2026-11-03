"""What a converter's `run(ctx)` receives, plus the error type it raises."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import sandbox
from .formats import FORMATS


class ConversionError(Exception):
    """A failure the user can act on. `code` is a stable error class for logs/UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class InputFile:
    path: Path
    format: str
    size: int
    index: int
    stem: str = "file"  # safe stem used for multi-output naming inside the job only
    name: str = ""  # sanitized original filename: metadata only (e.g. a name *inside* a ZIP), never a disk path


@dataclass
class Output:
    path: Path
    format: str
    label: str | None = None
    name: str | None = None  # download name override (sanitized again by the worker)


@dataclass
class Ctx:
    inputs: list[InputFile]
    target: str
    options: object
    out_dir: Path
    work_dir: Path
    job_dir: Path
    timeout_s: float
    emit: Callable[[dict], None]
    limits: dict = field(default_factory=dict)
    outputs: list[Output] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    _last_emit: float = 0.0

    @property
    def input(self) -> InputFile:
        return self.inputs[0]

    # --- progress -------------------------------------------------------
    def progress(self, done: float | None = None, total: float | None = None, *, stage: str | None = None,
                 message: str | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and done is not None and now - self._last_emit < 0.1 and (total is None or done < total):
            return
        self._last_emit = now
        ev: dict = {"t": "progress"}
        if done is not None and total:
            ev["done"] = done
            ev["total"] = total
        if stage:
            ev["stage"] = stage
        if message:
            ev["message"] = message
        self.emit(ev)

    def stage(self, name: str) -> None:
        self.progress(stage=name, force=True)

    def notice(self, msg: str) -> None:
        if msg not in self.notices:
            self.notices.append(msg)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    # --- outputs --------------------------------------------------------
    def out_path(self, name: str) -> Path:
        p = (self.out_dir / name).resolve()
        if self.out_dir.resolve() not in p.parents:
            raise ConversionError("internal", "The converter produced a result we couldn't save.")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def default_out(self, fmt: str | None = None, suffix: str = "") -> Path:
        f = FORMATS[fmt or self.target]
        return self.out_path(f"output{suffix}.{f.ext}")

    def limit(self, key: str, default: int) -> int:
        env = os.environ.get(key.upper())
        return int(self.limits.get(key) or (env if env else default))

    def add_output(self, path: Path, fmt: str | None = None, label: str | None = None, name: str | None = None,
                   allow_empty: bool = False) -> Output:
        if not path.exists() or (path.stat().st_size == 0 and not allow_empty):
            raise ConversionError("engine_error", "The conversion produced an empty file. The input may be damaged or use features we can't convert.")
        o = Output(path, fmt or self.target, label, name)
        self.outputs.append(o)
        return o

    # --- nested engines -------------------------------------------------
    def run(self, cmd: Sequence[str], *, on_line: Callable[[bytes], None] | None = None,
            timeout_s: float | None = None, env: dict[str, str] | None = None, cwd: Path | None = None,
            check: bool = True, error_message: str = "The conversion engine failed on this file.") -> sandbox.Result:
        res = sandbox.run_sync(
            cmd,
            job_dir=self.job_dir,
            limits=sandbox.Limits(timeout_s=timeout_s or self.timeout_s, memory_mb=None),
            on_stdout_line=on_line,
            env=env,
            cwd=cwd or self.work_dir,
        )
        if res.timed_out:
            raise ConversionError("timeout", "The conversion took too long and was stopped. Try a smaller or simpler file.")
        if check and res.returncode != 0:
            raise ConversionError("engine_error", error_message + _tail(res.stderr_tail))
        return res


def _tail(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if not lines or os.environ.get("UC_DEBUG_ERRORS") != "1":
        return ""
    return f" ({lines[-1][:200]})"


def which(name: str, env_var: str | None = None) -> str:
    p = (os.environ.get(env_var) if env_var else None) or shutil.which(name)
    if not p:
        raise ConversionError("engine_missing", f"The {name} engine isn't installed on this server.")
    return p


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
