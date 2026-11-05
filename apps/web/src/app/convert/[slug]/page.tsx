import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HistoryPanel, RecordRecent } from "@/components/History";
import { PageHeader } from "@/components/PageHeader";
import { Workspace } from "@/components/Workspace";
import { conversionsFrom, findBySlug, fmtLabel, fmtShort, unsupportedPair } from "@/lib/caps";
import type { Capabilities } from "@/lib/api";
import { serverCaps } from "@/lib/server";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const caps = await serverCaps();
  const e = caps ? findBySlug(caps, slug) : undefined;
  if (caps && !e) {
    const u = unsupportedPair(caps, slug);
    if (u) return { title: `${fmtShort(caps, u.source)} to ${fmtShort(caps, u.target)} isn't supported`, robots: { index: false } };
  }
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
  if (!e) {
    const u = unsupportedPair(caps, slug);
    if (!u) notFound();
    return <Unsupported caps={caps} source={u.source} target={u.target} />;
  }
  return (
    <>
      <PageHeader
        crumbs={[["All tools", "/tools"], [e.title]]}
        eyebrow={e.kind === "convert" ? "Conversion" : "Tool"}
        title={e.kind === "convert" ? (
          <>{fmtShort(caps, e.pair.source)} <span className="text-accent" aria-hidden="true">→</span><span className="sr-only">to</span> {fmtShort(caps, e.pair.target)}</>
        ) : e.title}
        description={e.kind === "convert" ? `${fmtLabel(caps, e.pair.source)} to ${fmtLabel(caps, e.pair.target)}. ${e.description}` : e.description}
      />
      <Workspace preset={{ opId: e.op.id, source: e.pair.source, target: e.pair.target }} />
      <RecordRecent slug={e.slug} title={e.title} />
      <div className="mt-10"><HistoryPanel /></div>
    </>
  );
}

/** "<a>-to-<b>" where both formats exist but no tested conversion joins them. */
function Unsupported({ caps, source, target }: { caps: Capabilities; source: string; target: string }) {
  const options = conversionsFrom(caps, source);
  const s = fmtShort(caps, source);
  const t = fmtShort(caps, target);
  return (
    <>
      <PageHeader crumbs={[["All tools", "/tools"]]} title={<>{s} to {t} isn&apos;t supported</>} />
      <div className="card max-w-2xl p-5" role="status" data-testid="unsupported">
        <p className="text-lg">
          {source === target
            ? `${fmtLabel(caps, source)} files are already ${t}.`
            : `We can't turn ${fmtLabel(caps, source)} files into ${fmtLabel(caps, target)}. We only offer conversions that pass our automated tests, and this one doesn't exist yet.`}
        </p>
        {options.length > 0 ? (
          <>
            <p className="mt-4 font-medium">{s} files can be converted to:</p>
            <ul className="mt-2 flex flex-wrap gap-2" data-testid="alternatives">
              {options.map((o) => (
                <li key={o.slug}>
                  <Link href={`/convert/${o.slug}`} className="block rounded-md border border-line bg-surface-2 px-2.5 py-1 font-mono text-[0.8rem] font-medium transition-colors duration-150 hover:border-accent hover:text-accent">
                    {fmtShort(caps, o.pair.target)}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-4 text-muted">There are no conversions for {s} files yet.</p>
        )}
        <p className="mt-4 text-[0.95rem] text-muted">
          See every <Link href="/formats" className="text-accent underline underline-offset-4 hover:decoration-2">supported format</Link>.
        </p>
      </div>
    </>
  );
}
