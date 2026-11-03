"""Conversion registry and chain planner.

Every capability is an `Operation`. Converter modules call `register(...)` at
import time; `load_all()` imports every module under `engine.converters`.

A *pair* is (operation, source format, target format). For same-format
transforms (rotate a PDF, compress an image) source == target.

Support levels are earned (DECISIONS D7): an operation declares its *target*
level; a pair is advertised only when `verified.json` records a passing test
for its key `"<op>:<src>-><dst>"`. Missing engines and disabled feature flags
also hide pairs.
"""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import shutil
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .formats import FORMATS

Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "transform"]
Level = Literal["full", "partial", "experimental", "unsupported"]

VERIFIED_PATH = Path(os.environ.get("UC_VERIFIED_PATH", Path(__file__).with_name("verified.json")))

CATEGORIES = [
    ("images", "Images"),
    ("documents", "Documents & PDF"),
    ("spreadsheets", "Spreadsheets"),
    ("presentations", "Presentations"),
    ("audio", "Audio"),
    ("video", "Video"),
    ("archives", "Archives"),
    ("developer", "Developer Tools"),
    ("utilities", "Utilities"),
]


class Options(BaseModel):
    """Base for every operation's options. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class NoOptions(Options):
    pass


def ui(*, advanced: bool = False, widget: str | None = None, targets: Iterable[str] | None = None, **extra: Any) -> dict:
    """json_schema_extra helper for form generation hints."""
    d: dict[str, Any] = {}
    if advanced:
        d["x-advanced"] = True
    if widget:
        d["x-widget"] = widget
    if targets is not None:
        d["x-targets"] = sorted(targets)
    d.update({f"x-{k}": v for k, v in extra.items()})
    return d


@dataclass
class Operation:
    id: str
    category: str
    label: str
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    cardinality: Cardinality
    options: type[Options] = NoOptions
    run: Callable[..., None] | None = None
    engines: tuple[str, ...] = ()
    format_engines: dict[str, tuple[str, ...]] = field(default_factory=dict)  # extra engines when a format is involved
    resource_class: Literal["fast", "heavy"] = "fast"
    heavy_over_mb: float | None = None  # promote to the heavy queue above this input size
    runtime: Literal["server", "client"] = "server"
    support: Level = "full"
    limitations: tuple[str, ...] = ()
    feature_flag: str | None = None
    exclude_pairs: frozenset[tuple[str, str]] = frozenset()
    pair_limitations: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    pair_support: dict[tuple[str, str], Level] = field(default_factory=dict)
    memory_mb: int | None = -1  # -1 = class default; None = no address-space limit
    min_inputs: int = 1
    max_inputs: int | None = None
    slug: str | None = None  # route slug for transforms ("pdf-merge"); pairs default to "<src>-to-<dst>"
    keywords: tuple[str, ...] = ()

    def pairs(self) -> list[tuple[str, str]]:
        if self.cardinality == "transform":
            out = [(f, f) for f in self.inputs]
        else:
            out = [(s, t) for s in self.inputs for t in self.outputs if s != t or self.cardinality == "many_to_one"]
        return [p for p in out if p not in self.exclude_pairs]

    def engines_for(self, src: str, dst: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.engines, *self.format_engines.get(src, ()), *self.format_engines.get(dst, ())]))

    def level(self, src: str, dst: str) -> Level:
        return self.pair_support.get((src, dst), self.support)

    def key(self, src: str, dst: str) -> str:
        return pair_key(self.id, src, dst)


def pair_key(op_id: str, src: str, dst: str) -> str:
    return f"{op_id}:{src}->{dst}"


def negative_key(op_id: str) -> str:
    return f"neg:{op_id}"


_REGISTRY: dict[str, Operation] = {}


def register(op: Operation) -> Operation:
    if op.id in _REGISTRY:
        raise ValueError(f"duplicate operation id {op.id}")
    for f in (*op.inputs, *op.outputs):
        if f not in FORMATS:
            raise ValueError(f"{op.id}: unknown format {f}")
    if op.category not in dict(CATEGORIES):
        raise ValueError(f"{op.id}: unknown category {op.category}")
    if op.support == "experimental" and not op.feature_flag:
        op.feature_flag = "ENABLE_EXPERIMENTAL"
    _REGISTRY[op.id] = op
    return op


@cache
def load_all() -> dict[str, Operation]:
    from . import converters

    for mod in pkgutil.walk_packages(converters.__path__, converters.__name__ + "."):
        importlib.import_module(mod.name)
    return _REGISTRY


def get(op_id: str) -> Operation | None:
    return load_all().get(op_id)


def all_ops() -> list[Operation]:
    return list(load_all().values())


# ---------------------------------------------------------------------------
# engines


ENGINE_PROBES: dict[str, Callable[[], str | None]] = {}


def _which_version(exe: str, args: list[str], env_var: str | None = None) -> Callable[[], str | None]:
    def probe() -> str | None:
        import subprocess

        path = (os.environ.get(env_var) if env_var else None) or shutil.which(exe)
        if not path:
            return None
        try:
            out = subprocess.run([path, *args], capture_output=True, text=True, timeout=30).stdout
        except Exception:
            return None
        return (out.strip().splitlines() or ["present"])[0][:120]

    return probe


def _py_version(mod: str, attr: str = "__version__") -> Callable[[], str | None]:
    def probe() -> str | None:
        try:
            m = importlib.import_module(mod)
            return str(getattr(m, attr, "present"))
        except Exception:
            return None

    return probe


def soffice_path() -> str | None:
    p = os.environ.get("UC_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice")
    if not p and Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists():
        p = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    return p


def _soffice_probe() -> str | None:
    p = soffice_path()
    if not p:
        return None
    import subprocess

    try:
        out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=60).stdout
        return out.strip().splitlines()[0][:120] if out.strip() else "present"
    except Exception:
        return None


def _chromium_probe() -> str | None:
    try:
        from playwright._repo_version import version  # type: ignore

        base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or (Path.home() / "Library/Caches/ms-playwright"))
        if not any(base.glob("chromium*")):
            return None
        return f"playwright {version}"
    except Exception:
        return None


def _avif_probe() -> str | None:
    try:
        import io

        from PIL import Image, features

        if not features.check("avif"):
            return None
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(buf, "AVIF")
        buf.seek(0)
        Image.open(buf).load()
        return "pillow avif encode+decode ok"
    except Exception:
        return None


ENGINE_PROBES.update(
    {
        "pillow": _py_version("PIL"),
        "avif": _avif_probe,
        "pillow-heif": _py_version("pillow_heif"),
        "resvg": _py_version("resvg_py", "__name__"),
        "vtracer": _py_version("vtracer", "__name__"),
        "pypdf": _py_version("pypdf"),
        "pikepdf": _py_version("pikepdf"),
        "pypdfium2": _py_version("pypdfium2", "V_PYPDFIUM2"),
        "pdfplumber": _py_version("pdfplumber"),
        "reportlab": _py_version("reportlab", "Version"),
        "img2pdf": _py_version("img2pdf"),
        "openpyxl": _py_version("openpyxl"),
        "pandas": _py_version("pandas"),
        "python-docx": _py_version("docx", "__name__"),
        "python-pptx": _py_version("pptx"),
        "fonttools": _py_version("fontTools", "version"),
        "py7zr": _py_version("py7zr"),
        "segno": _py_version("segno"),
        "ffmpeg": _which_version("ffmpeg", ["-version"], "UC_FFMPEG"),
        "ffprobe": _which_version("ffprobe", ["-version"], "UC_FFPROBE"),
        "pandoc": _which_version("pandoc", ["--version"], "UC_PANDOC"),
        "soffice": _soffice_probe,
        "chromium": _chromium_probe,
        "bsdtar": _which_version("bsdtar", ["--version"]),
        "qpdf": _which_version("qpdf", ["--version"]),
        "tesseract": _which_version("tesseract", ["--version"]),
        "ocrmypdf": _which_version("ocrmypdf", ["--version"]),
        "rembg": _py_version("rembg"),
    }
)


@cache
def engine_status() -> dict[str, str | None]:
    needed = {e for op in all_ops() for e in op.engines} | {e for op in all_ops() for v in op.format_engines.values() for e in v} | {"ffprobe"}
    return {e: (ENGINE_PROBES[e]() if e in ENGINE_PROBES else None) for e in sorted(needed)}


def missing_engines(op: Operation, src: str, dst: str) -> list[str]:
    st = engine_status()
    return [e for e in op.engines_for(src, dst) if not st.get(e)]


def flag_on(name: str | None) -> bool:
    if not name:
        return True
    return os.environ.get(name, "false").lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# verification results


def load_verified() -> dict[str, dict]:
    try:
        return json.loads(VERIFIED_PATH.read_text()).get("pairs", {})
    except (FileNotFoundError, ValueError):
        return {}


@dataclass
class PairInfo:
    op: Operation
    src: str
    dst: str
    level: Level
    verified: bool
    available: bool  # engines present and feature flag on
    reason: str | None = None

    @property
    def advertised(self) -> bool:
        return self.verified and self.available and self.level != "unsupported"


def pair_infos(verified: dict[str, dict] | None = None) -> list[PairInfo]:
    verified = load_verified() if verified is None else verified
    out: list[PairInfo] = []
    for op in all_ops():
        flag = flag_on(op.feature_flag)
        for s, d in op.pairs():
            missing = [] if op.runtime == "client" else missing_engines(op, s, d)
            eng = not missing
            pair_ok = verified.get(op.key(s, d), {}).get("status") == "passed"
            neg_ok = verified.get(negative_key(op.id), {}).get("status") == "passed"
            v = pair_ok and neg_ok
            reason = None
            if not eng:
                reason = "engine missing: " + ", ".join(missing)
            elif not flag:
                reason = f"disabled (set {op.feature_flag}=true)"
            elif not pair_ok:
                reason = "no passing matrix test recorded"
            elif not neg_ok:
                reason = "no passing negative test recorded"
            out.append(PairInfo(op, s, d, op.level(s, d), v, eng and flag, reason))
    return out


# ---------------------------------------------------------------------------
# chains

CHAIN_MAX_HOPS = 3


def plan_chain(src: str, dst: str, infos: list[PairInfo] | None = None) -> list[PairInfo] | None:
    """Shortest path src→dst over advertised one→one / one→many(first) pairs."""
    infos = infos if infos is not None else pair_infos()
    edges: dict[str, list[PairInfo]] = {}
    for p in infos:
        if p.advertised and p.op.cardinality in ("one_to_one",) and p.src != p.dst:
            edges.setdefault(p.src, []).append(p)
    q: deque[tuple[str, list[PairInfo]]] = deque([(src, [])])
    seen = {src}
    while q:
        node, path = q.popleft()
        if len(path) >= CHAIN_MAX_HOPS:
            continue
        for e in edges.get(node, []):
            if e.dst in seen:
                continue
            np = [*path, e]
            if e.dst == dst:
                return np
            seen.add(e.dst)
            q.append((e.dst, np))
    return None
