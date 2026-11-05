import type { Metadata } from "next";
import Link from "next/link";
import { ArrowDown, ArrowRight, CheckCircle2, FileText, Layers, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PdfHub } from "@/components/pdf/PdfHub";
import { serverCaps } from "@/lib/server";

export const metadata: Metadata = {
  title: "PDF tools",
  description: "Merge, split, compress, convert, edit, sign, redact, fill forms and compare PDFs. Files are deleted automatically.",
};

export default async function PdfToolsPage() {
  const caps = await serverCaps();
  const hub = caps?.hubs?.pdf;
  const merge = hub?.tools.find((t) => t.slug === "merge-pdf");
  return (
    <>
      <PageHeader
        icon={<FileText size={22} />}
        eyebrow="PDF toolkit"
        title="Every PDF tool, in one place"
        description={hub?.description ?? "Organize, convert, edit, sign and secure PDFs."}
        aside={hub && caps && (
          <dl className="flex gap-2">
            {[["Tools", hub.tools.length], ["Groups", hub.groups.length], ["Retention", `${caps.limits.retention_minutes} min`]].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-surface px-3 py-2 shadow-1">
                <dt className="text-[0.72rem] text-muted">{k}</dt>
                <dd className="font-mono text-[0.85rem] font-semibold">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      />

      {merge && (
        <section aria-labelledby="spotlight-h" className="rise relative mb-6 overflow-hidden rounded-[var(--radius-zone)] bg-[linear-gradient(120deg,#4f46e5,#6d28d9_55%,#7c3aed)] p-6 text-white shadow-3 sm:p-8" style={{ "--i": 1 } as React.CSSProperties}>
          <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-3xl" />
          <div className="relative grid items-center gap-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <div>
              <p className="inline-flex items-center gap-1.5 rounded-md bg-white/15 px-2 py-0.5 font-mono text-[11px] font-medium">
                <Sparkles size={12} aria-hidden="true" /> Spotlight
              </p>
              <h2 id="spotlight-h" className="mt-3 font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2.1rem]">
                {merge.title}: combine and reorder
              </h2>
              <p className="mt-2 max-w-xl text-[0.95rem] text-white/80">{merge.description} Drag pages into order before you merge, then download one file.</p>
              <div className="mt-5 flex flex-wrap gap-2.5">
                <Link href={`/pdf/${merge.slug}`} className="btn bg-white text-[#4338ca] shadow-1 hover:bg-white/90">
                  Open {merge.title} <ArrowRight size={15} aria-hidden="true" />
                </Link>
                <Link href="#pdf-g-organize" className="btn border border-white/30 text-white hover:bg-white/10">
                  <Layers size={15} aria-hidden="true" /> All organize tools
                </Link>
              </div>
            </div>
            <div aria-hidden="true" className="hidden rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur-md sm:block">
              <p className="font-mono text-[10px] uppercase tracking-wider text-white/70">How it runs</p>
              <div className="mt-3 flex flex-col items-stretch gap-1.5 font-mono text-[12px]">
                <div className="flex items-center justify-between rounded-lg bg-white/10 px-3 py-2"><span>contract.pdf + appendix.pdf</span><span className="text-white/60">2 files</span></div>
                <ArrowDown size={14} className="mx-auto text-white/50" />
                <div className="flex items-center justify-between rounded-lg bg-white/20 px-3 py-2"><span>Order pages</span><span className="text-white/60">drag &amp; drop</span></div>
                <ArrowDown size={14} className="mx-auto text-white/50" />
                <div className="flex items-center justify-between rounded-lg bg-white/10 px-3 py-2"><span className="flex items-center gap-1.5"><CheckCircle2 size={13} /> merged.pdf</span><span className="text-white/60">ready</span></div>
              </div>
            </div>
          </div>
        </section>
      )}

      {hub ? <PdfHub hub={hub} /> : <p className="text-muted">The PDF tools are unavailable right now. Reload the page in a moment.</p>}
    </>
  );
}
