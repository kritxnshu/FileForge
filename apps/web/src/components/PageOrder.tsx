"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, outputPages, uploadPages, type PageIndex } from "@/lib/api";

/** Loads a page index; the result is tagged with its key so a stale one is never shown for a new file. */
function usePages(load: () => Promise<PageIndex>, key: string) {
  const [state, setState] = useState<{ key: string; data?: PageIndex; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    load()
      .then((data) => live && setState({ key, data }))
      .catch((e) => live && setState({ key, error: e instanceof ApiError ? e.message : "Previews aren't available." }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const cur = state?.key === key ? state : null;
  return { data: cur?.data ?? null, error: cur?.error ?? null };
}

/** The order in `value` ("3,1,2") if it names every page once, otherwise 1..n (0-based). */
function parseOrder(value: string | undefined, pages: number): number[] {
  const parsed = (value ?? "").split(",").map((x) => Number(x.trim()) - 1).filter((n) => Number.isInteger(n) && n >= 0 && n < pages);
  return parsed.length === pages && new Set(parsed).size === pages ? parsed : [...Array(pages).keys()];
}

const serialize = (order: number[]) => order.map((n) => n + 1).join(",");

/** Thumbnails of an uploaded PDF that can be dragged (or moved with buttons) into a new order. */
export function PageOrder({ fileId, value, onChange }: { fileId: string; value: string | undefined; onChange: (v: string) => void }) {
  const { data, error } = usePages(() => uploadPages(fileId), fileId);
  const drag = useRef<number | null>(null);
  const order = data ? parseOrder(value, data.pages) : [];

  // the form starts with no value: once the page count is known, fill in the current order
  useEffect(() => {
    if (data && serialize(parseOrder(value, data.pages)) !== value) onChange(serialize(parseOrder(value, data.pages)));
  }, [data, value, onChange]);

  const commit = (next: number[]) => onChange(serialize(next));
  const move = (from: number, to: number) => {
    if (to < 0 || to >= order.length || from === to) return;
    const next = [...order];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    commit(next);
  };

  if (error) return <p className="text-[0.92rem] text-danger">{error}</p>;
  if (!data) return <p className="text-[0.92rem] text-muted">Loading page previews…</p>;
  const tooMany = data.pages > data.thumbnails.length;
  return (
    <div>
      <p className="mb-2 text-[0.9rem] text-muted">Drag pages into the order you want, or use the arrows.</p>
      <ol className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-6" data-testid="page-order">
        {order.map((page, idx) => (
          <li key={page} draggable onDragStart={() => (drag.current = idx)} onDragOver={(e) => e.preventDefault()}
            onDrop={() => { if (drag.current !== null) move(drag.current, idx); drag.current = null; }}
            className="flex cursor-grab flex-col items-center gap-1 rounded-[var(--radius-control)] border border-line bg-surface-2 p-2 active:cursor-grabbing"
            data-testid="page-card" data-page={page + 1}>
            {page < data.thumbnails.length ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={data.thumbnails[page]} alt={`Page ${page + 1}`} className="h-24 w-auto rounded bg-white object-contain shadow-sm" draggable={false} />
            ) : (
              <span className="grid h-24 w-16 place-items-center rounded bg-surface text-[0.8rem] text-muted">{page + 1}</span>
            )}
            <span className="flex items-center gap-1 text-[0.82rem]">
              <button type="button" aria-label={`Move page ${page + 1} earlier`} disabled={idx === 0} onClick={() => move(idx, idx - 1)}
                className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30"><ArrowLeft size={14} /></button>
              <span className="tabular-nums">Page {page + 1}</span>
              <button type="button" aria-label={`Move page ${page + 1} later`} disabled={idx === order.length - 1} onClick={() => move(idx, idx + 1)}
                className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30"><ArrowRight size={14} /></button>
            </span>
          </li>
        ))}
      </ol>
      {tooMany && <p className="mt-2 text-[0.88rem] text-muted">Previews show the first {data.thumbnails.length} of {data.pages} pages.</p>}
    </div>
  );
}

export function PdfThumbs({ jobId, index }: { jobId: string; index: number }) {
  const { data } = usePages(() => outputPages(jobId, index), `${jobId}/${index}`);
  if (!data) return null;
  return (
    <div className="flex w-fit max-w-full gap-2 overflow-x-auto rounded-[var(--radius-control)] border border-line bg-surface-2 p-2" data-testid="pdf-thumbs">
      {data.thumbnails.slice(0, 12).map((u, i) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={u} src={u} alt={`Page ${i + 1}`} className="h-28 w-auto rounded bg-white shadow-sm" />
      ))}
      {data.pages > 12 && <span className="self-center px-2 text-[0.85rem] text-muted">+{data.pages - 12} more</span>}
    </div>
  );
}
