# Progress

Resume guide: read this file, then `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`. Run `make test` to see the current state.

## Milestone plan

| Milestone | Status |
|---|---|
| M0 Analyze & plan | done |
| M1 Walking skeleton (upload → detect → PNG→JPG with progress → download → cleanup, 1 Playwright test) | done |
| M2 Engine framework (registry, schemas→forms, capabilities/health, sandbox, fixtures, validators, matrix generator, sessions, limits, rate limits) | done |
| M3 P1 modules: images → documents & PDF → spreadsheets → developer tools | done |
| M4 P2 modules: presentations, audio, video, archives, utilities | done |
| M5 UI completion | done |
| M6 Hardening | done |
| M7 Final verification | in progress |

## Environment (M0 check, 2026-11-03, macOS arm64)

Present: bsdtar (libarchive), node 22, pnpm, uv, Homebrew, Google Chrome.
Installed via Homebrew: ffmpeg (libx264, libvpx-vp9, libmp3lame, libopus, wmav2, aac), pandoc 3.13, qpdf, redis, libmagic,
LibreOffice (cask), caddy; tesseract 5.5 (M6, for OCR).
Python 3.12 venv in `services/api/.venv` (uv). Playwright Chromium installed.
Not available: Docker (Dockerfiles still shipped), bubblewrap/nsjail (macOS uses Seatbelt instead, D4).

## Done

- M0: environment check, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, this plan.
- M1: FastAPI + arq (fast/heavy workers) + Redis + Next.js 16 + Caddy on one origin (`./scripts/dev.sh`, http://localhost:8080).
  Streaming upload with mid-stream size limits, content-based detection, sandboxed job child (Seatbelt on macOS),
  SSE progress, download with safe headers, ZIP of a batch, delete now, sweeper + orphan cleanup, session binding.
- M2: limits/rate-limit/retention/cancel/timeout tests, registry + detection tests, Vitest, support-matrix generator +
  `--check` (CI gate).
- M3 (P1): images, documents & PDF, spreadsheets, developer tools (server and client-side), security canaries.
- M4 (P2): presentations, audio, video, archives, fonts, client utilities. Fixtures for all 62 formats.
- M5 (UI):
  - PDF page thumbnails, rendered in the sandbox (`app/previews.py`): drag or button reordering for `pdf.reorder`, and
    thumbnails on PDF results. Spreadsheet results (XLSX/XLS/ODS) preview their first 100 rows as a table, also via the
    sandbox. Images: before/after slider. Audio/video: players. Code/data: escaped text. CSV/TSV: table.
  - History panel (localStorage, metadata only, recent tools, clear, expired marked) on /convert and conversion pages.
  - /formats, /docs, /privacy, /terms (templates, marked), a 404 page, and an explanation page for
    `/convert/<a>-to-<b>` pairs that don't exist (links to what does). Files dropped on a conversion page they don't fit
    get a notice.
  - Tool directory ordered by category, with a cross-category sample on the home page.
  - Accessibility: axe-core (WCAG 2.1 A + AA) on every page type in both themes, plus a keyboard-only journey
    (skip link, Browse files, pick, convert, aria-live announcement). Fixed: in-text links now underlined.
  - Motion (entrance only, `reducedMotion="user"`). Lint clean (`make lint` added to `make test`).
  - Playwright journeys: batch ZIP, unsupported pair, merge with reordering, page reordering (buttons and drag),
    video → MP3 with real progress values, dark mode, history, spreadsheet preview, 390 px screenshots
    (`.data/screenshots/`), CSP.
- M6 (hardening):
  - Nonce-based CSP per request (`apps/web/src/proxy.ts`): no `'unsafe-inline'` scripts (D11).
  - Concurrency benchmark (`tests/api/test_concurrency.py`): 20 small jobs from 4 sessions while a VP9 encode runs.
    Measured: wall 2.70 s, median 1.72 s, max 2.70 s; the heavy job was still running at 7.8%.
  - Graceful worker shutdown: interrupted jobs are marked failed with "Try again" and cleaned up (D18, tested).
  - Error-message review: bare "Not found" 404s now say what expired; vague engine errors now give a next step.
  - Logs keep only the exception class for crashes, never stderr or messages (D19, tested).
  - OCR earned Experimental: OCRmyPDF (`ocr` dependency group) + Tesseract, no Ghostscript (D14). Fixed a dead
    "already has text" check.
  - Engine versions in `/api/health` are real (were "present"/module names); bubblewrap is probed before use (D17).
  - Dockerfiles (API/worker, web), `docker-compose.yml` (internal no-egress network for workers, read-only rootfs,
    cap_drop ALL, Valkey), `.dockerignore`.
  - Docs: README, ENV, DEPLOYMENT, SECURITY, THIRD_PARTY_LICENSES; DECISIONS D11–D22.
  - Background removal decided: not shipped, listed as Unsupported (D13).
- M7: see "Final verification" below.

## Final verification (M7)

At the M5+M6 commit (2026-11-03, this machine): `make test-api` 770 passed; `make test-web` (tsc, ESLint, Vitest) 68
passed; `make check-matrix` passed (617 Full, 22 Partial, 16 Experimental, 0 untested, 4 Unsupported);
`make test-e2e` 16 passed against the production build (`WEB_MODE=start`, standalone server).
Next: a fresh clone following README, then every suite.

## How to run

- Stack: `make dev` (or `./scripts/dev.sh`) → http://localhost:8080 (API docs at /api/docs). Logs in `.data/logs/`.
  Production web build: `cd apps/web && pnpm build`, then `WEB_MODE=start ./scripts/dev.sh`.
- Tests: `make test` (or `make test-api`, `make test-web`, `make test-e2e`). API tests record
  `services/api/engine/verified.json`, which decides what the API advertises. Then `make matrix` regenerates
  `docs/SUPPORT_MATRIX.md`.
- Don't run `make test-api` and `make test-e2e` at the same time on one machine: both start engines and live
  servers. Run them in sequence (as `make test` does).

## Known issues

- CSP keeps `style-src 'unsafe-inline'` (React style attributes can't carry a nonce; D11).
- macOS does not enforce `RLIMIT_AS` (DECISIONS D5); Linux/Docker does.
- Seatbelt profile allows LibreOffice's hard-coded `/tmp/OSL_PIPE_*` IPC socket and the `/tmp` directory entry.
- Experimental ops are hidden unless `ENABLE_EXPERIMENTAL=true` / `ENABLE_OCR=true` (tests run with them on).
- OGG output is Partial on hosts without libvorbis (FFmpeg's built-in encoder: stereo only); Full where libvorbis exists.
- Docker images and Compose file are untested here (no Docker). Run DEPLOYMENT.md's go-live checklist once.
- One full API run (2026-11-03) had 21 `test_extract_audio` failures (AVI/FLV/WMV/3GP sources) while e2e runs and a
  Homebrew install (which upgraded libarchive and other shared libraries) ran at the same time. They didn't reproduce in
  isolation, under heavy CPU load, or in any later full run, and the truncated log lost the error text, so the cause is
  unconfirmed. If it recurs, capture the full pytest output (`-rfE`).
- Accessibility is checked with automated rules plus a keyboard journey. A manual screen-reader pass is still
  recommended before launch.
