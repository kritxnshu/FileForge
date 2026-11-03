"""Retention: the sweeper and startup orphan cleanup."""

from __future__ import annotations

import asyncio
import logging
import time

from . import store
from .config import settings
from .storage import LocalStorage

log = logging.getLogger("uc.lifecycle")


async def sweep_once(*, orphans_only: bool = False) -> dict[str, int]:
    """Delete expired or orphaned upload and job directories.

    An *orphan* is a directory with no metadata record (e.g. left behind by a
    crash, or whose metadata TTL elapsed while the service was down).
    """
    s = settings()
    st = LocalStorage(s.STORAGE_DIR)
    now = time.time()
    removed = {"uploads": 0, "jobs": 0}
    for fid in st.list_ids("uploads"):
        meta = await store.fetch(store.k_file(fid))
        if meta is None or (not orphans_only and now > float(meta.get("expires") or 0)):
            st.delete_upload(fid)
            removed["uploads"] += 1
    for jid in st.list_ids("jobs"):
        meta = await store.fetch(store.k_job(jid))
        if meta is None:
            st.delete_job(jid)
            removed["jobs"] += 1
            continue
        if orphans_only or now <= float(meta.get("expires") or 0):
            continue
        if meta.get("state") in ("queued", "running"):
            await store.redis().set(store.k_cancel(jid), "1", ex=3600)
        st.delete_job(jid)
        await store.update(store.k_job(jid), {"state": "expired", "stage": "Expired", "outputs": []})
        await store.publish_job(jid)
        removed["jobs"] += 1
    if removed["uploads"] or removed["jobs"]:
        log.info("sweep removed uploads=%d jobs=%d orphans_only=%s", removed["uploads"], removed["jobs"], orphans_only)
    return removed


async def sweeper() -> None:
    interval = settings().SWEEP_INTERVAL_S
    while True:
        await asyncio.sleep(interval)
        try:
            await sweep_once()
        except Exception:  # never let the sweeper die
            log.exception("sweep failed")
