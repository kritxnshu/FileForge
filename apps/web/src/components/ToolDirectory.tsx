"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { fmtShort, searchTools, SUPPORT_LABEL, toolEntries } from "@/lib/caps";
import { useCaps } from "./providers";

export function ToolDirectory({ limit }: { limit?: number }) {
  const { caps } = useCaps();
  const params = useSearchParams();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>(params.get("category") ?? "all");
  const entries = useMemo(() => (caps ? toolEntries(caps) : []), [caps]);
  const results = useMemo(() => {
    const filtered = cat === "all" ? entries : entries.filter((e) => e.category === cat);
    return searchTools(filtered, q);
  }, [entries, q, cat]);
  if (!caps) return <p className="text-muted">Loading tools…</p>;
  const cats = caps.categories.filter((c) => entries.some((e) => e.category === c.id));
  const shown = limit && !q && cat === "all" ? results.slice(0, limit) : results;

  return (
    <div data-testid="tool-directory">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative flex-1">
          <span className="sr-only">Search tools</span>
          <Search size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search, e.g. “word to pdf” or “heic jpg”"
            data-testid="tool-search"
            className="w-full rounded-[var(--radius-control)] border border-line bg-surface py-3 pl-11 pr-4 text-ink placeholder:text-muted focus-visible:border-accent"
          />
        </label>
      </div>
      <div role="group" aria-label="Filter by category" className="mt-3 flex flex-wrap gap-2">
        {[{ id: "all", label: "All" }, ...cats].map((c) => (
          <button key={c.id} aria-pressed={cat === c.id} onClick={() => setCat(c.id)}
            className={`rounded-full border px-3 py-1 text-[0.9rem] transition-colors duration-150 ${cat === c.id ? "border-ink bg-ink text-paper" : "border-line text-muted hover:text-ink"}`}>
            {c.label}
          </button>
        ))}
      </div>
      <p className="mt-4 text-[0.9rem] text-muted" aria-live="polite">{results.length} {results.length === 1 ? "tool" : "tools"}</p>
      {results.length === 0 ? (
        <p className="mt-6 text-muted">No tool matches “{q}”. Try a format name like PDF, PNG or MP4.</p>
      ) : (
        <ul className="mt-3 grid gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((e) => (
            <li key={e.slug} className="border-b border-line">
              <Link href={e.op.runtime === "client" ? `/tools/${e.slug}` : `/convert/${e.slug}`} className="group flex items-center justify-between gap-3 py-3">
                <span className="flex min-w-0 items-center gap-2">
                  {e.kind === "convert" ? (
                    <span className="font-medium">
                      {fmtShort(caps, e.pair.source)} <span className="text-muted" aria-hidden="true">→</span>
                      <span className="sr-only">to</span> {fmtShort(caps, e.pair.target)}
                    </span>
                  ) : (
                    <span className="truncate font-medium">{e.title}</span>
                  )}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-[0.8rem]">
                  {e.op.runtime === "client" && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-ink">In browser</span>}
                  {e.pair.support !== "full" && (
                    <span className={`rounded-full px-2 py-0.5 ${e.pair.support === "partial" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>
                      {SUPPORT_LABEL[e.pair.support]}
                    </span>
                  )}
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
