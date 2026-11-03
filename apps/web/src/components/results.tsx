"use client";

import { AlertTriangle, CheckCircle2, Download, Info, RotateCcw, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { outputTable, outputUrl, uploadRawUrl, type Job, type JobOutput, type TablePreview } from "@/lib/api";
import { formatBytes, sizeDelta } from "@/lib/caps";
import { PdfThumbs } from "./PageOrder";

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
      <div className="flex justify-between text-[0.9rem] text-muted">
        <span data-testid="job-stage">{stage}</span>
        {p && <span className="tabular-nums">{Number.isInteger(p.done) && p.total > 1 ? `${p.done} of ${p.total}` : `${pct}%`}</span>}
      </div>
      <div
        role="progressbar"
        aria-label="Conversion progress"
        aria-valuetext={pct !== null ? `${pct}%` : stage}
        {...(pct !== null ? { "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 } : {})}
        className={`mt-1.5 h-1.5 rounded-full bg-surface-2 ${pct === null ? "indeterminate" : ""}`}
      >
        {pct !== null && <div className="h-full rounded-full bg-accent transition-[width] duration-200" style={{ width: `${pct}%` }} />}
      </div>
    </div>
  );
}

export function JobCard({ run, onCancel, onRetry }: { run: RunView; onCancel: () => void; onRetry: () => void }) {
  const j = run.job;
  const state = j?.state ?? "queued";
  const title = run.fileNames.length > 1 ? `${run.fileNames.length} files` : run.fileNames[0];
  return (
    <motion.li initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-5" data-testid="job-card" data-state={state}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium" title={title}>{title}</p>
          <p className="text-[0.9rem] text-muted">{run.transform ? run.targetLabel : `to ${run.targetLabel}`}</p>
        </div>
        {(state === "queued" || state === "running") && (
          <button onClick={onCancel} className="flex items-center gap-1 rounded-md px-2 py-1 text-[0.9rem] text-muted hover:text-ink">
            <X size={15} aria-hidden="true" /> Cancel
          </button>
        )}
        {state === "succeeded" && <CheckCircle2 className="shrink-0 text-accent" size={22} aria-label="Done" />}
      </div>
      <Progress job={j} />
      {state === "failed" && j?.error && (
        <div className="mt-3 flex items-start gap-2 rounded-[var(--radius-control)] bg-danger-soft p-3 text-[0.92rem]" role="alert">
          <AlertTriangle size={17} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
          <div className="flex-1">
            <p>{j.error.message}</p>
            <button onClick={onRetry} className="mt-2 flex items-center gap-1 font-medium text-ink underline-offset-2 hover:underline">
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </div>
        </div>
      )}
      {state === "cancelled" && <p className="mt-3 text-[0.92rem] text-muted">Cancelled. Nothing was kept.</p>}
      {state === "expired" && <p className="mt-3 text-[0.92rem] text-muted">This result has expired and was deleted.</p>}
      {j && (j.notices.length > 0 || j.warnings.length > 0) && state === "succeeded" && (
        <ul className="mt-3 flex flex-col gap-1.5 text-[0.9rem]">
          {j.warnings.map((w) => (
            <li key={w} className="flex gap-2 rounded-[var(--radius-control)] bg-warn-soft px-3 py-2"><AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />{w}</li>
          ))}
          {j.notices.map((n) => (
            <li key={n} className="flex gap-2 text-muted"><Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{n}</li>
          ))}
        </ul>
      )}
      {state === "succeeded" && j && (
        <ul className="mt-4 flex flex-col gap-4">
          {j.outputs.slice(0, 50).map((o) => {
            const delta = j.outputs.length === 1 ? sizeDelta(j.input_size, o.size) : null;
            return (
              <li key={o.index} className="flex flex-col gap-3">
                {j.outputs.length <= 4 && <Preview run={run} output={o} />}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate" title={o.name}>{o.label ?? o.name}</p>
                    <p className="text-[0.88rem] text-muted tabular-nums">
                      {formatBytes(o.size)}
                      {delta?.text && <> (was {formatBytes(j.input_size)}, {delta.text})</>}
                    </p>
                  </div>
                  <a href={outputUrl(run.jobId, o.index)} download data-testid="download"
                    className="flex items-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-4 py-2 font-medium text-accent-ink hover:opacity-90">
                    <Download size={16} aria-hidden="true" /> Download
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
