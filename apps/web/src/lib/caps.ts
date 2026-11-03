import type { Capabilities, Operation, Pair, SupportLevel } from "./api";

export interface Choice {
  op: Operation;
  pair: Pair;
}

export interface ToolEntry {
  slug: string;
  title: string;
  description: string;
  op: Operation;
  pair: Pair;
  category: string;
  kind: "convert" | "tool";
  sourceTerms: string[];
  targetTerms: string[];
  otherTerms: string[];
}

export const SUPPORT_LABEL: Record<SupportLevel, string> = {
  full: "Full",
  partial: "Partial",
  experimental: "Experimental",
};

export function fmtLabel(caps: Capabilities, id: string): string {
  return caps.formats[id]?.label ?? id.toUpperCase();
}

/** Short label for format chips: "Word (DOCX)" → "DOCX", "PNG" → "PNG". */
export function fmtShort(caps: Capabilities, id: string): string {
  const l = caps.formats[id]?.label ?? id;
  const m = l.match(/\(([^)]+)\)/);
  if (m) return m[1];
  return l.length <= 6 ? l : id.toUpperCase();
}

export function isConversion(op: Operation): boolean {
  return op.cardinality !== "transform";
}

export function choicesFor(caps: Capabilities, format: string, opts: { combine?: boolean } = {}): Choice[] {
  const out: Choice[] = [];
  for (const op of caps.operations) {
    if (op.runtime !== "server") continue;
    if (op.combine_only && !opts.combine) continue;
    for (const pair of op.pairs) if (pair.source === format) out.push({ op, pair });
  }
  return out;
}

export function choiceKey(c: { op: Operation; pair: Pair } | null): string {
  return c ? `${c.op.id}|${c.pair.target}` : "";
}

function termsFor(caps: Capabilities, id: string): string[] {
  const f = caps.formats[id];
  if (!f) return [id];
  const words = f.label
    .toLowerCase()
    .replace(/[()]/g, " ")
    .split(/[\s/-]+/)
    .filter((w) => w.length > 1 && !/^\d+$/.test(w));
  return Array.from(new Set([id, ...f.exts, ...words]));
}

export function toolTitle(caps: Capabilities, op: Operation, pair: Pair): string {
  if (op.cardinality === "transform") {
    return op.pairs.length > 1 ? `${op.label} (${fmtShort(caps, pair.source)})` : op.label;
  }
  if (op.cardinality === "many_to_one" && op.pairs.every((p) => p.target === pair.target) && op.pairs.length > 1) {
    return `${op.label} (${fmtShort(caps, pair.source)})`;
  }
  return `${fmtShort(caps, pair.source)} to ${fmtShort(caps, pair.target)}`;
}

export function toolEntries(caps: Capabilities): ToolEntry[] {
  const out: ToolEntry[] = [];
  for (const op of caps.operations) {
    for (const pair of op.pairs) {
      if (!pair.primary) continue;
      const kind = op.cardinality === "transform" ? "tool" : "convert";
      out.push({
        slug: pair.slug,
        title: toolTitle(caps, op, pair),
        description: op.description,
        op,
        pair,
        category: op.category,
        kind,
        sourceTerms: termsFor(caps, pair.source),
        targetTerms: kind === "tool" ? [] : termsFor(caps, pair.target),
        otherTerms: [
          ...op.label.toLowerCase().split(/\s+/),
          ...op.keywords.flatMap((k) => k.toLowerCase().split(/\s+/)),
          op.category,
          caps.formats[pair.source]?.family ?? "",
        ].filter(Boolean),
      });
    }
  }
  // category order as declared by the API (Images first, Utilities last); stable within a category
  const rank = new Map(caps.categories.map((c, i) => [c.id, i]));
  return out.sort((a, b) => (rank.get(a.category) ?? 99) - (rank.get(b.category) ?? 99));
}

/** A cross-section for previews: round-robin across categories, in category order. */
export function sampleAcrossCategories(entries: ToolEntry[], n: number): ToolEntry[] {
  const byCat = new Map<string, ToolEntry[]>();
  for (const e of entries) byCat.set(e.category, [...(byCat.get(e.category) ?? []), e]);
  const lists = [...byCat.values()];
  const out: ToolEntry[] = [];
  for (let i = 0; out.length < n && lists.some((l) => i < l.length); i++) {
    for (const l of lists) if (i < l.length && out.length < n) out.push(l[i]);
  }
  return out;
}

export function findBySlug(caps: Capabilities, slug: string): ToolEntry | undefined {
  return toolEntries(caps).find((e) => e.slug === slug);
}

/** A format id from a URL token: the id itself or one of its extensions ("jpeg" → "jpg"). */
export function resolveFormat(caps: Capabilities, token: string): string | null {
  const t = token.toLowerCase();
  if (caps.formats[t]) return t;
  const hit = Object.entries(caps.formats).find(([, f]) => f.exts.includes(t));
  return hit ? hit[0] : null;
}

/** For a "<a>-to-<b>" slug that names two known formats but no advertised conversion. */
export function unsupportedPair(caps: Capabilities, slug: string): { source: string; target: string } | null {
  const m = slug.toLowerCase().match(/^([a-z0-9]+)-to-([a-z0-9]+)$/);
  if (!m) return null;
  const source = resolveFormat(caps, m[1]);
  const target = resolveFormat(caps, m[2]);
  if (!source || !target) return null;
  const served = toolEntries(caps).some((e) => e.kind === "convert" && e.pair.source === source && e.pair.target === target);
  return served ? null : { source, target };
}

/** Conversion pages for files of this format (one per target), for "try instead" links. */
export function conversionsFrom(caps: Capabilities, source: string): ToolEntry[] {
  const seen = new Set<string>();
  return toolEntries(caps).filter((e) => {
    if (e.kind !== "convert" || e.op.runtime !== "server" || e.pair.source !== source || seen.has(e.pair.target)) return false;
    seen.add(e.pair.target);
    return true;
  });
}

// ---------------------------------------------------------------------------
// search: token-based, typo-tolerant, direction-aware ("word to pdf" ≠ "pdf to word")

const STOP = new Set(["to", "into", "convert", "converter", "from", "a", "an", "the", "file", "files", "online", "->", "→", "2"]);

function lev1(a: string, b: string): boolean {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i++;
      j++;
      continue;
    }
    if (++edits > 1) return false;
    if (a.length > b.length) i++;
    else if (b.length > a.length) j++;
    else if (a[i + 1] === b[j] && a[i] === b[j + 1]) {
      i += 2;
      j += 2;
    } else {
      i++;
      j++;
    }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

function tokenScore(q: string, terms: string[]): number {
  let best = 0;
  for (const t of terms) {
    if (t === q) return 3;
    if (t.startsWith(q) && q.length >= 2) best = Math.max(best, 2);
    else if (q.length >= 4 && lev1(q, t)) best = Math.max(best, 1.5);
    else if (q.length >= 3 && t.includes(q)) best = Math.max(best, 1);
  }
  return best;
}

export function searchTools(entries: ToolEntry[], query: string): ToolEntry[] {
  const tokens = query
    .toLowerCase()
    .replace(/[→>]/g, " ")
    .split(/[\s,]+/)
    .filter((t) => t && !STOP.has(t));
  if (!tokens.length) return entries;
  const scored: { e: ToolEntry; s: number }[] = [];
  for (const e of entries) {
    let total = 0;
    let ok = true;
    tokens.forEach((tok, idx) => {
      const src = tokenScore(tok, e.sourceTerms);
      const dst = tokenScore(tok, e.targetTerms);
      const other = tokenScore(tok, e.otherTerms) * 0.6;
      let s = Math.max(src, dst, other);
      if (s === 0) ok = false;
      // direction bonus: first format token should be the source, a later one the target
      if (tokens.length >= 2) {
        if (idx === 0 && src >= dst && src > 0) s += 1;
        if (idx > 0 && dst >= src && dst > 0) s += 1;
      }
      total += s;
    });
    if (ok) scored.push({ e, s: total + (e.kind === "convert" ? 0.1 : 0) });
  }
  return scored.sort((a, b) => b.s - a.s).map((x) => x.e);
}

export function formatBytes(n: number): string {
  if (n < 1000) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let i = -1;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function sizeDelta(before: number, after: number): { text: string; smaller: boolean } {
  if (!before) return { text: "", smaller: false };
  const pct = Math.round(((after - before) / before) * 100);
  if (pct === 0) return { text: "same size", smaller: false };
  return { text: pct < 0 ? `${-pct}% smaller` : `${pct}% larger`, smaller: pct < 0 };
}
