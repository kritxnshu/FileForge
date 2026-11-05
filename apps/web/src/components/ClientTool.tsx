"use client";

import { ArrowLeftRight, ClipboardPaste, Copy, Download, Eraser, FileUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, Operation } from "@/lib/api";
import { fmtShort } from "@/lib/caps";
import { FILE_INPUT, FILE_ONLY, TOOLS, ToolError, type ToolResult } from "@/lib/tools";
import { defaultsOf, OptionsForm, type OptionValues } from "./OptionsForm";
import { useCaps } from "./providers";

const EXT: Record<string, string> = { json: "json", xml: "xml", yaml: "yaml", toml: "toml", csv: "csv", tsv: "tsv", md: "md",
  html: "html", sql: "sql", css: "css", js: "js", txt: "txt" };

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function ClientTool({ opId, source: initialSource, target: initialTarget }: { opId: string; source: string; target: string }) {
  const { caps } = useCaps();
  const op = caps?.operations.find((o) => o.id === opId);
  if (!caps || !op) return <p className="text-muted">Loading…</p>;
  return <ToolBody caps={caps} op={op} initialSource={initialSource} initialTarget={initialTarget} />;
}

function ToolBody({ caps, op, initialSource, initialTarget }: { caps: Capabilities; op: Operation; initialSource: string; initialTarget: string }) {
  const [source, setSource] = useState(initialSource);
  const [pickedTarget, setTarget] = useState(initialTarget);
  const [text, setText] = useState("");
  const [bytes, setBytes] = useState<Uint8Array | undefined>();
  const [fileName, setFileName] = useState<string | undefined>();
  const [values, setValues] = useState<OptionValues>(() => defaultsOf(op.options_schema));
  const [outcome, setOutcome] = useState<{ result: ToolResult | null; error: ToolError | null }>({ result: null, error: null });
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const sources = useMemo(() => [...new Set(op.pairs.map((p) => p.source))], [op]);
  const targets = useMemo(() => op.pairs.filter((p) => p.source === source).map((p) => p.target), [op, source]);
  const target = targets.includes(pickedTarget) ? pickedTarget : targets[0];

  const debouncedText = useDebounced(text, 250);
  useEffect(() => {
    let cancelled = false;
    if (!debouncedText.trim() && !bytes) return;
    Promise.resolve()
      .then(() => TOOLS[op.id]({ text: debouncedText, bytes, fileName, source, target, options: values }))
      .then((r) => {
        if (cancelled) return;
        setOutcome({ result: r, error: null });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setOutcome({ result: null, error: e instanceof ToolError ? e : new ToolError((e as Error).message ?? "Something went wrong.") });
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedText, bytes, fileName, source, target, values, op.id]);
  // with no input there's nothing to show (an earlier result stays out of sight until the next one arrives)
  const empty = !debouncedText.trim() && !bytes;
  const result = empty ? null : outcome.result;
  const error = empty ? null : outcome.error;

  const jumpTo = (where: { line: number; column: number }) => {
    const el = input.current;
    if (!el) return;
    const lines = el.value.split("\n");
    let pos = 0;
    for (let i = 0; i < where.line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    pos += Math.max(0, where.column - 1);
    el.focus();
    el.setSelectionRange(pos, pos + 1);
  };

  const loadFile = async (f: File) => {
    const ext = f.name.toLowerCase().split(".").pop() ?? "";
    const byExt = sources.find((s) => s === ext || caps.formats[s]?.exts.includes(ext));
    if (byExt && FILE_ONLY.has(op.id)) setSource(byExt);
    if (FILE_INPUT.has(op.id) && values.direction !== "decode") {
      setBytes(new Uint8Array(await f.arrayBuffer()));
      setFileName(f.name);
      setText("");
    } else {
      setBytes(undefined);
      setFileName(undefined);
      setText(await f.text());
    }
  };

  const outExt = op.cardinality === "transform" ? EXT[source] ?? "txt" : EXT[target] ?? target;
  const download = () => {
    if (!result) return;
    const binary = result.bytes && !result.output;
    const blob = binary
      ? new Blob([result.bytes as BlobPart], { type: result.mime ?? "application/octet-stream" })
      : new Blob([result.output], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = binary ? (result.mime === "image/png" ? "output.png" : "decoded.bin") : `output.${outExt}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const field = "h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[0.9rem]";
  const inBytes = bytes ? bytes.length : new TextEncoder().encode(text).length;
  const outBytes = result?.output ? new TextEncoder().encode(result.output).length : result?.bytes?.length ?? 0;
  const lines = text ? text.split("\n").length : 0;
  const paneHead = "flex min-h-11 flex-wrap items-center justify-between gap-2 px-3 py-1.5";
  const inBtn = "btn !px-2 !py-1 text-[0.82rem] text-muted hover:bg-surface-2 hover:text-ink";
  const outBtn = "btn !px-2 !py-1 text-[0.82rem] text-term-muted hover:bg-white/10 hover:text-term-ink";
  const status = error
    ? { text: "Error", cls: "bg-rose-500/15 text-rose-300" }
    : result
      ? { text: "Ready", cls: "bg-emerald-500/15 text-emerald-300" }
      : { text: "Waiting for input", cls: "bg-white/10 text-zinc-300" };
  return (
    <div className="flex flex-col gap-4" data-testid="client-tool">
      <div className="card flex flex-col gap-4 p-4">
        {op.cardinality !== "transform" && (sources.length > 1 || targets.length > 1) && (
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-36 flex-1">
              <span className="mb-1 block text-[0.85rem] font-medium">From</span>
              <select className={field} value={source} onChange={(e) => setSource(e.target.value)} data-testid="tool-source">
                {sources.map((s) => <option key={s} value={s}>{fmtShort(caps, s)}</option>)}
              </select>
            </label>
            <button type="button" aria-label="Swap formats" disabled={!op.pairs.some((p) => p.source === target && p.target === source)}
              onClick={() => { setSource(target); setTarget(source); if (result?.output) setText(result.output); }}
              className="grid h-9 w-9 place-items-center rounded-lg border border-line transition-[transform,border-color] duration-200 hover:rotate-180 hover:border-line-strong disabled:opacity-30">
              <ArrowLeftRight size={15} />
            </button>
            <label className="min-w-36 flex-1">
              <span className="mb-1 block text-[0.85rem] font-medium">To</span>
              <select className={field} value={target} onChange={(e) => setTarget(e.target.value)} data-testid="tool-target">
                {targets.map((t) => <option key={t} value={t}>{fmtShort(caps, t)}</option>)}
              </select>
            </label>
          </div>
        )}
        {op.cardinality === "transform" && sources.length > 1 && (
          <label className="max-w-xs">
            <span className="mb-1 block text-[0.85rem] font-medium">Language</span>
            <select className={field} value={source} onChange={(e) => { setSource(e.target.value); setTarget(e.target.value); }} data-testid="tool-source">
              {sources.map((s) => <option key={s} value={s}>{fmtShort(caps, s)}</option>)}
            </select>
          </label>
        )}
        <OptionsForm grid schema={op.options_schema} target={op.cardinality === "transform" ? source : target} values={values} onChange={setValues} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* input */}
        <div className="card flex min-w-0 flex-col overflow-hidden">
          <div className={`${paneHead} border-b border-line`}>
            <span className="flex items-center gap-2">
              <label htmlFor="tool-in" className="text-[0.9rem] font-medium">Input</label>
              <span className="chip">{inBytes.toLocaleString()} bytes</span>
            </span>
            <span className="flex gap-0.5">
              {!FILE_ONLY.has(op.id) && (
                <button type="button" className={inBtn} onClick={() => void navigator.clipboard.readText().then(setText).catch(() => input.current?.focus())}>
                  <ClipboardPaste size={14} aria-hidden="true" /> Paste
                </button>
              )}
              <button type="button" onClick={() => fileRef.current?.click()} className={inBtn}>
                <FileUp size={14} aria-hidden="true" /> Open a file
              </button>
              <button type="button" className={inBtn} disabled={!text && !bytes} onClick={() => { setText(""); setBytes(undefined); setFileName(undefined); }}>
                <Eraser size={14} aria-hidden="true" /> Clear
              </button>
            </span>
            <input ref={fileRef} type="file" className="sr-only" tabIndex={-1} aria-hidden="true"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void loadFile(f); e.target.value = ""; }} />
          </div>
          {FILE_ONLY.has(op.id) && !bytes ? (
            <button type="button" onClick={() => fileRef.current?.click()} data-testid="tool-file"
              className="dropzone-surface m-3 flex min-h-72 flex-1 flex-col items-center justify-center gap-2 rounded-xl border-[1.5px] border-dashed border-line-strong p-6 text-muted transition-colors duration-150 hover:text-ink">
              <FileUp size={24} aria-hidden="true" />
              <span className="font-medium">Choose a file</span>
              <span className="text-[0.85rem]">It&apos;s read in your browser and never uploaded.</span>
            </button>
          ) : bytes ? (
            <div className="flex min-h-72 flex-1 items-center justify-center bg-surface-2 p-4 font-mono text-[0.85rem]">
              {fileName} ({bytes.length.toLocaleString()} bytes)
            </div>
          ) : (
            <textarea id="tool-in" ref={input} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              data-testid="tool-input" placeholder="Paste or type here…"
              className="min-h-80 w-full flex-1 resize-y bg-surface p-4 font-mono text-[0.82rem] leading-relaxed focus-visible:rounded-none focus-visible:outline-offset-[-2px] placeholder:text-muted" />
          )}
          <div className="flex justify-between border-t border-line px-3 py-1.5 font-mono text-[11px] text-muted">
            <span>UTF-8</span>
            <span>{bytes ? fileName : `${lines} ${lines === 1 ? "line" : "lines"}`}</span>
          </div>
        </div>

        {/* output */}
        <div className="flex min-w-0 flex-col overflow-hidden rounded-[var(--radius-panel)] border border-black/10 bg-term text-term-ink shadow-2">
          <div className={`${paneHead} border-b border-white/10`}>
            <span className="flex items-center gap-2">
              <label htmlFor="tool-out" className="text-[0.9rem] font-medium">Output</label>
              <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[11px] font-medium ${status.cls}`}>
                <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{status.text}
              </span>
              {outBytes > 0 && <span className="font-mono text-[11px] text-term-muted">{outBytes.toLocaleString()} bytes</span>}
            </span>
            <span className="flex gap-0.5">
              <button type="button" disabled={!result?.output} className={outBtn}
                onClick={() => { void navigator.clipboard.writeText(result!.output); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
                <Copy size={14} aria-hidden="true" /> {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" disabled={!result || (!result.output && !result.bytes)} onClick={download} data-testid="tool-download" className={outBtn}>
                <Download size={14} aria-hidden="true" /> Download
              </button>
            </span>
          </div>
          {typeof result?.data?.swatch === "string" && (
            <div className="m-3 flex overflow-hidden rounded-lg border border-white/10" data-testid="tool-swatch">
              <div className="h-20 flex-1" style={{ background: result.data.swatch as string }} aria-label={`Swatch ${result.data.swatch}`} role="img" />
              <div className="grid h-20 flex-1 place-items-center text-lg font-semibold"
                style={{ background: result.data.against as string, color: result.data.swatch as string }}>Sample text</div>
            </div>
          )}
          {typeof result?.data?.preview === "string" && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={result.data.preview as string} alt="Preview of the result" data-testid="tool-preview"
              className="m-3 max-h-72 self-start rounded-lg bg-[repeating-conic-gradient(#e4e4e7_0_25%,#ffffff_0_50%)] bg-[length:16px_16px] object-contain p-2" />
          )}
          {!(result?.bytes && !result.output) && (
            <textarea id="tool-out" readOnly value={result?.output ?? ""} spellCheck={false} data-testid="tool-output"
              placeholder="The result appears here as you type."
              className="min-h-80 w-full flex-1 resize-y bg-transparent p-4 font-mono text-[0.82rem] leading-relaxed text-term-ink focus-visible:rounded-none focus-visible:outline-offset-[-2px] placeholder:text-term-muted" />
          )}
          <div className="border-t border-white/10 px-3 py-1.5 font-mono text-[11px] text-term-muted">
            Computed locally{result?.mime ? ` · ${result.mime}` : ""}
          </div>
        </div>
      </div>
      <div aria-live="polite" className="flex flex-col gap-2">
        {error && (
          <p role="alert" className="rounded-[var(--radius-control)] border border-danger/30 bg-danger-soft p-3 text-[0.9rem]" data-testid="tool-error">
            {error.message}{" "}
            {error.where && <button className="font-medium underline underline-offset-2" onClick={() => jumpTo(error.where!)}>Show me</button>}
          </p>
        )}
        {result?.notices?.map((n) => <p key={n} className="text-[0.88rem] text-muted">{n}</p>)}
      </div>
    </div>
  );
}
