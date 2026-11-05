"use client";

import { Clock3, Download, FileClock, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { outputUrl } from "@/lib/api";
import { fmtShort } from "@/lib/caps";
import { addRecentTool, clearHistory, getHistory, getRecentTools, isExpired, type HistoryEntry } from "@/lib/history";
import { useCaps } from "./providers";

function useHistory() {
  const [items, setItems] = useState<HistoryEntry[]>([]);
  const [recent, setRecent] = useState<{ slug: string; title: string; href?: string }[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const load = () => {
      setItems(getHistory());
      setRecent(getRecentTools());
      setNow(Date.now() / 1000);
      setLoaded(true);
    };
    load();
    window.addEventListener("uc-history", load);
    window.addEventListener("storage", load);
    const t = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => {
      window.removeEventListener("uc-history", load);
      window.removeEventListener("storage", load);
      clearInterval(t);
    };
  }, []);
  return { items, recent, now, loaded };
}

function ago(at: number): string {
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(at).toLocaleDateString();
}

/** Recent conversions and tools. Metadata only, kept in this browser. */
export function HistoryPanel({ limit = 20, showEmpty = false }: { limit?: number; showEmpty?: boolean }) {
  const { items, recent, now, loaded } = useHistory();
  const { caps } = useCaps();
  const fmt = (id: string) => (caps ? fmtShort(caps, id) : id.toUpperCase());
  if (!items.length && !recent.length) {
    if (!showEmpty || !loaded) return null;
    return (
      <section aria-labelledby="history-h" className="card flex flex-col items-center px-6 py-10 text-center" data-testid="history-empty">
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-muted" aria-hidden="true"><FileClock size={20} /></span>
        <h2 id="history-h" className="mt-3 font-display text-lg font-semibold">No recent jobs yet</h2>
        <p className="mt-1 max-w-sm text-[0.9rem] text-muted">Finished conversions show up here. Only names and formats are kept, in this browser.</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="history-h" className="card overflow-hidden" data-testid="history">
      <div className="flex flex-wrap items-end justify-between gap-3 px-5 pb-4 pt-5">
        <div>
          <p className="eyebrow flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" /> Saved in this browser
          </p>
          <h2 id="history-h" className="mt-1 font-display text-xl font-semibold">Recent jobs</h2>
        </div>
        <button onClick={clearHistory} className="btn btn-ghost !py-1.5 text-muted" data-testid="clear-history">
          <Trash2 size={14} aria-hidden="true" /> Clear history
        </button>
      </div>
      {recent.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-5 pb-4">
          <span className="text-[0.82rem] text-muted">Recent tools:</span>
          {recent.map((r) => (
            <Link key={r.slug} href={r.href ?? `/convert/${r.slug}`}
              className="rounded-md border border-line bg-surface-2 px-2.5 py-1 text-[0.82rem] font-medium transition-colors duration-150 hover:border-line-strong hover:bg-surface">
              {r.title}
            </Link>
          ))}
        </div>
      )}
      {items.length > 0 && (
        <>
          <div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_minmax(0,1fr)_7rem] gap-4 border-y border-line bg-surface-2 px-5 py-2 font-mono text-[11px] uppercase tracking-wider text-muted md:grid" aria-hidden="true">
            <span>File</span><span>Route</span><span>Status</span><span className="text-right">Actions</span>
          </div>
          <ul className="divide-y divide-line border-t border-line md:border-t-0">
            {items.slice(0, limit).map((h) => {
              const expired = isExpired(h, now);
              return (
                <li key={h.jobId} data-expired={expired}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-5 py-3 transition-colors duration-150 hover:bg-surface-2/60 md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_minmax(0,1fr)_7rem]">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 font-mono text-[10px] font-semibold text-muted" aria-hidden="true">
                      {fmt(h.source).slice(0, 4)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[0.92rem] font-medium" title={h.fileName}>{h.fileName}</span>
                      <span className="flex items-center gap-1 font-mono text-[11px] text-muted"><Clock3 size={11} aria-hidden="true" />{ago(h.at)}</span>
                    </span>
                  </span>
                  <span className="order-last col-span-2 flex items-center gap-1.5 md:order-none md:col-span-1">
                    {h.tool ? (
                      <span className="chip">{h.label}</span>
                    ) : (
                      <>
                        <span className="chip">{fmt(h.source)}</span>
                        <span className="text-muted" aria-hidden="true">→</span>
                        <span className="sr-only">to</span>
                        <span className="chip !border-transparent !bg-accent-soft !text-accent">{h.label}</span>
                      </>
                    )}
                  </span>
                  <span className="hidden md:block">
                    {expired ? (
                      <span className="chip">Expired</span>
                    ) : (
                      <span className="chip !border-transparent !bg-ok-soft !text-ok">
                        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                        {h.outputs === 1 ? "Ready" : `${h.outputs} files`}
                      </span>
                    )}
                  </span>
                  <span className="flex justify-end">
                    {expired ? (
                      <span className="chip md:hidden">Expired</span>
                    ) : h.outputs === 1 ? (
                      <a href={outputUrl(h.jobId, 0)} download className="btn btn-ghost !px-2.5 !py-1 text-[0.82rem]">
                        <Download size={14} aria-hidden="true" /> Download
                      </a>
                    ) : (
                      <span className="font-mono text-[11px] text-muted md:hidden">{h.outputs} files</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

/** Remembers that a tool page was visited (for "recent tools"). */
export function RecordRecent({ slug, title, href }: { slug: string; title: string; href?: string }) {
  useEffect(() => {
    addRecentTool({ slug, title, ...(href ? { href } : {}) });
  }, [slug, title, href]);
  return null;
}
