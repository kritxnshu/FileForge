"use client";

import { AlertTriangle, Download, Info, RotateCcw, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { outputTable, outputUrl, uploadRawUrl, type Job, type JobOutput, type TablePreview } from "@/lib/api";
import { fmtShort, formatBytes, sizeDelta } from "@/lib/caps";
import { PdfThumbs } from "./PageOrder";
import { useCaps } from "./providers";

const BROWSER_IMAGES = new Set(["png", "jpg", "gif", "webp", "avif", "bmp", "ico", "svg"]);
const AUDIO = new Set(["mp3", "wav", "aac", "flac", "ogg", "m4a", "opus"]);
const VIDEO = new Set(["mp4", "webm", "mov"]);
const TEXT = new Set(["json", "xml", "yaml", "toml", "txt", "md", "html", "csv", "tsv"]);
const SHEETS = new Set(["xlsx", "xls", "ods"]);

export interface RunView {
  jobId: string;
  fileNames: string[];
  sourceFormat: string;
  sourceFileId: string | null;
  targetLabel: string;
  /** A tool (compress, reorder pages…) rather than a format conversion: label it "Reorder pages", not "to …". */
  transform?: boolean;
  job: Job | null;
}

function BeforeAfter({ before, after, alt }: { before: string; after: string; alt: string }) {
  const [pos, setPos] = useState(50);
  return (
    <figure className="overflow-hidden rounded-[var(--radius-control)] border border-line bg-[repeating-conic-gradient(var(--surface-2)_0_25%,var(--surface)_0_50%)] bg-[length:16px_16px]">
      <div className="relative grid max-h-80 place-items-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={after} alt={`${alt}, converted`} className="max-h-80 w-auto object-contain" />
        <div className="absolute inset-0 grid place-items-center" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={before} alt="" className="max-h-80 w-auto object-contain" />
        </div>
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-accent" style={{ left: `${pos}%` }} aria-hidden="true" />
      </div>
      <figcaption className="flex items-center gap-3 border-t border-line bg-surface px-3 py-2 text-[0.85rem] text-muted">
        <span>Before</span>
        <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))}
          aria-label="Compare before and after" className="flex-1 accent-[var(--accent)]" />
        <span>After</span>
      </figcaption>
    </figure>
  );
}

function TextPreview({ url, format }: { url: string; format: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(url, { signal: ctl.signal })
      .then(async (r) => {
        const reader = r.body?.getReader();
        if (!reader) return setText(await r.text());
        let got = "";
        const dec = new TextDecoder();
        while (got.length < 64_000) {
          const { done, value } = await reader.read();
          if (done) break;
          got += dec.decode(value, { stream: true });
        }
        void reader.cancel();
        setText(got);
      })
      .catch(() => {});
    return () => ctl.abort();
  }, [url]);
  if (text === null) return null;
  if (format === "csv" || format === "tsv") {
    const delim = format === "tsv" ? "\t" : ",";
    return <RowsTable rows={parseCsv(text, delim).slice(0, 101)} />;
  }
  // Rendered as text by React (escaped) — converted HTML/SVG is never rendered on this origin.
  return (
    <pre className="max-h-80 overflow-auto rounded-[var(--radius-control)] border border-line bg-surface-2 p-3 text-[0.82rem] leading-relaxed whitespace-pre-wrap break-words">
      {text.length >= 64_000 ? text.slice(0, 64_000) + "\n…" : text}
    </pre>
  );
}

/** First row as the header; cells are text (React escapes them). */
function RowsTable({ rows, caption }: { rows: string[][]; caption?: string }) {
  return (
    <div className="max-h-80 overflow-auto rounded-[var(--radius-control)] border border-line" data-testid="table-preview">
      <table className="w-full text-left text-[0.85rem]">
        {caption && <caption className="border-b border-line bg-surface px-3 py-1.5 text-left text-muted">{caption}</caption>}
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i === 0 ? "bg-surface-2 font-medium" : "border-t border-line"}>
              {r.map((c, j) => <td key={j} className="whitespace-nowrap px-3 py-1.5">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SheetPreview({ jobId, index }: { jobId: string; index: number }) {
  const key = `${jobId}/${index}`;
  const [state, setState] = useState<{ key: string; data: TablePreview | null } | null>(null);
  useEffect(() => {
    let live = true;
    outputTable(jobId, index)
      .then((data) => live && setState({ key, data }))
      .catch(() => live && setState({ key, data: null }));
    return () => {
      live = false;
    };
  }, [jobId, index, key]);
  const data = state?.key === key ? state.data : null;
  if (!data || !data.rows.length) return null;
  const caption = `${data.sheet ? `“${data.sheet}”, ` : ""}${data.truncated ? `first ${data.rows.length - 1} rows` : `${data.rows.length - 1} rows`}`;
  return <RowsTable rows={data.rows} caption={caption} />;
}

function parseCsv(text: string, d: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let q = false;
  for (let i = 0; i < text.length && rows.length < 101; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === d) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

export function Preview({ run, output }: { run: RunView; output: JobOutput }) {
  const url = outputUrl(run.jobId, output.index, true);
  const f = output.format;
  if (BROWSER_IMAGES.has(f)) {
    if (run.sourceFileId && BROWSER_IMAGES.has(run.sourceFormat) && run.sourceFormat !== "svg" && run.job?.outputs.length === 1) {
      return <BeforeAfter before={uploadRawUrl(run.sourceFileId)} after={url} alt={output.name} />;
    }
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt={output.name} className="max-h-64 rounded-[var(--radius-control)] border border-line bg-surface-2 object-contain" />
    );
  }
  if (AUDIO.has(f)) return <audio controls preload="metadata" src={url} className="w-full" />;
  if (VIDEO.has(f)) return <video controls preload="metadata" src={url} className="max-h-80 w-full rounded-[var(--radius-control)] bg-black" />;
  if (TEXT.has(f)) return <TextPreview url={url} format={f} />;
  if (f === "pdf") return <PdfThumbs jobId={run.jobId} index={output.index} />;
  if (SHEETS.has(f)) return <SheetPreview jobId={run.jobId} index={output.index} />;
  return null;
}

function Progress({ job }: { job: Job | null }) {
  const state = job?.state ?? "queued";
  const p = job?.progress;
  const stage = job?.stage ?? "Queued";
  if (state === "succeeded" || state === "failed" || state === "cancelled" || state === "expired") return null;
  const pct = p && p.total ? Math.min(100, Math.round((p.done / p.total) * 100)) : null;
  return (
    <div className="mt-3">
      <div className="flex justify-between font-mono text-[11px] text-muted">
        <span data-testid="job-stage">{stage}</span>
        {p && <span className="tabular-nums">{Number.isInteger(p.done) && p.total > 1 ? `${p.done} of ${p.total}` : `${pct}%`}</span>}
      </div>
      <div
        role="progressbar"
        aria-label="Conversion progress"
        aria-valuetext={pct !== null ? `${pct}%` : stage}
        {...(pct !== null ? { "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 } : {})}
        className={`mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2 ${pct === null ? "indeterminate" : ""}`}
      >
        {pct !== null && <div className="h-full origin-left rounded-full bg-accent transition-transform duration-300 ease-out" style={{ transform: `scaleX(${pct / 100})` }} />}
      </div>
    </div>
  );
}

const STATUS: Record<string, { text: string; cls: string; pulse?: boolean }> = {
  queued: { text: "Queued", cls: "bg-surface-2 text-muted", pulse: true },
  running: { text: "Processing", cls: "bg-warn-soft text-warn", pulse: true },
  succeeded: { text: "Complete", cls: "bg-ok-soft text-ok" },
  failed: { text: "Failed", cls: "bg-danger-soft text-danger" },
  cancelled: { text: "Cancelled", cls: "bg-surface-2 text-muted" },
  expired: { text: "Expired", cls: "bg-surface-2 text-muted" },
};

export function JobCard({ run, onCancel, onRetry }: { run: RunView; onCancel: () => void; onRetry: () => void }) {
  const { caps } = useCaps();
  const j = run.job;
  const state = j?.state ?? "queued";
  const title = run.fileNames.length > 1 ? `${run.fileNames.length} files` : run.fileNames[0];
  const src = caps ? fmtShort(caps, run.sourceFormat) : run.sourceFormat.toUpperCase();
  const status = STATUS[state] ?? STATUS.queued;
  return (
    <motion.li initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: [0.2, 0.7, 0.2, 1] }}
      className="card p-4 sm:p-5" data-testid="job-card" data-state={state}>
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-accent-soft font-mono text-[10px] font-semibold text-accent" aria-hidden="true">{src.slice(0, 5)}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium" title={title}>{title}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[0.85rem] text-muted">
            {run.transform ? (
              <span className="chip">{run.targetLabel}</span>
            ) : (
              <><span className="chip">{src}</span><span aria-hidden="true">→</span><span className="sr-only">to</span><span className="chip !border-transparent !bg-accent-soft !text-accent">{run.targetLabel}</span></>
            )}
          </p>
        </div>
        <span className={`chip !border-transparent ${status.cls}`}>
          <span className={`h-1.5 w-1.5 rounded-full bg-current ${status.pulse ? "pulse-dot" : ""}`} aria-hidden="true" />
          {status.text}
        </span>
        {(state === "queued" || state === "running") && (
          <button onClick={onCancel} aria-label="Cancel" title="Cancel" className="grid h-7 w-7 place-items-center rounded-md text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink">
            <X size={15} aria-hidden="true" />
          </button>
        )}
      </div>
      <Progress job={j} />
      {state === "failed" && j?.error && (
        <div className="mt-3 flex items-start gap-2 rounded-[var(--radius-control)] bg-danger-soft p-3 text-[0.9rem]" role="alert">
          <AlertTriangle size={17} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
          <div className="flex-1">
            <p>{j.error.message}</p>
            <button onClick={onRetry} className="mt-2 flex items-center gap-1 font-medium text-ink underline-offset-2 hover:underline">
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </div>
        </div>
      )}
      {state === "cancelled" && <p className="mt-3 text-[0.9rem] text-muted">Cancelled. Nothing was kept.</p>}
      {state === "expired" && <p className="mt-3 text-[0.9rem] text-muted">This result has expired and was deleted.</p>}
      {j && (j.notices.length > 0 || j.warnings.length > 0) && state === "succeeded" && (
        <ul className="mt-3 flex flex-col gap-1.5 text-[0.88rem]">
          {j.warnings.map((w) => (
            <li key={w} className="flex gap-2 rounded-[var(--radius-control)] bg-warn-soft px-3 py-2"><AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />{w}</li>
          ))}
          {j.notices.map((n) => (
            <li key={n} className="flex gap-2 text-muted"><Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{n}</li>
          ))}
        </ul>
      )}
      {state === "succeeded" && j && (
        <ul className="mt-4 flex flex-col gap-3 border-t border-line pt-4">
          {j.outputs.slice(0, 50).map((o) => {
            const delta = j.outputs.length === 1 ? sizeDelta(j.input_size, o.size) : null;
            return (
              <li key={o.index} className="flex flex-col gap-3">
                {j.outputs.length <= 4 && <Preview run={run} output={o} />}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-[0.92rem]" title={o.name}>{o.label ?? o.name}</p>
                    <p className="font-mono text-[11px] text-muted tabular-nums">
                      {delta?.text ? (
                        <>{formatBytes(j.input_size)} → {formatBytes(o.size)} <span className={delta.smaller ? "text-ok" : ""}>({delta.text})</span></>
                      ) : formatBytes(o.size)}
                    </p>
                  </div>
                  <a href={outputUrl(run.jobId, o.index)} download data-testid="download" className="btn btn-primary">
                    <Download size={15} aria-hidden="true" /> Download
                  </a>
                </div>
              </li>
            );
          })}
          {j.outputs.length > 50 && <li className="text-muted">…and {j.outputs.length - 50} more in the ZIP.</li>}
        </ul>
      )}
    </motion.li>
  );
}
