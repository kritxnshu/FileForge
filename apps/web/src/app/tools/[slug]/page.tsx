import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ClientTool } from "@/components/ClientTool";
import { fmtShort, toolEntries } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

type Props = { params: Promise<{ slug: string }> };

async function find(slug: string) {
  const caps = await serverCaps();
  const e = caps ? toolEntries(caps).find((x) => x.slug === slug && x.op.runtime === "client") : undefined;
  return { caps, e };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { e, caps } = await find((await params).slug);
  if (!e || !caps) return { title: "Tool" };
  const title = e.kind === "convert" ? `${fmtShort(caps, e.pair.source)} to ${fmtShort(caps, e.pair.target)} converter` : e.op.label;
  return { title, description: `${e.description} Runs in your browser; nothing is uploaded.` };
}

export default async function ToolPage({ params }: Props) {
  const { slug } = await params;
  const { caps, e } = await find(slug);
  if (!caps) return <p className="py-10 text-muted">The service is unavailable. Reload the page in a moment.</p>;
  if (!e) notFound();
  return (
    <div className="pb-10 pt-4">
      <nav aria-label="Breadcrumb" className="text-[0.92rem] text-muted">
        <Link href="/tools" className="hover:text-ink">All tools</Link>
        <span aria-hidden="true"> / </span>
        <span>{e.op.label}</span>
      </nav>
      <h1 className="mt-3 font-display text-[clamp(2.25rem,6vw,4rem)] font-bold leading-none">
        {e.kind === "convert" ? `${fmtShort(caps, e.pair.source)} to ${fmtShort(caps, e.pair.target)}` : e.op.label}
      </h1>
      <p className="mt-4 max-w-2xl text-lg text-muted">{e.description}</p>
      <div className="mt-8">
        <ClientTool opId={e.op.id} source={e.pair.source} target={e.pair.target} />
      </div>
    </div>
  );
}
