import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HistoryPanel, RecordRecent } from "@/components/History";
import { PageHeader } from "@/components/PageHeader";
import { HubIcon } from "@/components/pdf/icons";
import { ToolCard } from "@/components/pdf/PdfHub";
import { ScanCapture } from "@/components/pdf/ScanCapture";
import { Workspace } from "@/components/Workspace";
import { fmtShort } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

type Props = { params: Promise<{ slug: string }> };

async function toolFor(slug: string) {
  const caps = await serverCaps();
  const hub = caps?.hubs?.pdf;
  const tool = hub?.tools.find((t) => t.slug === slug);
  return { caps, hub, tool };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { tool } = await toolFor((await params).slug);
  if (!tool) return { title: "PDF tools" };
  return { title: tool.title, description: `${tool.description} Free, no account, and files are deleted automatically.` };
}

export default async function PdfToolPage({ params }: Props) {
  const { slug } = await params;
  const { caps, hub, tool } = await toolFor(slug);
  if (!caps) return <p className="py-10 text-muted">The conversion service is unavailable. Reload the page in a moment.</p>;
  if (!hub || !tool) notFound();
  const related = hub.tools.filter((t) => t.group === tool.group && t.slug !== tool.slug).slice(0, 4);
  const groupLabel = hub.groups.find((g) => g.id === tool.group)?.label;
  return (
    <>
      <PageHeader crumbs={[["PDF tools", "/pdf"], [tool.title]]} icon={<HubIcon name={tool.icon} size={24} />} title={tool.title} description={tool.description}>
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[0.82rem] text-muted">
          {groupLabel && <span className="chip !border-transparent !bg-accent-soft !text-accent">{groupLabel}</span>}
          <span className="ml-1">Works with</span>
          {tool.sources.map((s) => <span key={s} className="chip">{fmtShort(caps, s)}</span>)}
        </p>
      </PageHeader>
      {tool.special === "scan" && <div className="mb-6"><ScanCapture /></div>}
      <div>
        <Workspace preset={{ opId: tool.op, source: tool.sources[0], target: tool.target, options: tool.options, label: tool.title, sources: tool.sources }} />
      </div>
      <RecordRecent slug={`pdf:${tool.slug}`} title={tool.title} href={`/pdf/${tool.slug}`} />
      <div className="mt-10"><HistoryPanel /></div>
      {related.length > 0 && (
        <section aria-labelledby="related-h" className="mt-10">
          <div className="mb-3 flex items-baseline justify-between gap-4">
            <h2 id="related-h" className="font-display text-lg font-semibold">More {groupLabel?.toLowerCase()} tools</h2>
            <Link href="/pdf" className="text-[0.88rem] font-medium text-accent hover:underline">All PDF tools</Link>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {related.map((t) => <li key={t.slug}><ToolCard tool={t} compact /></li>)}
          </ul>
        </section>
      )}
    </>
  );
}
