"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, uploadFormFields, type FormField } from "@/lib/api";

type Values = Record<string, string | boolean | string[]>;

const human = (name: string) => {
  const s = name.replace(/[_.]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

/** Fill a PDF form: every field the PDF defines, with the right control for its type. */
export function PdfFormFill({ fileId, value, onChange }: { fileId: string; value: Values | undefined; onChange: (v: Values) => void }) {
  const [state, setState] = useState<{ key: string; fields?: FormField[]; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    uploadFormFields(fileId)
      .then((d) => live && setState({ key: fileId, fields: d.fields }))
      .catch((e) => live && setState({ key: fileId, error: e instanceof ApiError ? e.message : "This form couldn't be read." }));
    return () => {
      live = false;
    };
  }, [fileId]);
  const cur = state?.key === fileId ? state : null;
  if (cur?.error) {
    return (
      <p role="alert" className="rounded-[var(--radius-control)] bg-warn-soft p-3">
        {cur.error} <Link href="/pdf/create-pdf-form" className="font-medium underline underline-offset-4">Create a form</Link>
      </p>
    );
  }
  if (!cur?.fields) return <p className="text-muted">Reading the form…</p>;
  const values = value ?? {};
  const set = (name: string, v: string | boolean) => onChange({ ...values, [name]: v });
  const input = "w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 disabled:opacity-60";
  const fillable = cur.fields.filter((f) => f.type !== "signature" && f.type !== "button");
  const byPage = new Map<number, FormField[]>();
  for (const f of fillable) {
    const p = f.widgets[0]?.page ?? 1;
    byPage.set(p, [...(byPage.get(p) ?? []), f]);
  }

  return (
    <div className="flex flex-col gap-6" data-testid="pdf-form-fill">
      <p className="text-[0.92rem] text-muted">{fillable.length} field{fillable.length === 1 ? "" : "s"} found. Leave a field empty to keep what&apos;s there.</p>
      {[...byPage.entries()].sort(([a], [b]) => a - b).map(([page, fields]) => (
        <fieldset key={page} className="flex flex-col gap-4 rounded-[var(--radius-control)] border border-line p-4">
          <legend className="px-1 font-medium">Page {page}</legend>
          {fields.map((f) => {
            const id = `ff-${f.name}`;
            const v = values[f.name] ?? f.value ?? (f.type === "checkbox" ? false : "");
            const req = f.required ? <span className="text-danger" aria-hidden="true"> *</span> : null;
            if (f.type === "checkbox") {
              return (
                <label key={f.name} className="flex items-center gap-2">
                  <input type="checkbox" checked={v === true} disabled={f.read_only} onChange={(e) => set(f.name, e.target.checked)}
                    className="h-4 w-4 accent-[var(--accent)]" data-field={f.name} />
                  {human(f.name)}{req}
                </label>
              );
            }
            if (f.type === "radio") {
              return (
                <fieldset key={f.name}>
                  <legend className="mb-1.5 font-medium">{human(f.name)}{req}</legend>
                  <div className="flex flex-wrap gap-4">
                    {(f.options ?? []).map((o) => (
                      <label key={o} className="flex items-center gap-1.5">
                        <input type="radio" name={id} checked={v === o} disabled={f.read_only} onChange={() => set(f.name, o)} className="accent-[var(--accent)]" data-field={`${f.name}:${o}`} />
                        {human(o)}
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            }
            return (
              <div key={f.name}>
                <label htmlFor={id} className="mb-1.5 block font-medium">{human(f.name)}{req}</label>
                {f.type === "choice" ? (
                  <select id={id} value={String(v)} disabled={f.read_only} onChange={(e) => set(f.name, e.target.value)} className={input} data-field={f.name}>
                    {!f.options?.includes(String(v)) && <option value={String(v)}>{String(v) || "—"}</option>}
                    {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : f.multiline ? (
                  <textarea id={id} rows={3} value={String(v)} disabled={f.read_only} onChange={(e) => set(f.name, e.target.value)} className={input} data-field={f.name} />
                ) : (
                  <input id={id} value={String(v)} disabled={f.read_only} required={f.required} onChange={(e) => set(f.name, e.target.value)} className={input} data-field={f.name} />
                )}
              </div>
            );
          })}
        </fieldset>
      ))}
    </div>
  );
}
