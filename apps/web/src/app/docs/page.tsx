import type { Metadata } from "next";
import Link from "next/link";
import { serverCaps } from "@/lib/server";

export const metadata: Metadata = { title: "Docs", description: "How FileForge works, its limits and its API." };

export default async function DocsPage() {
  const caps = await serverCaps();
  const l = caps?.limits;
  return (
    <article className="max-w-3xl pb-10 pt-4">
      <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2rem]">How it works</h1>
      <div className="mt-6 flex flex-col gap-8 leading-relaxed">
        <section>
          <h2 className="font-display text-xl font-semibold">Converting</h2>
          <p className="mt-2 text-muted">
            Add files, and each one&apos;s real format is detected from its content, not just its extension. You only see the conversions that
            work for that format. Each conversion runs in its own isolated process with no network access and strict limits. Progress comes
            straight from the engine (for example “page 3 of 12”); engines that report nothing show their current step instead.
          </p>
        </section>
        <section>
          <h2 className="font-display text-xl font-semibold">Support levels</h2>
          <dl className="mt-2 grid gap-2 text-muted sm:grid-cols-[8rem_1fr]">
            <dt className="font-medium text-ink">Full</dt><dd>Reliable; content is preserved within the limits of the target format.</dd>
            <dt className="font-medium text-ink">Partial</dt><dd>Works, with a stated loss of fidelity shown before you convert.</dd>
            <dt className="font-medium text-ink">Experimental</dt><dd>Works on our test files; off unless the operator enables it.</dd>
          </dl>
          <p className="mt-2 text-muted">A conversion only appears once its automated tests pass. See <Link className="text-accent underline underline-offset-4 hover:decoration-2" href="/formats">supported formats</Link>.</p>
        </section>
        {l && (
          <section>
            <h2 className="font-display text-xl font-semibold">Limits</h2>
            <ul className="mt-2 list-disc pl-5 text-muted">
              <li>{l.max_file_size_mb} MB per file ({l.max_video_size_mb} MB for video), {l.max_batch_files} files and {l.max_batch_total_mb} MB per upload.</li>
              <li>Images up to {l.max_image_megapixels} megapixels.</li>
              <li>{l.jobs_per_10min} conversions per 10 minutes.</li>
              <li>Files are deleted {l.retention_minutes} minutes after upload.</li>
            </ul>
          </section>
        )}
        <section>
          <h2 className="font-display text-xl font-semibold">API</h2>
          <p className="mt-2 text-muted">
            The web app is built on a small HTTP API: <code>GET /api/capabilities</code> lists every operation, its option schema and support
            level; <code>POST /api/uploads</code> and <code>POST /api/jobs</code> start conversions; <code>GET /api/jobs/&#123;id&#125;/events</code> streams
            progress. It&apos;s for this site&apos;s own use (sessions are cookie-based; there are no API keys). Interactive reference:{" "}
            <a className="text-accent underline underline-offset-4 hover:decoration-2" href="/api/docs">/api/docs</a>.
          </p>
        </section>
      </div>
    </article>
  );
}
