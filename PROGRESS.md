# Progress

Resume guide: read this file, then `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`. Run `make test` to see the current state.

## Milestone plan

| Milestone | Status |
|---|---|
| M0 Analyze & plan | done |
| M1 Walking skeleton (upload → detect → PNG→JPG with progress → download → cleanup, 1 Playwright test) | done |
| M2 Engine framework (registry, schemas→forms, capabilities/health, sandbox, fixtures, validators, matrix generator, sessions, limits, rate limits) | done |
| M3 P1 modules: images → documents & PDF → spreadsheets → developer tools | done |
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

- M2: limits/rate-limit/retention/cancel/timeout tests (second live instance with tiny limits), registry + detection
  tests, Vitest, support-matrix generator + `--check` (CI gate).
- M3 (P1, all categories, 313 API tests + 43 Vitest passing):
  - Images: convert (72 pairs), resize, compress (never returns a larger file), metadata/DPI, SVG → PNG/JPG/WebP
    (resvg) and vector PDF (Chromium), with an SVG sanitizer; experimental trace-to-SVG and raster → HEIC.
  - Documents & PDF: LibreOffice (DOCX/DOC/ODT/RTF/TXT ↔, → PDF), Pandoc (MD/HTML/DOCX/ODT), HTML/MD → PDF
    (Chromium, JS off, requests blocked), PDF → PNG/JPG, images → PDF (JPEG lossless), merge/split/extract/delete/
    reorder/rotate, text + image watermark, AES-256 protect, unlock (password or authorization confirm), compress
    (Partial), PDF → TXT/MD/HTML/DOCX/XLSX/CSV (Partial), OCR registered behind ENABLE_OCR (engine not installed).
  - Spreadsheets: export (computed values, sheet pick/all, injection guard), import CSV/TSV/JSON, XLSX↔XLS↔ODS, → PDF.
  - Developer: server-side data.convert (JSON/XML/YAML/TOML/CSV/TSV) + CSV → SQL; client-side tools (data convert,
    HTML↔MD, JSON formatter, code beautify/minify, CSV → SQL, Base64, URL, timestamps) at /tools/<slug>.
  - Security tests: SVG/HTML SSRF + file:// canaries, XXE, billion laughs, YAML alias bomb, WEBSERVICE canary,
    Pandoc never fetching, sandbox network/home/fsize/timeout process-group kill.

## In progress

- M4 P2 modules.

## Next

- M4: presentations (LibreOffice + chain PPTX → PDF → PNG, images → PPTX, PDF → PPTX image slides), audio + video
  (FFmpeg with -progress, protocol whitelist, playlist rejection), archives (ZIP/TAR/7Z/RAR read, every §7 limit),
  utilities (image ↔ base64, colour, units, bytes, QR, fonts).
- M5: PDF page thumbnails for reordering, remaining pages (/formats, /privacy, /terms, /docs), history UI, a11y pass.
- Background removal (rembg) is registered nowhere yet: decide in M6 whether to ship it (model weights license).

## How to run

- Stack: `./scripts/dev.sh` → http://localhost:8080 (API docs at /api/docs). Logs in `.data/logs/`.
- Tests: `make test` (or `make test-api`, `make test-e2e`). API tests record `services/api/engine/verified.json`,
  which decides what the API advertises. Then `make matrix` regenerates `docs/SUPPORT_MATRIX.md`.

## Known issues

- CSP allows `'unsafe-inline'` scripts (Next.js inline bootstrap). Nonce-based CSP is planned for M6.
- macOS does not enforce `RLIMIT_AS` (DECISIONS D5); Linux/Docker does.
- Seatbelt profile allows LibreOffice's hard-coded `/tmp/OSL_PIPE_*` IPC socket and the `/tmp` directory entry.
- Experimental ops are hidden unless `ENABLE_EXPERIMENTAL=true` (tests run with it on).
