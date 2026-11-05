"use client";

import {
  ArrowRight, FileInput, FileOutput, FormInput, GitCompare, LayoutGrid, Lock, Minimize2, PencilLine, Search, type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Hub, HubTool } from "@/lib/api";
import { SUPPORT_LABEL } from "@/lib/caps";
import { HubIcon } from "./icons";

export const GROUP_ICON: Record<string, LucideIcon> = {
  organize: LayoutGrid, optimize: Minimize2, to_pdf: FileInput, from_pdf: FileOutput, edit: PencilLine,
  forms: FormInput, security: Lock, review: GitCompare,
};

function matches(t: HubTool, q: string): boolean {
  const words = q.toLowerCase().split(/\s+/).filter((w) => w && !["pdf", "to", "a", "the"].includes(w));
  if (!words.length) return true;
  const hay = `${t.title} ${t.description} ${t.sources.join(" ")} ${t.target}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

export function ToolCard({ tool, group, compact = false }: { tool: HubTool; group?: string; compact?: boolean }) {
  return (
    <Link
      href={`/pdf/${tool.slug}`}
      data-testid="pdf-tool"
      data-slug={tool.slug}
      className="card card-hover group flex h-full flex-col p-4"
    >
      <span className="flex items-start justify-between gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-accent" aria-hidden="true">
          <HubIcon name={tool.icon} size={18} />
        </span>
        {tool.support !== "full" && (
          <span className={`rounded px-1.5 py-px font-mono text-[10px] font-medium uppercase tracking-wide ${tool.support === "partial" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>
            {SUPPORT_LABEL[tool.support]}
          </span>
        )}
      </span>
      {group && <span className="eyebrow mt-3 !text-[10px]">{group}</span>}
      <span className={`${group ? "mt-0.5" : "mt-3"} font-display text-[1.02rem] font-semibold leading-snug`}>{tool.title}</span>
      {!compact && <span className="mt-1 line-clamp-3 text-[0.84rem] leading-snug text-muted">{tool.description}</span>}
      <span className="mt-auto pt-4">
        <span className="flex items-center justify-center gap-1.5 rounded-lg border border-line py-1.5 text-[0.82rem] font-medium text-muted transition-colors duration-150 group-hover:border-accent group-hover:bg-accent group-hover:text-accent-ink">
          Open tool <ArrowRight size={14} aria-hidden="true" className="transition-transform duration-200 group-hover:translate-x-0.5" />
        </span>
      </span>
    </Link>
  );
}

/** The PDF tools directory: filter by group, search by name. Everything listed comes from /api/capabilities. */
export function PdfHub({ hub }: { hub: Hub }) {
  const [group, setGroup] = useState("all");
  const [q, setQ] = useState("");
  const searched = useMemo(() => hub.tools.filter((t) => matches(t, q)), [hub, q]);
  const shown = useMemo(() => searched.filter((t) => group === "all" || t.group === group), [searched, group]);
  const sections = hub.groups
    .map((g) => ({ ...g, tools: shown.filter((t) => t.group === g.id) }))
    .filter((g) => g.tools.length);
  const label = (id: string) => hub.groups.find((g) => g.id === id)?.label;

  return (
    <div data-testid="pdf-hub">
      <div className="card flex flex-col gap-3 p-2 lg:flex-row lg:items-center">
        <label className="relative lg:w-72 lg:shrink-0">
          <span className="sr-only">Search PDF tools</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter tools, e.g. “sign”, “word”"
            data-testid="pdf-hub-search"
            className="h-9 w-full rounded-lg border border-line bg-surface-2 pl-9 pr-3 text-[0.9rem] text-ink transition-[border-color,box-shadow] duration-150 placeholder:text-muted focus:border-accent focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--accent)_20%,transparent)] focus:outline-none"
          />
        </label>
        <div role="group" aria-label="Filter PDF tools" className="no-scrollbar -mx-2 flex gap-1 overflow-x-auto px-2 lg:mx-0 lg:flex-wrap lg:px-0">
          {[{ id: "all", label: "All" }, ...hub.groups].map((g) => {
            const n = g.id === "all" ? searched.length : searched.filter((t) => t.group === g.id).length;
            const on = group === g.id;
            return (
              <button
                key={g.id}
                type="button"
                aria-pressed={on}
                onClick={() => setGroup(g.id)}
                data-testid={`pdf-group-${g.id}`}
                className={`relative shrink-0 rounded-lg px-3 py-1.5 text-[0.85rem] font-medium transition-colors duration-150 ${on ? "text-accent-ink" : "text-muted hover:text-ink"}`}
              >
                {on && <motion.span layoutId="pdf-group" transition={{ type: "spring", stiffness: 500, damping: 40 }} className="absolute inset-0 rounded-lg bg-accent" />}
                <span className="relative">{g.label} <span className="font-mono text-[11px]">({n})</span></span>
              </button>
            );
          })}
        </div>
      </div>
      <p className="sr-only" aria-live="polite">{shown.length} {shown.length === 1 ? "tool" : "tools"}</p>

      {sections.length === 0 ? (
        <p className="mt-8 text-muted">No PDF tool matches “{q}”.</p>
      ) : (
        sections.map((g) => {
          const Icon = GROUP_ICON[g.id] ?? LayoutGrid;
          return (
            <section key={g.id} id={`pdf-g-${g.id}`} aria-labelledby={`pdf-g-${g.id}-h`} className="mt-8 scroll-mt-20">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 id={`pdf-g-${g.id}-h`} className="flex items-center gap-2.5 font-display text-lg font-semibold">
                  <span className="grid h-8 w-8 place-items-center rounded-lg border border-line bg-surface text-accent shadow-1" aria-hidden="true"><Icon size={16} /></span>
                  {g.label}
                </h2>
                <span className="chip">{g.tools.length} {g.tools.length === 1 ? "tool" : "tools"}</span>
              </div>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {g.tools.map((t, i) => (
                  <li key={t.slug} className="rise" style={{ "--i": Math.min(i, 8) } as React.CSSProperties}>
                    <ToolCard tool={t} group={label(t.group)} />
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      )}

      {hub.not_offered.length > 0 && (
        <section aria-labelledby="pdf-not-offered" className="card mt-12 max-w-3xl p-5">
          <h2 id="pdf-not-offered" className="font-display text-lg font-semibold">Not offered here</h2>
          <ul className="mt-3 flex flex-col gap-2 text-[0.9rem] text-muted">
            {hub.not_offered.map((x) => (
              <li key={x.title}><span className="font-medium text-ink">{x.title}.</span> {x.reason}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
