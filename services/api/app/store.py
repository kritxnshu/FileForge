"""Redis-backed metadata for uploads, jobs and batches.

File contents never go to Redis. Original filenames are stored here only.
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as aioredis

from .config import settings

TERMINAL = {"succeeded", "failed", "cancelled", "expired"}
_redis: aioredis.Redis | None = None


def redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings().REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def meta_ttl() -> int:
    # Metadata outlives the files so the UI can show "expired" instead of a 404.
    return settings().retention_s + 6 * 3600


def k_file(i: str) -> str:
    return f"uc:file:{i}"


def k_job(i: str) -> str:
    return f"uc:job:{i}"


def k_batch(i: str) -> str:
    return f"uc:batch:{i}"


def k_events(i: str) -> str:
    return f"uc:events:{i}"


def k_cancel(i: str) -> str:
    return f"uc:cancel:{i}"


def k_sess(sid: str, kind: str) -> str:
    return f"uc:sess:{sid}:{kind}"


def k_active(sid: str) -> str:
    return f"uc:active:{sid}"


_JSON_FIELDS = {"warnings", "info", "options", "file_ids", "outputs", "notices", "job_ids", "progress"}


def _enc(d: dict[str, Any]) -> dict[str, str]:
    return {k: json.dumps(v) if k in _JSON_FIELDS else ("" if v is None else str(v)) for k, v in d.items()}


def _dec(d: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if k in _JSON_FIELDS:
            out[k] = json.loads(v) if v else None
        else:
            out[k] = v
    return out


async def put(key: str, data: dict[str, Any], ttl: int | None = None) -> None:
    r = redis()
    async with r.pipeline(transaction=True) as p:
        p.hset(key, mapping=_enc(data))
        p.expire(key, ttl or meta_ttl())
        await p.execute()


async def update(key: str, data: dict[str, Any]) -> None:
    await redis().hset(key, mapping=_enc(data))


async def fetch(key: str) -> dict[str, Any] | None:
    d = await redis().hgetall(key)
    return _dec(d) if d else None


async def owned(key: str, sid: str) -> dict[str, Any] | None:
    """Fetch a record only if it belongs to this session (else behave as missing)."""
    d = await fetch(key)
    if not d or d.get("session") != sid:
        return None
    return d


def job_public(job_id: str, j: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    state = j.get("state", "queued")
    expires = float(j.get("expires") or 0)
    if state not in ("expired",) and expires and now > expires:
        state = "expired"
    prog = j.get("progress") or {}
    return {
        "id": job_id,
        "batch_id": j.get("batch") or None,
        "operation": j.get("operation"),
        "target": j.get("target"),
        "file_ids": j.get("file_ids") or [],
        "state": state,
        "stage": j.get("stage") or None,
        "progress": prog or None,
        "error": ({"code": j.get("error_code"), "message": j.get("error")} if j.get("error") else None),
        "outputs": [
            {"index": n, "name": o["name"], "format": o["format"], "size": o["size"], "label": o.get("label")}
            for n, o in enumerate(j.get("outputs") or [])
        ],
        "notices": j.get("notices") or [],
        "warnings": j.get("warnings") or [],
        "input_size": int(j.get("input_size") or 0),
        "created_at": float(j.get("created") or 0),
        "finished_at": float(j.get("finished") or 0) or None,
        "expires_at": expires or None,
    }


async def publish_job(job_id: str) -> None:
    j = await fetch(k_job(job_id))
    if j:
        await redis().publish(k_events(job_id), json.dumps(job_public(job_id, j)))
