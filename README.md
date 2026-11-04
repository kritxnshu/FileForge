# Universal Converter

One site for converting files between formats: images, PDFs, Word/Excel/PowerPoint, audio, video, archives, fonts
and developer data. Drop in files, pick a target (only the ones that work for that file are offered), adjust
settings, watch real progress, preview and download. Files are deleted automatically after a configurable retention
window, or right away with "Delete now".

PDF tools live at `/pdf`: merge, split, organize, crop, compress, repair, convert to and from Office and images,
edit (text, shapes, images, drawings), sign, redact, fill and create forms, page numbers, watermarks, protect and
compare.

Every conversion the UI offers is backed by an automated test that opens the result with an independent parser. See
[`docs/SUPPORT_MATRIX.md`](docs/SUPPORT_MATRIX.md), which is generated from the registry and the latest test run.

- **Web**: Next.js 16 (App Router), TypeScript, Tailwind, Motion, Lucide (`apps/web`). Text and data tools run in the
  browser.
- **API + workers**: Python 3.12, FastAPI, arq on Redis, two queues (`fast`, `heavy`) (`services/api`). Every
  conversion runs in its own sandboxed process with no network.
- **Engines**: Pillow, pillow-heif, resvg, pypdf, pikepdf, pypdfium2, pdfplumber, openpyxl, python-docx/pptx,
  fontTools, reportlab, FFmpeg, LibreOffice, Pandoc, Chromium, libarchive, Tesseract (optional), Ghostscript (optional,
  AGPL, PDF/A only).
- **Proxy**: Caddy serves everything on one origin and routes `/api` to FastAPI.

## Quick start

### Docker Compose

```sh
docker compose up -d --build      # → http://localhost:8080
```

For a real domain with automatic HTTPS, set `UC_SITE_ADDRESS=convert.example.com` (see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).

### Native (macOS or Linux)

Install the system tools once:

```sh
# macOS (Homebrew)
brew install uv node pnpm redis caddy ffmpeg pandoc tesseract   # uv fetches Python 3.12 itself
brew install --cask libreoffice

# Debian/Ubuntu
sudo apt install ffmpeg pandoc libreoffice-nogui redis-server libarchive-tools bubblewrap tesseract-ocr
#   plus uv (https://docs.astral.sh/uv/), Node 22 + pnpm (corepack enable), and Caddy (https://caddyserver.com/docs/install)
```

Then, from the repo root:

```sh
make setup     # Python venv (uv), Playwright's Chromium, web + e2e dependencies
make dev       # Redis, API, both workers, Next.js and Caddy → http://localhost:8080
```

API docs (OpenAPI) are at http://localhost:8080/api/docs and engine status at `/api/health`. Logs go to
`.data/logs/`. Tesseract is optional; without it the OCR tool is disabled and `/api/health` says so.

## Tests

```sh
make test
```

That runs everything, in order:

| Target | What it runs |
|---|---|
| `make test-api` | pytest: the converter matrix (every advertised pair, validated with an independent parser), negative tests, security tests (SSRF, XXE, zip slip, bombs, playlists, `WEBSERVICE`, cross-session access…), lifecycle tests (limits, rate limits, expiry, cancel, timeouts), the concurrency benchmark, and HTTP tests against live API + worker processes. Results are recorded in `services/api/engine/verified.json`. |
| `make test-web` | `tsc`, ESLint, then Vitest round-trip tests for the client-side tools. |
| `make matrix` / `make check-matrix` | Regenerate `docs/SUPPORT_MATRIX.md`; fail if any Full/Partial pair lacks a passing test. |
| `make test-e2e` | Playwright: drag-and-drop PNG → JPG, a mixed batch → ZIP, unsupported pairs, merge with reordering, page-thumbnail reordering, video → MP3 with progress, dark mode, history, 390 px layouts, CSP, and WCAG 2.1 AA checks (axe-core) in both themes. Starts the stack with `scripts/dev.sh` if it isn't running. |

**What gets advertised is decided by the tests.** A pair appears in the UI only after its test passes, and stops
appearing if it fails (DECISIONS D7). Don't edit `verified.json` or `SUPPORT_MATRIX.md` by hand.

## Adding a conversion

Add a converter module under `services/api/engine/converters/<category>/` that registers an `Operation` (formats,
cardinality, a Pydantic options model, engines, queue, target support level, limitations), a fixture builder in
`tests/fixtures/generate.py`, and a matrix test plus a negative test. The UI picks up the new operation, its settings
form (from the JSON Schema) and its `/convert/<a>-to-<b>` page automatically.

## Docs

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, request flow, registry, storage |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every deviation from the build prompt and why |
| [`docs/SUPPORT_MATRIX.md`](docs/SUPPORT_MATRIX.md) | Generated: every operation and pair, its support level and test status |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, mitigations and the test for each |
| [`docs/ENV.md`](docs/ENV.md) | Every environment variable |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Single-VM Docker Compose with TLS, worker isolation, scaling, upgrades |
| [`docs/THIRD_PARTY_LICENSES.md`](docs/THIRD_PARTY_LICENSES.md) | Dependencies and licences, AGPL policy, image distribution |
| [`PROGRESS.md`](PROGRESS.md) | Milestones, current state, known issues |

The privacy notice and terms in the web app are **templates**: whoever runs the site must review them and add their
details.
