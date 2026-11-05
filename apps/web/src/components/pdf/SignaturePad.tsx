"use client";

import { Keyboard, PenLine, Upload } from "lucide-react";
import { Dancing_Script } from "next/font/google";
import { useEffect, useRef, useState } from "react";

const script = Dancing_Script({ subsets: ["latin"], weight: ["600"] });

export interface Signature {
  data: string; // PNG data URL, transparent background
  width: number;
  height: number;
}

const INKS = [{ id: "#111111", label: "Black" }, { id: "#1d3f8f", label: "Blue" }];

/** Crop a canvas to its non-transparent pixels and return a PNG signature. */
function trimmed(src: HTMLCanvasElement): Signature | null {
  const ctx = src.getContext("2d")!;
  const { width, height } = src;
  const px = ctx.getImageData(0, 0, width, height).data;
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (px[(y * width + x) * 4 + 3] > 8) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return null;
  const pad = 6;
  x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad);
  x1 = Math.min(width - 1, x1 + pad); y1 = Math.min(height - 1, y1 + pad);
  const out = document.createElement("canvas");
  out.width = x1 - x0 + 1;
  out.height = y1 - y0 + 1;
  out.getContext("2d")!.drawImage(src, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return { data: out.toDataURL("image/png"), width: out.width, height: out.height };
}

function DrawTab({ ink, onReady }: { ink: string; onReady: (c: HTMLCanvasElement | null) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [empty, setEmpty] = useState(true);

  useEffect(() => {
    const c = canvas.current!;
    const ratio = window.devicePixelRatio || 1;
    c.width = c.clientWidth * ratio;
    c.height = c.clientHeight * ratio;
    const ctx = c.getContext("2d")!;
    ctx.scale(ratio, ratio);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    onReady(null);
  }, [onReady]);

  const pos = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  return (
    <div>
      <canvas
        ref={canvas}
        className="h-48 w-full touch-none rounded-[var(--radius-control)] border border-line bg-white"
        aria-label="Signature drawing area. Draw with a mouse, pen or finger."
        data-testid="signature-canvas"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          last.current = pos(e);
        }}
        onPointerMove={(e) => {
          if (!last.current) return;
          const p = pos(e);
          const ctx = canvas.current!.getContext("2d")!;
          ctx.strokeStyle = ink;
          ctx.lineWidth = e.pressure && e.pointerType === "pen" ? 1.5 + e.pressure * 3 : 2.6;
          ctx.beginPath();
          ctx.moveTo(last.current.x, last.current.y);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
          last.current = p;
          if (empty) setEmpty(false);
          onReady(canvas.current);
        }}
        onPointerUp={() => (last.current = null)}
      />
      <div className="mt-2 flex items-center justify-between text-[0.9rem] text-muted">
        <span>{empty ? "Sign above." : "Looks good? Use it below."}</span>
        <button type="button" className="font-medium text-ink underline underline-offset-4" onClick={() => {
          const c = canvas.current!;
          c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
          setEmpty(true);
          onReady(null);
        }}>Clear</button>
      </div>
    </div>
  );
}

function renderTyped(name: string, ink: string): HTMLCanvasElement {
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d")!;
  const font = `600 96px ${script.style.fontFamily}`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(name).width) + 40;
  c.width = w;
  c.height = 150;
  const g = c.getContext("2d")!;
  g.font = font;
  g.fillStyle = ink;
  g.textBaseline = "middle";
  g.fillText(name, 20, 78);
  return c;
}

async function uploadedSignature(file: File): Promise<HTMLCanvasElement> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error("image"));
      i.src = url;
    });
    const scale = Math.min(1, 1200 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * scale);
    c.height = Math.round(img.height * scale);
    const ctx = c.getContext("2d")!;
    ctx.drawImage(img, 0, 0, c.width, c.height);
    // paper → transparent, so the signature sits on the page like ink
    const d = ctx.getImageData(0, 0, c.width, c.height);
    for (let i = 0; i < d.data.length; i += 4) {
      const lum = 0.299 * d.data[i] + 0.587 * d.data[i + 1] + 0.114 * d.data[i + 2];
      if (lum > 215) d.data[i + 3] = 0;
    }
    ctx.putImageData(d, 0, 0);
    return c;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Create a signature by drawing, typing or uploading. */
export function SignaturePad({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (s: Signature) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<"draw" | "type" | "upload">("draw");
  const [ink, setInk] = useState(INKS[0].id);
  const [name, setName] = useState("");
  const [drawn, setDrawn] = useState<HTMLCanvasElement | null>(null);
  const [uploaded, setUploaded] = useState<HTMLCanvasElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const use = async () => {
    setError(null);
    let c: HTMLCanvasElement | null = null;
    if (tab === "draw") c = drawn;
    else if (tab === "type") {
      if (!name.trim()) return setError("Type your name first.");
      await document.fonts.load(`600 96px ${script.style.fontFamily}`);
      c = renderTyped(name.trim(), ink);
    } else c = uploaded;
    const sig = c && trimmed(c);
    if (!sig) return setError(tab === "upload" ? "Choose an image of your signature." : "Draw your signature first.");
    onDone(sig);
  };

  const tabs = [
    { id: "draw" as const, label: "Draw", Icon: PenLine },
    { id: "type" as const, label: "Type", Icon: Keyboard },
    { id: "upload" as const, label: "Upload", Icon: Upload },
  ];
  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="sig-h"
      className="m-auto w-[min(640px,calc(100vw-32px))] rounded-[var(--radius-panel)] border border-line bg-surface p-0 text-ink backdrop:bg-black/50">
      <div className="p-5 sm:p-6" data-testid="signature-pad">
        <h2 id="sig-h" className="font-display text-xl font-semibold">Create your signature</h2>
        <div role="tablist" aria-label="How to sign" className="mt-4 flex gap-1 rounded-full border border-line bg-surface-2 p-1">
          {tabs.map(({ id, label, Icon }) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-[0.95rem] ${tab === id ? "bg-surface font-medium shadow-sm" : "text-muted"}`}>
              <Icon size={16} aria-hidden="true" /> {label}
            </button>
          ))}
        </div>
        <fieldset className="mt-4 flex items-center gap-3 text-[0.92rem]">
          <legend className="sr-only">Ink colour</legend>
          <span className="text-muted">Ink</span>
          {INKS.map((c) => (
            <label key={c.id} className="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="ink" checked={ink === c.id} onChange={() => setInk(c.id)} className="accent-[var(--accent)]" />
              <span className="inline-block h-4 w-4 rounded-full border border-line" style={{ background: c.id }} aria-hidden="true" />
              {c.label}
            </label>
          ))}
        </fieldset>
        <div className="mt-4" role="tabpanel">
          {tab === "draw" && <DrawTab ink={ink} onReady={setDrawn} />}
          {tab === "type" && (
            <div>
              <label className="block">
                <span className="mb-1.5 block font-medium">Your name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} data-testid="signature-name"
                  className="w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2" />
              </label>
              <div className="mt-3 grid h-32 place-items-center overflow-hidden rounded-[var(--radius-control)] border border-line bg-white px-4" aria-hidden="true">
                <span className={script.className} style={{ fontSize: 56, color: ink, fontWeight: 600 }}>{name || "Your name"}</span>
              </div>
            </div>
          )}
          {tab === "upload" && (
            <div>
              <label className="flex cursor-pointer flex-col items-center gap-2 rounded-[var(--radius-control)] border-2 border-dashed border-line-strong p-6 text-center text-muted hover:text-ink">
                <Upload size={22} aria-hidden="true" />
                <span className="font-medium">Choose a photo or scan of your signature</span>
                <span className="text-[0.88rem]">White paper is made transparent automatically.</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    try {
                      setUploaded(await uploadedSignature(f));
                      setError(null);
                    } catch {
                      setError("That image couldn't be read.");
                    }
                  }} />
              </label>
              {uploaded && <p className="mt-2 text-[0.9rem] text-muted">Image ready.</p>}
            </div>
          )}
        </div>
        {error && <p role="alert" className="mt-3 text-[0.92rem] text-danger">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-[var(--radius-control)] border border-line px-4 py-2 font-medium hover:border-line-strong">Cancel</button>
          <button type="button" onClick={() => void use()} data-testid="signature-use"
            className="rounded-[var(--radius-control)] bg-accent px-4 py-2 font-semibold text-accent-ink hover:opacity-90">Use signature</button>
        </div>
      </div>
    </dialog>
  );
}
