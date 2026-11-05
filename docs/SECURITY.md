# Security

FileForge accepts files from anyone and feeds them to large native parsers (FFmpeg, LibreOffice, Pandoc,
Chromium, Pillow, PDF libraries). Every upload is treated as hostile. This document covers the threat model, what
the code does about each threat, and the test that proves it. The tests are the source of truth. Run them with
`make test`.

## Threat model

| Asset | Threat |
|---|---|
| The host and its network | A crafted file makes an engine read local files, reach internal services (SSRF, e.g. cloud metadata at `169.254.169.254`), run code, or exhaust CPU, memory or disk. |
| Other users' files | Guessing or stealing IDs to download someone else's uploads or results. |
| Users' browsers | Converted HTML/SVG rendered on the app's origin (stored XSS); content sniffing. |
| Availability | Decompression bombs, huge uploads, floods of jobs, one long video blocking everyone. |
| Privacy | File names or contents ending up in logs; files kept longer than stated. |

Out of scope: accounts and authentication (there are none), and attackers with shell access to the host.

## Isolation

**One runner.** Every conversion runs in a fresh child process (`python -I -m engine.child`) started by
`engine/sandbox.py: run()`. The arq worker only supervises it. CLI engines (ffmpeg, soffice, pandoc, Chromium) are
started *from inside* that child, so they inherit its limits, process group and isolation (DECISIONS D3).

| Control | How | Test |
|---|---|---|
| No network | macOS: Seatbelt `(deny network*)`. Linux: bubblewrap `--unshare-net`. Docker: workers sit only on an `internal: true` network with no gateway. | `test_security.py::test_sandbox_blocks_network_and_home` |
| Filesystem | Seatbelt denies writes outside the job directory and reads of the home directory. bubblewrap mounts `/` read-only with only the job dir writable. Docker: read-only root filesystem, only the job volume and `/tmp` writable. | `test_sandbox_blocks_network_and_home` |
| Non-root | Docker image runs as UID 10001. If a worker runs as root, job processes drop to `SANDBOX_UID`. | (deployment) |
| Time | Wall-clock timeout per queue (`JOB_TIMEOUT_*`), plus `RLIMIT_CPU`. | `test_security.py::test_sandbox_timeout_kills_process_group`, `test_lifecycle.py::test_timeout_kills_process_and_fails_cleanly` |
| Kill everything | Each job gets a new session/process group; timeout and cancel `killpg` it, so engine grandchildren die too. | same, plus `test_lifecycle.py::test_cancel_kills_job_and_cleans_up` |
| Output size | `RLIMIT_FSIZE`. | `test_security.py::test_sandbox_output_size_limit` |
| Memory | `RLIMIT_AS` (`JOB_MEMORY_*_MB`). Enforced on Linux; macOS ignores it (DECISIONS D5), so the pixel cap, timeouts and size limits carry that load there. | (Linux only) |
| Container fallback | If bubblewrap is installed but can't create namespaces (typical under Docker's default seccomp profile), the sandbox detects that once at boot and runs with rlimits + timeouts, relying on the container's isolation. `/api/health` reports which mode is active. | `/api/health` → `isolation` |

## Engine-specific hazards

| Hazard | Mitigation | Test |
|---|---|---|
| **FFmpeg** playlists (HLS/concat) reading local files or the network | Every input is probed first; playlist/network demuxers are rejected. FFmpeg runs with `-protocol_whitelist file,pipe` and a demuxer whitelist. Playlists aren't even detected as media at upload. | `test_media.py::test_playlist_inputs_rejected`, `::test_playlist_upload_is_not_detected_as_media` |
| **LibreOffice** macros, linked files, `WEBSERVICE` formulas | Macros off, a fresh profile per job (`-env:UserInstallation=` in the job dir), no network. | `test_spreadsheets.py::test_webservice_formula_never_fetches` |
| **Pandoc** fetching resources or reading files | Always `--sandbox`. | `test_documents.py::test_pandoc_never_fetches` |
| **HTML → PDF** as an SSRF tool | Chromium with JavaScript off. Content goes in via `set_content` (never a URL), and every request except `data:` is aborted. | `test_documents.py::test_html_to_pdf_blocks_ssrf_and_js` |
| **SVG** external/local references, scripts | SVG is parsed with defusedxml (no DTD/entities); every `href`/`url()` that isn't `data:` or `#fragment` is removed, as are `<script>` and `<foreignObject>`; resvg runs with no resources directory. | `test_security.py::test_svg_cannot_fetch_urls_or_read_files`, `::test_svg_script_and_foreignobject_removed`, `::test_xxe_in_svg_blocked` |
| **XML** XXE, billion laughs | defusedxml with DTDs/entities forbidden. | `test_developer.py::test_xxe_blocked`, `::test_billion_laughs_xml_blocked` |
| **YAML** alias bombs, object construction | `yaml.safe_load` plus limits on size, alias expansion and nesting depth. | `test_developer.py::test_yaml_alias_bomb_blocked` |
| **Images** decompression bombs | `Image.MAX_IMAGE_PIXELS` = `MAX_IMAGE_PIXELS` (100 MP); the same cap applies to rendered PDF pages and resize targets. | `test_images.py::test_pixel_bomb_rejected` |
| **Archives** zip slip, links, devices, bombs | Absolute paths, `..`, symlinks, hardlinks, device files, NUL bytes and duplicate names are rejected; `tarfile` uses `filter="data"` *and* every member is validated. Entry count, total unpacked size, per-entry ratio and nesting depth are capped, counting bytes while streaming (header sizes aren't trusted). | `test_archives.py::test_zip_slip_blocked`, `::test_rar_zip_slip_blocked`, `::test_tar_links_and_devices_blocked`, `::test_zip_symlink_entry_blocked`, `::test_zip_bomb_blocked`, `::test_tgz_bomb_blocked`, `::test_entry_count_and_total_size_limits` |
| **PDF page previews** | Thumbnails are rendered by the same sandboxed job process as a conversion, never in the API process. | `test_api.py::test_pdf_page_thumbnails_are_sandboxed_and_cached` |
| Uploaded content executed | Never: there is no code path that runs uploaded content. | — |

## Files, names and downloads

| Control | How | Test |
|---|---|---|
| Path traversal via file names | Files on disk are named by random 128-bit IDs. The original name lives only in Redis metadata and is never used to build a path. | `test_api.py::test_path_traversal_filename_is_metadata_only`, `test_archives.py::test_create_zip_never_uses_paths_from_names` |
| Header injection | Names are sanitised for `Content-Disposition`; non-ASCII names use RFC 5987 `filename*`. | `test_api.py::test_non_ascii_filename_content_disposition` |
| Content sniffing / XSS via results | Downloads send `Content-Disposition: attachment`, the right MIME type, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox; default-src 'none'`. Only images, audio and video may be served inline (for previews); SVG inline also carries the sandbox CSP. Converted HTML/SVG/text is shown as escaped text, never rendered on the app origin. | `test_api.py::test_png_to_jpg_full_path` |
| Detection by content | Magic bytes plus container inspection (ZIP/OLE2/ISO-BMFF/RIFF), `ffprobe` for media, parse attempts for text formats. If the extension and content disagree, content wins and a warning is shown; unidentifiable binary files are rejected. | `test_api.py::test_extension_mismatch_warns_and_content_wins`, `::test_unidentifiable_file_rejected` |

## Access control

- **Sessions.** No accounts. Each browser gets a random token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie
  scoped to `/api`. Every upload, job, batch, download and thumbnail is bound to it.
- **IDs** are random 128 bits. Another session's IDs return the same 404 ("expired or deleted") as IDs that never
  existed. Test: `test_api.py::test_png_to_jpg_full_path` (cross-session job, download and raw-upload access all 404),
  `::test_pdf_page_thumbnails_are_sandboxed_and_cached`.
- **Rate limits** per session and per IP: uploads, bytes per hour, jobs per 10 minutes and concurrent jobs; over the
  limit returns 429 with `Retry-After` (`docs/ENV.md`). Test: `test_lifecycle.py::test_job_rate_limit_429_with_retry_after`.
  The client IP trusts exactly `TRUSTED_PROXY_HOPS` proxies.
- **Upload size** is enforced while streaming: the request is aborted at the limit and nothing is kept. Tests:
  `test_lifecycle.py::test_oversized_upload_413_and_nothing_kept`, `::test_oversized_upload_aborts_mid_stream`,
  `::test_too_many_files_rejected`.
- **Other request bodies** (job settings, which can carry editor images) are capped at 20 MB by Caddy before FastAPI
  reads them, and job settings at 16 MB by the API (413).

## Web app

- **CSP** is set per request in `apps/web/src/proxy.ts`: scripts only with that request's nonce (`'strict-dynamic'`),
  no `'unsafe-inline'` scripts and no `eval` in production, `object-src 'none'`, `frame-ancestors 'none'`,
  `connect-src 'self'`. Styles allow `'unsafe-inline'` because React `style` attributes can't carry a nonce; style
  injection can't run code, and no uploaded content is rendered on this origin (DECISIONS D11). Test:
  `tests/e2e/csp.spec.ts` (fresh nonce per request, and no CSP violation while using the workspace and the
  client-side tools).
- `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `nosniff`, HSTS and a restrictive `Permissions-Policy`
  (Caddy). The camera is allowed for this origin only (`camera=(self)`), for Scan to PDF; microphone and geolocation
  stay off. Photos are captured in the browser and uploaded like any other file, only when taken (DECISIONS D27).
- Redaction removes content, not just covers it: pages with redactions are re-rendered as images, and document
  properties and bookmarks are dropped (DECISIONS D25). Signatures are visual, not certificate-based (D26).
- Client-side tools ("Runs in your browser") never send their input to the server.

## Retention and privacy

- Uploads and results are deleted by the sweeper `FILE_RETENTION_MINUTES` after upload (default 60), immediately on
  "Delete now", and at startup for any orphaned directories. A failed or cancelled job deletes its partial outputs
  at once. Tests: `test_lifecycle.py::test_files_expire_and_are_deleted`, `::test_succeeded_job_expires`,
  `::test_cancel_kills_job_and_cleans_up`, `::test_delete_session_removes_everything`,
  `test_api.py::test_failed_job_has_actionable_error_and_no_outputs`.
- **Logs** record job IDs, operations, formats, sizes, durations, states and error codes. For crashes they record only
  the exception *class* (e.g. `ValueError`), because exception messages and engine output can quote file contents.
  Original file names are never logged. Test: `test_api.py::test_failure_logs_name_the_error_class_never_the_message`.
- Browser history is kept in `localStorage` as metadata only (names, formats, times) and can be cleared. Test:
  `tests/e2e/journeys.spec.ts` "history keeps metadata only…".

## Known gaps

- macOS doesn't enforce `RLIMIT_AS` (D5). Production is meant to run on Linux.
- The Seatbelt profile allows LibreOffice's hard-coded `/tmp/OSL_PIPE_*` socket and the `/tmp` directory entry.
- Under Docker, bubblewrap usually can't create namespaces, so per-job network isolation comes from the container
  network (`internal: true`) rather than a per-job namespace; jobs on the same worker share that container.
- The Docker images were written but not built in the development environment (no Docker there, DECISIONS D15).

## Reporting

[Operator: add a security contact address here.]
