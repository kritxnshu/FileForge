"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { outputUrl } from "@/lib/api";
import { addRecentTool, clearHistory, getHistory, getRecentTools, isExpired, type HistoryEntry } from "@/lib/history";

function useHistory() {
  const [items, setItems] = useState<HistoryEntry[]>([]);
  const [recent, setRecent] = useState<{ slug: string; title: string; href?: string }[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const load = () => {
      setItems(getHistory());
      setRecent(getRecentTools());
      setNow(Date.now() / 1000);
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
  return { items, recent, now };
}

function ago(at: number): string {
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(at).toLocaleDateString();
}

/** Conversion history and recent tools. Metadata only, kept in this browser. */
export function HistoryPanel() {
  const { items, recent, now } = useHistory();
  if (!items.length && !recent.length) return null;
  return (
    <section aria-labelledby="history-h" className="mt-10 rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-6" data-testid="history">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="history-h" className="font-display text-2xl font-semibold">History</h2>
        <button onClick={clearHistory} className="rounded-md px-2 py-1 text-[0.92rem] text-muted hover:text-ink" data-testid="clear-history">
          Clear history
        </button>
      </div>
      <p className="mb-4 text-[0.9rem] text-muted">Saved only in this browser: file names and formats, never file contents.</p>
      {recent.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {recent.map((r) => (
            <Link key={r.slug} href={r.href ?? `/convert/${r.slug}`} className="rounded-full border border-line px-3 py-1 text-[0.9rem] hover:border-line-strong">
              {r.title}
            </Link>
          ))}
        </div>
      )}
      <ul className="divide-y divide-line">
        {items.slice(0, 20).map((h) => {
          const expired = isExpired(h, now);
          return (
            <li key={h.jobId} className="flex flex-wrap items-center justify-between gap-2 py-2.5" data-expired={expired}>
              <span className="min-w-0">
                <span className="block truncate font-medium" title={h.fileName}>{h.fileName}</span>
                <span className="text-[0.88rem] text-muted">{h.tool ? h.label : `to ${h.label}`}, {ago(h.at)}</span>
              </span>
              {expired ? (
                <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-[0.82rem] text-muted">Expired</span>
              ) : h.outputs === 1 ? (
                <a href={outputUrl(h.jobId, 0)} download className="text-[0.92rem] font-medium text-accent underline-offset-4 hover:underline">Download</a>
              ) : (
                <span className="text-[0.88rem] text-muted">{h.outputs} files</span>
              )}
            </li>
          );
        })}
      </ul>
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
