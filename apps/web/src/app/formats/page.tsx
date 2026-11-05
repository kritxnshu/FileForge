import type { Metadata } from "next";
import Link from "next/link";
import { fmtShort, SUPPORT_LABEL, toolEntries } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

export const metadata: Metadata = { title: "Supported formats", description: "Every file format and what it converts to." };

const FAMILY: [string, string][] = [
  ["image", "Images"], ["pdf", "PDF"], ["document", "Documents"], ["text", "Text & markup"], ["spreadsheet", "Spreadsheets"],
  ["data", "Data"], ["presentation", "Presentations"], ["audio", "Audio"], ["video", "Video"], ["archive", "Archives"], ["font", "Fonts"],
];

export default async function FormatsPage() {
  const caps = await serverCaps();
  if (!caps) return <p className="py-10 text-muted">The service is unavailable. Reload the page in a moment.</p>;
  const entries = toolEntries(caps);
  return (
    <div className="pb-10 pt-4">
      <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2rem]">Supported formats</h1>
      <p className="mt-2 max-w-2xl text-[0.95rem] text-muted">
        Everything listed here is backed by an automated test that opens the result with an independent parser.
        <span className="font-medium text-ink"> Partial</span> means it works with a stated loss of fidelity.
      </p>
      {FAMILY.map(([fam, label]) => {
        const fmts = Object.entries(caps.formats).filter(([, f]) => f.family === fam);
        if (!fmts.length) return null;
        return (
          <section key={fam} className="mt-10" aria-labelledby={`f-${fam}`}>
            <h2 id={`f-${fam}`} className="font-display text-xl font-semibold">{label}</h2>
            <div className="card mt-3 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-[0.95rem]">
                <thead className="bg-surface-2 text-[0.88rem] text-muted">
                  <tr><th className="px-4 py-2 font-medium">Format</th><th className="px-4 py-2 font-medium">Converts to</th><th className="px-4 py-2 font-medium">Tools</th></tr>
                </thead>
                <tbody>
                  {fmts.map(([id, f]) => {
                    const mine = entries.filter((e) => e.pair.source === id && e.op.runtime === "server");
                    const conv = mine.filter((e) => e.kind === "convert");
                    const tools = mine.filter((e) => e.kind === "tool");
                    return (
                      <tr key={id} className="border-t border-line align-top">
                        <td className="px-4 py-3"><span className="font-medium">{f.label}</span><span className="block text-[0.85rem] text-muted">.{f.exts.join(", .")}</span></td>
                        <td className="px-4 py-3">
                          <span className="flex flex-wrap gap-1.5">
                            {conv.length ? conv.map((e) => (
                              <Link key={e.slug} href={`/convert/${e.slug}`} className="rounded-full border border-line px-2 py-0.5 text-[0.85rem] hover:border-line-strong">
                                {fmtShort(caps, e.pair.target)}{e.pair.support !== "full" && <span className="text-warn"> ({SUPPORT_LABEL[e.pair.support]})</span>}
                              </Link>
                            )) : <span className="text-muted">—</span>}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[0.9rem] text-muted">{tools.map((t) => t.op.label).join(", ") || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      <section className="mt-10" aria-labelledby="unsupported-h">
        <h2 id="unsupported-h" className="font-display text-xl font-semibold">Not supported</h2>
        <ul className="mt-3 list-disc pl-5 text-muted">
          <li>Creating RAR archives: RAR is a proprietary format, so RAR files can be opened and repacked but not created.</li>
          <li>Removing passwords you don&apos;t know, or DRM: we never guess or crack passwords.</li>
        </ul>
      </section>
    </div>
  );
}
