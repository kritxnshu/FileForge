import Link from "next/link";
import { ArrowUpRight, Boxes, Layers, ShieldCheck, Sparkles, TerminalSquare, Zap } from "lucide-react";
import { CATEGORY_ICON } from "@/components/categoryIcons";
import { Dock } from "@/components/chrome";
import { DropZone } from "@/components/DropZone";
import { HistoryPanel } from "@/components/History";
import type { Capabilities } from "@/lib/api";
import { fmtShort, toolEntries, type ToolEntry } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

const POPULAR: [string, string][] = [
  ["heic", "jpg"], ["pdf", "docx"], ["mp4", "mp3"], ["png", "webp"], ["docx", "pdf"], ["xlsx", "csv"],
];
const HERO_FORMATS = ["png", "heic", "pdf", "mp4", "csv", "docx", "webp"];

/** Short names of formats in these families, most common first (the registry's order). */
function familyFormats(caps: Capabilities, families: string[], n = 4): string {
  return Object.entries(caps.formats).filter(([, f]) => families.includes(f.family)).slice(0, n).map(([id]) => fmtShort(caps, id)).join(", ");
}

export default async function Home() {
  const caps = await serverCaps();
  const entries = caps ? toolEntries(caps) : [];
  const count = (cats: string[]) => entries.filter((e) => cats.includes(e.category)).length;
  const devSlug = entries.find((e) => e.category === "developer" && e.op.runtime === "client")?.slug;
  const popular = POPULAR.map(([s, t]) => entries.find((e) => e.kind === "convert" && e.pair.source === s && e.pair.target === t)).filter(
    (e): e is ToolEntry => Boolean(e),
  );
  const heroFormats = caps ? HERO_FORMATS.filter((f) => caps.formats[f]).map((f) => fmtShort(caps, f)) : [];
  const moreFormats = caps ? Object.keys(caps.formats).length - heroFormats.length : 0;
  const limits = caps?.limits;

  const quick = caps
    ? [
        { title: "Image converter", href: "/tools?category=images", icon: CATEGORY_ICON.images, desc: familyFormats(caps, ["image"], 5), n: count(["images"]) },
        { title: "PDF suite", href: "/pdf", icon: CATEGORY_ICON.documents, desc: "Merge, compress, sign, redact, OCR", n: caps.hubs?.pdf?.tools.length ?? 0 },
        { title: "Video & audio", href: "/tools?category=video", icon: CATEGORY_ICON.video, desc: familyFormats(caps, ["video", "audio"], 5), n: count(["video", "audio"]) },
        { title: "Developer tools", href: devSlug ? `/tools/${devSlug}` : "/tools?category=developer", icon: TerminalSquare, desc: "JSON, YAML, SQL, Base64, URL", n: count(["developer", "utilities"]) },
        { title: "Archives", href: "/tools?category=archives", icon: CATEGORY_ICON.archives, desc: familyFormats(caps, ["archive"], 4), n: count(["archives"]) },
        { title: "Documents", href: "/tools?category=documents", icon: Layers, desc: familyFormats(caps, ["document", "spreadsheet", "presentation"], 5), n: count(["documents", "spreadsheets", "presentations"]) },
      ].filter((q) => q.n > 0)
    : [];

  return (
    <div className="flex flex-col gap-8 pb-16">
      <section className="card rise overflow-hidden p-5 sm:p-8">
        <p className="chip !border-transparent !bg-accent-soft !text-accent">
          <Sparkles size={12} aria-hidden="true" /> Local-first · sandboxed · no accounts
        </p>
        <h1 className="mt-3 font-display text-[1.85rem] font-semibold leading-tight tracking-[-0.03em] sm:text-[2.5rem]">
          What do you want to create today?
        </h1>
        <p className="mt-2 max-w-2xl text-[0.98rem] text-muted">
          Upload any file and let FileForge handle the rest: real conversions, checked by an independent parser, deleted automatically.
        </p>
        <div className="mt-6">
          <DropZone navigateTo="/convert" formats={heroFormats} moreFormats={moreFormats} global />
        </div>
      </section>

      {quick.length > 0 && (
        <section aria-labelledby="quick-h" data-testid="quick-actions">
          <div className="mb-4 flex items-end justify-between gap-3">
            <div>
              <p className="eyebrow">Specialized utilities</p>
              <h2 id="quick-h" className="mt-1 font-display text-xl font-semibold">Quick actions</h2>
            </div>
            <p className="font-mono text-[11px] text-muted">{entries.length} tools loaded</p>
          </div>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {quick.map((q, i) => (
              <li key={q.title} className="rise" style={{ "--i": i + 1 } as React.CSSProperties}>
                <Link href={q.href} className="card card-hover group flex h-full flex-col p-4">
                  <span className="flex items-start justify-between">
                    <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-accent" aria-hidden="true"><q.icon size={18} /></span>
                    <ArrowUpRight size={16} className="text-line-strong transition-[color,transform] duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden="true" />
                  </span>
                  <span className="mt-3 font-display text-[0.98rem] font-semibold">{q.title}</span>
                  <span className="mt-0.5 line-clamp-2 text-[0.82rem] text-muted">{q.desc}</span>
                  <span className="mt-auto pt-3 font-mono text-[11px] text-muted">{q.n} tools</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {caps && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          {popular.length > 0 && (
            <section aria-labelledby="popular-h" className="card p-5">
              <p className="eyebrow">Shortcuts</p>
              <h2 id="popular-h" className="mt-1 font-display text-xl font-semibold">Popular conversions</h2>
              <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                {popular.map((e) => {
                  const Icon = CATEGORY_ICON[e.category] ?? Zap;
                  return (
                    <li key={e.slug}>
                      <Link href={`/convert/${e.slug}`} className="group flex h-full gap-3 rounded-xl border border-line bg-surface-2 p-3.5 transition-[border-color,background-color] duration-150 hover:border-line-strong hover:bg-surface">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface text-accent" aria-hidden="true"><Icon size={17} /></span>
                        <span className="min-w-0">
                          <span className="block font-medium">
                            {fmtShort(caps, e.pair.source)} <span className="text-muted" aria-hidden="true">→</span><span className="sr-only">to</span> {fmtShort(caps, e.pair.target)}
                          </span>
                          <span className="mt-0.5 line-clamp-2 text-[0.82rem] text-muted">{e.description}</span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <Link href="/tools" className="mt-4 inline-flex items-center gap-1 text-[0.88rem] font-medium text-accent hover:underline">
                Browse all {entries.length} tools <ArrowUpRight size={14} aria-hidden="true" />
              </Link>
            </section>
          )}
          {limits && (
            <section aria-labelledby="limits-h" className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="eyebrow">Conversion engine</p>
                  <h2 id="limits-h" className="mt-1 font-display text-xl font-semibold">Limits per batch</h2>
                </div>
                <span className="chip !border-transparent !bg-ok-soft !text-ok"><span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />Online</span>
              </div>
              <dl className="mt-4 grid flex-1 grid-cols-2 gap-2.5">
                {[
                  ["File size", `${limits.max_file_size_mb} MB`, "per file"],
                  ["Video", `${limits.max_video_size_mb} MB`, "per file"],
                  ["Batch", `${limits.max_batch_files}`, `files, ${limits.max_batch_total_mb} MB total`],
                  ["Retention", `${limits.retention_minutes} min`, "then wiped"],
                ].map(([k, v, s]) => (
                  <div key={k} className="rounded-xl border border-line bg-surface-2 p-3">
                    <dt className="text-[0.78rem] text-muted">{k}</dt>
                    <dd className="mt-0.5 font-display text-[1.35rem] font-semibold tabular-nums">{v}</dd>
                    <dd className="font-mono text-[11px] text-muted">{s}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 flex items-center gap-2 font-mono text-[11px] text-muted">
                <ShieldCheck size={13} aria-hidden="true" /> Each job runs in its own isolated process, with no network access.
              </p>
            </section>
          )}
        </div>
      )}

      <HistoryPanel limit={8} showEmpty />

      <ul className="grid gap-3 md:grid-cols-3">
        {[
          { icon: ShieldCheck, title: "Sandboxed engines", text: "FFmpeg, LibreOffice and friends run isolated, with strict time and size limits." },
          { icon: Boxes, title: "Batch conversions", text: limits ? `Up to ${limits.max_batch_files} files at once, downloaded together as one ZIP.` : "Many files at once, downloaded together as one ZIP." },
          { icon: TerminalSquare, title: "Same engine over HTTP", text: "Everything here is also available through the API.", href: "/docs" },
        ].map((f) => (
          <li key={f.title} className="card flex gap-3 p-4">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true"><f.icon size={19} /></span>
            <span>
              <span className="block font-medium">{f.title}</span>
              <span className="text-[0.85rem] text-muted">
                {f.text} {f.href && <Link href={f.href} className="font-medium text-accent hover:underline">Read the docs</Link>}
              </span>
            </span>
          </li>
        ))}
      </ul>

      <Dock />
    </div>
  );
}
