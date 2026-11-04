"""Previews for the UI: PDF page thumbnails (reordering pages, PDF results) and the first rows of spreadsheets.

Reading a hostile file is done exactly like a conversion: in a sandboxed job process (`pdf.to_images` at low
resolution, `sheet.export` to CSV), never in the API process. Previews are cached next to the file they belong
to, so they're deleted with it.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import HTTPException

from engine import child_cmd, sandbox
from engine.formats import FORMATS

MAX_THUMB_PAGES = 60
TABLE_ROWS = 100  # data rows, plus the header
TABLE_COLS = 50
CELL_CHARS = 200
_locks: dict[str, asyncio.Lock] = {}


async def _cached(meta: Path, build: Callable[[], Awaitable[dict]]) -> dict:
    if meta.exists():
        return json.loads(meta.read_text())
    async with _locks.setdefault(str(meta), asyncio.Lock()):
        if meta.exists():
            return json.loads(meta.read_text())
        info = await build()
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps(info))
        return info


async def _sandboxed(src: Path, fmt: str, work: Path, operation: str, target: str, options: dict,
                     failure: str) -> dict:
    """Run one operation on `src` in a sandboxed job process in `work`; returns its result.json."""
    shutil.rmtree(work, ignore_errors=True)
    (work / "in").mkdir(parents=True)
    dst = work / "in" / f"0.{FORMATS[fmt].ext}"
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)
    (work / "spec.json").write_text(json.dumps({
        "operation": operation, "target": target, "timeout_s": 30, "options": options,
        "inputs": [{"path": str(dst), "format": fmt, "size": dst.stat().st_size, "stem": "output"}],
    }))
    res = await sandbox.run(child_cmd(work), job_dir=work, limits=sandbox.Limits(timeout_s=30, memory_mb=1024))
    if not res.ok or not (work / "result.json").exists():
        err = json.loads((work / "error.json").read_text()) if (work / "error.json").exists() else {}
        shutil.rmtree(work, ignore_errors=True)
        if err.get("code") == "password_required":  # previews never get the password typed under Advanced settings
            raise HTTPException(422, "This PDF is password-protected, so its pages can't be shown. Unlock it first with "
                                     "Unlock PDF, then add the unlocked copy.")
        raise HTTPException(422, err.get("message") or failure)
    return json.loads((work / "result.json").read_text())


async def thumbnails(src: Path, cache: Path) -> dict:
    async def build() -> dict:
        work = cache / "job"
        result = await _sandboxed(src, "pdf", work, "pdf.to_images", "png", {"dpi": 36, "first_n": MAX_THUMB_PAGES},
                                  "We couldn't render previews for this PDF.")
        for n, o in enumerate(result["outputs"]):
            (work / o["path"]).replace(cache / f"{n}.png")
        shutil.rmtree(work, ignore_errors=True)
        info = result["info"]
        return {"pages": info.get("total_pages", len(result["outputs"])), "thumbnails": len(result["outputs"]),
                "sizes": info.get("page_sizes", [])}

    return await _cached(cache / "pages.json", build)


VIEW_DPI = 110


async def page_view(src: Path, cache: Path, n: int) -> Path:
    """One page rendered large enough to edit on (cached)."""
    target = cache / f"view-{n}.png"
    if target.exists():
        return target

    async def build() -> dict:
        work = cache / f"vjob-{n}"
        result = await _sandboxed(src, "pdf", work, "pdf.to_images", "png", {"dpi": VIEW_DPI, "pages": str(n + 1)},
                                  "We couldn't render this page.")
        (work / result["outputs"][0]["path"]).replace(target)
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": True}

    await _cached(cache / f"view-{n}.json", build)
    return target


async def form_fields(src: Path, cache: Path) -> dict:
    """A PDF form's fields, types, options, values and positions (from pdf.form_data, sandboxed)."""
    async def build() -> dict:
        work = cache / "fjob"
        result = await _sandboxed(src, "pdf", work, "pdf.form_data", "json", {},
                                  "We couldn't read this PDF's form fields.")
        data = json.loads((work / result["outputs"][0]["path"]).read_text(encoding="utf-8"))
        shutil.rmtree(work, ignore_errors=True)
        return data

    return await _cached(cache / "form.json", build)


async def table(src: Path, fmt: str, cache: Path) -> dict:
    """First rows of the first sheet, as text cells. The browser renders them as escaped text."""
    async def build() -> dict:
        work = cache / "tjob"
        result = await _sandboxed(src, fmt, work, "sheet.export", "csv", {"neutralize_formulas": False},
                                  "We couldn't read this spreadsheet for a preview.")
        rows: list[list[str]] = []
        truncated = False
        if result["outputs"]:
            with (work / result["outputs"][0]["path"]).open(newline="", encoding="utf-8-sig") as f:
                for row in csv.reader(f):
                    if len(rows) > TABLE_ROWS:
                        truncated = True
                        break
                    rows.append([c[:CELL_CHARS] for c in row[:TABLE_COLS]])
        shutil.rmtree(work, ignore_errors=True)
        exported = result.get("info", {}).get("exported") or [None]
        return {"sheet": exported[0], "rows": rows, "truncated": truncated}

    return await _cached(cache / "table.json", build)
