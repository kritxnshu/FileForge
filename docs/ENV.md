# Environment variables

The API and workers read these through `services/api/app/config.py` (one `Settings` class). They share one set of
values: set them identically for the `api`, `worker-fast` and `worker-heavy` services (`docker-compose.yml` does this
with a shared anchor). Booleans accept `true`/`false`.

## Core

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_DIR` | `./data` (Docker: `/data`) | Job volume shared by the API and workers: `uploads/<id>/` and `jobs/<id>/{in,out,work}`. Must be the same path in every process. |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue, job state, sessions, rate-limit counters and progress pub/sub. Nothing in it needs backing up. |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | The site's public origin, e.g. `https://convert.example.com`. |
| `LOG_LEVEL` | `INFO` | Python log level for the API and workers. Logs hold job IDs, formats, sizes, durations and error classes, never file names or contents. |
| `COOKIE_SECURE` | `true` | Sets `Secure` on the session cookie. Browsers accept Secure cookies on `http://localhost`; only set `false` for plain-HTTP testing on another host. |
| `TRUSTED_PROXY_HOPS` | `0` (Docker and `dev.sh`: `1`) | How many reverse proxies sit in front of the API. The client IP used for per-IP rate limits is taken that many entries from the right of `X-Forwarded-For`. `0` uses the socket address. Set it to exactly the number of proxies you run, or clients can spoof their IP. |

## Size and content limits

| Variable | Default | Purpose |
|---|---|---|
| `MAX_FILE_SIZE_MB` | `100` | Per-file upload limit (non-video). Enforced while streaming; the upload is cut off at the limit (413). |
| `MAX_VIDEO_SIZE_MB` | `500` | Per-file limit for files detected as video. |
| `MAX_BATCH_FILES` | `20` | Files per upload request and per batch. |
| `MAX_BATCH_TOTAL_MB` | `1000` | Total bytes per upload request. |
| `MAX_IMAGE_PIXELS` | `100000000` | Pillow's decompression-bomb limit (100 MP), also applied to rendered PDF pages and resize targets. |
| `ARCHIVE_MAX_ENTRIES` | `10000` | Entries per archive. |
| `ARCHIVE_MAX_UNCOMPRESSED_MB` | `2000` | Total unpacked size per archive, counted while streaming (header sizes are not trusted). |
| `ARCHIVE_MAX_RATIO` | `100` | Maximum compression ratio per entry (zip-bomb guard). |
| `ARCHIVE_MAX_DEPTH` | `2` | How deep archives nested inside archives may go. |

## Jobs and workers

| Variable | Default | Purpose |
|---|---|---|
| `JOB_TIMEOUT_FAST_S` | `60` | Wall-clock limit for jobs on the `fast` queue (images, data, small PDFs). The whole process group is killed. |
| `JOB_TIMEOUT_HEAVY_S` | `900` | Limit for the `heavy` queue (video, office documents, OCR). |
| `JOB_MEMORY_FAST_MB` | `2048` | `RLIMIT_AS` per fast job (enforced on Linux; macOS ignores it, see DECISIONS D5). |
| `JOB_MEMORY_HEAVY_MB` | `4096` | `RLIMIT_AS` per heavy job. |
| `WORKER_CONCURRENCY_FAST` | CPU count (min 2) | Jobs one fast-worker process runs at once. Docker Compose sets `4`. |
| `WORKER_CONCURRENCY_HEAVY` | CPU count ÷ 4 (min 1) | Jobs one heavy-worker process runs at once. Docker Compose sets `1`. |
| `WORKER_SHUTDOWN_GRACE_S` | `20` | On SIGTERM a worker stops taking jobs and lets running ones finish for this long; any still running are then stopped and shown as "The server restarted while converting this file. Try again." Keep the container stop timeout above it (Compose: `stop_grace_period: 30s`). |
| `FILE_RETENTION_MINUTES` | `60` | Uploads and results are deleted this long after upload. The UI, privacy notice and docs read this value from the API. Fractions allowed (tests use seconds). |
| `SWEEP_INTERVAL_S` | `60` | How often the sweeper deletes expired files. Orphaned directories are also removed at startup. |

## Rate limits

Per session and per IP. The per-IP limit is 3× the session limit, so a few people behind one NAT aren't blocked by each
other. Over a limit the API returns 429 with `Retry-After`.

| Variable | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_JOBS_PER_10MIN` | `30` | Conversions started per 10 minutes. |
| `RATE_LIMIT_UPLOADS_PER_10MIN` | `60` | Upload requests per 10 minutes. |
| `RATE_LIMIT_MB_PER_HOUR` | `2000` | Uploaded megabytes per hour. |
| `RATE_LIMIT_CONCURRENT_JOBS` | `10` | Unfinished jobs one session may have at once. |

## Feature flags

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_AGPL_ENGINES` | `false` | Allows AGPL engines, each used only if it is also installed: pdf2docx (via PyMuPDF) for PDF → DOCX (otherwise the permissive pdfplumber → python-docx pipeline is used), and Ghostscript for the "PDF to PDF/A" tool (otherwise that tool isn't offered; the Docker image doesn't install `gs`). AGPL obligations apply to network services; see THIRD_PARTY_LICENSES.md. |
| `ENABLE_OCR` | `false` | Shows the Experimental "Make PDF searchable (OCR)" tool. Needs `ocrmypdf` and `tesseract` (Docker: build with `WITH_OCR=true`). |
| `ENABLE_BACKGROUND_REMOVAL` | `false` | Reserved. Background removal is not shipped (DECISIONS D13), so this currently has no effect. |
| `ENABLE_EXPERIMENTAL` | `false` | Shows the other Experimental operations (raster → HEIC, trace to SVG, TTF ↔ OTF outlines). They're tested either way; the flag only controls whether they're offered. |

## Sandbox and engines

| Variable | Default | Purpose |
|---|---|---|
| `SANDBOX_ISOLATION` | `auto` | `auto` uses Seatbelt on macOS, or bubblewrap on Linux when it can create namespaces; otherwise rlimits + timeouts. `off` forces rlimits + timeouts only (in containers that's fine, because the container provides network and filesystem isolation). `/api/health` reports the mode in use. |
| `SANDBOX_UID` | `65534` | If the worker runs as root, job processes drop to this UID. The Docker image runs as UID 10001 and never needs it. |
| `SANDBOX_EXTRA_READ` | (empty) | Extra read-only paths (`:`-separated) job processes may read under the macOS Seatbelt profile, e.g. a custom font directory. |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright's default (Docker: `/opt/ms-playwright`) | Where the Chromium used for HTML → PDF and SVG → PDF lives. |
| `UC_FFMPEG`, `UC_FFPROBE`, `UC_PANDOC`, `UC_SOFFICE`, `UC_GS` | found on `PATH` | Absolute paths to override the engine binaries (`UC_GS`: Ghostscript, for PDF/A). |
| `UC_SRGB_ICC` | Ghostscript's own `srgb.icc` | sRGB ICC profile embedded as the PDF/A output intent. |
| `UC_UNICODE_FONT` | DejaVu Sans or Arial Unicode, if found | TrueType font for text the built-in PDF fonts can't show (e.g. Cyrillic, Greek) in Edit PDF, Sign PDF and page numbers. Coverage depends on the font (DejaVu Sans, for example, has no Devanagari). Without one, such text is refused with a clear message. |
| `UC_DEBUG_ERRORS` | (unset) | `1` appends the engine's last stderr line to error messages shown to the user. Development only: engine output can contain file contents. |
| `UC_VERIFIED_PATH` | `services/api/engine/verified.json` | Where test results (which decide what is advertised) are read from and written to. |

## Web app (`apps/web`)

| Variable | Default | Purpose |
|---|---|---|
| `INTERNAL_API_URL` | `http://127.0.0.1:8000` (Docker: `http://api:8000`) | Where the Next.js server fetches `/api/capabilities` during server rendering. Browsers always use the same-origin `/api`. |
| `PORT`, `HOSTNAME` | `3000`, `0.0.0.0` in Docker | Next.js standalone server bind address. |

## Reverse proxy (`deploy/Caddyfile`)

| Variable | Default | Purpose |
|---|---|---|
| `UC_SITE_ADDRESS` | `:8080` | Caddy site address. A domain name (e.g. `convert.example.com`) turns on automatic HTTPS. |
| `UC_API_UPSTREAM` | `127.0.0.1:8000` (Docker: `api:8000`) | FastAPI upstream for `/api/*`. Uploads stream straight here and never pass through Next.js. |
| `UC_WEB_UPSTREAM` | `127.0.0.1:3000` (Docker: `web:3000`) | Next.js upstream for everything else. |
| `UC_MAX_REQUEST_MB` | `1100` | Request-body cap at the proxy for uploads. Keep it a little above `MAX_BATCH_TOTAL_MB`. Every other API request is capped at 20 MB by the proxy (and job settings at 16 MB by the API). |
| `UC_CADDY_GLOBAL` | (empty) | Extra Caddy global options, e.g. `email ops@example.com` for ACME. |

## Development and tests

| Variable | Default | Purpose |
|---|---|---|
| `WEB_MODE` | `dev` | `scripts/dev.sh`: `dev` runs `next dev`; `start` runs the production build (`pnpm build` first). |
| `E2E_BASE_URL` | (unset) | Run Playwright against an already-running site instead of starting `scripts/dev.sh`. |
| `UC_NO_RECORD` | (unset) | `1` stops a pytest run from writing results to `verified.json` (useful for partial runs). |
