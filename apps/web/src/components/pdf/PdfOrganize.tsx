"use client";

import { ArrowLeft, ArrowRight, Copy, FilePlus, RotateCcw, RotateCw, Trash2, Undo2, ArrowLeftRight } from "lucide-react";
import { useEffect, useRef } from "react";
import { usePdfIndex } from "./usePdfIndex";

export interface OrganizePage {
  source: number | null; // 1-based page of the original, or null for a blank page
  rotate: 0 | 90 | 180 | 270;
}

const turn = (r: number, by: number) => (((r + by) % 360) + 360) % 360 as OrganizePage["rotate"];

/** Visual page organizer: reorder (drag or buttons), rotate, delete, duplicate and insert blank pages. */
export function PdfOrganize({ fileId, value, onChange }: { fileId: string; value: OrganizePage[] | undefined; onChange: (v: OrganizePage[]) => void }) {
  const { data, error } = usePdfIndex(fileId);
  const drag = useRef<number | null>(null);
  const initial = (n: number) => Array.from({ length: n }, (_, i) => ({ source: i + 1, rotate: 0 as const }));
  const pages = value && value.length ? value : data ? initial(data.pages) : [];

  // the form starts empty: once the page count is known, fill in the original order
  useEffect(() => {
    if (data && (!value || !value.length)) onChange(initial(data.pages));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (error) return <p role="alert" className="rounded-[var(--radius-control)] bg-danger-soft p-3">{error}</p>;
  if (!data) return <p className="text-muted">Loading pages…</p>;

  const set = (next: OrganizePage[]) => onChange(next);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= pages.length || from === to) return;
    const next = [...pages];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    set(next);
  };
  const removed = Array.from({ length: data.pages }, (_, i) => i + 1).filter((n) => !pages.some((p) => p.source === n));
  const btn = "rounded p-1 text-muted hover:bg-surface hover:text-ink disabled:opacity-30";

  return (
    <div data-testid="pdf-organize">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[0.92rem]">
        <span className="mr-auto text-muted">{pages.length} page{pages.length === 1 ? "" : "s"} in the new PDF. Drag to reorder, or use the buttons.</span>
        <button type="button" onClick={() => set(pages.map((p) => ({ ...p, rotate: turn(p.rotate, 90) })))} className="flex items-center gap-1 rounded-[var(--radius-control)] border border-line px-2.5 py-1.5 hover:border-line-strong">
          <RotateCw size={15} aria-hidden="true" /> Rotate all
        </button>
        <button type="button" onClick={() => set([...pages].reverse())} className="flex items-center gap-1 rounded-[var(--radius-control)] border border-line px-2.5 py-1.5 hover:border-line-strong" data-testid="organize-reverse">
          <ArrowLeftRight size={15} aria-hidden="true" /> Reverse
        </button>
        <button type="button" onClick={() => set(initial(data.pages))} className="flex items-center gap-1 rounded-[var(--radius-control)] border border-line px-2.5 py-1.5 hover:border-line-strong">
          <Undo2 size={15} aria-hidden="true" /> Reset
        </button>
      </div>
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {pages.map((p, idx) => {
          const name = p.source ? `Page ${p.source}` : "Blank page";
          const thumb = p.source && p.source <= data.thumbnails.length ? data.thumbnails[p.source - 1] : null;
          return (
            <li key={idx} draggable onDragStart={() => (drag.current = idx)} onDragOver={(e) => e.preventDefault()}
              onDrop={() => { if (drag.current !== null) move(drag.current, idx); drag.current = null; }}
              className="flex cursor-grab flex-col items-center gap-1.5 rounded-[var(--radius-control)] border border-line bg-surface-2 p-2 active:cursor-grabbing"
              data-testid="organize-card" data-source={p.source ?? "blank"} data-rotate={p.rotate}>
              <span className="text-[0.78rem] text-muted tabular-nums">{idx + 1}</span>
              <span className="grid h-28 w-full place-items-center overflow-hidden">
                {thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={thumb} alt={name} draggable={false} className="max-h-24 w-auto bg-white shadow-sm transition-transform duration-200" style={{ transform: `rotate(${p.rotate}deg)` }} />
                ) : (
                  <span className="grid h-24 w-[68px] place-items-center bg-white text-[0.75rem] text-muted shadow-sm" style={{ transform: `rotate(${p.rotate}deg)` }}>{p.source ? p.source : "Blank"}</span>
                )}
              </span>
              <span className="text-[0.82rem] font-medium">{name}{p.rotate ? ` · ${p.rotate}°` : ""}</span>
              <span className="flex flex-wrap justify-center gap-0.5">
                <button type="button" className={btn} aria-label={`Move ${name} (position ${idx + 1}) earlier`} disabled={idx === 0} onClick={() => move(idx, idx - 1)}><ArrowLeft size={15} /></button>
                <button type="button" className={btn} aria-label={`Rotate ${name} left`} onClick={() => set(pages.map((x, k) => (k === idx ? { ...x, rotate: turn(x.rotate, -90) } : x)))}><RotateCcw size={15} /></button>
                <button type="button" className={btn} aria-label={`Rotate ${name} right`} data-testid="organize-rotate" onClick={() => set(pages.map((x, k) => (k === idx ? { ...x, rotate: turn(x.rotate, 90) } : x)))}><RotateCw size={15} /></button>
                <button type="button" className={btn} aria-label={`Duplicate ${name}`} data-testid="organize-duplicate" onClick={() => set([...pages.slice(0, idx + 1), { ...p }, ...pages.slice(idx + 1)])}><Copy size={15} /></button>
                <button type="button" className={btn} aria-label={`Insert a blank page after ${name}`} data-testid="organize-blank" onClick={() => set([...pages.slice(0, idx + 1), { source: null, rotate: 0 }, ...pages.slice(idx + 1)])}><FilePlus size={15} /></button>
                <button type="button" className={btn} aria-label={`Delete ${name}`} data-testid="organize-delete" disabled={pages.length === 1} onClick={() => set(pages.filter((_, k) => k !== idx))}><Trash2 size={15} /></button>
                <button type="button" className={btn} aria-label={`Move ${name} (position ${idx + 1}) later`} disabled={idx === pages.length - 1} onClick={() => move(idx, idx + 1)}><ArrowRight size={15} /></button>
              </span>
            </li>
          );
        })}
      </ol>
      {removed.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-[0.9rem] text-muted">
          Deleted:
          {removed.map((n) => (
            <button key={n} type="button" onClick={() => set([...pages, { source: n, rotate: 0 }])} className="rounded-full border border-line px-2.5 py-0.5 text-ink hover:border-line-strong">
              Page {n} · restore
            </button>
          ))}
        </p>
      )}
      {data.pages > data.thumbnails.length && <p className="mt-2 text-[0.88rem] text-muted">Previews show the first {data.thumbnails.length} of {data.pages} pages.</p>}
    </div>
  );
}
