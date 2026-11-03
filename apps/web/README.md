# Universal Converter: web app

Next.js 16 (App Router). Run the whole stack from the repo root with `make dev` (see the root `README.md`). This
app expects the API on the same origin at `/api` (Caddy), and on `INTERNAL_API_URL` for server rendering.

- `src/app/`: routes. `/convert/<a>-to-<b>` and `/tools/<slug>` pages are generated from `/api/capabilities`.
- `src/components/Workspace.tsx`: the upload → pick → settings → progress → results flow for every server operation.
- `src/components/OptionsForm.tsx`: settings forms built from each operation's JSON Schema.
- `src/lib/tools/`: client-side tools (run in the browser; tested with Vitest).
- `src/proxy.ts`: per-request Content Security Policy with a nonce.

Checks: `pnpm exec tsc --noEmit`, `pnpm exec eslint src`, `pnpm exec vitest run` (all part of `make test`).
