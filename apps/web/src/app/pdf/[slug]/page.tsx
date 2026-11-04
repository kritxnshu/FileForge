import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HistoryPanel, RecordRecent } from "@/components/History";
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
  const accepts = tool.sources.map((s) => fmtShort(caps, s)).join(", ");
  return (
    <div className="pb-10 pt-4">
      <nav aria-label="Breadcrumb" className="text-[0.92rem] text-muted">
        <Link href="/pdf" className="hover:text-ink">PDF tools</Link>
        <span aria-hidden="true"> / </span>
        <span>{tool.title}</span>
      </nav>
      <div className="mt-4 flex items-start gap-4">
        <span className="mt-1 hidden h-14 w-14 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent sm:grid" aria-hidden="true">
          <HubIcon name={tool.icon} size={28} />
        </span>
        <div>
          <h1 className="font-display text-[clamp(2.4rem,6vw,3.8rem)] font-bold leading-none">{tool.title}</h1>
          <p className="mt-3 max-w-2xl text-lg text-muted">{tool.description}</p>
          <p className="mt-1 text-[0.92rem] text-muted">Works with: {accepts}</p>
        </div>
      </div>
      {tool.special === "scan" && <div className="mt-8"><ScanCapture /></div>}
      <div className="mt-8">
        <Workspace preset={{ opId: tool.op, source: tool.sources[0], target: tool.target, options: tool.options, label: tool.title, sources: tool.sources }} />
      </div>
      <RecordRecent slug={`pdf:${tool.slug}`} title={tool.title} href={`/pdf/${tool.slug}`} />
      <HistoryPanel />
      {related.length > 0 && (
        <section aria-labelledby="related-h" className="mt-14">
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h2 id="related-h" className="font-display text-2xl font-semibold">More {hub.groups.find((g) => g.id === tool.group)?.label.toLowerCase()} tools</h2>
            <Link href="/pdf" className="font-medium text-accent underline underline-offset-4 hover:decoration-2">All PDF tools</Link>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {related.map((t) => <li key={t.slug}><ToolCard tool={t} compact /></li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
