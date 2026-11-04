"use client";

import {
  ChevronLeft, ChevronRight, Circle, Copy, Crop, Eraser, FormInput, Highlighter, ImagePlus, ListChecks, Minus,
  MousePointer2, MoveUpRight, PenLine, Signature as SignatureIcon, Square, SquareCheck, CalendarDays, Trash2, Type,
  Undo2, ChevronDown, type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { pageViewUrl } from "@/lib/api";
import * as M from "./editorModel";
import { SignaturePad, type Signature } from "./SignaturePad";
import { pageSize, usePdfIndex } from "./usePdfIndex";

type Tool = "select" | "text" | "rect" | "ellipse" | "line" | "arrow" | "draw" | "highlight" | "whiteout" | "redact" | "crop"
  | "field-text" | "field-checkbox" | "field-dropdown";

const TOOLS: Record<M.EditorMode, { id: Tool; label: string; Icon: LucideIcon }[]> = {
  edit: [
    { id: "select", label: "Select and move", Icon: MousePointer2 }, { id: "text", label: "Text", Icon: Type },
    { id: "rect", label: "Rectangle", Icon: Square }, { id: "ellipse", label: "Ellipse", Icon: Circle },
    { id: "line", label: "Line", Icon: Minus }, { id: "arrow", label: "Arrow", Icon: MoveUpRight },
    { id: "draw", label: "Draw", Icon: PenLine }, { id: "highlight", label: "Highlight", Icon: Highlighter },
    { id: "whiteout", label: "White-out", Icon: Eraser },
  ],
  sign: [{ id: "select", label: "Select and move", Icon: MousePointer2 }, { id: "text", label: "Text", Icon: Type },
    { id: "draw", label: "Draw", Icon: PenLine }],
  redact: [{ id: "select", label: "Select and move", Icon: MousePointer2 }, { id: "redact", label: "Mark area", Icon: Square }],
  crop: [{ id: "crop", label: "Draw area to keep", Icon: Crop }, { id: "select", label: "Move area", Icon: MousePointer2 }],
  form: [
    { id: "select", label: "Select and move", Icon: MousePointer2 }, { id: "field-text", label: "Text box", Icon: FormInput },
    { id: "field-checkbox", label: "Checkbox", Icon: SquareCheck }, { id: "field-dropdown", label: "Dropdown", Icon: ListChecks },
  ],
};

const TIPS: Record<M.EditorMode, string> = {
  edit: "Choose a tool, then click or drag on the page. Use Select to move things, and drag the corner handle to resize.",
  sign: "Create your signature, then drag it into place and resize it from the corner. Add the date or your initials if needed.",
  redact: "Drag over everything that must go. Each box is blacked out and the content under it is removed from the file.",
  crop: "Drag over the area to keep. It applies to every page you choose below.",
  form: "Pick a field type and drag where the answer should go. Give each field a short, clear name.",
};

const FONTS: [M.Font, string][] = [["helvetica", "Sans"], ["helvetica-bold", "Sans bold"], ["helvetica-italic", "Sans italic"],
  ["times", "Serif"], ["times-bold", "Serif bold"], ["times-italic", "Serif italic"], ["courier", "Mono"], ["courier-bold", "Mono bold"]];

interface Style { ink: string; stroke: string; fill: string | null; size: number; font: M.Font; width: number }
type Gesture = { kind: "move" | "resize" | "draw"; start: [number, number]; orig?: M.Item; index?: number };

const clamp = (n: number) => Math.min(1, Math.max(0, n));
const pct = (n: number) => `${n * 100}%`;

function defaultTool(mode: M.EditorMode): Tool {
  return mode === "redact" ? "redact" : mode === "crop" ? "crop" : mode === "form" ? "field-text" : mode === "sign" ? "select" : "text";
}

function ItemView({ it, scale, selected }: { it: M.Item; scale: number; selected: boolean }) {
  const ring = selected ? "outline outline-2 outline-offset-2 outline-[var(--accent)]" : "";
  const box = M.isBoxy(it) ? { left: pct(it.x), top: pct(it.y), width: pct(it.w), height: pct(it.h) } : {};
  switch (it.type) {
    case "text": {
      const f = M.CSS_FONT[it.font];
      return (
        <div className={`absolute whitespace-pre ${ring}`} style={{ left: pct(it.x), top: pct(it.y), fontSize: it.size * scale, lineHeight: 1.2,
          color: it.color, opacity: it.opacity, fontFamily: f.family, fontWeight: f.weight, fontStyle: f.style }}>
          {it.text || " "}
        </div>
      );
    }
    case "image":
      // eslint-disable-next-line @next/next/no-img-element
      return <img src={it.data} alt="" className={`absolute select-none ${ring}`} style={{ ...box, opacity: it.opacity }} draggable={false} />;
    case "rect": case "ellipse":
      return <div className={`absolute ${ring}`} style={{ ...box, borderRadius: it.type === "ellipse" ? "50%" : 0, opacity: it.opacity,
        border: it.stroke && it.width ? `${Math.max(1, it.width * scale)}px solid ${it.stroke}` : undefined, background: it.fill ?? "transparent" }} />;
    case "highlight":
      return <div className={`absolute ${ring}`} style={{ ...box, background: it.fill ?? "#ffd400", opacity: 0.4 }} />;
    case "whiteout":
      return <div className={`absolute bg-white ${ring}`} style={{ ...box, boxShadow: "0 0 0 1px rgba(0,0,0,0.12)" }} />;
    case "redact":
      return <div className={`absolute bg-black/85 ${ring}`} style={box} data-testid="redact-box" />;
    case "crop":
      return <div className={`absolute outline outline-2 outline-[var(--accent)] ${selected ? "outline-dashed" : ""}`}
        style={{ ...box, boxShadow: "0 0 0 9999px rgba(15,23,28,0.5)" }} data-testid="crop-box" />;
    case "field":
      return (
        <div className={`absolute flex items-center overflow-hidden border-2 border-dashed border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_12%,transparent)] px-1 text-[11px] font-medium text-[#0b5e4f] ${ring}`}
          style={box} data-testid="form-field-box">
          <span className="truncate">{it.kind === "checkbox" ? "☐" : it.kind === "dropdown" ? `▾ ${it.name}` : it.name}</span>
        </div>
      );
    default:
      return null; // lines and drawings are drawn in the SVG layer
  }
}

/** Page editor used by Edit, Sign, Redact, Crop and Create a form. Value is the operation's option value. */
export function PdfEditor({ fileId, mode, value, onChange }: { fileId: string; mode: M.EditorMode; value: unknown; onChange: (v: unknown) => void }) {
  const { data, error } = usePdfIndex(fileId);
  const items = useMemo(() => M.toItems(mode, value), [mode, value]);
  const [page, setPage] = useState(1);
  const [tool, setTool] = useState<Tool>(defaultTool(mode));
  const [sel, setSel] = useState<number | null>(null);
  const [draft, setDraft] = useState<M.Item | null>(null);
  const [drag, setDrag] = useState<{ index: number; item: M.Item } | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [style, setStyle] = useState<Style>({ ink: "#111111", stroke: "#d92d20", fill: null, size: 14, font: "helvetica", width: 2 });
  const [sigOpen, setSigOpen] = useState(false);
  const [signature, setSignature] = useState<Signature | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [widthPx, setWidthPx] = useState(800);
  const overlay = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = overlay.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidthPx(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);

  const pages = data?.pages ?? 0;
  const [pw, ph] = pageSize(data, page);
  const scale = widthPx / pw;
  const H = (1000 * ph) / pw; // SVG viewBox height for a 1000-wide page
  const shown = items.map((it, i) => (drag && drag.index === i ? drag.item : it));
  const onPage = (it: M.Item) => it.type === "crop" || it.page === page;
  const selected = sel !== null ? shown[sel] ?? null : null;

  const commit = (next: M.Item[]) => {
    setHistory((h) => [...h.slice(-49), JSON.stringify(value ?? null)]);
    onChange(M.fromItems(mode, next));
  };
  const undo = () => {
    const prev = history[history.length - 1];
    if (prev === undefined) return;
    setHistory((h) => h.slice(0, -1));
    setSel(null);
    onChange(JSON.parse(prev));
  };
  const update = (patch: Partial<M.Item>) => {
    if (sel === null) return;
    commit(items.map((it, i) => (i === sel ? ({ ...it, ...patch } as M.Item) : it)));
  };
  const remove = (i: number) => {
    commit(items.filter((_, k) => k !== i));
    setSel(null);
  };
  const add = (it: M.Item, select = true) => {
    const next = mode === "crop" ? [...items.filter((x) => x.type !== "crop"), it] : [...items, it];
    commit(next);
    if (select) setSel(next.length - 1);
  };

  const norm = (e: React.PointerEvent): [number, number] => {
    const r = overlay.current!.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  };

  const fieldName = (kind: string) => {
    const used = new Set(items.filter((i): i is M.FieldItem => i.type === "field").map((f) => f.name));
    let n = 1;
    while (used.has(`${kind}_${n}`)) n++;
    return `${kind}_${n}`;
  };

  const startItem = (u: number, v: number): M.Item | null => {
    const base = { page, x: u, y: v, w: 0, h: 0 };
    switch (tool) {
      case "rect": case "ellipse":
        return { type: tool, ...base, stroke: style.stroke, fill: style.fill, width: style.width, opacity: 1 };
      case "highlight": return { type: "highlight", ...base, stroke: null, fill: "#ffd400", width: 0, opacity: 0.4 };
      case "whiteout": return { type: "whiteout", ...base, stroke: null, fill: "#ffffff", width: 0, opacity: 1 };
      case "redact": return { type: "redact", ...base };
      case "crop": return { type: "crop", ...base };
      case "field-text": case "field-checkbox": case "field-dropdown": {
        const kind = tool.slice(6) as M.FieldItem["kind"];
        return { type: "field", kind, ...base, name: fieldName(kind), options: kind === "dropdown" ? ["Option 1", "Option 2"] : [], multiline: false, required: false };
      }
      case "line": case "arrow": return { type: tool, page, x1: u, y1: v, x2: u, y2: v, color: style.stroke, width: style.width, opacity: 1 };
      case "draw": return { type: "path", page, points: [[u, v]], color: mode === "sign" ? "#111111" : style.stroke, width: mode === "sign" ? 2 : style.width + 1, opacity: 1 };
      default: return null;
    }
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const [u, v] = norm(e);
    overlay.current!.setPointerCapture(e.pointerId);
    overlay.current!.focus();
    if ((e.target as HTMLElement).dataset.handle && sel !== null) {
      gesture.current = { kind: "resize", start: [u, v], orig: items[sel], index: sel };
      return;
    }
    if (tool === "select") {
      for (let i = shown.length - 1; i >= 0; i--) {
        if (onPage(shown[i]) && M.hit(shown[i], u, v, pw, ph)) {
          setSel(i);
          gesture.current = { kind: "move", start: [u, v], orig: items[i], index: i };
          return;
        }
      }
      setSel(null);
      return;
    }
    if (tool === "text") {
      add({ type: "text", page, x: u, y: v, text: "Text", font: style.font, size: style.size, color: style.ink, opacity: 1 });
      setTool("select");
      setTimeout(() => textRef.current?.select(), 0);
      return;
    }
    const it = startItem(u, v);
    if (it) {
      setDraft(it);
      gesture.current = { kind: "draw", start: [u, v] };
    }
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g) return;
    const [u, v] = norm(e);
    if (g.kind === "move" && g.orig) setDrag({ index: g.index!, item: M.moved(g.orig, u - g.start[0], v - g.start[1]) });
    else if (g.kind === "resize" && g.orig && M.isBoxy(g.orig)) {
      const o = g.orig;
      const w = Math.max(0.01, u - o.x);
      const h = o.type === "image" ? (w * o.h) / o.w : Math.max(0.006, v - o.y);
      setDrag({ index: g.index!, item: { ...o, w, h } });
    } else if (g.kind === "draw" && draft) {
      if (draft.type === "path") {
        const last = draft.points[draft.points.length - 1];
        if (Math.hypot(u - last[0], v - last[1]) > 0.002) setDraft({ ...draft, points: [...draft.points, [u, v]] });
      } else if (draft.type === "line" || draft.type === "arrow") setDraft({ ...draft, x2: u, y2: v });
      else if (M.isBoxy(draft)) {
        const [su, sv] = g.start;
        setDraft({ ...draft, x: Math.min(su, u), y: Math.min(sv, v), w: Math.abs(u - su), h: Math.abs(v - sv) } as M.Item);
      }
    }
  };

  const onPointerUp = () => {
    const g = gesture.current;
    gesture.current = null;
    if (drag) {
      commit(items.map((it, i) => (i === drag.index ? drag.item : it)));
      setDrag(null);
      return;
    }
    if (!g || !draft) return;
    let it: M.Item | null = draft;
    if (it.type === "path" && it.points.length < 2) it = null;
    else if ((it.type === "line" || it.type === "arrow") && Math.hypot(it.x2 - it.x1, it.y2 - it.y1) < 0.01) it = null;
    else if (M.isBoxy(it) && (it.w < 0.008 || it.h < 0.006)) {
      // a click: fields get a sensible default size, everything else needs a drag
      if (it.type === "field") {
        const aspect = pw / ph;
        it = it.kind === "checkbox" ? { ...it, w: 0.03, h: 0.03 * aspect } : { ...it, w: it.kind === "dropdown" ? 0.25 : 0.32, h: 0.03 };
      } else it = null;
    }
    setDraft(null);
    if (it) add(it, mode !== "edit" || it.type !== "path");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      undo();
      return;
    }
    if (sel === null || (e.target as HTMLElement).closest("input,textarea,select")) return;
    const step = e.shiftKey ? 0.02 : 0.004;
    const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (d[e.key]) {
      e.preventDefault();
      commit(items.map((it, i) => (i === sel ? M.moved(it, ...d[e.key]) : it)));
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove(sel);
    } else if (e.key === "Escape") setSel(null);
  };

  const addImage = async (file: File) => {
    const img = await M.imageFileToData(file);
    const w = 0.3;
    add({ type: "image", page, x: 0.35, y: 0.35, w, h: (w * img.height * pw) / (img.width * ph), data: img.data, opacity: 1 });
    setTool("select");
  };
  const placeSignature = (s: Signature) => {
    const w = 0.28;
    add({ type: "image", page, x: 0.55, y: 0.78, w, h: (w * s.height * pw) / (s.width * ph), data: s.data, opacity: 1 });
    setTool("select");
  };

  if (error) {
    return <p role="alert" className="rounded-[var(--radius-control)] bg-danger-soft p-3">{error}</p>;
  }
  if (!data) return <p className="text-muted">Loading pages…</p>;

  const lineLike = [...shown.map((it, i) => ({ it, i })), ...(draft ? [{ it: draft, i: -1 }] : [])]
    .filter(({ it }) => onPage(it) && (it.type === "line" || it.type === "arrow" || it.type === "path"));
  const listed = shown.map((it, i) => ({ it, i }));
  const sw = (w: number) => (w * 1000) / pw;

  return (
    <div className="flex flex-col gap-4" onKeyDown={onKeyDown} data-testid="pdf-editor" data-mode={mode}>
      <p className="text-[0.92rem] text-muted">{TIPS[mode]}</p>

      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Editing tools">
        {TOOLS[mode].map(({ id, label: l, Icon }) => (
          <button key={id} type="button" aria-pressed={tool === id} title={l} onClick={() => { setTool(id); if (id !== "select") setSel(null); }}
            data-testid={`tool-${id}`}
            className={`flex items-center gap-1.5 rounded-[var(--radius-control)] border px-3 py-2 text-[0.9rem] ${tool === id ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:border-line-strong"}`}>
            <Icon size={16} aria-hidden="true" /><span className={mode === "edit" ? "sr-only sm:not-sr-only" : ""}>{l}</span>
          </button>
        ))}
        {mode === "edit" && (
          <button type="button" onClick={() => imageInput.current?.click()} data-testid="tool-image"
            className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-[0.9rem] hover:border-line-strong">
            <ImagePlus size={16} aria-hidden="true" /><span className="sr-only sm:not-sr-only">Image</span>
          </button>
        )}
        {mode === "sign" && (
          <>
            <button type="button" onClick={() => (signature ? placeSignature(signature) : setSigOpen(true))} data-testid="sign-place"
              className="flex items-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3.5 py-2 font-semibold text-accent-ink hover:opacity-90">
              <SignatureIcon size={16} aria-hidden="true" /> {signature ? "Place signature again" : "Create signature"}
            </button>
            {signature && <button type="button" onClick={() => setSigOpen(true)} className="rounded-[var(--radius-control)] border border-line px-3 py-2 text-[0.9rem] hover:border-line-strong">New signature</button>}
            <button type="button" data-testid="sign-date" onClick={() => add({ type: "text", page, x: 0.55, y: 0.88, text: new Date().toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }), font: "helvetica", size: 11, color: "#111111", opacity: 1 })}
              className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line px-3 py-2 text-[0.9rem] hover:border-line-strong">
              <CalendarDays size={16} aria-hidden="true" /> Add date
            </button>
          </>
        )}
        <button type="button" onClick={undo} disabled={!history.length} title="Undo (Ctrl+Z)"
          className="ml-auto flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line px-3 py-2 text-[0.9rem] hover:border-line-strong disabled:opacity-40">
          <Undo2 size={16} aria-hidden="true" /> Undo
        </button>
        <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" tabIndex={-1} aria-hidden="true" data-testid="editor-image-input"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void addImage(f); e.target.value = ""; }} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
        {/* page */}
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-2 text-[0.92rem]">
            <button type="button" onClick={() => { setPage((p) => Math.max(1, p - 1)); setSel(null); }} disabled={page <= 1} aria-label="Previous page"
              className="rounded-md border border-line p-1.5 hover:border-line-strong disabled:opacity-30"><ChevronLeft size={16} /></button>
            <span className="tabular-nums" aria-live="polite">Page {page} of {pages}</span>
            <button type="button" onClick={() => { setPage((p) => Math.min(pages, p + 1)); setSel(null); }} disabled={page >= pages} aria-label="Next page"
              data-testid="editor-next-page" className="rounded-md border border-line p-1.5 hover:border-line-strong disabled:opacity-30"><ChevronRight size={16} /></button>
          </div>
          <div className="relative mx-auto w-full max-w-[900px] overflow-hidden rounded-md bg-white shadow-sm ring-1 ring-[var(--line)]" style={{ aspectRatio: `${pw} / ${ph}` }}>
            {data.thumbnails[page - 1] && loaded !== `${fileId}/${page}` && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={data.thumbnails[page - 1]} alt="" aria-hidden="true" className="absolute inset-0 h-full w-full object-contain opacity-60 blur-[1px]" />
            )}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img key={`${fileId}/${page}`} src={pageViewUrl(fileId, page - 1)} alt={`Page ${page}`} draggable={false}
              onLoad={() => setLoaded(`${fileId}/${page}`)} className="absolute inset-0 h-full w-full select-none object-contain" data-testid="editor-page" />
            <div
              ref={overlay}
              tabIndex={0}
              role="application"
              aria-label={`Page ${page}. ${TIPS[mode]} With something selected, arrow keys move it and Delete removes it.`}
              className={`absolute inset-0 touch-none outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] ${tool === "select" ? "cursor-default" : "cursor-crosshair"}`}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              data-testid="editor-overlay"
            >
              <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  {lineLike.filter(({ it }) => it.type === "arrow").map(({ it, i }) => (
                    <marker key={i} id={`ah-${i}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
                      <path d="M0,0 L10,5 L0,10 z" fill={(it as M.LineItem).color} />
                    </marker>
                  ))}
                </defs>
                {lineLike.map(({ it, i }) => it.type === "path" ? (
                  <polyline key={i} points={it.points.map(([a, b]) => `${a * 1000},${b * H}`).join(" ")} fill="none" stroke={it.color}
                    strokeWidth={sw(it.width)} strokeLinecap="round" strokeLinejoin="round" opacity={it.opacity}
                    className={sel === i ? "[filter:drop-shadow(0_0_2px_var(--accent))]" : ""} />
                ) : it.type === "line" || it.type === "arrow" ? (
                  <line key={i} x1={it.x1 * 1000} y1={it.y1 * H} x2={it.x2 * 1000} y2={it.y2 * H} stroke={it.color} strokeWidth={sw(it.width)}
                    strokeLinecap="round" opacity={it.opacity} markerEnd={it.type === "arrow" ? `url(#ah-${i})` : undefined}
                    className={sel === i ? "[filter:drop-shadow(0_0_2px_var(--accent))]" : ""} />
                ) : null)}
              </svg>
              {shown.map((it, i) => onPage(it) && <ItemView key={i} it={it} scale={scale} selected={sel === i} />)}
              {draft && onPage(draft) && <ItemView it={draft} scale={scale} selected={false} />}
              {selected && onPage(selected) && M.isBoxy(selected) && (
                <span data-handle="se" aria-hidden="true" className="absolute z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize rounded-sm border-2 border-white bg-accent shadow"
                  style={{ left: pct(selected.x + selected.w), top: pct(selected.y + selected.h) }} data-testid="resize-handle" />
              )}
            </div>
          </div>
          {pages > 1 && (
            <ol className="mt-3 flex gap-2 overflow-x-auto pb-1" aria-label="Pages">
              {Array.from({ length: pages }, (_, k) => k + 1).map((n) => {
                const count = items.filter((it) => it.type !== "crop" && it.page === n).length;
                return (
                  <li key={n} className="shrink-0">
                    <button type="button" onClick={() => { setPage(n); setSel(null); }} aria-current={n === page ? "page" : undefined} aria-label={`Page ${n}${count ? `, ${count} change${count === 1 ? "" : "s"}` : ""}`}
                      className={`relative flex flex-col items-center gap-1 rounded-md border p-1 text-[0.78rem] ${n === page ? "border-accent" : "border-line hover:border-line-strong"}`}>
                      {data.thumbnails[n - 1] ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={data.thumbnails[n - 1]} alt="" className="h-16 w-auto bg-white" />
                      ) : <span className="grid h-16 w-12 place-items-center bg-surface-2">{n}</span>}
                      <span className="tabular-nums">{n}</span>
                      {count > 0 && <span className="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[0.7rem] font-semibold text-accent-ink">{count}</span>}
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
        </div>

        {/* properties and list */}
        <aside className="flex flex-col gap-4 text-[0.92rem]" aria-label="Selected item and changes">
          {selected ? (
            <Properties it={selected} pw={pw} ph={ph} textRef={textRef}
              onChange={(patch) => {
                update(patch);
                const p = patch as Partial<{ color: string; size: number; font: M.Font; stroke: string | null; fill: string | null; width: number }>;
                setStyle((s) => ({ ...s, ...(p.color && selected.type === "text" ? { ink: p.color } : {}), ...(p.color && selected.type !== "text" ? { stroke: p.color } : {}),
                  ...(p.size ? { size: p.size } : {}), ...(p.font ? { font: p.font } : {}), ...(p.stroke ? { stroke: p.stroke } : {}),
                  ...("fill" in p && selected.type !== "highlight" && selected.type !== "whiteout" ? { fill: p.fill ?? null } : {}), ...(p.width ? { width: p.width } : {}) }));
              }}
              onDuplicate={mode === "crop" ? undefined : () => add(M.moved(selected, 0.02, 0.02))}
              onDelete={() => remove(sel!)} />
          ) : (
            mode === "edit" && (
              <div className="rounded-[var(--radius-control)] border border-line p-3">
                <p className="mb-2 font-medium">New items</p>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-1.5">Text <input type="color" value={style.ink} onChange={(e) => setStyle({ ...style, ink: e.target.value })} className="h-7 w-9" /></label>
                  <label className="flex items-center gap-1.5">Shapes <input type="color" value={style.stroke} onChange={(e) => setStyle({ ...style, stroke: e.target.value })} className="h-7 w-9" /></label>
                  <label className="flex items-center gap-1.5">Size <input type="number" min={6} max={96} value={style.size} onChange={(e) => setStyle({ ...style, size: Number(e.target.value) || 14 })} className="w-16 rounded border border-line bg-surface px-1.5 py-1" /></label>
                </div>
              </div>
            )
          )}
          <div>
            <p className="mb-2 font-medium">{mode === "redact" ? "Redactions" : mode === "form" ? "Fields" : mode === "crop" ? "Area" : "Your changes"} ({listed.length})</p>
            {listed.length === 0 ? (
              <p className="text-muted">{mode === "crop" ? "No area yet." : "Nothing added yet."}</p>
            ) : (
              <ol className="flex max-h-72 flex-col divide-y divide-line overflow-y-auto rounded-[var(--radius-control)] border border-line" data-testid="editor-items">
                {listed.map(({ it, i }) => (
                  <li key={i} className={`flex items-center justify-between gap-2 px-2.5 py-1.5 ${sel === i ? "bg-accent-soft" : ""}`}>
                    <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => { if (it.type !== "crop") setPage(it.page); setSel(i); setTool("select"); }}>
                      {it.type !== "crop" && <span className="text-muted">p.{it.page} · </span>}{M.label(it)}
                    </button>
                    <button type="button" aria-label={`Remove ${M.label(it)}`} onClick={() => remove(i)} className="rounded p-1 text-muted hover:text-danger"><Trash2 size={15} /></button>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </aside>
      </div>
      {mode === "sign" && <SignaturePad open={sigOpen} onClose={() => setSigOpen(false)} onDone={(s) => { setSignature(s); setSigOpen(false); placeSignature(s); }} />}
    </div>
  );
}

function Properties({ it, pw, ph, textRef, onChange, onDuplicate, onDelete }: {
  it: M.Item; pw: number; ph: number; textRef: React.RefObject<HTMLTextAreaElement | null>;
  onChange: (p: Partial<M.Item>) => void; onDuplicate?: () => void; onDelete: () => void;
}) {
  const input = "rounded border border-line bg-surface px-2 py-1";
  const mm = (n: number) => `${Math.round((n * 25.4) / 72)} mm`;
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-control)] border border-line p-3" data-testid="editor-properties">
      <p className="font-medium">{M.label(it)}</p>
      {it.type === "text" && (
        <>
          <label className="flex flex-col gap-1">Text
            <textarea ref={textRef} value={it.text} rows={3} onChange={(e) => onChange({ text: e.target.value })} className={input} data-testid="text-input" />
          </label>
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-1.5">Font
              <span className="relative">
                <select value={it.font} onChange={(e) => onChange({ font: e.target.value as M.Font })} className={`${input} appearance-none pr-6`}>
                  {FONTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <ChevronDown size={14} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2" aria-hidden="true" />
              </span>
            </label>
            <label className="flex items-center gap-1.5">Size <input type="number" min={4} max={300} value={it.size} onChange={(e) => onChange({ size: Math.min(300, Math.max(4, Number(e.target.value) || 12)) })} className={`${input} w-16`} /></label>
            <label className="flex items-center gap-1.5">Colour <input type="color" value={it.color} onChange={(e) => onChange({ color: e.target.value })} className="h-7 w-9" /></label>
          </div>
        </>
      )}
      {(it.type === "rect" || it.type === "ellipse") && (
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-1.5">Outline <input type="color" value={it.stroke ?? "#d92d20"} onChange={(e) => onChange({ stroke: e.target.value })} className="h-7 w-9" /></label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!it.fill} onChange={(e) => onChange({ fill: e.target.checked ? it.stroke ?? "#d92d20" : null })} /> Fill</label>
          {it.fill && <label className="flex items-center gap-1.5">Fill colour <input type="color" value={it.fill} onChange={(e) => onChange({ fill: e.target.value })} className="h-7 w-9" /></label>}
          <label className="flex items-center gap-1.5">Thickness <input type="number" min={0} max={40} value={it.width} onChange={(e) => onChange({ width: Number(e.target.value) })} className={`${input} w-14`} /></label>
        </div>
      )}
      {it.type === "highlight" && <label className="flex items-center gap-1.5">Colour <input type="color" value={it.fill ?? "#ffd400"} onChange={(e) => onChange({ fill: e.target.value })} className="h-7 w-9" /></label>}
      {(it.type === "line" || it.type === "arrow" || it.type === "path") && (
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-1.5">Colour <input type="color" value={it.color} onChange={(e) => onChange({ color: e.target.value })} className="h-7 w-9" /></label>
          <label className="flex items-center gap-1.5">Thickness <input type="number" min={1} max={40} value={it.width} onChange={(e) => onChange({ width: Math.max(1, Number(e.target.value)) })} className={`${input} w-14`} /></label>
        </div>
      )}
      {it.type === "image" && (
        <label className="flex items-center gap-2">Opacity
          <input type="range" min={0.1} max={1} step={0.05} value={it.opacity} onChange={(e) => onChange({ opacity: Number(e.target.value) })} className="flex-1 accent-[var(--accent)]" />
        </label>
      )}
      {(it.type === "crop" || it.type === "redact") && <p className="text-muted tabular-nums">{mm(it.w * pw)} × {mm(it.h * ph)}</p>}
      {it.type === "field" && (
        <>
          <label className="flex flex-col gap-1">Field name
            <input value={it.name} maxLength={64} onChange={(e) => onChange({ name: e.target.value.replace(/[^A-Za-z0-9_\-. ]/g, "") })} className={input} data-testid="field-name" />
          </label>
          {it.kind === "dropdown" && (
            <label className="flex flex-col gap-1">Choices (one per line)
              <textarea rows={4} value={it.options.join("\n")} onChange={(e) => onChange({ options: e.target.value.split("\n").slice(0, 200) })} className={input} />
            </label>
          )}
          {it.kind === "text" && <label className="flex items-center gap-1.5"><input type="checkbox" checked={it.multiline} onChange={(e) => onChange({ multiline: e.target.checked })} /> Several lines</label>}
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={it.required} onChange={(e) => onChange({ required: e.target.checked })} /> Required</label>
        </>
      )}
      <div className="flex gap-2">
        {onDuplicate && (
          <button type="button" onClick={onDuplicate} className="flex items-center gap-1 rounded border border-line px-2.5 py-1.5 hover:border-line-strong"><Copy size={14} aria-hidden="true" /> Duplicate</button>
        )}
        <button type="button" onClick={onDelete} className="flex items-center gap-1 rounded border border-line px-2.5 py-1.5 text-danger hover:border-line-strong" data-testid="editor-delete"><Trash2 size={14} aria-hidden="true" /> Remove</button>
      </div>
    </div>
  );
}
