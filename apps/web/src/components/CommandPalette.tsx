"use client";

import { ArrowRight, CornerDownLeft, FileText, LayoutGrid, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { fmtShort, searchTools, toolEntries } from "@/lib/caps";
import { useCaps } from "./providers";

interface Hit {
  title: string;
  hint: string;
  href: string;
  kind: "page" | "pdf" | "tool";
}

const PAGES: Hit[] = [
  { title: "Dashboard", hint: "Home", href: "/", kind: "page" },
  { title: "Convert files", hint: "Workspace", href: "/convert", kind: "page" },
  { title: "PDF tools", hint: "All PDF tools", href: "/pdf", kind: "page" },
  { title: "All tools", hint: "Directory", href: "/tools", kind: "page" },
  { title: "Supported formats", hint: "Reference", href: "/formats", kind: "page" },
  { title: "Docs and API", hint: "Reference", href: "/docs", kind: "page" },
  { title: "Privacy", hint: "Legal", href: "/privacy", kind: "page" },
];

const words = (q: string) => q.toLowerCase().split(/\s+/).filter(Boolean);
const hasAll = (text: string, q: string) => words(q).every((w) => text.toLowerCase().includes(w));

/** ⌘K / Ctrl+K: jump to any page or tool. A native <dialog>, so focus and Escape are handled by the browser. */
export function CommandPalette() {
  const ref = useRef<HTMLDialogElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const { caps } = useCaps();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);

  useEffect(() => {
    const open = () => {
      setQ("");
      setSel(0);
      if (!ref.current?.open) ref.current?.showModal();
    };
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (ref.current?.open) ref.current.close();
        else open();
      }
    };
    window.addEventListener("ff-palette", open);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("ff-palette", open);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const entries = useMemo(() => (caps ? toolEntries(caps) : []), [caps]);
  const hits = useMemo<Hit[]>(() => {
    const pdf: Hit[] = (caps?.hubs?.pdf?.tools ?? []).map((t) => ({ title: t.title, hint: "PDF tool", href: `/pdf/${t.slug}`, kind: "pdf" }));
    const tool = (e: (typeof entries)[number]): Hit => ({
      title: e.kind === "convert" && caps ? `${fmtShort(caps, e.pair.source)} → ${fmtShort(caps, e.pair.target)}` : e.title,
      hint: e.op.runtime === "client" ? "Runs in browser" : e.kind === "convert" ? "Conversion" : "Tool",
      href: e.op.runtime === "client" ? `/tools/${e.slug}` : `/convert/${e.slug}`,
      kind: "tool",
    });
    if (!q.trim()) return [...PAGES, ...pdf.slice(0, 3)];
    return [
      ...PAGES.filter((p) => hasAll(p.title, q)),
      ...pdf.filter((p) => hasAll(p.title, q)),
      ...searchTools(entries, q).map(tool),
    ].filter((h, i, all) => all.findIndex((x) => x.href === h.href) === i).slice(0, 9);
  }, [q, caps, entries]);

  const go = (h: Hit | undefined) => {
    if (!h) return;
    ref.current?.close();
    router.push(h.href);
  };
  const active = Math.min(sel, Math.max(0, hits.length - 1));
  const move = (d: number) => {
    const next = (active + d + hits.length) % Math.max(1, hits.length);
    setSel(next);
    list.current?.children[next]?.scrollIntoView({ block: "nearest" });
  };

  return (
    <dialog
      ref={ref}
      aria-label="Search tools"
      className="palette glass m-auto mt-[12vh] w-[min(36rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border p-0 text-ink shadow-3"
      onClick={(e) => e.target === ref.current && ref.current?.close()}
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={17} className="shrink-0 text-muted" aria-hidden="true" />
        <input
          autoFocus
          value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
            if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
            if (e.key === "Enter") { e.preventDefault(); go(hits[active]); }
          }}
          placeholder="Search tools, e.g. “heic jpg” or “sign”"
          aria-label="Search tools"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={hits.length ? `palette-${active}` : undefined}
          className="h-13 flex-1 bg-transparent py-4 text-[0.98rem] outline-none placeholder:text-muted"
          data-testid="palette-input"
        />
        <kbd className="rounded border border-line px-1.5 font-mono text-[10px] text-muted">ESC</kbd>
      </div>
      <ul ref={list} id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
        {hits.length === 0 && <li className="px-3 py-6 text-center text-[0.9rem] text-muted">No tool matches “{q}”.</li>}
        {hits.map((h, i) => {
          const Icon = h.kind === "pdf" ? FileText : h.kind === "page" ? LayoutGrid : ArrowRight;
          return (
            <li
              key={h.href}
              id={`palette-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseMove={() => setSel(i)}
              onClick={() => go(h)}
              className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-[0.92rem] ${i === active ? "bg-accent-soft" : ""}`}
            >
              <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-md ${i === active ? "bg-accent text-accent-ink" : "bg-surface-2 text-muted"}`}>
                <Icon size={14} aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1 truncate font-medium">{h.title}</span>
              <span className="font-mono text-[11px] text-muted">{h.hint}</span>
              {i === active && <CornerDownLeft size={14} className="text-muted" aria-hidden="true" />}
            </li>
          );
        })}
      </ul>
    </dialog>
  );
}
