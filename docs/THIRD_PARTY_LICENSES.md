# Third-party licences

Every dependency, with its licence, and what each licence asks of you. Python and JavaScript licences were read from
the installed packages' metadata (`importlib.metadata`, `pnpm licenses list --prod`) on 2026-11-03; versions are
the ones in `services/api/uv.lock` and `apps/web/pnpm-lock.yaml` at that date.

**Policy.** Prefer permissive licences. GPL/LGPL command-line tools run only as separate processes, never linked into
our code. AGPL components are off by default behind `ENABLE_AGPL_ENGINES=false` and aren't installed. Non-free
codecs (e.g. fdk-aac) aren't used: AAC uses FFmpeg's built-in encoder.

## Engines (separate processes)

| Component | Licence | Used for | Notes |
|---|---|---|---|
| FFmpeg / ffprobe | LGPL-2.1+; **GPL** when built with libx264/libx265 (Debian's build and Homebrew's are; Homebrew's is GPL-3.0) | Audio and video | Separate process. Bundled codecs: libx264, libx265 (GPL-2.0+), libvpx (BSD-3), LAME (LGPL-2.0), Opus and Vorbis (BSD-3). |
| LibreOffice (headless `soffice`) | MPL-2.0 | Office documents, spreadsheets, presentations | Separate process, fresh profile per job. |
| Pandoc | GPL-2.0-or-later | Markdown/HTML/DOCX/ODT | Separate process, always `--sandbox`. |
| Chromium (via Playwright) | BSD-3-Clause and others (Chromium's bundled third-party licences) | HTML → PDF, SVG → PDF | Downloaded by `playwright install`. |
| bsdtar / libarchive | BSD-2-Clause | Reading RAR and other archives | Also loaded by `libarchive-c`. |
| bubblewrap | LGPL-2.0-or-later | Linux job isolation | Separate process. |
| Tesseract (optional, `ENABLE_OCR`) | Apache-2.0 | OCR | Docker: `WITH_OCR=true`. |
| OCRmyPDF (optional, `ENABLE_OCR`) | MPL-2.0 | OCR pipeline | Run with `--output-type pdf`, so Ghostscript (AGPL) isn't needed. |
| Valkey (Docker Compose) | BSD-3-Clause | Queue and job state | Development uses whatever Redis is installed (Homebrew's Redis 8 is RSALv2/SSPLv1/AGPLv3). Redis ≤ 7.2 is BSD-3. The app talks to it over the network only. |
| Caddy | Apache-2.0 | Reverse proxy, TLS | |

## Python (`services/api`)

| Package | Licence | | Package | Licence |
|---|---|---|---|---|
| fastapi | MIT | | pdfplumber (+ pdfminer.six) | MIT |
| uvicorn | BSD-3-Clause | | reportlab | BSD |
| pydantic, pydantic-settings | MIT | | img2pdf | **LGPL-3.0** |
| python-multipart | Apache-2.0 | | openpyxl | MIT |
| arq | MIT | | pandas | BSD-3-Clause |
| redis (client) | MIT | | xlrd | BSD |
| sse-starlette | BSD-3-Clause | | odfpy | Apache-2.0 / GPL / LGPL (choose Apache-2.0) |
| charset-normalizer | MIT | | python-docx | MIT |
| olefile | BSD-2-Clause | | python-pptx | MIT |
| defusedxml | PSF-2.0 | | fonttools | MIT |
| pyyaml | MIT | | brotli | MIT |
| tomli-w | MIT | | py7zr | **LGPL-2.1-or-later** |
| Pillow (bundles libavif, libaom, dav1d: BSD-2) | MIT-CMU (HPND) | | segno | BSD-3-Clause |
| pillow-heif | BSD-3-Clause; **bundles libheif and libde265 (LGPL-3.0) and libx265 (GPL-2.0+)** | | playwright | Apache-2.0 |
| resvg-py (bundles resvg) | MIT (resvg: Apache-2.0 OR MIT) | | markdown-it-py | MIT |
| pypdf | BSD-3-Clause | | zipstream-ng | **LGPL-3.0-only** |
| pikepdf (bundles qpdf) | MPL-2.0 (qpdf: Apache-2.0) | | vtracer | MIT |
| pypdfium2 (bundles PDFium) | BSD-3-Clause / Apache-2.0 (PDFium: BSD-3) | | libarchive-c | CC0-1.0 |

Optional `ocr` group (installed by default for development; in Docker only with `WITH_OCR=true`): ocrmypdf (MPL-2.0),
fpdf2 (**LGPL-3.0-only**), uharfbuzz (Apache-2.0), rich, jsonschema, attrs, referencing, rpds-py (MIT).

Test-only: pytest (MIT), pytest-asyncio (Apache-2.0), pytest-timeout (MIT), httpx (BSD-3), zxing-cpp (Apache-2.0,
decodes QR codes back in tests).

**LGPL Python libraries** (img2pdf, py7zr, zipstream-ng, fpdf2, and the LGPL parts of pillow-heif) are used unmodified and
imported dynamically; their source is what's installed, and users can replace them. Keep their licence texts with any
distribution.

**pillow-heif and x265.** HEIC *decoding* uses libheif/libde265 (LGPL). HEIC *encoding* (raster → HEIC,
Experimental) uses the bundled x265 encoder, which is GPL-2.0+, and HEVC is patent-encumbered in some
jurisdictions. That is one reason raster → HEIC is Experimental and hidden by default.

## JavaScript (`apps/web`, production dependencies)

About 100 packages, nearly all MIT/ISC/BSD/Apache. By licence:

| Licence | Packages (notable) |
|---|---|
| MIT | next, react, react-dom, motion (framer-motion), prettier, sql-formatter, qrcode, marked, js-yaml, fast-xml-parser, csso, papaparse, node-html-markdown, xml-formatter, fast-png, acorn, and ~60 small transitive packages |
| ISC | lucide-react, and small transitive packages |
| BSD-2-Clause | terser, css-select/css-what/domhandler family |
| BSD-3-Clause | smol-toml, source-map |
| Apache-2.0 | @swc/helpers |
| 0BSD | tslib |
| CC0-1.0 | mdn-data |
| CC-BY-4.0 | caniuse-lite (browser support data used at build time) |

Fonts: Bricolage Grotesque and Instrument Sans, both SIL Open Font License 1.1, self-hosted by `next/font`.

Development and test only: TypeScript (Apache-2.0), ESLint (MIT), Tailwind CSS (MIT), Vitest (MIT), jsqr
(Apache-2.0), @playwright/test (Apache-2.0), @axe-core/playwright and axe-core (MPL-2.0).

## AGPL components (off by default)

`ENABLE_AGPL_ENGINES=false`. None of these are installed or imported unless you opt in. AGPL obligations apply to
network services: if users interact with the service over a network, you must offer them the complete corresponding
source of the AGPL work and your modifications to it.

| Component | What it would unlock |
|---|---|
| PyMuPDF → pdf2docx | Better layout fidelity for PDF → DOCX (tables, columns, images in place). With the flag on *and* pdf2docx installed, PDF → DOCX uses it; otherwise the permissive pdfplumber → python-docx pipeline (Partial) is used. |
| Ghostscript | PDF/A output from OCRmyPDF, and Ghostscript-based PDF compression. Not used: OCR runs with `--output-type pdf`, and compression uses pikepdf + Pillow. |
| IMG.LY background removal | In-browser/server background removal. Not shipped (DECISIONS D13). |

## Distributing the Docker images

Running the service yourself needs nothing beyond keeping these notices. **If you distribute the images** (push them
to a public registry, hand them to customers), the GPL/LGPL components inside obligate you to provide their
corresponding source, or a written offer for it, and their licence texts:

- FFmpeg (GPL, with x264), Pandoc (GPL), bubblewrap (LGPL), LibreOffice (MPL, file-level source), and other Debian
  packages: source via `apt-get source <package>` from the Debian release used (bookworm). Licence texts are in
  `/usr/share/doc/<package>/copyright` inside the image.
- pillow-heif's bundled libx265 (GPL-2.0+) and libheif/libde265 (LGPL-3.0): source at the versions recorded in the
  pillow-heif release you ship.
- Pandoc is installed from the upstream `.deb` (`PANDOC_VERSION` in `services/api/Dockerfile`); its source is the
  matching tag at github.com/jgm/pandoc.
