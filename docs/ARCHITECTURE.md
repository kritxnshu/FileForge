# Architecture

```
 Browser ──► Caddy (:8080 dev / :443 prod)
               ├── /api/*  ──► FastAPI (uvicorn)  ──┐
               └── /*      ──► Next.js (App Router) │
                                                    ▼
                                  Redis ◄──── arq workers (fast, heavy)
                                    ▲                │ spawn per job
                                    │                ▼
                                 job state     sandbox.run(python -I -m engine.child)
                                 + pub/sub         │ (seatbelt / bwrap, rlimits, new process group)
                                                   ├── Pillow / pypdf / openpyxl … (in-process)
                                                   └── ffmpeg / soffice / pandoc (child of child)
                       STORAGE_DIR/<job-id>/{in,out,work}  (shared volume)
```

## Components

| Component | Path | Role |
|---|---|---|
| Web app | `apps/web` | Next.js UI. Reads every capability from `/api/capabilities`; builds settings forms from JSON Schema. Client-side tools run here. |
| API | `services/api/app` | Streaming uploads, job creation, SSE events, downloads, streamed ZIPs, deletion, health. Session cookie binding + rate limits. |
| Engine | `services/api/engine` | Format catalog, detection, registry + chain planner, sandbox runner, converters, validators. |
| Worker | `services/api/worker.py` | arq worker. One process per queue. Supervises sandboxed child processes. |
| Sweeper | inside the API process (`app/lifecycle.py`) | Deletes expired uploads/jobs every minute and orphaned directories at startup. |
| Previews | `services/api/app/previews.py` | PDF page thumbnails and spreadsheet table previews. Rendered by the same sandboxed job process as a conversion (`pdf.to_images`, `sheet.export`), cached next to the file they belong to, so they're deleted with it. |
| Web proxy | `apps/web/src/proxy.ts` | Sets a per-request nonce-based Content-Security-Policy on every page. |

## Request flow

1. `POST /api/uploads` streams each multipart part to `STORAGE_DIR/uploads/<file-id>/data`, counting bytes and aborting at the size limit (413). Detection runs on the stored file; metadata (session, detected format, size, sanitized original name) goes to Redis with a TTL of `FILE_RETENTION_MINUTES`.
2. `POST /api/jobs` validates `{file_ids, operation, target, options}` against the registry (pair advertised? options valid against the operation's Pydantic model?). Creates one job per file (or one job for many→one ops) plus a batch ID; enqueues each on the operation's `resource_class` queue.
3. The worker creates `jobs/<job-id>/{in,out,work}`, hard-links inputs into `in/`, writes `spec.json`, and calls `sandbox.run()` on `python -I -m engine.child <job-dir>`. The child prints progress as JSON lines on stdout; the worker forwards them to Redis (`job:<id>` hash + `events:<id>` pub/sub). A cancel flag in Redis makes the worker kill the child's whole process group.
4. On success the child writes `result.json` (outputs, notices, warnings). The worker records outputs; on failure it deletes `out/` immediately and stores an actionable error class + message.
5. `GET /api/jobs/{id}/events` (SSE) replays current state, then streams updates. Downloads and ZIPs stream from disk.

## Registry

`engine/registry.py` holds `Operation` objects (see the module docstring). Converters register themselves at import (`engine/converters/<category>/*.py`). An operation declares id, category, labels, input/output formats, cardinality, Pydantic options model, engine requirements, resource class, runtime, target support level and known limitations.

Effective support level of a (operation, source, target) pair = target level **if** `verified.json` records a passing test for that pair, otherwise the pair is not advertised. Missing engines (checked at boot) disable their operations and are reported by `/api/health`.

Chains (≤3 hops) are planned by BFS over advertised one→one pairs, and only exposed when `verified.json` has a passing test for the chain key `chain:<src>-><dst>`.

## Storage

`app/storage.py` is a small interface (`put_upload`, `open`, `job_dir`, `delete`); only the local-volume implementation exists. Files on disk are named by random 128-bit IDs; original filenames exist only in Redis metadata and in sanitized `Content-Disposition` headers.
