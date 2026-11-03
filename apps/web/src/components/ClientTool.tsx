"use client";

import { ArrowLeftRight, Copy, Download, FileUp, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, Operation } from "@/lib/api";
import { fmtShort } from "@/lib/caps";
import { FILE_INPUT, TOOLS, ToolError, type ToolResult } from "@/lib/tools";
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
  const [target, setTarget] = useState(initialTarget);
  const [text, setText] = useState("");
  const [bytes, setBytes] = useState<Uint8Array | undefined>();
  const [fileName, setFileName] = useState<string | undefined>();
  const [values, setValues] = useState<OptionValues>(() => defaultsOf(op.options_schema));
  const [result, setResult] = useState<ToolResult | null>(null);
  const [error, setError] = useState<ToolError | null>(null);
  const [copied, setCopied] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const sources = useMemo(() => [...new Set(op.pairs.map((p) => p.source))], [op]);
  const targets = useMemo(() => op.pairs.filter((p) => p.source === source).map((p) => p.target), [op, source]);
  useEffect(() => {
    if (!targets.includes(target)) setTarget(targets[0]);
  }, [targets, target]);

  const debouncedText = useDebounced(text, 250);
  useEffect(() => {
    let cancelled = false;
    if (!debouncedText.trim() && !bytes) {
      setResult(null);
      setError(null);
      return;
    }
    Promise.resolve()
      .then(() => TOOLS[op.id]({ text: debouncedText, bytes, fileName, source, target, options: values }))
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setResult(null);
        setError(e instanceof ToolError ? e : new ToolError((e as Error).message ?? "Something went wrong."));
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedText, bytes, fileName, source, target, values, op.id]);

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

  const outExt = op.cardinality === "transform" ? EXT[source] ?? "txt" : EXT[target] ?? "txt";
  const download = () => {
    if (!result) return;
    const blob = result.bytes && !result.output
      ? new Blob([result.bytes as BlobPart], { type: result.mime ?? "application/octet-stream" })
      : new Blob([result.output], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = result.bytes && !result.output ? "decoded.bin" : `output.${outExt}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const field = "w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2";
  return (
    <div className="flex flex-col gap-5" data-testid="client-tool">
      <p className="flex items-center gap-2 rounded-[var(--radius-control)] bg-accent-soft px-3 py-2 text-[0.95rem]">
        <ShieldCheck size={18} className="shrink-0 text-accent" aria-hidden="true" />
        <span><span className="font-medium">Runs in your browser.</span> Nothing you paste or open here is uploaded.</span>
      </p>

      {op.cardinality !== "transform" && (sources.length > 1 || targets.length > 1) && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-36 flex-1">
            <span className="mb-1.5 block font-medium">From</span>
            <select className={field} value={source} onChange={(e) => setSource(e.target.value)} data-testid="tool-source">
              {sources.map((s) => <option key={s} value={s}>{fmtShort(caps, s)}</option>)}
            </select>
          </label>
          <button type="button" aria-label="Swap formats" disabled={!op.pairs.some((p) => p.source === target && p.target === source)}
            onClick={() => { setSource(target); setTarget(source); if (result?.output) setText(result.output); }}
            className="mb-1 grid h-10 w-10 place-items-center rounded-full border border-line hover:border-line-strong disabled:opacity-30">
            <ArrowLeftRight size={16} />
          </button>
          <label className="min-w-36 flex-1">
            <span className="mb-1.5 block font-medium">To</span>
            <select className={field} value={target} onChange={(e) => setTarget(e.target.value)} data-testid="tool-target">
              {targets.map((t) => <option key={t} value={t}>{fmtShort(caps, t)}</option>)}
            </select>
          </label>
        </div>
      )}
      {op.cardinality === "transform" && sources.length > 1 && (
        <label className="max-w-xs">
          <span className="mb-1.5 block font-medium">Language</span>
          <select className={field} value={source} onChange={(e) => { setSource(e.target.value); setTarget(e.target.value); }} data-testid="tool-source">
            {sources.map((s) => <option key={s} value={s}>{fmtShort(caps, s)}</option>)}
          </select>
        </label>
      )}

      <div className="rounded-[var(--radius-panel)] border border-line bg-surface p-4">
        <OptionsForm schema={op.options_schema} target={op.cardinality === "transform" ? source : target} values={values} onChange={setValues} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="tool-in" className="font-medium">Input</label>
            <button type="button" onClick={() => fileRef.current?.click()} className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.9rem] text-muted hover:text-ink">
              <FileUp size={15} aria-hidden="true" /> Open a file
            </button>
            <input ref={fileRef} type="file" className="sr-only" tabIndex={-1} aria-hidden="true"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void loadFile(f); e.target.value = ""; }} />
          </div>
          {bytes ? (
            <div className="flex min-h-64 items-center justify-between rounded-[var(--radius-control)] border border-line bg-surface-2 p-3">
              <span>{fileName} ({bytes.length.toLocaleString()} bytes)</span>
              <button className="text-[0.9rem] text-muted hover:text-ink" onClick={() => { setBytes(undefined); setFileName(undefined); }}>Clear</button>
            </div>
          ) : (
            <textarea id="tool-in" ref={input} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              data-testid="tool-input" placeholder="Paste here…"
              className="min-h-64 w-full rounded-[var(--radius-control)] border border-line bg-surface p-3 font-mono text-[0.85rem] leading-relaxed" />
          )}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="tool-out" className="font-medium">Output</label>
            <div className="flex gap-1">
              <button type="button" disabled={!result?.output} onClick={() => { void navigator.clipboard.writeText(result!.output); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.9rem] text-muted hover:text-ink disabled:opacity-40">
                <Copy size={15} aria-hidden="true" /> {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" disabled={!result || (!result.output && !result.bytes)} onClick={download} data-testid="tool-download"
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.9rem] text-muted hover:text-ink disabled:opacity-40">
                <Download size={15} aria-hidden="true" /> Download
              </button>
            </div>
          </div>
          <textarea id="tool-out" readOnly value={result?.output ?? ""} spellCheck={false} data-testid="tool-output"
            className="min-h-64 w-full rounded-[var(--radius-control)] border border-line bg-surface-2 p-3 font-mono text-[0.85rem] leading-relaxed" />
        </div>
      </div>
      <div aria-live="polite" className="flex flex-col gap-2">
        {error && (
          <p role="alert" className="rounded-[var(--radius-control)] bg-danger-soft p-3" data-testid="tool-error">
            {error.message}{" "}
            {error.where && <button className="font-medium underline underline-offset-2" onClick={() => jumpTo(error.where!)}>Show me</button>}
          </p>
        )}
        {result?.notices?.map((n) => <p key={n} className="text-[0.92rem] text-muted">{n}</p>)}
      </div>
    </div>
  );
}
