"use client";

import { ArrowRight, Search } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { fmtShort, sampleAcrossCategories, searchTools, SUPPORT_LABEL, toolEntries } from "@/lib/caps";
import { useCaps } from "./providers";

export function ToolDirectory({ limit }: { limit?: number }) {
  const { caps } = useCaps();
  const params = useSearchParams();
  const [q, setQ] = useState("");
  // the category lives in the URL, so sidebar links and this filter stay in sync
  const cat = params.get("category") ?? "all";
  const setCat = (id: string) => window.history.replaceState(null, "", id === "all" ? "/tools" : `/tools?category=${id}`);
  const entries = useMemo(() => (caps ? toolEntries(caps) : []), [caps]);
  const searched = useMemo(() => searchTools(entries, q), [entries, q]);
  const results = useMemo(() => (cat === "all" ? searched : searched.filter((e) => e.category === cat)), [searched, cat]);
  if (!caps) return <p className="text-muted">Loading tools…</p>;
  const cats = caps.categories.filter((c) => entries.some((e) => e.category === c.id));
  const shown = limit && !q && cat === "all" ? sampleAcrossCategories(results, limit) : results;

  return (
    <div data-testid="tool-directory">
      <div className="card flex flex-col gap-2 p-2">
        <label className="relative">
          <span className="sr-only">Search tools</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search, e.g. “word to pdf” or “heic jpg”"
            data-testid="tool-search"
            className="h-10 w-full rounded-lg border border-line bg-surface-2 pl-9 pr-3 text-[0.92rem] text-ink transition-[border-color,box-shadow] duration-150 placeholder:text-muted focus:border-accent focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--accent)_20%,transparent)] focus:outline-none"
          />
        </label>
        <div role="group" aria-label="Filter by category" className="no-scrollbar flex gap-1 overflow-x-auto">
          {[{ id: "all", label: "All" }, ...cats].map((c) => {
            const on = cat === c.id;
            const n = c.id === "all" ? searched.length : searched.filter((e) => e.category === c.id).length;
            return (
              <button key={c.id} aria-pressed={on} onClick={() => setCat(c.id)}
                className={`relative shrink-0 rounded-lg px-3 py-1.5 text-[0.85rem] font-medium transition-colors duration-150 ${on ? "text-accent-ink" : "text-muted hover:text-ink"}`}>
                {on && <motion.span layoutId="tool-cat" transition={{ type: "spring", stiffness: 500, damping: 40 }} className="absolute inset-0 rounded-lg bg-accent" />}
                <span className="relative">{c.label} <span className="font-mono text-[11px]">({n})</span></span>
              </button>
            );
          })}
        </div>
      </div>
      <p className="mt-4 font-mono text-[11px] text-muted" aria-live="polite">{results.length} {results.length === 1 ? "tool" : "tools"}</p>
      {results.length === 0 ? (
        <p className="mt-6 text-muted">No tool matches “{q}”. Try a format name like PDF, PNG or MP4.</p>
      ) : (
        <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((e) => (
            <li key={`${e.op.id}:${e.slug}`}>{/* a pair can exist both on the server and in the browser */}
              <Link href={e.op.runtime === "client" ? `/tools/${e.slug}` : `/convert/${e.slug}`}
                className="group flex h-full items-center justify-between gap-3 rounded-xl border border-line bg-surface px-3.5 py-2.5 transition-[border-color,background-color] duration-150 hover:border-line-strong hover:bg-surface-2">
                <span className="min-w-0">
                  {e.kind === "convert" ? (
                    <span className="flex items-center gap-1.5 font-mono text-[0.82rem] font-semibold">
                      {fmtShort(caps, e.pair.source)} <span className="text-muted" aria-hidden="true">→</span>
                      <span className="sr-only">to</span> {fmtShort(caps, e.pair.target)}
                    </span>
                  ) : (
                    <span className="block truncate text-[0.9rem] font-medium">{e.title}</span>
                  )}
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {e.op.runtime === "client" && <span className="rounded bg-ok-soft px-1.5 py-px font-mono text-[10px] font-medium text-ok">In browser</span>}
                  {e.pair.support !== "full" && (
                    <span className={`rounded px-1.5 py-px font-mono text-[10px] font-medium ${e.pair.support === "partial" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>
                      {SUPPORT_LABEL[e.pair.support]}
                    </span>
                  )}
                  <ArrowRight size={14} className="text-line-strong transition-[color,transform] duration-200 group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden="true" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {shown.length < results.length && (
        <Link href="/tools" className="mt-5 inline-block font-medium text-accent underline-offset-4 hover:underline">
          See all {results.length} tools
        </Link>
      )}
    </div>
  );
}
