"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Hub, HubTool } from "@/lib/api";
import { SUPPORT_LABEL } from "@/lib/caps";
import { HubIcon } from "./icons";

function matches(t: HubTool, q: string): boolean {
  const words = q.toLowerCase().split(/\s+/).filter((w) => w && !["pdf", "to", "a", "the"].includes(w));
  if (!words.length) return true;
  const hay = `${t.title} ${t.description} ${t.sources.join(" ")} ${t.target}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

export function ToolCard({ tool, compact = false }: { tool: HubTool; compact?: boolean }) {
  return (
    <Link
      href={`/pdf/${tool.slug}`}
      data-testid="pdf-tool"
      data-slug={tool.slug}
      className="group flex h-full flex-col gap-3 rounded-[var(--radius-panel)] border border-line bg-surface p-5 transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-line-strong"
    >
      <span className="flex items-start justify-between gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true">
          <HubIcon name={tool.icon} />
        </span>
        {tool.support !== "full" && (
          <span className={`rounded-full px-2 py-0.5 text-[0.75rem] font-medium ${tool.support === "partial" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>
            {SUPPORT_LABEL[tool.support]}
          </span>
        )}
      </span>
      <span className="font-display text-[1.25rem] font-semibold leading-tight">{tool.title}</span>
      {!compact && <span className="text-[0.95rem] leading-snug text-muted">{tool.description}</span>}
    </Link>
  );
}

/** The PDF tools directory: filter by group, search by name. Everything listed comes from /api/capabilities. */
export function PdfHub({ hub }: { hub: Hub }) {
  const [group, setGroup] = useState("all");
  const [q, setQ] = useState("");
  const shown = useMemo(() => hub.tools.filter((t) => (group === "all" || t.group === group) && matches(t, q)), [hub, group, q]);
  const sections = hub.groups
    .map((g) => ({ ...g, tools: shown.filter((t) => t.group === g.id) }))
    .filter((g) => g.tools.length);

  return (
    <div data-testid="pdf-hub">
      <div className="flex flex-col gap-4">
        <label className="relative max-w-xl">
          <span className="sr-only">Search PDF tools</span>
          <Search size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search, e.g. “sign”, “word”, “compress”"
            data-testid="pdf-hub-search"
            className="w-full rounded-[var(--radius-control)] border border-line bg-surface py-3 pl-11 pr-4 text-ink placeholder:text-muted focus-visible:border-accent"
          />
        </label>
        <div role="group" aria-label="Filter PDF tools" className="flex flex-wrap gap-2">
          {[{ id: "all", label: "All" }, ...hub.groups].map((g) => (
            <button
              key={g.id}
              type="button"
              aria-pressed={group === g.id}
              onClick={() => setGroup(g.id)}
              data-testid={`pdf-group-${g.id}`}
              className={`rounded-full border px-3.5 py-1.5 text-[0.95rem] transition-colors duration-150 ${
                group === g.id ? "border-ink bg-ink text-paper" : "border-line bg-surface text-muted hover:text-ink"
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
        <p className="text-[0.9rem] text-muted" aria-live="polite">{shown.length} {shown.length === 1 ? "tool" : "tools"}</p>
      </div>

      {sections.length === 0 ? (
        <p className="mt-8 text-muted">No PDF tool matches “{q}”.</p>
      ) : (
        sections.map((g) => (
          <section key={g.id} aria-labelledby={`pdf-g-${g.id}`} className="mt-8">
            <h2 id={`pdf-g-${g.id}`} className="mb-4 font-display text-2xl font-semibold">{g.label}</h2>
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {g.tools.map((t) => (
                <li key={t.slug}><ToolCard tool={t} /></li>
              ))}
            </ul>
          </section>
        ))
      )}

      {hub.not_offered.length > 0 && (
        <section aria-labelledby="pdf-not-offered" className="mt-14 max-w-3xl">
          <h2 id="pdf-not-offered" className="font-display text-xl font-semibold">Not offered here</h2>
          <ul className="mt-3 flex flex-col gap-2 text-[0.95rem] text-muted">
            {hub.not_offered.map((x) => (
              <li key={x.title}><span className="font-medium text-ink">{x.title}.</span> {x.reason}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
