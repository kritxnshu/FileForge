import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeftRight, Binary, Braces, Clock, Code, Database, FileCode, HardDrive, Image, Link2, Palette, QrCode, Ruler, ShieldCheck, Wrench,
  type LucideIcon,
} from "lucide-react";
import { ClientTool } from "@/components/ClientTool";
import { RecordRecent } from "@/components/History";
import { PageHeader } from "@/components/PageHeader";
import { fmtShort, toolEntries } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

type Props = { params: Promise<{ slug: string }> };

const OP_ICON: Record<string, LucideIcon> = {
  "dev.json_format": Braces, "dev.data_convert": ArrowLeftRight, "dev.code_format": Code, "dev.html_markdown": FileCode,
  "dev.csv_to_sql": Database, "dev.base64": Binary, "dev.url": Link2, "dev.timestamp": Clock, "util.image_base64": Image,
  "util.color": Palette, "util.units": Ruler, "util.bytes": HardDrive, "util.qr": QrCode,
};

async function find(slug: string) {
  const caps = await serverCaps();
  const all = caps ? toolEntries(caps).filter((x) => x.op.runtime === "client") : [];
  return { caps, all, e: all.find((x) => x.slug === slug) };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { e, caps } = await find((await params).slug);
  if (!e || !caps) return { title: "Tool" };
  const title = e.kind === "convert" ? `${fmtShort(caps, e.pair.source)} to ${fmtShort(caps, e.pair.target)} converter` : e.op.label;
  return { title, description: `${e.description} Runs in your browser; nothing is uploaded.` };
}

export default async function ToolPage({ params }: Props) {
  const { slug } = await params;
  const { caps, all, e } = await find(slug);
  if (!caps) return <p className="py-10 text-muted">The service is unavailable. Reload the page in a moment.</p>;
  if (!e) notFound();
  // one tab per browser tool, linking to its first page
  const tabs = all.filter((x, i) => all.findIndex((y) => y.op.id === x.op.id) === i);
  const title = e.kind === "convert" ? `${fmtShort(caps, e.pair.source)} to ${fmtShort(caps, e.pair.target)}` : e.op.label;
  return (
    <>
      <nav aria-label="Browser tools" className="rise no-scrollbar card mb-6 flex gap-1 overflow-x-auto p-1">
        {tabs.map((t) => {
          const Icon = OP_ICON[t.op.id] ?? Wrench;
          const on = t.op.id === e.op.id;
          return (
            <Link key={t.op.id} href={`/tools/${t.slug}`} aria-current={on ? "page" : undefined}
              className={`flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[0.85rem] font-medium transition-colors duration-150 ${
                on ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-ink"
              }`}>
              <Icon size={15} aria-hidden="true" /> {t.op.label}
            </Link>
          );
        })}
      </nav>
      <PageHeader
        crumbs={[["All tools", "/tools"], [e.category === "developer" ? "Developer tools" : "Utilities"]]}
        title={title}
        description={e.description}
        aside={
          <span className="chip !h-auto !border-transparent !bg-ok-soft !py-1 !text-ok">
            <ShieldCheck size={13} aria-hidden="true" /> Runs in your browser · nothing uploaded
          </span>
        }
      />
      <ClientTool opId={e.op.id} source={e.pair.source} target={e.pair.target} />
      <RecordRecent slug={e.slug} title={title} href={`/tools/${e.slug}`} />
    </>
  );
}
