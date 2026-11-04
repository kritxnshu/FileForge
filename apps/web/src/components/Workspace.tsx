"use client";

import { AlertTriangle, ArrowDown, ArrowUp, FileArchive, Loader2, Trash2, X } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  batchZipUrl,
  cancelJob,
  createJobs,
  deleteJob,
  getJob,
  watchJob,
  TERMINAL,
  type Capabilities,
  type Job,
} from "@/lib/api";
import { choiceKey, choicesFor, fmtLabel, fmtShort, formatBytes, SUPPORT_LABEL, toolTitle, type Choice } from "@/lib/caps";
import { addHistory } from "@/lib/history";
import { DropZone } from "./DropZone";
import { cleanOptions, defaultsOf, nothingPlaced, onePdfOnly, OptionsForm, type OptionValues } from "./OptionsForm";
import { useCaps, useWorkspace, type Item } from "./providers";
import { JobCard, type RunView } from "./results";

export interface Preset {
  opId: string;
  source: string;
  target: string;
  /** Settings this page starts with (e.g. Scan to PDF cleans up photos). */
  options?: OptionValues;
  /** A tool page's name ("Edit PDF"), used in messages instead of "converts X to Y". */
  label?: string;
  /** Formats the tool accepts, for messages. */
  sources?: string[];
}

interface Run extends RunView {
  fileIds: string[];
  opId: string;
  target: string;
  options: OptionValues;
}

const COMBINE = "__all__";

function SupportBadge({ level }: { level: string }) {
  if (level === "full") return null;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[0.75rem] font-medium ${level === "partial" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>
      {SUPPORT_LABEL[level as keyof typeof SUPPORT_LABEL]}
    </span>
  );
}

function Picker({ caps, choices, value, onPick, label }: {
  caps: Capabilities;
  choices: Choice[];
  value: string;
  onPick: (k: string) => void;
  label: string;
}) {
  const converts = choices.filter((c) => c.op.cardinality !== "transform" && c.pair.target !== c.pair.source);
  const tools = choices.filter((c) => !converts.includes(c));
  const chip = (c: Choice, text: string) => {
    const k = choiceKey(c);
    const on = k === value;
    return (
      <button
        key={k}
        type="button"
        role="radio"
        aria-checked={on}
        data-testid={`target-${c.op.id}-${c.pair.target}`}
        onClick={() => onPick(on ? "" : k)}
        className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 transition-colors duration-150 ${
          on ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:border-line-strong"
        }`}
      >
        <span className="font-medium">{text}</span>
        {!on && <SupportBadge level={c.pair.support} />}
      </button>
    );
  };
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-col gap-4">
      {converts.length > 0 && (
        <div>
          <p className="mb-2 text-[0.9rem] text-muted">Convert to</p>
          <div className="flex flex-wrap gap-2">
            {converts.map((c) => chip(c, converts.filter((x) => x.pair.target === c.pair.target).length > 1 ? `${fmtShort(caps, c.pair.target)} (${c.op.label})` : fmtShort(caps, c.pair.target)))}
          </div>
        </div>
      )}
      {tools.length > 0 && (
        <div>
          <p className="mb-2 text-[0.9rem] text-muted">Tools</p>
          <div className="flex flex-wrap gap-2">{tools.map((c) => chip(c, c.op.label))}</div>
        </div>
      )}
    </div>
  );
}

export function Workspace({ preset }: { preset?: Preset }) {
  const { caps, error: capsError } = useCaps();
  const { items, remove, clear } = useWorkspace();
  const [orderPref, setOrderPref] = useState<string[]>([]);
  const [userPicks, setPicks] = useState<Record<string, string>>({});
  const [optValues, setOptValues] = useState<Record<string, OptionValues>>({});
  const [runs, setRuns] = useState<Run[]>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [announce, setAnnounce] = useState("");
  const stops = useRef<Record<string, () => void>>({});

  // the user's chosen order (used for merges), with newly added files at the end
  const order = useMemo(() => {
    const keys = items.map((i) => i.key);
    return [...orderPref.filter((k) => keys.includes(k)), ...keys.filter((k) => !orderPref.includes(k))];
  }, [orderPref, items]);
  const ordered = useMemo(() => order.map((k) => items.find((i) => i.key === k)).filter(Boolean) as Item[], [order, items]);
  const ready = useMemo(() => ordered.filter((i) => i.status === "ready" && i.server?.format), [ordered]);
  const uploading = ordered.some((i) => i.status === "uploading");

  const groups = useMemo(() => {
    const m = new Map<string, Item[]>();
    for (const it of ready) {
      const f = it.server!.format!;
      m.set(f, [...(m.get(f) ?? []), it]);
    }
    return m;
  }, [ready]);

  const choicesByFormat = useMemo(() => {
    const m = new Map<string, Choice[]>();
    if (caps) for (const f of groups.keys()) m.set(f, choicesFor(caps, f));
    return m;
  }, [caps, groups]);

  // many→one choices valid for every file (e.g. images → PDF across PNG + JPG)
  const combineChoices = useMemo(() => {
    if (groups.size < 2) return [];
    const lists = [...groups.keys()].map((f) => choicesFor(caps!, f, { combine: true }).filter((c) => c.op.cardinality === "many_to_one"));
    if (!lists.length) return [];
    const keys = lists.map((l) => new Set(l.map((c) => `${c.op.id}|${c.pair.target}`)));
    return lists[0].filter((c) => keys.every((s) => s.has(`${c.op.id}|${c.pair.target}`)));
  }, [groups, caps]);

  // a conversion page's own choice, pre-picked for each matching file type until the user picks something else;
  // file types it can't apply to are "mismatched" (e.g. an MP3 dropped on "PNG to JPG")
  const { presetPicks, mismatched, waiting } = useMemo(() => {
    const presetPicks: Record<string, string> = {};
    const mismatched: string[] = [];
    const waiting: string[] = []; // the tool takes this type, but only together with another (a PDF and a logo)
    if (preset) {
      // a tool that takes several kinds of file at once runs over all of them together
      const together = combineChoices.find((c) => c.op.id === preset.opId && c.pair.target === preset.target);
      if (together) presetPicks[COMBINE] = choiceKey(together);
      else for (const [f, list] of choicesByFormat) {
        // a conversion page may fall back to the same target (a GIF on "PNG to JPG"); a tool page never swaps tools
        const match = list.find((c) => c.op.id === preset.opId && c.pair.target === preset.target)
          ?? (preset.label ? undefined : list.find((c) => c.pair.target === preset.target && c.op.cardinality !== "transform"));
        if (match) presetPicks[f] = choiceKey(match);
        else if (preset.label && preset.sources?.includes(f)) waiting.push(f);
        else mismatched.push(f);
      }
    }
    return { presetPicks, mismatched, waiting };
  }, [preset, choicesByFormat, combineChoices]);
  const picks = useMemo(() => ({ ...presetPicks, ...userPicks }), [presetPicks, userPicks]);

  const presetOptions = useCallback((opId: string): OptionValues => (preset && preset.opId === opId ? preset.options ?? {} : {}), [preset]);
  const startValues = useCallback((c: Choice): OptionValues => ({ ...defaultsOf(c.op.options_schema), ...presetOptions(c.op.id) }), [presetOptions]);
  const valuesFor = useCallback((c: Choice): OptionValues => ({ ...startValues(c), ...(optValues[c.op.id] ?? {}) }), [startValues, optValues]);

  const findChoice = useCallback((k: string, list: Choice[]) => list.find((c) => choiceKey(c) === k) ?? null, []);
  const combined = picks[COMBINE] ? findChoice(picks[COMBINE], combineChoices) : null;

  const planned: { choice: Choice; items: Item[] }[] = useMemo(() => {
    if (combined) return [{ choice: combined, items: ready }];
    const out: { choice: Choice; items: Item[] }[] = [];
    for (const [f, its] of groups) {
      const c = findChoice(picks[f] ?? "", choicesByFormat.get(f) ?? []);
      if (c) out.push({ choice: c, items: its });
    }
    return out;
  }, [combined, ready, groups, picks, choicesByFormat, findChoice]);

  const distinctOps = useMemo(() => {
    const m = new Map<string, Choice>();
    for (const p of planned) if (!m.has(p.choice.op.id)) m.set(p.choice.op.id, p.choice);
    return [...m.values()];
  }, [planned]);

  const allPicked = groups.size > 0 && (combined !== null || [...groups.keys()].every((f) => picks[f]));
  const active = runs.some((r) => !r.job || !TERMINAL.includes(r.job.state));
  // Edit, Sign, Organize…: what you place is drawn on one PDF's pages, so it can't be applied to other PDFs
  const severalPdfs = planned.find((p) => p.items.length > 1 && onePdfOnly(p.choice.op.options_schema));
  const nothingYet = planned.find((p) => nothingPlaced(p.choice.op.options_schema, valuesFor(p.choice), startValues(p.choice)));
  const canRun = allPicked && !uploading && !submitting && ready.length > 0 && !severalPdfs && !nothingYet;

  const updateRun = useCallback((jobId: string, job: Job) => {
    setRuns((prev) => prev.map((r) => (r.jobId === jobId ? { ...r, job } : r)));
    setAnnounce(`${job.state === "running" ? job.stage ?? "Converting" : job.state}`);
  }, []);

  const follow = useCallback((jobId: string) => {
    const poll = async () => {
      for (;;) {
        try {
          const j = await getJob(jobId);
          updateRun(jobId, j);
          if (TERMINAL.includes(j.state)) return;
        } catch {
          return;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    };
    stops.current[jobId] = watchJob(jobId, (j) => updateRun(jobId, j), () => void poll());
  }, [updateRun]);

  useEffect(() => () => Object.values(stops.current).forEach((s) => s()), []);

  // record finished conversions in local history (metadata only)
  useEffect(() => {
    if (!caps) return;
    for (const r of runs) {
      if (r.job?.state === "succeeded") {
        addHistory({
          jobId: r.jobId, at: Date.now(), fileName: r.fileNames[0], operation: r.opId,
          label: r.targetLabel, source: r.sourceFormat, target: r.target, outputs: r.job.outputs.length,
          expiresAt: r.job.expires_at, tool: r.transform,
        });
      }
    }
  }, [runs, caps]);

  const submit = async () => {
    if (!caps) return;
    setSubmitError(null);
    setSubmitting(true);
    let bid = batchId;
    try {
      for (const { choice, items: its } of planned) {
        const options = cleanOptions(choice.op.options_schema, choice.pair.target, valuesFor(choice));
        const res = await createJobs({
          file_ids: its.map((i) => i.server!.id),
          operation: choice.op.id,
          target: choice.op.cardinality === "transform" ? null : choice.pair.target,
          options,
          ...(bid ? { batch_id: bid } : {}),
        });
        bid = res.batch_id;
        setBatchId(bid);
        const newRuns: Run[] = res.jobs.map((j) => {
          const files = its.filter((i) => j.file_ids.includes(i.server!.id));
          return {
            jobId: j.id, fileIds: j.file_ids, fileNames: files.map((f) => f.name), opId: choice.op.id,
            target: choice.pair.target, options, sourceFormat: files[0].server!.format!,
            sourceFileId: files.length === 1 ? files[0].server!.id : null,
            targetLabel: choice.op.cardinality === "transform" ? choice.op.label : toolTitle(caps, choice.op, choice.pair).replace(/^.* to /, ""),
            transform: choice.op.cardinality === "transform",
            job: null,
          };
        });
        setRuns((prev) => [...prev, ...newRuns]);
        newRuns.forEach((r) => follow(r.jobId));
      }
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "We couldn't start the conversion. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const retry = async (run: Run) => {
    try {
      const res = await createJobs({ file_ids: run.fileIds, operation: run.opId, target: run.target, options: run.options, ...(batchId ? { batch_id: batchId } : {}) });
      const j = res.jobs[0];
      setRuns((prev) => prev.map((r) => (r.jobId === run.jobId ? { ...r, jobId: j.id, job: null } : r)));
      follow(j.id);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Retry failed. Upload the file again.");
    }
  };

  const deleteAll = async () => {
    Object.values(stops.current).forEach((s) => s());
    await Promise.all(runs.map((r) => deleteJob(r.jobId)));
    clear();
    setRuns([]);
    setBatchId(null);
    setAnnounce("Your files and results were deleted.");
  };

  const startOver = () => {
    clear();
    setRuns([]);
    setBatchId(null);
    setPicks({});
  };

  const move = (key: string, dir: -1 | 1) => {
    const i = order.indexOf(key);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= order.length) return;
    const next = [...order];
    [next[i], next[j]] = [next[j], next[i]];
    setOrderPref(next);
  };

  if (capsError) return <p role="alert" className="rounded-[var(--radius-panel)] bg-danger-soft p-4">{capsError}</p>;

  const totalOutputs = runs.reduce((n, r) => n + (r.job?.state === "succeeded" ? r.job.outputs.length : 0), 0);
  const ordering = planned.some((p) => p.choice.op.cardinality === "many_to_one") && ready.length > 1;
  const limitations = planned.flatMap((p) => (p.choice.pair.support !== "full" || p.choice.pair.limitations.length
    ? [{ key: choiceKey(p.choice), title: toolTitle(caps!, p.choice.op, p.choice.pair), level: p.choice.pair.support, items: p.choice.pair.limitations }]
    : []));

  return (
    <div className="flex flex-col gap-6" data-testid="workspace">
      <p aria-live="polite" className="sr-only">{announce}</p>

      {/* files */}
      <section aria-labelledby="files-h" className="rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="files-h" className="font-display text-2xl font-semibold">Your files</h2>
          {items.length > 0 && !runs.length && (
            <button onClick={clear} className="rounded-md px-2 py-1 text-[0.92rem] text-muted hover:text-ink">Clear all</button>
          )}
        </div>
        {items.length === 0 ? (
          <DropZone families="Add a file to see what it can be converted to." />
        ) : (
          <>
            <ul className="flex flex-col divide-y divide-line" data-testid="file-list">
              {ordered.map((it, idx) => (
                <motion.li key={it.key} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  className="flex items-center gap-3 py-3" data-testid="file-row" data-status={it.status}>
                  {ordering && it.status === "ready" && (
                    <span className="flex flex-col">
                      <button aria-label={`Move ${it.name} up`} disabled={idx === 0} onClick={() => move(it.key, -1)} className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30"><ArrowUp size={15} /></button>
                      <button aria-label={`Move ${it.name} down`} disabled={idx === ordered.length - 1} onClick={() => move(it.key, 1)} className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30"><ArrowDown size={15} /></button>
                    </span>
                  )}
                  <span className="grid h-10 min-w-12 place-items-center rounded-lg bg-surface-2 px-1.5 text-[0.78rem] font-semibold">
                    {it.server?.format ? fmtShort(caps ?? ({ formats: {} } as Capabilities), it.server.format) : it.status === "uploading" ? <Loader2 size={16} className="animate-spin" aria-label="Uploading" /> : "?"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium" title={it.name}>{it.name}</p>
                    <p className="text-[0.88rem] text-muted tabular-nums">
                      {formatBytes(it.size)}
                      {it.status === "uploading" && `, uploading ${Math.round(it.progress * 100)}%`}
                      {it.server?.format && caps && `, ${fmtLabel(caps, it.server.format)}`}
                    </p>
                    {it.server?.warnings.map((w) => (
                      <p key={w} className="mt-1 flex gap-1.5 text-[0.88rem] text-warn"><AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />{w}</p>
                    ))}
                    {it.error && <p role="alert" className="mt-1 text-[0.88rem] text-danger">{it.error}</p>}
                  </div>
                  {!runs.length && (
                    <button aria-label={`Remove ${it.name}`} onClick={() => remove(it.key)} className="rounded-md p-1.5 text-muted hover:text-ink"><X size={17} /></button>
                  )}
                </motion.li>
              ))}
            </ul>
            {!runs.length && <div className="mt-4"><DropZone compact /></div>}
          </>
        )}
      </section>

      {/* target */}
      {caps && groups.size > 0 && !runs.length && (
        <section aria-labelledby="target-h" className="rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-6">
          <h2 id="target-h" className="mb-4 font-display text-2xl font-semibold">Choose what to make</h2>
          {preset && mismatched.length > 0 && (
            <p className="mb-5 flex gap-2 rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.95rem]" role="status" data-testid="preset-mismatch">
              <AlertTriangle size={17} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
              <span>
                {preset.label ? (
                  <>
                    {preset.label} works with {(preset.sources ?? [preset.source]).map((f) => fmtShort(caps, f)).join(", ")} files.{" "}
                    {mismatched.map((f) => fmtLabel(caps, f)).join(" and ")} files can&apos;t be used here, so pick another option below.
                  </>
                ) : (
                  <>
                    This page converts {fmtShort(caps, preset.source)} to {fmtShort(caps, preset.target)}.{" "}
                    {mismatched.map((f) => fmtLabel(caps, f)).join(" and ")} files can&apos;t be converted to {fmtShort(caps, preset.target)}, so pick
                    another option below.
                  </>
                )}
              </span>
            </p>
          )}
          {preset?.label && waiting.length > 0 && (
            <p className="mb-5 flex gap-2 rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.95rem]" role="status" data-testid="preset-needs-more">
              <AlertTriangle size={17} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
              <span>{preset.label} uses more than one kind of file at once. Add the other file it needs to continue.</span>
            </p>
          )}
          <div className="flex flex-col gap-6">
            {combineChoices.length > 0 && (
              <div>
                <p className="mb-2 font-medium">All {ready.length} files together</p>
                <Picker caps={caps} label="Combine all files" choices={combineChoices} value={picks[COMBINE] ?? ""}
                  onPick={(k) => setPicks((p) => ({ ...p, [COMBINE]: k }))} />
              </div>
            )}
            {!combined && [...groups.entries()].map(([f, its]) => {
              const list = choicesByFormat.get(f) ?? [];
              return (
                <div key={f} data-testid={`group-${f}`}>
                  {groups.size > 1 && <p className="mb-2 font-medium">{its.length} {fmtLabel(caps, f)} {its.length === 1 ? "file" : "files"}</p>}
                  {list.length ? (
                    <Picker caps={caps} label={`Target for ${fmtLabel(caps, f)} files`} choices={list} value={picks[f] ?? ""}
                      onPick={(k) => setPicks((p) => ({ ...p, [f]: k }))} />
                  ) : (
                    <p className="text-muted" data-testid="no-targets">We can&apos;t convert {fmtLabel(caps, f)} files yet. Check the supported formats page for what&apos;s available.</p>
                  )}
                </div>
              );
            })}
          </div>
          {limitations.length > 0 && (
            <div className="mt-5 flex flex-col gap-2" data-testid="limitations">
              {limitations.map((l) => (
                <div key={l.key} className="rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.92rem]">
                  <p className="font-medium">{l.title}{l.level !== "full" && `: ${SUPPORT_LABEL[l.level]} support`}</p>
                  <ul className="mt-1 list-disc pl-5">{l.items.map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* settings */}
      {caps && distinctOps.length > 0 && !runs.length && (
        <section aria-labelledby="settings-h" className="rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-6">
          <h2 id="settings-h" className="mb-4 font-display text-2xl font-semibold">Settings</h2>
          <div className="flex flex-col gap-8">
            {distinctOps.map((c) => (
              <div key={c.op.id}>
                {distinctOps.length > 1 && <p className="mb-3 font-medium">{c.op.label}</p>}
                <OptionsForm schema={c.op.options_schema} target={c.pair.target}
                  context={{ pdfFileId: planned.find((p) => p.choice.op.id === c.op.id)?.items.find((i) => i.server?.format === "pdf")?.server?.id }}
                  values={valuesFor(c)}
                  onChange={(v) => setOptValues((p) => ({ ...p, [c.op.id]: v }))} />
              </div>
            ))}
          </div>
          {submitError && <p role="alert" className="mt-4 rounded-[var(--radius-control)] bg-danger-soft p-3">{submitError}</p>}
          {severalPdfs ? (
            <p id="run-hint" role="status" data-testid="one-pdf-only" className="mt-6 flex gap-2 rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.95rem]">
              <AlertTriangle size={17} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
              <span>{severalPdfs.choice.op.label} works on one PDF at a time, because what you place is drawn on that PDF&apos;s pages. Remove the other PDFs, then do them one by one.</span>
            </p>
          ) : nothingYet && (
            <p id="run-hint" data-testid="nothing-placed" className="mt-6 text-[0.95rem] text-muted">Nothing to apply yet: use the tools above on the page first.</p>
          )}
          <button onClick={submit} disabled={!canRun} data-testid="convert" aria-describedby={severalPdfs || nothingYet ? "run-hint" : undefined}
            className="mt-6 w-full rounded-[var(--radius-control)] bg-accent px-6 py-3.5 text-lg font-semibold text-accent-ink transition-opacity duration-150 hover:opacity-90 disabled:opacity-40 sm:w-auto">
            {submitting ? "Starting…" : uploading ? "Waiting for uploads…" : ready.length > 1 && !combined && planned.every((p) => p.choice.op.cardinality !== "many_to_one") ? `Convert ${ready.length} files` : "Convert"}
          </button>
        </section>
      )}

      {/* jobs & results */}
      {runs.length > 0 && (
        <section aria-labelledby="results-h" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="results-h" className="font-display text-2xl font-semibold">{active ? "Converting" : "Results"}</h2>
            <div className="flex flex-wrap gap-2">
              {totalOutputs > 1 && batchId && (
                <a href={batchZipUrl(batchId)} download data-testid="download-zip"
                  className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line bg-surface px-4 py-2 font-medium hover:border-line-strong">
                  <FileArchive size={16} aria-hidden="true" /> Download all (ZIP)
                </a>
              )}
              <button onClick={deleteAll} data-testid="delete-now" className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line bg-surface px-4 py-2 font-medium hover:border-line-strong">
                <Trash2 size={16} aria-hidden="true" /> Delete now
              </button>
              {!active && (
                <button onClick={startOver} className="rounded-[var(--radius-control)] bg-ink px-4 py-2 font-medium text-paper hover:opacity-90">Convert another</button>
              )}
            </div>
          </div>
          {submitError && <p role="alert" className="rounded-[var(--radius-control)] bg-danger-soft p-3">{submitError}</p>}
          <ul className="flex flex-col gap-3">
            {runs.map((r) => (
              <JobCard key={r.jobId} run={r} onCancel={() => void cancelJob(r.jobId).then((j) => updateRun(r.jobId, j))} onRetry={() => void retry(r)} />
            ))}
          </ul>
          {caps && <p className="text-[0.9rem] text-muted">Results are deleted automatically {caps.limits.retention_minutes} minutes after upload.</p>}
        </section>
      )}
    </div>
  );
}
