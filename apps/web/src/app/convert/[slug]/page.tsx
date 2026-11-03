import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Workspace } from "@/components/Workspace";
import { findBySlug, fmtLabel, fmtShort } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const caps = await serverCaps();
  const e = caps ? findBySlug(caps, slug) : undefined;
  if (!caps || !e) return { title: "Convert files" };
  if (e.kind === "tool") return { title: e.title, description: e.description };
  const s = fmtLabel(caps, e.pair.source);
  const t = fmtLabel(caps, e.pair.target);
  return {
    title: `Convert ${fmtShort(caps, e.pair.source)} to ${fmtShort(caps, e.pair.target)}`,
    description: `Convert ${s} files to ${t}. ${e.description} Files are deleted automatically.`,
  };
}

export default async function ConversionPage({ params }: Props) {
  const { slug } = await params;
  const caps = await serverCaps();
  if (!caps) return <p className="py-10 text-muted">The conversion service is unavailable. Reload the page in a moment.</p>;
  const e = findBySlug(caps, slug);
  if (!e) notFound();
  return (
    <div className="pb-10 pt-4">
      <nav aria-label="Breadcrumb" className="text-[0.92rem] text-muted">
        <Link href="/tools" className="hover:text-ink">All tools</Link>
        <span aria-hidden="true"> / </span>
        <span>{e.title}</span>
      </nav>
      {e.kind === "convert" ? (
        <h1 className="mt-3 font-display text-[clamp(3rem,10vw,6.5rem)] font-bold leading-none" style={{ fontVariationSettings: '"wdth" 75' }}>
          {fmtShort(caps, e.pair.source)} <span className="text-accent" aria-hidden="true">→</span>
          <span className="sr-only">to</span> {fmtShort(caps, e.pair.target)}
        </h1>
      ) : (
        <h1 className="mt-3 font-display text-[clamp(2.5rem,7vw,4.5rem)] font-bold leading-none">{e.title}</h1>
      )}
      <p className="mt-4 max-w-2xl text-lg text-muted">
        {e.kind === "convert" ? `${fmtLabel(caps, e.pair.source)} to ${fmtLabel(caps, e.pair.target)}. ${e.description}` : e.description}
      </p>
      <div className="mt-8">
        <Workspace preset={{ opId: e.op.id, source: e.pair.source, target: e.pair.target }} />
      </div>
    </div>
  );
}
