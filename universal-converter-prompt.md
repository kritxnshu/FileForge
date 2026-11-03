# Build "Universal Converter": an all-in-one file conversion platform

You're the lead engineer on this project, covering full-stack development, architecture, UX and document processing. You'll build a production-quality web app where people convert files between formats in one place, so nobody needs five different websites for five file types.

This is a long build that will run across several sessions. **The goal is a working, tested product at every milestone, not a long feature list.** A smaller set of conversions that really work beats a large set that are half done. Sections 1–4 are the non-negotiables. Sections 5–10 are the spec. Sections 11–12 cover how to work and what to hand back.

Where this prompt gives a default (a library, a limit, a layout), use it unless you find a concrete reason not to. Record every deviation and its reason in `docs/DECISIONS.md`.

---

## 1. Outcome

A user can open one site and:

1. Drop in one or many files, or paste text for the developer tools.
2. See each file's detected format and size.
3. Pick a target format or operation from the options that are supported for that input, and no others.
4. Adjust settings relevant to that conversion.
5. Watch real progress.
6. Preview results where it makes sense (before/after for images).
7. Download each result, or all results as one ZIP.
8. Delete their files right away, or let them expire automatically.

**Success means** every conversion the UI advertises is backed by a passing automated test. That test opens the output with an independent parser or decoder.

## 2. Non-negotiable rules (and why)

1. **Real conversions only.** Every output must be a valid file in the target format, produced by actually transcoding, re-encoding or re-rendering the content. These all count as fakes:
   - renaming an extension
   - wrapping one format inside another and calling it converted (for example, putting a PNG inside an `<svg><image>` tag)
   - putting page screenshots into a PPTX without saying so

   When the only feasible approach is lossy or produces something non-editable, ship it with a label that says so ("Image-based slides — not editable").
2. **No mocks and no fake progress.** The progress users see comes from the engine: FFmpeg progress output, page N of M, or file N of M in a batch. Some engines report nothing (LibreOffice, for example). For those, show honest stage labels (Queued → Converting → Finalizing) with an indeterminate indicator. Never show a made-up percentage.
3. **Nothing is advertised until it's tested.** Support levels come from the registry plus test results (§9). The UI reads them from the API and never hard-codes a list of supported conversions.
4. **Copy must not overstate.** Marketing, privacy and security text must match what the code does:
   - the retention period comes from config
   - "Files never leave your browser" appears only on client-side tools
   - no "military-grade encryption" and no compliance claims

   Legal pages are clearly marked as templates for the owner to review.
5. **Never weaken a test to make it pass.** Don't delete, skip or loosen a test so a conversion looks supported. Lower its support level and document why.
6. **Keep the architecture simple.** One frontend, one backend service with worker processes, and one queue. No per-engine microservices and no Kubernetes.
7. **No major features left as TODOs.** If something is out of reach, list it as Unsupported or Experimental in the matrix with a reason. Don't leave a stub in the code.
8. **Keep the build green at every milestone.** If you run out of time or context, the repo must still run, still pass its tests, and still describe accurately what works.

## 3. Out of scope

Don't build any of these:

- user accounts or payments
- cloud-drive integrations
- a public API with keys
- password cracking or brute-forcing
- DRM removal
- creating RAR archives (the format is proprietary, so RAR is extract-only)
- AI features, apart from optional background removal

## 4. Starting point

1. **Inspect the repo first.** If it has code, write `docs/ANALYSIS.md` covering its architecture, dependencies, features and gaps. Extend what's there rather than rewriting it. The exception is code that's fundamentally unsuitable, in which case explain why in `DECISIONS.md`.
2. **If the repo is empty,** scaffold from the defaults below.
3. **Check which system tools are present:** `ffmpeg`, `ffprobe`, `soffice` (LibreOffice), `pandoc`, Chromium, `bsdtar` (libarchive), `qpdf` and Redis. Install whatever's missing. If Docker isn't available where you're working, install packages natively for development and still ship Dockerfiles for deployment. Don't block on Docker.

---

## 5. Architecture (defaults)

### Stack

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Motion (Framer Motion) and Lucide icons.
- **Backend:** one Python 3.12+ service. FastAPI serves the HTTP API. Worker processes consume a Redis-backed job queue; pick one of RQ, arq, Celery or Huey and note why.
  - Python is the default because most of the libraries this needs are Python libraries (Pillow, pypdf, pikepdf, openpyxl, python-docx, python-pptx, fontTools).
  - The heavy engines (FFmpeg, LibreOffice, Pandoc, Chromium) are command-line tools, so any language can drive them.
  - Don't add a second backend language without a strong reason.
- **One origin:** a reverse proxy (Caddy or nginx) serves the web app and routes `/api` to FastAPI. Large uploads go straight to FastAPI and never stream through Next.js.
- **Storage:** a local job-directory volume shared by the API and the workers, behind a small storage interface so S3-compatible storage can be added later.
- **Client-side tools:** pure text and data utilities run entirely in the browser. That covers JSON/YAML/XML formatting, Base64, URL encoding, timestamps, colors, units and QR codes. They're faster and cheaper this way, and the data never leaves the device. Give them a "Runs in your browser" badge.

### Suggested layout

```
apps/web/                  Next.js app
services/api/
  app/                     FastAPI routes: uploads, jobs, capabilities, downloads, health
  engine/
    registry.py            conversion registry + chain planner
    detect.py              format detection
    sandbox.py             subprocess runner with isolation + limits
    converters/<category>/ one module per engine/family
    validators/            independent output validators (used by tests)
  worker.py
tests/                     fixture generator, converter matrix, security, lifecycle, e2e (Playwright)
docs/                      ANALYSIS, DECISIONS, ARCHITECTURE, SUPPORT_MATRIX (generated),
                           SECURITY, ENV, DEPLOYMENT, THIRD_PARTY_LICENSES
PROGRESS.md
docker-compose.yml
```

### The conversion registry (the heart of the system)

Every capability is a registered **operation** that declares:

- **Identity:** `id`, `category`, a human-readable label and a description.
- **Inputs, outputs and cardinality:**
  - one → one (PNG → JPG)
  - one → many (PDF → JPG pages, split PDF)
  - many → one (merge PDFs, images → PDF)
  - same-format transforms (compress, rotate, trim)
- **Options:** a Pydantic model, exported as JSON Schema. The frontend builds its settings forms from that schema, so a new converter gets a UI without any frontend code.
- **`engine_requirements`** (for example `ffmpeg` or `soffice`), checked at boot. If an engine is missing, its operations are disabled automatically and `/api/health` reports it.
- **`resource_class`:** `fast` or `heavy`, which decides the queue.
- **`runtime`:** `server` or `client`.
- **Target support level and `known_limitations`.** Tests confirm the level or lower it.

**Adding a format means adding one converter module plus its fixtures.** Nothing else in the app should have to change.

**Chained conversions** can be planned automatically as a shortest path through the registry, up to 3 hops. Examples: PPTX → PNG runs as PPTX → PDF → PNG, and HEIC → PDF as HEIC → PNG → PDF. A chain is exposed only after it has its own end-to-end test.

### API (minimum)

| Endpoint | Purpose |
|---|---|
| `GET /api/capabilities` | Formats, operations, option schemas, support levels and limits |
| `POST /api/uploads` | Streaming multipart upload. Returns file IDs, detected format, size and warnings. |
| `POST /api/jobs` | Takes `{file_ids, operation, target, options}` and returns job IDs. A batch is one job per file plus a batch ID. |
| `GET /api/jobs/{id}` and `GET /api/jobs/{id}/events` (SSE) | State, progress and errors |
| `GET /api/jobs/{id}/files/{n}` | Download one output |
| `GET /api/batches/{id}/zip` | ZIP of a batch, streamed and built on the fly |
| `DELETE /api/jobs/{id}` (and per session) | Delete immediately |
| `GET /api/health` | Engine availability and versions |

Job states: `queued → running → succeeded | failed | cancelled | expired`. Users can cancel a job, and cancelling kills the engine's whole process group.

### Format detection

Detect the format from the content, not only the extension.

**Binary formats**

- Check magic bytes with libmagic or `filetype`.
- Where magic bytes are ambiguous, look inside the container:
  - **ZIP-based:** DOCX/XLSX/PPTX (`[Content_Types].xml`), ODF (`mimetype` entry), EPUB, plain ZIP
  - **OLE2/CFB:** DOC, XLS and PPT by stream name (`olefile`)
  - **ISO-BMFF:** the `ftyp` brand tells MP4, MOV, M4A, HEIC and AVIF apart
  - **RIFF:** WAV, AVI or WebP
- Confirm audio and video with `ffprobe`.

**Text formats** have no signature.

- Detect the encoding with `charset-normalizer`, then try to parse:
  - JSON
  - XML, SVG or HTML (by the root element)
  - YAML
  - CSV or TSV (with a sniffer)
- Markdown and TXT go by extension.

**Mismatches:** if the extension and the content disagree, trust the content and show a warning. Reject a file whose content can't be identified and isn't plain text.

---

## 6. Conversion scope and target support levels

There are four support levels:

- **Full:** reliable, and content is preserved within the limits of the format.
- **Partial:** works, with a documented loss of fidelity. The UI states the limitation before the user converts.
- **Experimental:** works on the test fixtures. Hidden unless its feature flag is on, and labeled in the UI.
- **Unsupported:** listed in the docs with a reason.

The levels below are targets; the tests decide the final level. **Build all P1 categories, each fully tested, before starting P2.**

### Images (P1)

**Engines:**

- Pillow
- `pillow-heif` for HEIC and HEIF
- a sandboxed SVG rasterizer such as resvg or CairoSVG, with external resource loading turned off

| Conversion / tool | Target | Notes |
|---|---|---|
| PNG, JPG, WebP, GIF, BMP, TIFF, ICO, AVIF ↔ each other | Full | **Detection:** probe AVIF encode/decode support at boot.<br>**Transparency:** keep alpha where the target supports it. Otherwise flatten onto a background color the user picks (default white).<br>**ICO:** write multiple sizes, 16–256 px. |
| Animated GIF / WebP ↔ each other | Full | Keep frames and timing. Converting to a static format uses the first frame and shows a notice. |
| HEIC/HEIF → any raster format, PDF | Full | Respect EXIF orientation. |
| Raster → HEIC | Experimental | Encoder and patent constraints. |
| SVG → PNG/JPG/WebP/PDF | Full | Option for output size or DPI. No external fetches. |
| Raster → SVG | Experimental | Real vector tracing only (for example vtracer), labeled "Trace to vector". |
| Resize, compress, quality, DPI, strip metadata | Full | Show size before and after. If the "compressed" output is larger, warn and offer the original. |
| Background removal | Experimental | `rembg`, behind `ENABLE_BACKGROUND_REMOVAL`. Check the license on the model weights; some, such as BRIA RMBG, are non-commercial. |

### Documents & PDF (P1)

**Engines:**

- LibreOffice (headless)
- Pandoc (always with `--sandbox`)
- Chromium via Playwright for HTML → PDF
- PDF libraries: pypdf, pikepdf, pypdfium2, pdfplumber, reportlab and img2pdf

| Conversion / tool | Target | Notes |
|---|---|---|
| DOCX, DOC, ODT, RTF, TXT → PDF | Full | LibreOffice. |
| DOCX ↔ DOC ↔ ODT ↔ RTF | Full | LibreOffice. |
| Markdown ↔ HTML; Markdown/HTML → DOCX/ODT; DOCX → Markdown | Full | Pandoc with `--sandbox`. |
| HTML → PDF | Full | Chromium with JavaScript off and all network requests blocked. Options for page size and margins. |
| PDF → DOCX | Partial | **Scope:** text-based PDFs only, and layout fidelity varies. Scanned PDFs are Unsupported unless OCR is on.<br>**Engine and license:** the best open-source quality comes from pdf2docx, which depends on PyMuPDF (AGPL; see §8). With AGPL engines off, either build a permissive approach that passes the content-preservation tests (for example pdfplumber → python-docx) and mark it Partial, or mark the conversion Unsupported. |
| PDF → TXT / Markdown / HTML | Partial | Extracts text; layout is not preserved. |
| PDF → PNG/JPG (per page, DPI option) | Full | pypdfium2. |
| Images → PDF | Full | One image per page, with page-size and fit options. img2pdf (lossless JPEG embedding) or Pillow. |
| Merge, split, extract, delete, reorder, rotate pages | Full | pypdf or pikepdf. Page ranges in the form `1-3,7`. The UI shows page thumbnails for reordering. |
| Text or image watermark | Full | reportlab overlay plus pypdf. |
| Password-protect (AES-256) | Full | pikepdf. |
| Remove password | Full | Only with the correct password, supplied by the user. For restriction-only (owner-password) PDFs, the user must confirm they're authorized. No cracking. |
| Compress PDF | Partial | Downsample and recompress images and optimize object streams. Report the size change, and never return a larger file as "compressed". |
| OCR: scanned PDF → searchable PDF | Experimental | OCRmyPDF and Tesseract, behind `ENABLE_OCR`. |

### Spreadsheets (P1)

**Engines:** openpyxl, pandas and LibreOffice.

| Conversion | Target | Notes |
|---|---|---|
| XLSX / XLS / ODS → CSV / TSV / JSON | Full | CSV holds one sheet, so the user picks a sheet or gets a ZIP with one CSV per sheet. Exports computed values, not formulas. |
| CSV / TSV / JSON → XLSX / ODS | Full | Detect delimiter and encoding. JSON must be an array of objects; nested data is flattened by documented rules. |
| XLSX ↔ XLS ↔ ODS | Full | LibreOffice. All sheets are preserved. |
| XLSX / XLS / ODS / CSV → PDF | Full | LibreOffice, with a fit-to-width option. |
| PDF → XLSX / CSV | Partial | Table extraction with pdfplumber on text-based PDFs. Tell the user when no tables are found. |

- **Preview:** the first 100 rows of the chosen sheet, shown as a table.
- **CSV option:** neutralize cells that start with `=`, `+`, `-` or `@`. This protects against formula injection.

### Developer & data tools (P1, mostly client-side)

| Tool | Target | Notes |
|---|---|---|
| JSON ↔ XML ↔ YAML ↔ TOML | Full | Document the mapping: XML attributes become `@attr`, text becomes `#text`, and a root element is required. Server-side parsing uses defusedxml and `yaml.safe_load`. |
| CSV / TSV ↔ JSON | Full | |
| HTML ↔ Markdown | Full | |
| JSON format, validate (errors with line:column), minify | Full | |
| CSS, JavaScript, SQL, XML beautify/minify | Full | For example Prettier standalone, terser and sql-formatter. |
| CSV → SQL INSERT statements | Full | |
| Base64 encode/decode (text and files), URL encode/decode | Full | |
| Unix timestamp ↔ ISO 8601 / local time | Full | Handles seconds and milliseconds, with a timezone picker. |

### Presentations (P2)

| Conversion | Target | Notes |
|---|---|---|
| PPTX / PPT / ODP → PDF | Full | LibreOffice. |
| PPTX / PPT / ODP → PNG/JPG per slide | Full | Converted to PDF, then rendered with pypdfium2. Tested as a chain. |
| PPTX ↔ PPT ↔ ODP | Full | LibreOffice. |
| Images → PPTX | Full | python-pptx, one image per slide. |
| PDF → PPTX | Partial | Each slide is one rendered image, labeled "not editable". |

### Audio (P2)

**Engine:** FFmpeg and ffprobe.

| Conversion / tool | Target | Notes |
|---|---|---|
| MP3, WAV, AAC, FLAC, OGG (Vorbis), M4A, OPUS, WMA ↔ each other | Full | Sensible defaults for each target. For example, MP3 at 192 kbps with LAME, and AAC with FFmpeg's built-in encoder. |
| Bitrate, sample rate, channels, trim (start/end), loudness normalization | Full | |
| Carry over metadata (title, artist, album, cover art) | Partial | Tag mapping differs between containers. Report what was kept. |

### Video (P2)

**Engine:** FFmpeg and ffprobe.

| Conversion / tool | Target | Notes |
|---|---|---|
| MP4, MOV, MKV, WEBM, AVI, FLV, WMV, 3GP ↔ each other | Full | **Default codecs per container:** MP4/MOV use H.264 + AAC; WEBM uses VP9 + Opus.<br>**Fast path:** when the source codecs are valid for the target container, remux with stream copy. It's far faster and lossless; tell the user it happened. |
| Video → GIF | Full | Two-pass palette (palettegen/paletteuse). Limits on fps, width and duration. |
| GIF → MP4 / WEBM | Full | |
| Extract audio (→ MP3/AAC/WAV/…) | Full | |
| Trim, resolution, FPS, quality presets (CRF), compress to an approximate target size (two-pass) | Full | |
| Thumbnail or frame at a timestamp → PNG/JPG | Full | |

### Archives (P2)

**Engines:**

- Python `zipfile` and `tarfile`
- `py7zr` for 7z
- libarchive (`bsdtar`) for reading RAR

| Conversion / tool | Target | Notes |
|---|---|---|
| ZIP ↔ TAR ↔ TAR.GZ ↔ TAR.BZ2 ↔ TAR.XZ ↔ 7Z | Full | Repack with every limit in §7 enforced. |
| GZ ↔ the original single file | Full | |
| RAR → ZIP / TAR / 7Z, or extract | Partial | Read-only, through libarchive. Some RAR5 features may fail. |
| Create RAR | Unsupported | Proprietary format. |
| Extract (list contents, download single files); create a ZIP from uploads | Full | |
| Password-protected archives | Partial | Extract with a password the user supplies, where the library supports it. |

### Utilities (P2, client-side unless noted)

| Tool | Target | Notes |
|---|---|---|
| Image ↔ Base64 / data URI | Full | |
| Color: HEX ↔ RGB ↔ HSL (and OKLCH) | Full | Live swatch and contrast ratio. |
| px ↔ in ↔ cm ↔ mm ↔ pt | Full | Pixel conversions need a DPI input (default 96). |
| Bytes ↔ KB/MB/GB/TB | Full | Show decimal units (1000) and binary units (KiB, 1024) side by side. |
| Fonts: TTF/OTF ↔ WOFF / WOFF2 | Full | Server-side, with fontTools and brotli. |
| TTF ↔ OTF outline conversion | Experimental | |
| QR code → PNG/SVG | Full | Options for error-correction level, size and colors. Tests decode the output back. |

### Expansion candidates (only after everything above is done and passing)

- EPUB ↔ PDF/DOCX/HTML (Pandoc)
- SRT ↔ VTT subtitles
- image OCR → text
- PDF → PDF/A
- burning subtitles into video

Research other useful conversions too, and add them through the registry the same way.

---

## 7. Security requirements

Treat every upload as hostile. The converters parse complex formats using large native codebases, so isolation and limits matter as much as input checks.

### Isolation

- **One runner:** every engine runs as a subprocess through a single `sandbox.run()` helper. That helper enforces:
  - access to the job's own working directory only
  - a non-root user
  - no network
  - a timeout
  - limits on memory (`RLIMIT_AS`), CPU and output file size
  - killing the whole process group on timeout or cancel
- **Production:** workers run in a container with no outbound network and a read-only root filesystem. Only the job volume is writable.
- **Locally:** use bubblewrap or nsjail if available. At minimum, enforce the limits and timeouts.
- **Filenames:** files on disk get generated UUID names. The original filename lives only in metadata and is never used to build a path. It's sanitized for `Content-Disposition`, using RFC 5987 `filename*` for non-ASCII names.

### Engine-specific hazards (each one needs a test)

- **FFmpeg:** an input can be a crafted playlist (HLS or concat) that reads local files or reaches the network.
  - Probe every input first and reject playlist or network demuxers.
  - Pass `-protocol_whitelist file,pipe`.
- **LibreOffice:** documents can carry macros, linked files, or formulas such as `WEBSERVICE` that read local files or call URLs during conversion.
  - Turn macros off and give it no network.
  - Use a separate profile per job (`-env:UserInstallation=…`), which also makes parallel conversions safe, or use a managed pool such as unoserver.
- **Pandoc:** always run with `--sandbox`.
- **HTML → PDF:** without these controls it becomes an SSRF tool (for example, reaching cloud metadata at `169.254.169.254` or `file://` paths).
  - Render with `set_content` and JavaScript disabled.
  - Block every request except `data:` URIs.
- **SVG:** no loading of external or local resources. The SSRF and local-file-read risks are the same.
- **XML and YAML:** parse XML with defusedxml (it blocks XXE and billion-laughs attacks). Parse YAML with `safe_load`, plus limits on size and alias expansion.
- **Images:** set `Image.MAX_IMAGE_PIXELS` (default 100 MP) to stop decompression bombs.
- **Archives:**
  - Reject absolute paths, `..`, symlinks, hardlinks and device files. Use `tarfile` with `filter="data"`, and still validate every member yourself.
  - Cap the number of entries, total uncompressed size, per-entry compression ratio and nesting depth.
  - Count bytes while streaming; don't trust the sizes in archive headers.
- **Uploaded content:** never execute it.
- **Converted HTML and SVG:** never render them on the app's own origin, which would allow stored XSS. Rasterize them for preview, or show them in a sandboxed iframe with scripts disabled.

### Access and transport

- **Session token:** there are no accounts. Each browser gets a random session token in an HttpOnly, Secure, SameSite=Strict cookie. Every upload, job and download is bound to that token.
- **IDs:** random 128-bit values, so they can't be enumerated.
- **Downloads:** send `Content-Disposition: attachment`, the correct MIME type and `X-Content-Type-Options: nosniff`. The app has a strict CSP.
- **Upload size limits:** enforce them while streaming. Abort at the limit; don't buffer the whole file and check afterwards.
- **Rate limits:** per session and per IP, on uploads, concurrent jobs and bytes per hour. Over the limit, return 429 with `Retry-After`.
- **Logging:** record job IDs, formats, sizes, durations and error classes. Never log file contents or original filenames.

### Retention

- Inputs and outputs are deleted:
  - by a sweeper after `FILE_RETENTION_MINUTES` (default 60)
  - immediately when the user asks
  - at startup, for any orphaned directories
- A failed job cleans up its partial outputs immediately.

## 8. Performance, reliability and licensing

**Performance and reliability**

- Stream uploads to disk, and stream downloads and ZIPs from disk. Never load a whole video into memory.
- Use two queues with separate concurrency limits, so one long video never blocks a PNG → JPG:
  - `fast`: images, data and small PDFs
  - `heavy`: video, office documents and OCR
- Set a timeout for each resource class.
- A failed or timed-out job must:
  - return a specific error a person can act on, such as "This PDF is password-protected — enter the password to continue"
  - never crash the worker
- Benchmark: 20 concurrent small jobs succeed while a heavy job is running.

**Licensing**

- Record every dependency and its license in `docs/THIRD_PARTY_LICENSES.md`, and prefer permissive licenses.
- Run GPL and LGPL tools as separate processes. This applies to FFmpeg builds that include x264, and to Pandoc. Note the obligations that apply if you distribute the Docker image.
- AGPL obligations apply to network services. So AGPL components are off by default, behind `ENABLE_AGPL_ENGINES=false`. These are PyMuPDF (and so pdf2docx), Ghostscript, and IMG.LY's background-removal library. Document what each one would unlock.
- Don't use non-free codecs, such as fdk-aac.

## 9. Testing and the support matrix

Testing is how an operation earns its support level.

**Definition of done.** An operation can be marked Full only when:

1. its converter and option schema exist
2. its matrix test passes with independent validation, including a content check
3. at least one negative test passes
4. it runs inside the sandbox with limits applied
5. it shows up in the generated matrix, and in the UI through `/api/capabilities`

### What to build

- **Fixtures.** A script generates a small input file for every format. Example sources:
  - FFmpeg `testsrc` and `sine`
  - Pillow
  - python-docx, openpyxl and python-pptx
  - LibreOffice, for the legacy DOC, XLS and PPT formats

  Add a handful of small real-world files to the repo as well. Fixtures hold known content so tests can check that it survives: a sentence, a table of known values, a known color block, a 3-second tone.
- **Converter matrix tests.** These are parametrized over the registry. For each (input, output, operation), run the conversion and validate the output with an independent parser:

  | Output type | Validator | What it checks |
  |---|---|---|
  | Images | Pillow | Format, dimensions, alpha |
  | Audio and video | ffprobe | Codec, duration within a tolerance |
  | PDFs | pypdf | Page count; extracted text contains the known sentence |
  | Office files | python-docx, openpyxl, python-pptx | The file opens and the known content is present |
  | Archives | zipfile, tarfile, py7zr | Contents |
  | Data | `json`, `yaml`, defusedxml | Parses |
  | QR codes | A QR decoder | Decodes back to the input |
- **Negative tests.** Each should fail cleanly with a clear error:

  | Case | Expected |
  |---|---|
  | Corrupt or truncated file | Clear error |
  | Extension and content don't match | Warning; content wins |
  | Unsupported pair | Clear 4xx error |
  | Wrong PDF password | Clear error |
  | Oversized upload | 413 |
  | Too many pixels | Rejected |
  | Timeout | Process killed; job fails cleanly |
- **Security tests.** Each one should be blocked:
  - ZIP Slip
  - a symlink inside a tar
  - a small zip bomb
  - XXE
  - a YAML alias bomb
  - SVG and HTML that reference `file://` and `http://169.254.169.254`
  - an FFmpeg HLS-playlist input
  - a spreadsheet using `WEBSERVICE`
  - path-traversal filenames
  - a download attempt from a different session (must return 404)
- **Lifecycle tests.**
  - Temp files are deleted after success, failure, cancel and expiry. Use a short TTL in tests.
  - A batch's ZIP contains every output.
- **Client-side tools.** Unit tests in Vitest, with round-trip checks.
- **End-to-end (Playwright):**
  - Upload a PNG by drag and drop, convert to JPG, download it, and assert the JPEG magic bytes.
  - Convert a batch of 3 mixed files and download the ZIP.
  - Pick an unsupported pair and see a helpful message.
  - Merge PDFs with reordering.
  - Convert video → MP3 with visible progress.
  - Switch to dark mode.
  - Take screenshots of the homepage and workspace at a 390 px mobile width.

### The support matrix

- `docs/SUPPORT_MATRIX.md` is generated from the registry plus the latest test run. Never edit it by hand.
- CI fails if any operation marked Full or Partial has no passing test.
- `/api/capabilities` exposes the same levels the UI shows.

## 10. UI/UX

The interface should feel premium, minimal and fast:

- one typeface pairing and one accent color
- generous spacing, rounded cards, subtle gradients
- restrained motion: 250 ms or less, and respect `prefers-reduced-motion`
- light and dark mode

Avoid the generic template look.

### Homepage

1. **Hero:**
   - the heading "One Platform. Every Conversion." with a one-line subtitle
   - a large drop zone with a Browse button
   - a line listing the supported format families

   Dropping files goes straight into the workspace.
2. **Popular conversions:** PNG → JPG, JPG → PNG, PDF → Word, Word → PDF, PDF → JPG, MP4 → MP3, Excel → PDF, HEIC → JPG.
3. **Categories:** Images, Documents & PDF, Spreadsheets, Presentations, Audio, Video, Archives, Developer Tools, Utilities.
4. **All tools:**
   - searchable with fuzzy matching, so "word to pdf" and "docx pdf" both work
   - filterable by category
   - shows input → output formats and support-level badges

   It's generated from `/api/capabilities`.
5. **How it works:** three steps.
6. **Privacy & security:** facts only. The retention window, deletion, isolation, and which tools run locally.
7. **Footer:** tools, a supported-formats page, docs, privacy, terms.

### A page for each conversion

Each registered pair gets its own route (for example `/convert/png-to-jpg`) with its own title and description. That helps search and makes direct links possible.

### Workspace (the same flow for every category)

- **File list:**
  - name, size, detected format and any warnings for each file
  - remove one file, add more, or clear all
- **Target picker:** shows only the targets valid for the selected files. Mixed batches are grouped by input type.
- **Settings:** generated from the option schema, with sensible defaults and an "Advanced" disclosure.
- **Progress:** progress and state for each file, a cancel button, and retry on failure with the error explained.
- **Results:**
  - a preview suited to the output:
    - images: a before/after slider
    - PDFs: page thumbnails
    - audio and video: players
    - spreadsheets: a table
    - code and data: escaped text
  - output size compared with input size
  - Download, Download all (ZIP), Delete now, Convert another
- **History:** recent tools and conversion history live in `localStorage`. Store metadata only, never file contents. Provide a clear-history button, and mark expired results as expired.

### Accessibility

Meet WCAG 2.1 AA:

- a keyboard-operable drop zone and controls
- visible focus
- progress announced through `aria-live`
- enough contrast in both themes
- labeled form fields

---

## 11. How to work

Work in vertical slices. End every milestone with these steps:

1. all tests passing
2. the support matrix regenerated
3. `PROGRESS.md` updated (done, in progress, next, known issues)
4. a git commit

Keep `PROGRESS.md` complete enough that you, or a new session, can resume cold after a context reset.

### Milestones

- **M0, Analyze & plan:**
  - repo analysis and an environment check
  - `docs/ARCHITECTURE.md`, `DECISIONS.md` and the milestone plan

  Then keep going; don't wait for approval.
- **M1, Walking skeleton:**
  - the web app, API, worker and queue all running
  - one full path working: upload, detection, PNG → JPG with real progress, download and cleanup
  - one Playwright test passing
- **M2, Engine framework:**
  - the registry, with option schemas that generate forms
  - the capabilities and health endpoints
  - the sandbox runner
  - the fixture generator, validators and matrix generator
  - session tokens, limits and rate limiting

  By the end, the generic workspace UI works for any registered operation.
- **M3, P1 modules:** images, documents & PDF tools, spreadsheets, developer/data tools. Do one category at a time and test each fully before starting the next.
- **M4, P2 modules:** presentations, audio, video, archives, utilities.
- **M5, UI completion:**
  - homepage, tool directory and search, per-conversion pages
  - previews, history, dark mode and mobile layouts
  - an accessibility pass
- **M6, Hardening:**
  - the full security test suite, the concurrency test, timeouts and cleanup
  - a clarity review of every error message
  - the license inventory
- **M7, Final verification:**
  1. Do a fresh install from the README on a clean checkout and run every test suite.
  2. Walk the full user journey in a real browser at desktop and mobile widths, and fix what you find.
  3. Write the docs.

If you can run subagents, build category modules in parallel after M2, once the framework is stable.

Only ask the owner when you're blocked on a decision that can't be undone later, such as accepting an AGPL dependency. Otherwise, make the call, record it and keep going.

## 12. Deliverables and final report

### In the repo

- A working frontend, backend, worker and conversion engine.
- `README.md`: what the project is, a quick start (Docker Compose and native), and how to run the tests.
- `docs/ENV.md`: every environment variable, with its default and purpose.
- `docs/DEPLOYMENT.md`, covering:
  - a single-VM Docker Compose deployment with TLS through the reverse proxy
  - network isolation for the workers
  - scaling workers
  - upgrading engines
  - a note that backups aren't needed, because no user data is kept
- Generated docs: `docs/SUPPORT_MATRIX.md`.
- Security: `docs/SECURITY.md`, covering the threat model, the mitigations, and how each one is tested.
- Licensing: `docs/THIRD_PARTY_LICENSES.md`.
- Automated tests, with a single command that runs them all.

**Environment variables `docs/ENV.md` must cover, at minimum:**

| Variable | Default |
|---|---|
| `STORAGE_DIR` | (no default listed) |
| `REDIS_URL` | (no default listed) |
| `PUBLIC_BASE_URL` | (no default listed) |
| `MAX_FILE_SIZE_MB` | 100 |
| `MAX_VIDEO_SIZE_MB` | 500 |
| `MAX_BATCH_FILES` | 20 |
| `MAX_BATCH_TOTAL_MB` | 1000 |
| `MAX_IMAGE_PIXELS` | 100000000 |
| `ARCHIVE_MAX_ENTRIES` | 10000 |
| `ARCHIVE_MAX_UNCOMPRESSED_MB` | 2000 |
| `ARCHIVE_MAX_RATIO` | 100 |
| `JOB_TIMEOUT_FAST_S` | 60 |
| `JOB_TIMEOUT_HEAVY_S` | 900 |
| `WORKER_CONCURRENCY_FAST` | (no default listed) |
| `WORKER_CONCURRENCY_HEAVY` | (no default listed) |
| `FILE_RETENTION_MINUTES` | 60 |
| `RATE_LIMIT_JOBS_PER_10MIN` | 30 |
| `ENABLE_AGPL_ENGINES` | false |
| `ENABLE_OCR` | false |
| `ENABLE_BACKGROUND_REMOVAL` | false |
| `LOG_LEVEL` | (no default listed) |

### Final message to me

1. What you built, and how to run it in two commands.
2. A support matrix summary:
   - the number of Full, Partial, Experimental and Unsupported operations
   - every Partial, Experimental and Unsupported item, with its reason
3. Test results: paste the actual summary output from the test run, including counts and any failures. Don't paraphrase it.
4. Any deviations from this prompt, and why.
5. Known limitations and recommended next steps.
