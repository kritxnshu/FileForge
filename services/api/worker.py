"""arq workers. One process per queue:

    arq worker.FastWorker     # images, data, small PDFs
    arq worker.HeavyWorker    # video, office documents, OCR

A worker never converts in-process: it supervises one sandboxed child per job
(DECISIONS D1, D3), forwards the child's progress lines to Redis, polls the
cancel flag, and kills the child's process group on cancel or timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from arq.worker import func

from app import store
from app.config import settings
from app.storage import LocalStorage, stem_of
from engine import child_cmd, registry, sandbox
from engine.formats import FORMATS

log = logging.getLogger("uc.worker")

TIMEOUT_MESSAGES = {
    "fast": "This conversion took longer than {s} seconds and was stopped. Try a smaller file.",
    "heavy": "This conversion took longer than {m} minutes and was stopped. Try a smaller or shorter file.",
}


def _limits(op: registry.Operation, queue: str) -> sandbox.Limits:
    s = settings()
    timeout = s.JOB_TIMEOUT_HEAVY_S if queue == "heavy" else s.JOB_TIMEOUT_FAST_S
    mem: int | None = s.JOB_MEMORY_HEAVY_MB if queue == "heavy" else s.JOB_MEMORY_FAST_MB
    if op.memory_mb != -1:
        mem = op.memory_mb
    return sandbox.Limits(timeout_s=timeout, memory_mb=mem, fsize_mb=max(2048, s.MAX_VIDEO_SIZE_MB * 4))


def _output_names(orig_names: list[str], outputs: list[dict], op: registry.Operation) -> list[dict]:
    """Download names come from the original filename (metadata only), never from disk paths."""
    stem = stem_of(orig_names[0]) if orig_names else "converted"
    if op.cardinality == "many_to_one" and len(orig_names) > 1:
        stem = {"pdf.merge": "merged"}.get(op.id, stem)
    for o in outputs:
        ext = FORMATS[o["format"]].ext if o["format"] in FORMATS else "bin"
        inner = Path(o["path"]).name
        inner_stem = inner[: -(len(ext) + 1)] if inner.endswith("." + ext) else inner.rsplit(".", 1)[0]
        o["name"] = f"{stem}.{ext}" if inner_stem == "output" else f"{stem}-{inner_stem}.{ext}"
    return outputs


async def run_job(ctx: dict[str, Any], job_id: str) -> str:
    s = settings()
    r = store.redis()
    key = store.k_job(job_id)
    j = await store.fetch(key)
    if not j:
        return "missing"
    sid = j.get("session", "")
    if j.get("state") != "queued" or await r.exists(store.k_cancel(job_id)):
        await r.srem(store.k_active(sid), job_id)
        return "skipped"
    op = registry.get(j["operation"])
    if op is None:
        await store.update(key, {"state": "failed", "error_code": "unsupported", "error": "This operation is no longer available."})
        await store.publish_job(job_id)
        return "failed"

    storage = LocalStorage(s.STORAGE_DIR)
    job_dir = storage.job_dir(job_id)
    (job_dir / "in").mkdir(parents=True, exist_ok=True)
    inputs, names = [], []
    for n, fid in enumerate(j.get("file_ids") or []):
        f = await store.fetch(store.k_file(fid))
        src = storage.upload_path(fid)
        if not f or not src.exists():
            await store.update(key, {"state": "failed", "error_code": "expired", "finished": time.time(),
                                     "error": "An input file expired before the conversion started. Upload it again."})
            await store.publish_job(job_id)
            await r.srem(store.k_active(sid), job_id)
            shutil.rmtree(job_dir, ignore_errors=True)
            return "failed"
        dst = job_dir / "in" / f"{n}.{FORMATS[f['format']].ext}"
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        inputs.append({"path": str(dst), "format": f["format"], "size": int(f["size"]), "stem": "output" if len(j["file_ids"]) == 1 else f"file{n + 1}"})
        names.append(f["name"])

    queue = j.get("queue", "fast")
    limits = _limits(op, queue)
    spec = {"operation": op.id, "target": j["target"], "options": j.get("options") or {}, "inputs": inputs,
            "timeout_s": limits.timeout_s, "limits": {"max_image_pixels": s.MAX_IMAGE_PIXELS,
            "archive_max_entries": s.ARCHIVE_MAX_ENTRIES, "archive_max_uncompressed_mb": s.ARCHIVE_MAX_UNCOMPRESSED_MB,
            "archive_max_ratio": s.ARCHIVE_MAX_RATIO, "archive_max_depth": s.ARCHIVE_MAX_DEPTH}}
    (job_dir / "spec.json").write_text(json.dumps(spec))

    started = time.time()
    await store.update(key, {"state": "running", "stage": "Starting", "started": started})
    await store.publish_job(job_id)

    last_pub = 0.0

    async def on_line(line: bytes) -> None:
        nonlocal last_pub
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if ev.get("t") != "progress":
            return
        upd: dict[str, Any] = {}
        if ev.get("stage"):
            upd["stage"] = ev["stage"]
        if "done" in ev and ev.get("total"):
            upd["progress"] = {"done": ev["done"], "total": ev["total"]}
        if upd:
            await store.update(key, upd)
            now = time.monotonic()
            if now - last_pub > 0.15 or ev.get("stage"):
                last_pub = now
                await store.publish_job(job_id)

    async def cancelled() -> bool:
        return bool(await r.exists(store.k_cancel(job_id)))

    res = await sandbox.run(child_cmd(job_dir), job_dir=job_dir, limits=limits, on_stdout_line=on_line,
                            cancel_check=cancelled)
    finished = time.time()
    shutil.rmtree(job_dir / "work", ignore_errors=True)
    shutil.rmtree(job_dir / "tmp", ignore_errors=True)
    shutil.rmtree(job_dir / "home", ignore_errors=True)
    outcome: dict[str, Any] = {"finished": finished}

    if res.cancelled:
        outcome.update(state="cancelled", stage="Cancelled")
    elif res.timed_out:
        outcome.update(state="failed", stage="Failed", error_code="timeout",
                       error=TIMEOUT_MESSAGES[queue].format(s=int(limits.timeout_s), m=int(limits.timeout_s // 60)))
    elif res.returncode == 0 and (job_dir / "result.json").exists():
        result = json.loads((job_dir / "result.json").read_text())
        outs = _output_names(names, result["outputs"], op)
        outcome.update(state="succeeded", stage="Done", outputs=outs, notices=result.get("notices", []),
                       warnings=result.get("warnings", []), progress={})
    else:
        err = {}
        if (job_dir / "error.json").exists():
            err = json.loads((job_dir / "error.json").read_text())
        elif res.signal in (9, 24, 25) or res.returncode in (-9, -24, -25, 137):
            err = {"code": "limit_exceeded", "message": "This conversion used more time, memory or disk than we allow and was stopped."}
        else:
            err = {"code": "internal", "message": "The converter crashed on this file. It may be damaged or use unsupported features."}
        outcome.update(state="failed", stage="Failed", error_code=err.get("code", "internal"), error=err.get("message"))
        if res.stderr_tail and err.get("code") in ("internal", "engine_error"):
            log.warning("job %s failed (%s): %s", job_id, err.get("code"), res.stderr_tail[-500:].replace("\n", " | "))

    if outcome["state"] != "succeeded":
        # failed or cancelled jobs drop partial outputs immediately
        shutil.rmtree(job_dir, ignore_errors=True)
    else:
        shutil.rmtree(job_dir / "in", ignore_errors=True)

    # A cancel/delete may have raced us; never resurrect a cancelled job.
    current = await store.fetch(key)
    if current is None:
        shutil.rmtree(job_dir, ignore_errors=True)
        return "deleted"
    if current.get("state") == "cancelled" and outcome["state"] != "cancelled":
        shutil.rmtree(job_dir, ignore_errors=True)
        outcome = {"state": "cancelled", "stage": "Cancelled", "finished": finished}
    await store.update(key, outcome)
    await store.publish_job(job_id)
    await r.srem(store.k_active(sid), job_id)
    log.info("job=%s op=%s src=%s dst=%s bytes=%s queue=%s state=%s code=%s duration=%.2fs",
             job_id, op.id, ",".join(i["format"] for i in inputs), j["target"], j.get("input_size"), queue,
             outcome["state"], outcome.get("error_code", "-"), res.duration_s)
    return outcome["state"]


async def _heartbeat(ctx: dict[str, Any]) -> None:
    q = ctx["uc_queue"]
    k = f"uc:worker:{q}:{os.getpid()}"
    while True:
        try:
            await store.redis().set(k, str(time.time()), ex=30)
        except Exception:
            pass
        await asyncio.sleep(10)


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(level=settings().LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    registry.load_all()
    ctx["hb"] = asyncio.create_task(_heartbeat(ctx))


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["hb"].cancel()
    await store.close_redis()


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings().REDIS_URL)


def _worker(queue: str) -> type:
    s = settings()
    timeout = (s.JOB_TIMEOUT_HEAVY_S if queue == "heavy" else s.JOB_TIMEOUT_FAST_S) + 60

    async def _startup(ctx: dict[str, Any]) -> None:
        ctx["uc_queue"] = queue
        await startup(ctx)

    class W:
        functions = [func(run_job, name="run_job", timeout=timeout, max_tries=1)]
        queue_name = f"uc:{queue}"
        max_jobs = s.WORKER_CONCURRENCY_HEAVY if queue == "heavy" else s.WORKER_CONCURRENCY_FAST
        redis_settings = _redis_settings()
        on_startup = _startup
        on_shutdown = shutdown
        allow_abort_jobs = True
        keep_result = 60
        health_check_interval = 30
        handle_signals = True

    W.__name__ = f"{queue.title()}Worker"
    return W


FastWorker = _worker("fast")
HeavyWorker = _worker("heavy")
