# Progress

Resume guide: read this file, then `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`. Run `make test` to see the current state.

## Milestone plan

| Milestone | Status |
|---|---|
| M0 Analyze & plan | done |
| M1 Walking skeleton (upload → detect → PNG→JPG with progress → download → cleanup, 1 Playwright test) | done |
| M2 Engine framework (registry, schemas→forms, capabilities/health, sandbox, fixtures, validators, matrix generator, sessions, limits, rate limits) | in progress (most pieces landed with M1) |
| M3 P1 modules: images → documents & PDF → spreadsheets → developer tools | not started |
| M4 P2 modules: presentations, audio, video, archives, utilities | not started |
| M5 UI completion | not started |
| M6 Hardening | not started |
| M7 Final verification | not started |

## Environment (M0 check, 2026-11-03, macOS arm64)

Present: bsdtar (libarchive), node 22, pnpm, uv, Homebrew, Google Chrome.
Installed via Homebrew: ffmpeg (libx264, libvpx-vp9, libmp3lame, libopus, wmav2, aac), pandoc 3.13, qpdf, redis, libmagic, LibreOffice (cask).
Python 3.12 venv in `services/api/.venv` (uv). Playwright Chromium installed.
Not available: Docker (Dockerfiles still shipped), bubblewrap/nsjail (macOS uses Seatbelt instead — D4).

## Done

- M0: environment check, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, this plan.
- M1: FastAPI + arq (fast/heavy workers) + Redis + Next.js 16 + Caddy on one origin (`./scripts/dev.sh`, http://localhost:8080).
  Streaming upload with mid-stream size limits, content-based detection, sandboxed job child (Seatbelt on macOS),
  SSE progress, download with safe headers, ZIP of a batch, delete now, sweeper + orphan cleanup, session binding.
  `image.convert` (9 raster formats incl. HEIC input, AVIF, ICO multi-size, animation) — 72 pairs Full.
  Playwright: drag-drop PNG → JPG → download → magic bytes.

## In progress

- M2 remaining: rate-limit + oversized-upload tests (need a second live instance with tiny limits), lifecycle
  tests with a short TTL, timeout/cancel tests, Vitest setup, health-driven engine disabling test.

## Next

- M3 images: `image.transform` (resize/compress/DPI/strip metadata, larger-output warning), SVG → raster/PDF
  (resvg + sanitizer), raster → SVG trace (experimental), raster → HEIC (experimental), background removal (flag).
- M3 documents & PDF, spreadsheets, developer tools (in that order).

## How to run

- Stack: `./scripts/dev.sh` → http://localhost:8080 (API docs at /api/docs). Logs in `.data/logs/`.
- Tests: `make test` (or `make test-api`, `make test-e2e`). API tests record `services/api/engine/verified.json`,
  which decides what the API advertises. Then `make matrix` regenerates `docs/SUPPORT_MATRIX.md`.

## Known issues

- CSP allows `'unsafe-inline'` scripts (Next.js inline bootstrap). Nonce-based CSP is planned for M6.
- macOS does not enforce `RLIMIT_AS` (DECISIONS D5); Linux/Docker does.
