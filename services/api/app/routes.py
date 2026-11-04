"""HTTP API."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sse_starlette.sse import EventSourceResponse

from engine import registry, sandbox
from engine.formats import FORMATS

from . import capabilities, store
from .config import settings
from .security import client_ip, existing_session, get_session, limit_jobs
from .storage import LocalStorage, content_disposition, new_id, valid_id
from .uploads import receive_uploads

router = APIRouter(prefix="/api")
MB = 1024 * 1024


def storage() -> LocalStorage:
    return LocalStorage(settings().STORAGE_DIR)


# 404s don't say whether something never existed or belongs to another session; both read as "gone".
GONE_FILE = "This file has expired or was deleted. Upload it again."
GONE_JOB = "This conversion has expired or was deleted. Convert the file again."
GONE_BATCH = "These results have expired or were deleted."

def _check_id(i: str) -> None:
    if not valid_id(i):
        raise HTTPException(404, "Not found. Check the link, or upload your file again.")


# ---------------------------------------------------------------------------
# capabilities & health


@router.get("/capabilities")
async def get_capabilities() -> JSONResponse:
    doc, _ = await asyncio.to_thread(capabilities.build)
    return JSONResponse(doc, headers={"Cache-Control": "public, max-age=30"})


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    engines = await asyncio.to_thread(registry.engine_status)
    try:
        redis_ok = bool(await store.redis().ping())
    except Exception:
        redis_ok = False
    workers: dict[str, int] = {"fast": 0, "heavy": 0}
    if redis_ok:
        async for k in store.redis().scan_iter("uc:worker:*"):
            q = k.split(":")[2]
            workers[q] = workers.get(q, 0) + 1
    disabled = sorted({p["operation"] for p in capabilities.hidden_pairs() if (p["reason"] or "").startswith("engine")})
    iso = sandbox.isolation_mode()
    return {
        "status": "ok" if redis_ok and all(workers.values()) else "degraded",
        "redis": redis_ok,
        "workers": workers,
        "engines": {k: {"available": bool(v), "version": v} for k, v in engines.items()},
        "disabled_operations": disabled,
        "isolation": {"mode": iso.kind, "detail": iso.detail},
        "retention_minutes": settings().limits_public()["retention_minutes"],
    }


# ---------------------------------------------------------------------------
# uploads


@router.post("/uploads")
async def upload(request: Request, response: Response, sid: str = Depends(get_session)) -> dict[str, Any]:
    files = await receive_uploads(request, sid)
    return {"files": files}


def _file_public(fid: str, f: dict) -> dict[str, Any]:
    fmt = FORMATS.get(f["format"])
    return {"id": fid, "name": f["name"], "size": int(f["size"]), "format": f["format"],
            "format_label": fmt.label if fmt else f["format"], "family": fmt.family if fmt else None,
            "warnings": f.get("warnings") or [], "info": f.get("info") or {}, "expires_at": float(f["expires"])}


@router.get("/uploads/{file_id}")
async def get_upload(file_id: str, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(file_id)
    f = await store.owned(store.k_file(file_id), sid)
    if not f or not storage().upload_path(file_id).exists():
        raise HTTPException(404, "This file has expired or was deleted.")
    return _file_public(file_id, f)


INLINE_SAFE = {"png", "jpg", "gif", "webp", "avif", "bmp", "ico", "mp3", "wav", "aac", "flac", "ogg", "m4a", "opus",
               "mp4", "webm", "mov", "pdf"}
SANDBOX_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def _file_response(path, fmt: str, name: str, inline: bool) -> FileResponse:
    mime = FORMATS[fmt].mime if fmt in FORMATS else "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    if inline and fmt in INLINE_SAFE:
        disp = content_disposition(name, inline=True)
    elif inline and fmt == "svg":
        disp = content_disposition(name, inline=True)
        headers["Content-Security-Policy"] = SANDBOX_CSP
    else:
        disp = content_disposition(name)
        headers["Content-Security-Policy"] = SANDBOX_CSP
    headers["Content-Disposition"] = disp
    return FileResponse(path, media_type=mime, headers=headers)


@router.get("/uploads/{file_id}/raw")
async def upload_raw(file_id: str, inline: bool = False, sid: str = Depends(existing_session)) -> FileResponse:
    _check_id(file_id)
    f = await store.owned(store.k_file(file_id), sid)
    path = storage().upload_path(file_id)
    if not f or not path.exists():
        raise HTTPException(404, "This file has expired or was deleted.")
    return _file_response(path, f["format"], f["name"], inline)


async def _thumbs_index(src, cache, base: str, sid: str, request: Request) -> dict[str, Any]:
    from .previews import thumbnails
    from .security import _hit

    await _hit(f"thumbs:s:{sid}", 600, 1, 300)
    info = await thumbnails(src, cache)
    return {"pages": info["pages"], "thumbnails": [f"{base}/{n}" for n in range(info["thumbnails"])],
            "sizes": info.get("sizes", [])}


def _thumb_file(cache, n: int) -> FileResponse:
    p = cache / f"{n}.png"
    if n < 0 or not p.exists():
        raise HTTPException(404, "That page preview isn't available.")
    return FileResponse(p, media_type="image/png", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=600"})


@router.get("/uploads/{file_id}/pages")
async def upload_pages(file_id: str, request: Request, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(file_id)
    f = await store.owned(store.k_file(file_id), sid)
    src = storage().upload_path(file_id)
    if not f or not src.exists():
        raise HTTPException(404, "This file has expired or was deleted.")
    if f["format"] != "pdf":
        raise HTTPException(400, "Page previews are only available for PDFs.")
    return await _thumbs_index(src, src.parent / "thumbs", f"/api/uploads/{file_id}/pages", sid, request)


@router.get("/uploads/{file_id}/pages/{n}")
async def upload_page(file_id: str, n: int, sid: str = Depends(existing_session)) -> FileResponse:
    _check_id(file_id)
    if not await store.owned(store.k_file(file_id), sid):
        raise HTTPException(404, GONE_FILE)
    return _thumb_file(storage().upload_path(file_id).parent / "thumbs", n)


async def _owned_pdf(file_id: str, sid: str) -> Path:
    _check_id(file_id)
    f = await store.owned(store.k_file(file_id), sid)
    src = storage().upload_path(file_id)
    if not f or not src.exists():
        raise HTTPException(404, GONE_FILE)
    if f["format"] != "pdf":
        raise HTTPException(400, "This only works with PDFs.")
    return src


@router.get("/uploads/{file_id}/view/{n}")
async def upload_page_view(file_id: str, n: int, sid: str = Depends(existing_session)) -> FileResponse:
    """A page rendered large for the page editors."""
    from .previews import page_view
    from .security import _hit

    src = await _owned_pdf(file_id, sid)
    if n < 0 or n > 9999:
        raise HTTPException(404, "That page preview isn't available.")
    await _hit(f"views:s:{sid}", 600, 1, 1200)
    p = await page_view(src, src.parent / "thumbs", n)
    return FileResponse(p, media_type="image/png", headers={"X-Content-Type-Options": "nosniff",
                                                             "Cache-Control": "private, max-age=600"})


@router.get("/uploads/{file_id}/form")
async def upload_form_fields(file_id: str, sid: str = Depends(existing_session)) -> dict[str, Any]:
    """A PDF form's fields, for the Fill a form tool."""
    from .previews import form_fields
    from .security import _hit

    src = await _owned_pdf(file_id, sid)
    await _hit(f"thumbs:s:{sid}", 600, 1, 300)
    return await form_fields(src, src.parent / "thumbs")


@router.delete("/uploads/{file_id}")
async def delete_upload(file_id: str, sid: str = Depends(existing_session)) -> dict[str, bool]:
    _check_id(file_id)
    if not await store.owned(store.k_file(file_id), sid):
        raise HTTPException(404, GONE_FILE)
    storage().delete_upload(file_id)
    await store.redis().delete(store.k_file(file_id))
    await store.redis().srem(store.k_sess(sid, "files"), file_id)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# jobs


MAX_OPTIONS_BYTES = 16 * 1024 * 1024  # editor images travel inside the options


class JobRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1)
    operation: str
    target: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    batch_id: str | None = None  # append to an existing batch (mixed-format groups share one ZIP)


def _queue_for(op: registry.Operation, total_bytes: int) -> str:
    if op.resource_class == "heavy" or (op.heavy_over_mb and total_bytes > op.heavy_over_mb * MB):
        return "heavy"
    return "fast"


def _unsupported(src: str, op: registry.Operation, target: str | None, index: dict) -> HTTPException:
    avail = sorted({FORMATS[d].label for (oid, s, d) in index if oid == op.id and s == src})
    sl = FORMATS[src].label if src in FORMATS else src
    if op.cardinality == "transform":
        msg = f"“{op.label}” doesn't work on {sl} files."
    else:
        tl = FORMATS[target].label if target in FORMATS else (target or "?")
        msg = f"Converting {sl} to {tl} isn't supported."
        if avail:
            msg += f" From {sl} you can convert to: {', '.join(avail)}."
    return HTTPException(400, msg)


@router.post("/jobs")
async def create_jobs(body: JobRequest, request: Request, sid: str = Depends(get_session)) -> dict[str, Any]:
    s = settings()
    _, index = await asyncio.to_thread(capabilities.build)
    op = registry.get(body.operation)
    if op is None or op.runtime != "server":
        raise HTTPException(400, "Unknown operation.")
    if len(body.file_ids) > s.MAX_BATCH_FILES:
        raise HTTPException(400, f"A batch can have at most {s.MAX_BATCH_FILES} files.")
    if len(json.dumps(body.options, separators=(",", ":"))) > MAX_OPTIONS_BYTES:
        raise HTTPException(413, "These settings are too large. Use fewer or smaller images.")
    try:
        opts = op.options.model_validate(body.options)
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, er['loc'])) or 'options'}: {er['msg']}" for er in e.errors()[:5])
        raise HTTPException(422, f"Invalid settings — {errs}") from None
    files = []
    for fid in body.file_ids:
        _check_id(fid)
        f = await store.owned(store.k_file(fid), sid)
        if not f or not storage().upload_path(fid).exists():
            raise HTTPException(404, "One of the files has expired or was deleted. Upload it again.")
        files.append((fid, f))
    if op.cardinality == "many_to_one":
        if len(files) < op.min_inputs:
            raise HTTPException(400, f"“{op.label}” needs at least {op.min_inputs} files.")
        if op.max_inputs and len(files) > op.max_inputs:
            raise HTTPException(400, f"“{op.label}” accepts at most {op.max_inputs} files.")
        groups = [files]
    else:
        groups = [[f] for f in files]
    for g in groups:
        for _, f in g:
            dst = f["format"] if op.cardinality == "transform" else body.target
            if (op.id, f["format"], dst) not in index:
                raise _unsupported(f["format"], op, body.target, index)

    existing: list[str] = []
    if body.batch_id:
        _check_id(body.batch_id)
        b = await store.owned(store.k_batch(body.batch_id), sid)
        if not b:
            raise HTTPException(404, "That batch has expired.")
        existing = b.get("job_ids") or []
    await limit_jobs(sid, client_ip(request), len(groups))
    batch_id = body.batch_id or new_id()
    now = time.time()
    jobs_out = []
    pool = request.app.state.arq
    for g in groups:
        job_id = new_id()
        target = g[0][1]["format"] if op.cardinality == "transform" else body.target
        total = sum(int(f["size"]) for _, f in g)
        queue = _queue_for(op, total)
        await store.put(store.k_job(job_id), {
            "session": sid, "batch": batch_id, "operation": op.id, "target": target,
            "options": opts.model_dump(mode="json"), "file_ids": [fid for fid, _ in g],
            "state": "queued", "stage": "Queued", "created": now, "expires": now + s.retention_s,
            "queue": queue, "input_size": total,
        })
        await store.redis().sadd(store.k_active(sid), job_id)
        await store.redis().expire(store.k_active(sid), 3600)
        await store.redis().sadd(store.k_sess(sid, "jobs"), job_id)
        await store.redis().expire(store.k_sess(sid, "jobs"), store.meta_ttl())
        await pool.enqueue_job("run_job", job_id, _job_id=job_id, _queue_name=f"uc:{queue}")
        jobs_out.append({"id": job_id, "file_ids": [fid for fid, _ in g], "state": "queued", "queue": queue})
    await store.put(store.k_batch(batch_id), {"session": sid, "job_ids": existing + [j["id"] for j in jobs_out], "created": now})
    return {"batch_id": batch_id, "jobs": jobs_out}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    return store.job_public(job_id, j)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, sid: str = Depends(existing_session)):
    _check_id(job_id)
    if not await store.owned(store.k_job(job_id), sid):
        raise HTTPException(404, GONE_JOB)

    async def gen():
        pubsub = store.redis().pubsub()
        await pubsub.subscribe(store.k_events(job_id))
        try:
            j = await store.fetch(store.k_job(job_id))
            snap = store.job_public(job_id, j or {})
            yield {"event": "job", "data": json.dumps(snap)}
            if snap["state"] in store.TERMINAL:
                return
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if msg is None:
                    j = await store.fetch(store.k_job(job_id))
                    if not j:
                        return
                    snap = store.job_public(job_id, j)
                    if snap["state"] in store.TERMINAL:
                        yield {"event": "job", "data": json.dumps(snap)}
                        return
                    continue
                yield {"event": "job", "data": msg["data"]}
                if json.loads(msg["data"]).get("state") in store.TERMINAL:
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    return EventSourceResponse(gen(), ping=15, headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _output_path(job_id: str, j: dict, n: int):
    outs = j.get("outputs") or []
    if n < 0 or n >= len(outs) or j.get("state") != "succeeded":
        raise HTTPException(404, "This result has expired or was deleted.")
    o = outs[n]
    path = (storage().job_dir(job_id) / o["path"]).resolve()
    if storage().job_dir(job_id).resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "This result has expired or was deleted.")
    return path, o


@router.get("/jobs/{job_id}/files/{n}")
async def download(job_id: str, n: int, inline: bool = False, sid: str = Depends(existing_session)) -> FileResponse:
    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    path, o = _output_path(job_id, j, n)
    return _file_response(path, o["format"], o["name"], inline)


@router.get("/jobs/{job_id}/files/{n}/pages")
async def output_pages(job_id: str, n: int, request: Request, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    path, o = _output_path(job_id, j, n)
    if o["format"] != "pdf":
        raise HTTPException(400, "Page previews are only available for PDFs.")
    return await _thumbs_index(path, storage().job_dir(job_id) / "thumbs" / str(n), f"/api/jobs/{job_id}/files/{n}/pages/p",
                               sid, request)


@router.get("/jobs/{job_id}/files/{n}/pages/p/{page}")
async def output_page(job_id: str, n: int, page: int, sid: str = Depends(existing_session)) -> FileResponse:
    _check_id(job_id)
    if not await store.owned(store.k_job(job_id), sid):
        raise HTTPException(404, GONE_JOB)
    return _thumb_file(storage().job_dir(job_id) / "thumbs" / str(n), page)


SHEET_FORMATS = {"xlsx", "xls", "ods"}


@router.get("/jobs/{job_id}/files/{n}/table")
async def output_table(job_id: str, n: int, sid: str = Depends(existing_session)) -> dict[str, Any]:
    """The first rows of a spreadsheet result, read in a sandboxed job process."""
    from .previews import table
    from .security import _hit

    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    path, o = _output_path(job_id, j, n)
    if o["format"] not in SHEET_FORMATS:
        raise HTTPException(400, "Table previews are only available for spreadsheets.")
    await _hit(f"thumbs:s:{sid}", 600, 1, 300)
    return await table(path, o["format"], storage().job_dir(job_id) / "previews" / str(n))


async def _cancel_and_delete(job_id: str, sid: str) -> None:
    j = await store.fetch(store.k_job(job_id))
    if not j:
        return
    r = store.redis()
    await r.set(store.k_cancel(job_id), "1", ex=3600)
    if j.get("state") not in store.TERMINAL:
        await store.update(store.k_job(job_id), {"state": "cancelled", "stage": "Cancelled", "finished": time.time()})
        await r.srem(store.k_active(sid), job_id)
        try:
            from arq.jobs import Job

            await Job(job_id, r, _queue_name=f"uc:{j.get('queue', 'fast')}").abort(timeout=0)
        except Exception:
            pass
    await store.publish_job(job_id)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    if j.get("state") in store.TERMINAL:
        return store.job_public(job_id, j)
    await _cancel_and_delete(job_id, sid)
    j = await store.fetch(store.k_job(job_id))
    return store.job_public(job_id, j or {})


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, sid: str = Depends(existing_session)) -> dict[str, bool]:
    _check_id(job_id)
    j = await store.owned(store.k_job(job_id), sid)
    if not j:
        raise HTTPException(404, GONE_JOB)
    await _cancel_and_delete(job_id, sid)
    storage().delete_job(job_id)
    await store.update(store.k_job(job_id), {"outputs": [], "state": "expired" if j.get("state") == "succeeded" else
                                             (await store.fetch(store.k_job(job_id)) or {}).get("state")})
    await store.publish_job(job_id)
    await store.redis().delete(store.k_job(job_id))
    await store.redis().srem(store.k_sess(sid, "jobs"), job_id)
    return {"deleted": True}


@router.delete("/session")
async def delete_session(sid: str = Depends(existing_session)) -> dict[str, int]:
    r = store.redis()
    fids = await r.smembers(store.k_sess(sid, "files"))
    jids = await r.smembers(store.k_sess(sid, "jobs"))
    for jid in jids:
        if valid_id(jid):
            await _cancel_and_delete(jid, sid)
            storage().delete_job(jid)
            await r.delete(store.k_job(jid))
    for fid in fids:
        if valid_id(fid):
            storage().delete_upload(fid)
            await r.delete(store.k_file(fid))
    await r.delete(store.k_sess(sid, "files"), store.k_sess(sid, "jobs"), store.k_active(sid))
    return {"deleted_files": len(fids), "deleted_jobs": len(jids)}


# ---------------------------------------------------------------------------
# batches


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str, sid: str = Depends(existing_session)) -> dict[str, Any]:
    _check_id(batch_id)
    b = await store.owned(store.k_batch(batch_id), sid)
    if not b:
        raise HTTPException(404, GONE_BATCH)
    jobs = []
    for jid in b.get("job_ids") or []:
        j = await store.fetch(store.k_job(jid))
        if j:
            jobs.append(store.job_public(jid, j))
    return {"id": batch_id, "jobs": jobs}


@router.get("/batches/{batch_id}/zip")
async def batch_zip(batch_id: str, sid: str = Depends(existing_session)) -> StreamingResponse:
    from zipstream import ZIP_DEFLATED, ZipStream

    _check_id(batch_id)
    b = await store.owned(store.k_batch(batch_id), sid)
    if not b:
        raise HTTPException(404, GONE_BATCH)
    zs = ZipStream(compress_type=ZIP_DEFLATED, compress_level=6, sized=False)
    used: set[str] = set()
    count = 0
    for jid in b.get("job_ids") or []:
        j = await store.fetch(store.k_job(jid))
        if not j or j.get("state") != "succeeded":
            continue
        for n, o in enumerate(j.get("outputs") or []):
            try:
                path, o = _output_path(jid, j, n)
            except HTTPException:
                continue
            name = o["name"]
            base, dot, ext = name.rpartition(".")
            k = 2
            while name in used:
                name = f"{base} ({k}).{ext}" if dot else f"{o['name']} ({k})"
                k += 1
            used.add(name)
            zs.add_path(str(path), name)
            count += 1
    if not count:
        raise HTTPException(404, "There are no finished results in this batch to download.")
    return StreamingResponse(iter(zs), media_type="application/zip", headers={
        "Content-Disposition": content_disposition("converted-files.zip"),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })
