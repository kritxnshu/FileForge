// JSON formatting, code beautify/minify, HTML↔Markdown, CSV→SQL, Base64, URL encoding, timestamps.

import Papa from "papaparse";
import { parseJson } from "./data";
import { ToolError, type ToolInput, type ToolResult } from "./types";

// ---------------------------------------------------------------------------
// JSON

function sortDeep(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortDeep);
  if (v && typeof v === "object")
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortDeep((v as Record<string, unknown>)[k])]));
  return v;
}

export function jsonFormat({ text, options }: ToolInput): ToolResult {
  if (!text.trim()) throw new ToolError("Paste some JSON.");
  let v = parseJson(text);
  if (options.sort_keys) v = sortDeep(v);
  const mode = (options.mode as string) ?? "format";
  if (mode === "validate") {
    const kind = Array.isArray(v) ? `an array of ${v.length} item${v.length === 1 ? "" : "s"}` : v && typeof v === "object" ? `an object with ${Object.keys(v).length} key${Object.keys(v).length === 1 ? "" : "s"}` : `a ${typeof v}`;
    return { output: text, notices: [`Valid JSON: ${kind}.`] };
  }
  if (mode === "minify") return { output: JSON.stringify(v) };
  return { output: JSON.stringify(v, null, Number(options.indent ?? 2)) + "\n" };
}

// ---------------------------------------------------------------------------
// code

function minifySql(sql: string): string {
  let out = "";
  let i = 0;
  let pendingSpace = false;
  while (i < sql.length) {
    const c = sql[i];
    if (c === "'" || c === '"' || c === "`") {
      let j = i + 1;
      while (j < sql.length) {
        if (sql[j] === c && sql[j + 1] === c) j += 2;
        else if (sql[j] === c) break;
        else j++;
      }
      if (pendingSpace && out && !/[\s(,;=<>+\-*/]$/.test(out)) out += " ";
      pendingSpace = false;
      out += sql.slice(i, j + 1);
      i = j + 1;
    } else if (c === "-" && sql[i + 1] === "-") {
      while (i < sql.length && sql[i] !== "\n") i++;
      pendingSpace = true;
    } else if (c === "/" && sql[i + 1] === "*") {
      const end = sql.indexOf("*/", i + 2);
      i = end < 0 ? sql.length : end + 2;
      pendingSpace = true;
    } else if (/\s/.test(c)) {
      pendingSpace = true;
      i++;
    } else {
      if (pendingSpace && out && !/[(,;=<>+\-*/]$/.test(out) && !/[),;=<>+\-*/]/.test(c)) out += " ";
      pendingSpace = false;
      out += c;
      i++;
    }
  }
  return out.trim();
}

export async function codeFormat({ text, source, options }: ToolInput): Promise<ToolResult> {
  if (!text.trim()) throw new ToolError("Paste some code.");
  const mode = (options.mode as string) ?? "beautify";
  const indent = Number(options.indent ?? 2);
  try {
    if (source === "css") {
      if (mode === "minify") {
        const { minify } = await import("csso");
        return { output: minify(text).css };
      }
      const [prettier, postcss] = await Promise.all([import("prettier/standalone"), import("prettier/plugins/postcss")]);
      return { output: await prettier.format(text, { parser: "css", plugins: [postcss], tabWidth: indent }) };
    }
    if (source === "js") {
      if (mode === "minify") {
        const { minify } = await import("terser");
        const r = await minify(text, { compress: true, mangle: true });
        return { output: r.code ?? "" };
      }
      const [prettier, babel, estree] = await Promise.all([
        import("prettier/standalone"), import("prettier/plugins/babel"), import("prettier/plugins/estree"),
      ]);
      return { output: await prettier.format(text, { parser: "babel", plugins: [babel, estree], tabWidth: indent }) };
    }
    if (source === "sql") {
      if (mode === "minify") return { output: minifySql(text) };
      const { format } = await import("sql-formatter");
      return { output: format(text, { tabWidth: indent, keywordCase: "upper" }) + "\n" };
    }
    if (source === "xml") {
      const xmlFormat = (await import("xml-formatter")).default;
      if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new ToolError("XML with DTDs or entities isn't accepted, for security reasons.");
      const { XMLValidator } = await import("fast-xml-parser");
      const ok = XMLValidator.validate(text);
      if (ok !== true) throw new ToolError(`This XML couldn't be parsed at line ${ok.err.line}, column ${ok.err.col}: ${ok.err.msg}`, { line: ok.err.line, column: ok.err.col });
      return {
        output: mode === "minify"
          ? xmlFormat.minify(text, { collapseContent: true })
          : xmlFormat(text, { indentation: " ".repeat(indent), collapseContent: true, lineSeparator: "\n" }) + "\n",
      };
    }
  } catch (e) {
    if (e instanceof ToolError) throw e;
    const err = e as { message: string; loc?: { start?: { line: number; column: number } }; line?: number; col?: number };
    const loc = err.loc?.start ?? (err.line ? { line: err.line, column: err.col ?? 0 } : undefined);
    throw new ToolError(`This ${source.toUpperCase()} couldn't be parsed${loc ? ` at line ${loc.line}, column ${loc.column}` : ""}: ${err.message.split("\n")[0]}`, loc);
  }
  throw new ToolError(`Unsupported language: ${source}`);
}

// ---------------------------------------------------------------------------
// HTML ↔ Markdown

export async function htmlMarkdown({ text, source }: ToolInput): Promise<ToolResult> {
  if (!text.trim()) throw new ToolError("Paste some " + (source === "html" ? "HTML" : "Markdown") + ".");
  if (source === "html") {
    const { NodeHtmlMarkdown } = await import("node-html-markdown");
    return { output: NodeHtmlMarkdown.translate(text) + "\n", notices: ["Scripts, styles and forms are dropped."] };
  }
  const { marked } = await import("marked");
  return { output: (await marked.parse(text, { async: true, gfm: true })) as string };
}

// ---------------------------------------------------------------------------
// CSV → SQL

const quoteIdent = (n: string, d: string) =>
  d === "mysql" ? "`" + n.replace(/`/g, "``") + "`" : d === "sqlserver" ? "[" + n.replace(/]/g, "]]") + "]" : '"' + n.replace(/"/g, '""') + '"';
const sqlLiteral = (v: string) => (v === "" ? "NULL" : /^-?(0|[1-9]\d{0,17})(\.\d+)?$/.test(v) ? v : "'" + v.replace(/'/g, "''") + "'");

export function csvToSql({ text, source, options }: ToolInput): ToolResult {
  const res = Papa.parse<string[]>(text.trim(), { delimiter: source === "tsv" ? "\t" : "", skipEmptyLines: true });
  const [head, ...body] = res.data;
  if (!head?.length) throw new ToolError("This CSV has no header row.");
  const d = (options.dialect as string) ?? "postgres";
  const table = (options.table as string) ?? "my_table";
  if (!/^[A-Za-z_][A-Za-z0-9_]{0,62}$/.test(table)) throw new ToolError("Table names can use letters, numbers and _ only.");
  const cols = head.map((h, i) => quoteIdent(h || `column_${i + 1}`, d));
  const out: string[] = [];
  if (options.create_table !== false) {
    const typ = (i: number) => {
      const vals = body.map((r) => r[i] ?? "").filter((v) => v !== "");
      if (vals.length && vals.every((v) => /^-?\d{1,18}$/.test(v))) return d === "sqlite" ? "INTEGER" : "BIGINT";
      if (vals.length && vals.every((v) => /^-?\d+(\.\d+)?$/.test(v))) return d === "sqlite" ? "REAL" : "NUMERIC";
      return d === "sqlserver" ? "NVARCHAR(MAX)" : "TEXT";
    };
    out.push(`CREATE TABLE ${quoteIdent(table, d)} (\n  ${cols.map((c, i) => `${c} ${typ(i)}`).join(",\n  ")}\n);\n`);
  }
  for (let k = 0; k < body.length; k += 100) {
    const values = body.slice(k, k + 100).map((r) => "(" + head.map((_, i) => sqlLiteral(r[i] ?? "")).join(", ") + ")");
    out.push(`INSERT INTO ${quoteIdent(table, d)} (${cols.join(", ")}) VALUES\n  ${values.join(",\n  ")};\n`);
  }
  return { output: out.join("\n"), notices: [`Generated INSERT statements for ${body.length} row${body.length === 1 ? "" : "s"}.`] };
}

// ---------------------------------------------------------------------------
// Base64 / URL

export function bytesToBase64(bytes: Uint8Array, urlSafe = false): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  const b = btoa(bin);
  return urlSafe ? b.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "") : b;
}

export function base64ToBytes(s: string): Uint8Array {
  const clean = s.trim().replace(/^data:[^,]*;base64,/, "").replace(/\s+/g, "").replace(/-/g, "+").replace(/_/g, "/");
  if (!/^[A-Za-z0-9+/]*=*$/.test(clean)) throw new ToolError("That isn't valid Base64: it contains characters outside A–Z, a–z, 0–9, + / (or - _).");
  const padded = clean + "=".repeat((4 - (clean.length % 4)) % 4);
  let bin: string;
  try {
    bin = atob(padded);
  } catch {
    throw new ToolError("That isn't valid Base64.");
  }
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

export function base64({ text, bytes, options }: ToolInput): ToolResult {
  const urlSafe = Boolean(options.url_safe);
  if ((options.direction ?? "encode") === "encode") {
    const data = bytes ?? new TextEncoder().encode(text);
    return { output: bytesToBase64(data, urlSafe) };
  }
  if (!text.trim()) throw new ToolError("Paste Base64 to decode.");
  const out = base64ToBytes(text);
  try {
    return { output: new TextDecoder("utf-8", { fatal: true }).decode(out), bytes: out };
  } catch {
    return { output: "", bytes: out, mime: "application/octet-stream", notices: ["The decoded data isn't text; download it as a file."] };
  }
}

export function url({ text, options }: ToolInput): ToolResult {
  const full = options.mode === "full";
  if ((options.direction ?? "encode") === "encode") return { output: full ? encodeURI(text) : encodeURIComponent(text) };
  try {
    return { output: full ? decodeURI(text.replace(/\+/g, " ")) : decodeURIComponent(text.replace(/\+/g, " ")) };
  } catch {
    throw new ToolError("This text has a malformed % escape (for example “%E0%A4%A” is cut short).");
  }
}

// ---------------------------------------------------------------------------
// timestamps

export function timestamp({ text, options }: ToolInput): ToolResult {
  const tz = (options.timezone as string) || "UTC";
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
  } catch {
    throw new ToolError(`Unknown time zone “${tz}”. Use a name like Europe/Berlin or America/New_York.`);
  }
  const s = text.trim();
  if (!s) throw new ToolError("Enter a Unix timestamp or a date.");
  let ms: number;
  const notices: string[] = [];
  if (/^-?\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    const isMs = Math.abs(n) >= 1e11;
    ms = isMs ? n : n * 1000;
    notices.push(isMs ? "Read as milliseconds (13 digits)." : "Read as seconds.");
  } else {
    ms = Date.parse(s);
    if (Number.isNaN(ms)) throw new ToolError("That isn't a timestamp or a date we recognize. Try 1700000000 or 2024-05-01T12:00:00Z.");
  }
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) throw new ToolError("That date is out of range.");
  const local = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, dateStyle: "full", timeStyle: "long",
  }).format(d);
  const lines = [
    `Unix seconds:      ${Math.floor(ms / 1000)}`,
    `Unix milliseconds: ${Math.round(ms)}`,
    `ISO 8601 (UTC):    ${d.toISOString()}`,
    `${tz}: ${local}`,
  ];
  return { output: lines.join("\n") + "\n", notices, data: { ms } };
}
