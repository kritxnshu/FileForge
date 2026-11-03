"""Benchmark (§8): 20 concurrent small jobs succeed while a heavy job is running.

The two queues have separate concurrency limits, so a long video encode must not delay image conversions.
Runs against its own live instance (API + fast worker + heavy worker) with explicit concurrency settings.
"""

from __future__ import annotations

import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import TMP, start_live, stop_live, upload, wait_job
from fixtures.generate import path

pytestmark = pytest.mark.live

SESSIONS = 4
PER_SESSION = 5  # 20 jobs in all; each session stays under RATE_LIMIT_CONCURRENT_JOBS


@pytest.fixture(scope="module")
def bench(redis_server):
    lv = start_live({"REDIS_URL": redis_server.replace("/0", "/2"), "WORKER_CONCURRENCY_FAST": "4",
                     "WORKER_CONCURRENCY_HEAVY": "1"}, name="bench")
    yield lv
    stop_live(lv)


def _long_video() -> "Path":  # noqa: F821
    p = TMP / "bench-long.mp4"
    if not p.exists():
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-f", "lavfi", "-i", "sine=f=330",
                        "-t", "240", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(p)],
                       check=True)
    return p


def test_twenty_small_jobs_while_a_heavy_job_runs(bench):
    heavy_client = bench.client()
    vid = upload(heavy_client, _long_video()).json()["files"][0]
    r = heavy_client.post("/api/jobs", json={"file_ids": [vid["id"]], "operation": "video.convert", "target": "webm", "options": {}})
    assert r.status_code == 200, r.text
    heavy_id = r.json()["jobs"][0]["id"]
    end = time.time() + 30
    while heavy_client.get(f"/api/jobs/{heavy_id}").json()["state"] != "running":
        assert time.time() < end, "heavy job never started"
        time.sleep(0.1)

    clients = [bench.client() for _ in range(SESSIONS)]
    files = [[f["id"] for f in upload(c, *[path("image.png")] * PER_SESSION).json()["files"]] for c in clients]

    def one(args) -> tuple[str, float]:
        c, fid = args
        t0 = time.monotonic()
        res = c.post("/api/jobs", json={"file_ids": [fid], "operation": "image.convert", "target": "jpg", "options": {}})
        assert res.status_code == 200, res.text
        j = wait_job(c, res.json()["jobs"][0]["id"], timeout=120)
        return j["state"], time.monotonic() - t0

    work = [(clients[s], fid) for s in range(SESSIONS) for fid in files[s]]
    t0 = time.monotonic()
    with ThreadPoolExecutor(len(work)) as pool:
        results = list(pool.map(one, work))
    wall = time.monotonic() - t0

    heavy = heavy_client.get(f"/api/jobs/{heavy_id}").json()
    states = [s for s, _ in results]
    lat = sorted(t for _, t in results)
    print(f"\n20 small jobs during a heavy encode: wall {wall:.2f}s, latency median {statistics.median(lat):.2f}s, "
          f"p95 {lat[int(0.95 * (len(lat) - 1))]:.2f}s, max {lat[-1]:.2f}s; heavy job: {heavy['state']} "
          f"({(heavy.get('progress') or {}).get('done', 0)}%)")
    assert states == ["succeeded"] * 20
    assert heavy["state"] == "running", "the heavy job finished before the small jobs did: the benchmark proved nothing"
    assert lat[-1] < 30, f"small jobs were held up: slowest took {lat[-1]:.1f}s"

    # cancelling the heavy job kills the encoder and keeps nothing
    assert heavy_client.post(f"/api/jobs/{heavy_id}/cancel").status_code == 200
    assert wait_job(heavy_client, heavy_id, timeout=30)["state"] == "cancelled"
    for c in [heavy_client, *clients]:
        c.close()


def test_worker_restart_mid_job_fails_cleanly_with_retry_message(redis_server):
    """A deploy (SIGTERM) must never leave a job stuck "running" or its files on disk."""
    import signal
    from pathlib import Path

    lv = start_live({"REDIS_URL": redis_server.replace("/0", "/3"), "WORKER_SHUTDOWN_GRACE_S": "1",
                     "WORKER_CONCURRENCY_HEAVY": "1"}, name="restart")
    try:
        with lv.client() as c:
            vid = upload(c, _long_video()).json()["files"][0]
            jid = c.post("/api/jobs", json={"file_ids": [vid["id"]], "operation": "video.convert", "target": "webm",
                                            "options": {}}).json()["jobs"][0]["id"]
            end = time.time() + 30
            while c.get(f"/api/jobs/{jid}").json()["state"] != "running":
                assert time.time() < end, "job never started"
                time.sleep(0.1)
            heavy = lv.procs["heavy"]
            heavy.send_signal(signal.SIGTERM)
            heavy.wait(timeout=30)  # grace (1 s) + cancel + cleanup

            j = c.get(f"/api/jobs/{jid}").json()
            assert j["state"] == "failed", j
            assert "Try again" in j["error"]["message"]
            assert not (Path(lv.env["STORAGE_DIR"]) / "jobs" / jid).exists()
            # the session isn't left holding a phantom "active" job: it can start new ones
            img = upload(c, path("image.png")).json()["files"][0]
            assert c.post("/api/jobs", json={"file_ids": [img["id"]], "operation": "image.convert", "target": "jpg",
                                             "options": {}}).status_code == 200
    finally:
        stop_live(lv)
