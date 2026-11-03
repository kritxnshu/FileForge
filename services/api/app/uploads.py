"""Streaming multipart upload: bytes go straight to disk and are counted as they
arrive; the request is aborted the moment a limit is crossed."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from engine import detect as detect_mod
from engine.formats import FORMATS

from . import store
from .config import settings
from .security import client_ip, limit_bytes, limit_uploads
from .storage import LocalStorage, new_id, sanitize_filename

MB = 1024 * 1024
_VIDEO_HEADS = (b"ftyp", b"\x1a\x45\xdf\xa3", b"RIFF", b"FLV", bytes.fromhex("3026b2758e66cf11"))


def _looks_like_video(head: bytes) -> bool:
    return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3" or (head[:4] == b"RIFF" and head[8:12] == b"AVI ") \
        or head[:3] == b"FLV" or head[:8] == bytes.fromhex("3026b2758e66cf11")


class LimitExceeded(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@dataclass
class _Part:
    file_id: str
    name: str
    fh: object
    size: int = 0
    cap: int = 0
    head: bytes = b""


@dataclass
class _State:
    storage: LocalStorage
    parts: list[_Part] = field(default_factory=list)
    current: _Part | None = None
    headers: dict[str, bytes] = field(default_factory=dict)
    hname: bytes = b""
    hval: bytes = b""
    total: int = 0
    error: LimitExceeded | None = None


def _filename_from(disposition: bytes) -> str | None:
    _, params = parse_options_header(disposition)
    fn = params.get(b"filename*") or params.get(b"filename")
    if fn is None:
        return None
    s = fn.decode("utf-8", "replace")
    if s.lower().startswith("utf-8''"):
        from urllib.parse import unquote

        s = unquote(s[7:])
    return s


async def receive_uploads(request: Request, sid: str) -> list[dict]:
    s = settings()
    ip = client_ip(request)
    ctype = request.headers.get("content-type", "")
    mime, params = parse_options_header(ctype)
    if mime != b"multipart/form-data" or b"boundary" not in params:
        raise HTTPException(400, "Expected a multipart/form-data upload.")
    total_cap = s.MAX_BATCH_TOTAL_MB * MB
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > total_cap + 64 * 1024:
        raise HTTPException(413, f"This upload is larger than the {s.MAX_BATCH_TOTAL_MB} MB batch limit.")
    await limit_uploads(sid, ip, int(clen or 0))
    if clen and clen.isdigit():
        await limit_bytes(sid, ip, int(clen))

    storage = LocalStorage(s.STORAGE_DIR)
    st = _State(storage)
    file_cap, video_cap = s.MAX_FILE_SIZE_MB * MB, s.MAX_VIDEO_SIZE_MB * MB

    def fail(status: int, msg: str) -> None:
        if st.error is None:
            st.error = LimitExceeded(status, msg)

    def on_part_begin() -> None:
        st.headers = {}

    def on_header_field(data: bytes, start: int, end: int) -> None:
        st.hname += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        st.hval += data[start:end]

    def on_header_end() -> None:
        st.headers[st.hname.decode("latin-1").lower()] = st.hval
        st.hname, st.hval = b"", b""

    def on_headers_finished() -> None:
        fn = _filename_from(st.headers.get("content-disposition", b""))
        if fn is None:
            st.current = None
            return
        if len(st.parts) >= s.MAX_BATCH_FILES:
            fail(413, f"You can upload at most {s.MAX_BATCH_FILES} files at once.")
            st.current = None
            return
        fid = new_id()
        path = storage.upload_path(fid)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = _Part(fid, sanitize_filename(fn), path.open("wb"), cap=file_cap)
        st.parts.append(part)
        st.current = part

    def on_part_data(data: bytes, start: int, end: int) -> None:
        p = st.current
        if p is None or st.error:
            return
        chunk = data[start:end]
        if p.size == 0 and not p.head:
            p.head = chunk[:64]
            if _looks_like_video(p.head):
                p.cap = video_cap
        elif len(p.head) < 16:
            p.head += chunk[:16]
            if _looks_like_video(p.head):
                p.cap = video_cap
        p.size += len(chunk)
        st.total += len(chunk)
        if p.size > p.cap:
            lim = s.MAX_VIDEO_SIZE_MB if p.cap == video_cap else s.MAX_FILE_SIZE_MB
            fail(413, f"“{p.name}” is larger than the {lim} MB limit for this file type.")
            return
        if st.total > total_cap:
            fail(413, f"This upload is larger than the {s.MAX_BATCH_TOTAL_MB} MB batch limit.")
            return
        p.fh.write(chunk)  # type: ignore[attr-defined]

    def on_part_end() -> None:
        if st.current is not None:
            st.current.fh.close()  # type: ignore[attr-defined]
        st.current = None

    parser = MultipartParser(params[b"boundary"], {
        "on_part_begin": on_part_begin, "on_part_data": on_part_data, "on_part_end": on_part_end,
        "on_header_field": on_header_field, "on_header_value": on_header_value,
        "on_header_end": on_header_end, "on_headers_finished": on_headers_finished,
    })

    def cleanup() -> None:
        for p in st.parts:
            try:
                p.fh.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            storage.delete_upload(p.file_id)

    try:
        async for chunk in request.stream():
            parser.write(chunk)
            if st.error:
                break
        else:
            parser.finalize()
    except HTTPException:
        cleanup()
        raise
    except Exception:
        cleanup()
        raise HTTPException(400, "The upload was interrupted or malformed. Try again.")
    if st.error:
        cleanup()
        raise HTTPException(st.error.status, st.error.message)
    if not st.parts:
        raise HTTPException(400, "No files were found in the upload.")
    if not clen:
        await limit_bytes(sid, ip, st.total)

    results = []
    now = time.time()
    for p in st.parts:
        path = storage.upload_path(p.file_id)
        det = await asyncio.to_thread(detect_mod.detect, path, p.name, probe_dir=path.parent)
        item: dict = {"id": p.file_id, "name": p.name, "size": p.size, "format": det.format, "warnings": det.warnings}
        if det.format and FORMATS[det.format].family != "video" and p.size > file_cap:
            det.error = f"“{p.name}” is larger than the {s.MAX_FILE_SIZE_MB} MB limit for this file type."
        if det.error or not det.format:
            storage.delete_upload(p.file_id)
            item["format"] = None
            item["error"] = det.error or "We couldn't identify this file's format."
            results.append(item)
            continue
        f = FORMATS[det.format]
        item.update(format_label=f.label, family=f.family, info=det.info)
        await store.put(store.k_file(p.file_id), {
            "session": sid, "name": p.name, "format": det.format, "size": p.size, "created": now,
            "expires": now + s.retention_s, "warnings": det.warnings, "info": det.info,
        })
        await store.redis().sadd(store.k_sess(sid, "files"), p.file_id)
        await store.redis().expire(store.k_sess(sid, "files"), store.meta_ttl())
        item["expires_at"] = now + s.retention_s
        results.append(item)
    return results
