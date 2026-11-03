"""FastAPI application: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from engine import registry

from . import lifecycle, store
from .config import settings
from .routes import router

log = logging.getLogger("uc.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = settings()
    logging.basicConfig(level=s.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    registry.load_all()
    await asyncio.to_thread(registry.engine_status)
    app.state.arq = await create_pool(RedisSettings.from_dsn(s.REDIS_URL))
    await lifecycle.sweep_once(orphans_only=True)
    task = asyncio.create_task(lifecycle.sweeper())
    yield
    task.cancel()
    await app.state.arq.aclose()
    await store.close_redis()


app = FastAPI(title="Universal Converter API", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json",
              redoc_url=None)
app.include_router(router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith("/api/docs"):
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": {"status": exc.status_code, "message": exc.detail}}, status_code=exc.status_code,
                        headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return JSONResponse({"error": {"status": 422, "message": f"Invalid request: {loc} {first.get('msg', '')}".strip()}},
                        status_code=422)
