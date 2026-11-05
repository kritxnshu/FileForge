# Deployment

FileForge is one web app, one API service with two worker processes, and one Redis-compatible queue,
behind Caddy on a single origin. The supported production shape is **one Linux VM running Docker Compose**.

> The Dockerfiles and `docker-compose.yml` were written alongside the native setup but couldn't be built in the
> development environment, which had no Docker (DECISIONS D15). The native stack they mirror (`scripts/dev.sh`) is
> what the test suites exercise. Build and smoke-test the images once before going live (the checklist at the end
> covers this).

## Single VM with Docker Compose and TLS

Requirements: a Linux VM (4+ vCPU and 8 GB RAM is comfortable; video and office conversions are CPU-bound), Docker
Engine with the Compose plugin, a DNS name pointing at the VM, and ports 80 and 443 open.

```sh
git clone <your fork> fileforge && cd fileforge
cat > .env <<'EOF'
UC_SITE_ADDRESS=convert.example.com
PUBLIC_BASE_URL=https://convert.example.com
EOF
docker compose up -d --build
docker compose ps                     # all services "running"
curl -s https://convert.example.com/api/health | jq .status   # "ok"
```

- **TLS.** When `UC_SITE_ADDRESS` is a domain name, Caddy obtains and renews a Let's Encrypt certificate
  automatically (ports 80 and 443) and redirects HTTP to HTTPS. Certificates live in the `caddy-data` volume. Add
  `UC_CADDY_GLOBAL=email ops@example.com` for expiry notices.
- **Local trial.** Leave `UC_SITE_ADDRESS` unset: the site is served on `http://localhost:8080`.
- **Configuration.** Every variable is in `docs/ENV.md`. Put overrides in `.env`; Compose passes them to the API and
  both workers.
- **OCR.** Build with `WITH_OCR=true docker compose build` and set `ENABLE_OCR=true`.
- **Before going live**, edit the privacy notice and terms (`apps/web/src/app/privacy`, `terms`). They are marked
  as templates and need your organisation's details.

## Network isolation for the workers

`docker-compose.yml` defines two networks:

| Network | Members | Purpose |
|---|---|---|
| `internal` (`internal: true`) | redis, api, worker-fast, worker-heavy, web | No gateway: nothing on it can reach the internet or your LAN. |
| `edge` | caddy, api, web | Caddy's upstreams. |

The workers, which are the only processes that touch file contents, are on `internal` only, so even an engine
tricked by a crafted file can't make outbound requests. The API and web are on both networks so Caddy can reach
them; they don't run converters.

Every service that touches uploads runs with a **read-only root filesystem** (writable: the `jobs` volume and a
`tmpfs` at `/tmp`), `cap_drop: ALL`, `no-new-privileges`, and as an unprivileged user (UID 10001). Inside a
container, bubblewrap usually can't create namespaces under Docker's default seccomp profile. The sandbox detects
this at boot and runs jobs with rlimits + timeouts, relying on the container for network and filesystem isolation
(`/api/health` → `isolation.mode`). If you run workers outside containers on Linux, install `bubblewrap` and each
job gets its own network namespace and read-only view of the filesystem.

## Scaling workers

Two knobs:

1. **Concurrency per worker process**: `WORKER_CONCURRENCY_FAST` (Compose default 4) and `WORKER_CONCURRENCY_HEAVY`
   (default 1). Each job is a separate sandboxed process, so this is how many run at once. A good start: fast =
   number of vCPUs, heavy = vCPUs ÷ 4 (video encodes use several cores each).
2. **More worker containers** on the same VM: `docker compose up -d --scale worker-fast=2 --scale worker-heavy=2`.
   They share the `jobs` volume and Redis.

The two queues are independent, so a long video never delays an image conversion. The benchmark
`tests/api/test_concurrency.py` checks that 20 concurrent small jobs all succeed while a heavy encode runs. Scaling
across several VMs needs shared storage for `STORAGE_DIR` (the storage layer is an interface; only the local
volume implementation exists today) and a shared Redis.

Timeouts per queue: `JOB_TIMEOUT_FAST_S` (60) and `JOB_TIMEOUT_HEAVY_S` (900). Memory per job:
`JOB_MEMORY_FAST_MB` / `JOB_MEMORY_HEAVY_MB`. Raising `MAX_VIDEO_SIZE_MB` usually means raising the heavy timeout
too.

## Upgrading engines

Engines come from the images: FFmpeg, LibreOffice, bubblewrap and fonts from Debian (`python:3.12-slim-bookworm`),
Pandoc from its upstream `.deb` (`PANDOC_VERSION` build arg), Chromium from Playwright, and Python libraries from
`services/api/uv.lock`.

1. Update: `docker compose build --pull --no-cache` picks up Debian security updates. For Python libraries, run
   `uv lock --upgrade-package <name>` in `services/api`. For Pandoc, change `PANDOC_VERSION`.
2. **Re-run the test suites against the new engines before deploying** (`make test` on a machine with the same
   engine versions, or inside the image). Support levels are earned by tests (`verified.json`): a pair whose test
   fails after an upgrade stops being advertised, which is the intended safety net.
3. `docker compose up -d`. On SIGTERM a worker stops taking new jobs and gives running ones
   `WORKER_SHUTDOWN_GRACE_S` (20 s) to finish. Jobs still running after that are stopped, cleaned up and shown to
   the user as "The server restarted while converting this file. Try again." Queued jobs wait in Redis for the new
   workers. To let long video jobs finish, raise both `WORKER_SHUTDOWN_GRACE_S` and `stop_grace_period`.

`/api/health` lists every engine and its version, so you can confirm what's running after an upgrade.

## Backups

**None needed.** The service keeps no user data: uploads and results are deleted after `FILE_RETENTION_MINUTES`
(default 60), and Redis holds only short-lived job state (persistence is turned off). Losing the `jobs` volume or
Redis only cancels in-flight conversions. Keep your `.env` and any customised legal pages in version control.

## Operations

- **Logs**: `docker compose logs -f api worker-fast worker-heavy`. Each job logs one line with its ID, operation,
  formats, size, queue, state, error code and duration. File names and contents are never logged.
- **Health**: `GET /api/health` reports Redis, worker heartbeats per queue, engines and versions, disabled
  operations (with missing engines) and the isolation mode. Point your uptime monitor at it.
- **Disk**: the `jobs` volume holds at most what users uploaded within the retention window, plus outputs. Size it
  for your peak hourly volume × 2.
- **Abuse**: rate limits are per session and per IP (`docs/ENV.md`). Keep `TRUSTED_PROXY_HOPS=1` behind the bundled
  Caddy; if you put a CDN or load balancer in front of Caddy, add one per extra proxy.

## Go-live checklist

- [ ] `docker compose build` succeeds and `/api/health` shows every engine available and `status: ok`.
- [ ] Convert one file per category in the browser (PNG → JPG, DOCX → PDF, MP4 → MP3, XLSX → CSV, ZIP → 7Z).
- [ ] From inside a worker, outbound network fails: `docker compose exec worker-fast python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)"` must error.
- [ ] Run the e2e suite against the deployment: `E2E_BASE_URL=https://convert.example.com make test-e2e`.
- [ ] Privacy notice and terms edited and reviewed.
- [ ] `FILE_RETENTION_MINUTES` matches what your privacy notice says (the site shows the configured value).
