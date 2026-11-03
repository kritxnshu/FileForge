"use client";

// Builds a settings form from an operation's JSON Schema (exported from its Pydantic model).
// Supported: integer/number (input or slider), boolean (switch), string (text, color, enum select),
// arrays of enums (multi-select chips), and Optional[...] (anyOf with null).
// Hints: x-advanced, x-widget, x-targets, x-unit, x-placeholder.

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import type { JsonSchema } from "@/lib/api";

export type OptionValues = Record<string, unknown>;

function unwrap(s: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  if (s.anyOf) {
    const nonNull = s.anyOf.filter((x) => x.type !== "null");
    return { schema: { ...nonNull[0], ...omit(s, ["anyOf"]) }, nullable: nonNull.length < s.anyOf.length };
  }
  return { schema: s, nullable: false };
}

function omit<T extends object>(o: T, keys: string[]): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([k]) => !keys.includes(k))) as Partial<T>;
}

export function defaultsOf(schema: JsonSchema): OptionValues {
  const out: OptionValues = {};
  for (const [k, v] of Object.entries(schema.properties ?? {})) if (v.default !== undefined) out[k] = v.default;
  return out;
}

export function visibleFields(schema: JsonSchema, target: string | null): [string, JsonSchema][] {
  return Object.entries(schema.properties ?? {}).filter(([, s]) => {
    const t = s["x-targets"];
    return !t || !target || t.includes(target);
  });
}

/** Only send fields that apply to this target and differ from defaults. */
export function cleanOptions(schema: JsonSchema, target: string | null, values: OptionValues): OptionValues {
  const out: OptionValues = {};
  for (const [k, s] of visibleFields(schema, target)) {
    if (k in values && JSON.stringify(values[k]) !== JSON.stringify(s.default)) out[k] = values[k];
  }
  return out;
}

function Field({ name, schema, value, onChange }: { name: string; schema: JsonSchema; value: unknown; onChange: (v: unknown) => void }) {
  const id = useId();
  const { schema: s, nullable } = unwrap(schema);
  const label = s.title ?? name;
  const help = s.description;
  const helpId = help ? `${id}-help` : undefined;
  const base =
    "w-full rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-ink placeholder:text-muted focus-visible:border-accent";

  let control: React.ReactNode;
  if (s.type === "boolean") {
    return (
      <div className="flex items-start justify-between gap-4 py-1">
        <div>
          <label htmlFor={id} className="font-medium">{label}</label>
          {help && <p id={helpId} className="text-[0.9rem] text-muted">{help}</p>}
        </div>
        <button
          id={id}
          type="button"
          role="switch"
          aria-checked={Boolean(value)}
          aria-describedby={helpId}
          onClick={() => onChange(!value)}
          className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors duration-150 ${value ? "bg-accent" : "bg-line-strong"}`}
        >
          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface transition-transform duration-150 ${value ? "translate-x-[1.375rem]" : "translate-x-0.5"}`} />
        </button>
      </div>
    );
  }
  if (s.type === "array" && s.items?.enum) {
    const arr = Array.isArray(value) ? (value as unknown[]) : [];
    control = (
      <div role="group" aria-labelledby={`${id}-l`} aria-describedby={helpId} className="flex flex-wrap gap-2">
        {s.items.enum.map((opt) => {
          const on = arr.includes(opt);
          return (
            <button
              key={String(opt)}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? arr.filter((x) => x !== opt) : [...arr, opt].sort((a, b) => (a as number) - (b as number)))}
              className={`rounded-full border px-3 py-1 text-[0.9rem] transition-colors duration-150 ${on ? "border-accent bg-accent-soft text-ink" : "border-line text-muted hover:text-ink"}`}
            >
              {String(opt)}{s["x-unit"] ? ` ${s["x-unit"]}` : ""}
            </button>
          );
        })}
      </div>
    );
    return (
      <div>
        <span id={`${id}-l`} className="mb-1.5 block font-medium">{label}</span>
        {control}
        {help && <p id={helpId} className="mt-1.5 text-[0.9rem] text-muted">{help}</p>}
      </div>
    );
  }
  if (s.enum) {
    control = (
      <select id={id} aria-describedby={helpId} className={base} value={String(value ?? "")} onChange={(e) => {
        const raw = e.target.value;
        const match = s.enum!.find((x) => String(x) === raw);
        onChange(match ?? raw);
      }}>
        {nullable && <option value="">—</option>}
        {s.enum.map((o) => (
          <option key={String(o)} value={String(o)}>{String(o)}</option>
        ))}
      </select>
    );
  } else if (s.type === "integer" || s.type === "number") {
    const step = s["x-step"] ?? (s.type === "integer" ? 1 : 0.1);
    if (s["x-widget"] === "slider" && s.minimum !== undefined && s.maximum !== undefined) {
      control = (
        <div className="flex items-center gap-3">
          <input id={id} type="range" aria-describedby={helpId} min={s.minimum} max={s.maximum} step={step}
            value={Number(value ?? s.default ?? s.minimum)} onChange={(e) => onChange(Number(e.target.value))}
            className="flex-1 accent-[var(--accent)]" />
          <output htmlFor={id} className="w-12 text-right tabular-nums">{String(value ?? s.default)}</output>
        </div>
      );
    } else {
      control = (
        <div className="flex items-center gap-2">
          <input id={id} type="number" aria-describedby={helpId} className={base} min={s.minimum ?? s.exclusiveMinimum} max={s.maximum} step={step}
            placeholder={s["x-placeholder"] ?? (nullable ? "Auto" : undefined)}
            value={value === null || value === undefined ? "" : String(value)}
            onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : s.default) : Number(e.target.value))} />
          {s["x-unit"] && <span className="text-muted">{s["x-unit"]}</span>}
        </div>
      );
    }
  } else if (s["x-widget"] === "color") {
    control = (
      <div className="flex items-center gap-2">
        <input id={id} type="color" aria-describedby={helpId} value={String(value ?? "#ffffff")} onChange={(e) => onChange(e.target.value)}
          className="h-10 w-14 cursor-pointer rounded-[var(--radius-control)] border border-line bg-surface p-1" />
        <code className="text-muted">{String(value ?? "")}</code>
      </div>
    );
  } else {
    const multiline = s["x-widget"] === "textarea";
    control = multiline ? (
      <textarea id={id} aria-describedby={helpId} className={`${base} min-h-24`} maxLength={s.maxLength}
        placeholder={s["x-placeholder"]} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || (nullable ? null : ""))} />
    ) : (
      <input id={id} type={s["x-widget"] === "password" ? "password" : "text"} autoComplete="off" aria-describedby={helpId} className={base}
        maxLength={s.maxLength} placeholder={s["x-placeholder"]} value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value || (nullable ? null : ""))} />
    );
  }
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block font-medium">{label}</label>
      {control}
      {help && <p id={helpId} className="mt-1.5 text-[0.9rem] text-muted">{help}</p>}
    </div>
  );
}

export function OptionsForm({ schema, target, values, onChange }: {
  schema: JsonSchema;
  target: string | null;
  values: OptionValues;
  onChange: (v: OptionValues) => void;
}) {
  const [open, setOpen] = useState(false);
  const fields = visibleFields(schema, target);
  const basic = fields.filter(([, s]) => !s["x-advanced"]);
  const advanced = fields.filter(([, s]) => s["x-advanced"]);
  if (!fields.length) return <p className="text-muted">No settings needed for this conversion.</p>;
  const set = (k: string) => (v: unknown) => onChange({ ...values, [k]: v });
  return (
    <div className="flex flex-col gap-5" data-testid="options-form">
      {basic.map(([k, s]) => <Field key={k} name={k} schema={s} value={values[k] ?? s.default} onChange={set(k)} />)}
      {advanced.length > 0 && (
        <div className="border-t border-line pt-3">
          <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
            className="flex items-center gap-1.5 rounded-md font-medium text-muted hover:text-ink">
            <ChevronDown size={16} className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`} aria-hidden="true" />
            Advanced
          </button>
          {open && (
            <div className="mt-4 flex flex-col gap-5">
              {advanced.map(([k, s]) => <Field key={k} name={k} schema={s} value={values[k] ?? s.default} onChange={set(k)} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
