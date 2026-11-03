"""Anonymous session tokens, client IP resolution and rate limiting."""

from __future__ import annotations

import hashlib
import math
import secrets
import time

from fastapi import HTTPException, Request, Response

from .config import settings
from .store import redis

COOKIE = "uc_session"


def _sid(token: str) -> str:
    # Redis only ever sees a hash of the cookie value.
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def session_id(request: Request, response: Response, create: bool = True) -> str | None:
    token = request.cookies.get(COOKIE)
    if token and 20 <= len(token) <= 128:
        return _sid(token)
    if not create:
        return None
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        COOKIE, token, httponly=True, secure=settings().COOKIE_SECURE, samesite="strict", path="/api",
        max_age=7 * 24 * 3600,
    )
    request.state.new_session = True
    return _sid(token)


def get_session(request: Request, response: Response) -> str:
    sid = session_id(request, response)
    assert sid
    return sid


def existing_session(request: Request, response: Response) -> str:
    """For reads/downloads: no cookie means nothing can be yours → 404."""
    sid = session_id(request, response, create=False)
    if not sid:
        raise HTTPException(404, "Not found")
    return sid


def client_ip(request: Request) -> str:
    hops = settings().TRUSTED_PROXY_HOPS
    if hops > 0:
        xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(xff) >= hops:
            return xff[-hops]
    return request.client.host if request.client else "unknown"


async def _hit(key: str, window_s: int, amount: int, limit: int) -> None:
    r = redis()
    bucket = int(time.time() // window_s)
    k = f"uc:rl:{key}:{bucket}"
    async with r.pipeline(transaction=True) as p:
        p.incrby(k, amount)
        p.expire(k, window_s + 5)
        used, _ = await p.execute()
    if used > limit:
        retry = math.ceil((bucket + 1) * window_s - time.time())
        raise HTTPException(
            429,
            f"You've hit the rate limit. Try again in {max(1, retry // 60) if retry >= 60 else retry} "
            f"{'minute(s)' if retry >= 60 else 'second(s)'}.",
            headers={"Retry-After": str(max(1, retry))},
        )


async def limit_uploads(sid: str, ip: str, nbytes_hint: int) -> None:
    s = settings()
    for who in (f"s:{sid}", f"ip:{ip}"):
        await _hit(f"up:{who}", 600, 1, s.RATE_LIMIT_UPLOADS_PER_10MIN * (1 if who.startswith("s") else 3))


async def limit_bytes(sid: str, ip: str, nbytes: int) -> None:
    s = settings()
    mb = max(1, nbytes // (1024 * 1024))
    for who in (f"s:{sid}", f"ip:{ip}"):
        await _hit(f"mb:{who}", 3600, mb, s.RATE_LIMIT_MB_PER_HOUR * (1 if who.startswith("s") else 3))


async def limit_jobs(sid: str, ip: str, count: int) -> None:
    s = settings()
    for who in (f"s:{sid}", f"ip:{ip}"):
        await _hit(f"jobs:{who}", 600, count, s.RATE_LIMIT_JOBS_PER_10MIN * (1 if who.startswith("s") else 3))
    active = await redis().scard(f"uc:active:{sid}")
    if active + count > s.RATE_LIMIT_CONCURRENT_JOBS:
        raise HTTPException(429, "Too many conversions are running at once. Wait for some to finish.",
                            headers={"Retry-After": "10"})
