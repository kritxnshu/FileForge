import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HistoryPanel, RecordRecent } from "@/components/History";
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
      <RecordRecent slug={e.slug} title={e.title} />
      <HistoryPanel />
    </div>
  );
}

/** "<a>-to-<b>" where both formats exist but no tested conversion joins them. */
function Unsupported({ caps, source, target }: { caps: Capabilities; source: string; target: string }) {
  const options = conversionsFrom(caps, source);
  const s = fmtShort(caps, source);
  const t = fmtShort(caps, target);
  return (
    <div className="pb-10 pt-4">
      <nav aria-label="Breadcrumb" className="text-[0.92rem] text-muted">
        <Link href="/tools" className="hover:text-ink">All tools</Link>
      </nav>
      <h1 className="mt-3 font-display text-4xl font-bold sm:text-5xl">{s} to {t} isn&apos;t supported</h1>
      <div className="mt-6 max-w-2xl rounded-[var(--radius-panel)] border border-line bg-surface p-5" role="status" data-testid="unsupported">
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
                  <Link href={`/convert/${o.slug}`} className="block rounded-full border border-line px-3 py-1 hover:border-line-strong">
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
    </div>
  );
}
