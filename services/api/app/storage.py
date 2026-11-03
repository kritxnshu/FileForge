"""Storage interface. Only the local shared-volume backend exists today.

Layout under STORAGE_DIR:
  uploads/<file-id>/data      one uploaded file (name is never user-controlled)
  jobs/<job-id>/in|out|work   one job's working directory
"""

from __future__ import annotations

import re
import secrets
import shutil
import unicodedata
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

_ID = re.compile(r"^[0-9a-f]{32}$")


def new_id() -> str:
    """Random 128-bit id, hex encoded."""
    return secrets.token_hex(16)


def valid_id(value: str) -> bool:
    return bool(_ID.match(value or ""))


class Storage(Protocol):
    def upload_path(self, file_id: str) -> Path: ...
    def job_dir(self, job_id: str) -> Path: ...
    def delete_upload(self, file_id: str) -> None: ...
    def delete_job(self, job_id: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        (root / "uploads").mkdir(parents=True, exist_ok=True)
        (root / "jobs").mkdir(parents=True, exist_ok=True)

    def _checked(self, kind: str, ident: str) -> Path:
        if not valid_id(ident):
            raise ValueError("invalid id")
        return self.root / kind / ident

    def upload_dir(self, file_id: str) -> Path:
        return self._checked("uploads", file_id)

    def upload_path(self, file_id: str) -> Path:
        return self.upload_dir(file_id) / "data"

    def job_dir(self, job_id: str) -> Path:
        return self._checked("jobs", job_id)

    def delete_upload(self, file_id: str) -> None:
        shutil.rmtree(self.upload_dir(file_id), ignore_errors=True)

    def delete_job(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def list_ids(self, kind: str) -> list[str]:
        d = self.root / kind
        return [p.name for p in d.iterdir() if valid_id(p.name)] if d.exists() else []


# ---------------------------------------------------------------------------
# filenames (metadata only, never used to build paths)


def sanitize_filename(name: str, max_len: int = 150) -> str:
    name = unicodedata.normalize("NFC", name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*\x00')
    name = name.strip(" .")
    if not name:
        name = "file"
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: max_len - len(ext) - 1] + "." + ext) if dot and len(ext) < 12 else name[:max_len]
    return name


def stem_of(name: str) -> str:
    from engine.formats import FORMATS, format_from_extension

    fmt = format_from_extension(name)
    if fmt:
        for ext in sorted(FORMATS[fmt].exts, key=len, reverse=True):
            if name.lower().endswith("." + ext):
                return name[: -(len(ext) + 1)] or "file"
    return name.rsplit(".", 1)[0] if "." in name else name


def content_disposition(filename: str, inline: bool = False) -> str:
    """RFC 6266 / RFC 5987: ASCII fallback plus UTF-8 `filename*`."""
    safe = sanitize_filename(filename)
    ascii_name = unicodedata.normalize("NFKD", safe).encode("ascii", "ignore").decode() or "download"
    ascii_name = re.sub(r'[^A-Za-z0-9._ ()\[\]-]', "_", ascii_name)
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe, safe='')}"
