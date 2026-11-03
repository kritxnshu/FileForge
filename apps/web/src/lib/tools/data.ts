// Structured data conversion in the browser. Same mapping as the server (engine/converters/developer/data.py):
// XML attributes ↔ "@name", element text ↔ "#text", one root element (otherwise wrapped in <root>),
// nested objects → dotted CSV columns, arrays → JSON text in CSV cells.

import * as yaml from "js-yaml";
import Papa from "papaparse";
import { parse as parseToml, stringify as stringifyToml } from "smol-toml";
import { XMLBuilder, XMLParser, XMLValidator } from "fast-xml-parser";
import { ToolError, type ToolResult } from "./types";

const MAX_NODES = 2_000_000;
const MAX_DEPTH = 200;

export function lineCol(text: string, pos: number): { line: number; column: number } {
  const before = text.slice(0, pos);
  const line = before.split("\n").length;
  return { line, column: pos - before.lastIndexOf("\n") };
}

/** Offset of the first syntax error in a JSON text (engines don't always report one). */
export function jsonErrorOffset(t: string): number {
  let i = 0;
  const ws = () => { while (i < t.length && " \t\n\r".includes(t[i])) i++; };
  const fail = (): never => { throw i; };
  const lit = (w: string) => { if (t.startsWith(w, i)) i += w.length; else fail(); };
  const str = () => {
    i++;
    while (i < t.length && t[i] !== '"') {
      if (t[i] === "\\") {
        i++;
        if (t[i] === "u") { if (!/^[0-9a-fA-F]{4}$/.test(t.slice(i + 1, i + 5))) fail(); i += 4; }
        else if (!'"\\/bfnrt'.includes(t[i] ?? "")) fail();
      } else if (t.charCodeAt(i) < 0x20) fail();
      i++;
    }
    if (t[i] !== '"') fail();
    i++;
  };
  const num = () => {
    const m = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(t.slice(i));
    if (!m || !m[0]) fail();
    i += m![0].length;
  };
  const val = (): void => {
    ws();
    const c = t[i];
    if (c === "{") {
      i++; ws();
      if (t[i] === "}") { i++; return; }
      for (;;) {
        ws(); if (t[i] !== '"') fail(); str(); ws();
        if (t[i] !== ":") fail(); i++; val(); ws();
        if (t[i] === ",") { i++; continue; }
        if (t[i] === "}") { i++; return; }
        fail();
      }
    } else if (c === "[") {
      i++; ws();
      if (t[i] === "]") { i++; return; }
      for (;;) {
        val(); ws();
        if (t[i] === ",") { i++; continue; }
        if (t[i] === "]") { i++; return; }
        fail();
      }
    } else if (c === '"') str();
    else if (c === "t") lit("true");
    else if (c === "f") lit("false");
    else if (c === "n") lit("null");
    else num();
  };
  try {
    val(); ws();
    if (i < t.length) fail();
  } catch (pos) {
    if (typeof pos === "number") return pos;
    throw pos;
  }
  return -1;
}

export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch (e) {
    const msg = (e as Error).message;
    const lc = msg.match(/line (\d+) column (\d+)/);
    const pos = msg.match(/position (\d+)/);
    const off = lc || pos ? -1 : jsonErrorOffset(text);
    const where = lc ? { line: Number(lc[1]), column: Number(lc[2]) } : pos ? lineCol(text, Number(pos[1])) : off >= 0 ? lineCol(text, off) : null;
    const reason = msg.replace(/^JSON\.parse: /, "").replace(/ in JSON at position \d+.*$/, "").replace(/\s*\(line \d+ column \d+\)/, "")
      .replace(/, "[\s\S]*" is not valid JSON$/, "");
    throw new ToolError(`Invalid JSON${where ? ` at line ${where.line}, column ${where.column}` : ""}: ${reason}`, where ?? undefined);
  }
}

function budget(v: unknown) {
  let n = 0;
  const stack: [unknown, number][] = [[v, 0]];
  while (stack.length) {
    const [cur, d] = stack.pop()!;
    if (++n > MAX_NODES) throw new ToolError("This data expands to too many values to convert safely.");
    if (d > MAX_DEPTH) throw new ToolError("This data is nested too deeply to convert.");
    if (Array.isArray(cur)) cur.forEach((x) => stack.push([x, d + 1]));
    else if (cur && typeof cur === "object") Object.values(cur).forEach((x) => stack.push([x, d + 1]));
  }
}

const xmlOpts = {
  ignoreAttributes: false,
  attributeNamePrefix: "@",
  textNodeName: "#text",
  parseTagValue: false,
  parseAttributeValue: false,
  trimValues: true,
  processEntities: true,
  htmlEntities: false,
  ignoreDeclaration: true,
  ignorePiTags: true,
};

export function parseAs(fmt: string, text: string): unknown {
  let v: unknown;
  switch (fmt) {
    case "json":
      v = parseJson(text);
      break;
    case "yaml":
      try {
        v = yaml.load(text, { schema: yaml.CORE_SCHEMA, json: true });
      } catch (e) {
        const m = (e as { mark?: { line: number; column: number }; reason?: string }).mark;
        throw new ToolError(`Invalid YAML${m ? ` at line ${m.line + 1}, column ${m.column + 1}` : ""}: ${(e as { reason?: string }).reason ?? (e as Error).message}`,
          m ? { line: m.line + 1, column: m.column + 1 } : undefined);
      }
      break;
    case "toml":
      try {
        v = parseToml(text);
      } catch (e) {
        const err = e as { line?: number; column?: number; message: string };
        throw new ToolError(`Invalid TOML: ${err.message.split("\n")[0]}`, err.line ? { line: err.line, column: err.column ?? 1 } : undefined);
      }
      break;
    case "xml": {
      if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new ToolError("XML with DTDs or entities isn't accepted, for security reasons.");
      const parser = new XMLParser(xmlOpts);
      const ok = XMLValidator.validate(text);
      if (ok !== true) throw new ToolError(`Invalid XML at line ${ok.err.line}, column ${ok.err.col}: ${ok.err.msg}`, { line: ok.err.line, column: ok.err.col });
      v = parser.parse(text);
      const keys = Object.keys(v as object);
      if (keys.length !== 1) throw new ToolError("XML must have exactly one root element.");
      break;
    }
    case "csv":
    case "tsv": {
      const res = Papa.parse<Record<string, string>>(text.trim(), { header: true, delimiter: fmt === "tsv" ? "\t" : "", skipEmptyLines: true });
      if (res.errors.length && !res.data.length) throw new ToolError(`Invalid ${fmt.toUpperCase()}: ${res.errors[0].message}`);
      v = res.data;
      break;
    }
    default:
      throw new ToolError(`Can't read ${fmt}.`);
  }
  budget(v);
  return v;
}

export function neutralize(v: unknown): unknown {
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(v) && Number.isNaN(Number(v))) return "'" + v;
  return v;
}

export function flatten(records: unknown): { head: string[]; rows: unknown[][] } {
  if (!Array.isArray(records) || !records.every((r) => r && typeof r === "object" && !Array.isArray(r)))
    throw new ToolError('To make CSV, the JSON must be an array of objects, like [{"a": 1}, …].');
  const cols = new Map<string, true>();
  const flat = records.map((r) => {
    const out: Record<string, unknown> = {};
    const walk = (prefix: string, val: unknown) => {
      if (val && typeof val === "object" && !Array.isArray(val) && Object.keys(val).length) {
        for (const [k, x] of Object.entries(val)) walk(prefix ? `${prefix}.${k}` : k, x);
      } else if (val && typeof val === "object") out[prefix] = JSON.stringify(val);
      else out[prefix] = val;
    };
    walk("", r);
    Object.keys(out).forEach((k) => cols.set(k, true));
    return out;
  });
  const head = [...cols.keys()];
  return { head, rows: flat.map((f) => head.map((h) => f[h])) };
}

function toXml(v: unknown, indent: number, notices: string[]): string {
  let root: Record<string, unknown>;
  const keys = v && typeof v === "object" && !Array.isArray(v) ? Object.keys(v) : [];
  if (keys.length === 1 && /^[A-Za-z_][\w.-]*$/.test(keys[0]) && !/^[@#]/.test(keys[0])) root = v as Record<string, unknown>;
  else {
    root = { root: Array.isArray(v) ? { item: v } : v };
    notices.push("XML needs a single root element, so the data was wrapped in <root>.");
  }
  const b = new XMLBuilder({ ...xmlOpts, format: indent > 0, indentBy: " ".repeat(indent), suppressEmptyNode: true });
  return '<?xml version="1.0" encoding="UTF-8"?>\n' + b.build(root).trim() + "\n";
}

export function dumpAs(fmt: string, v: unknown, opts: { indent?: number; neutralize_formulas?: boolean }, notices: string[]): string {
  const indent = opts.indent ?? 2;
  switch (fmt) {
    case "json":
      return JSON.stringify(v, null, indent || undefined) + "\n";
    case "yaml":
      return yaml.dump(v, { indent: Math.max(2, indent), noRefs: true, lineWidth: -1 });
    case "toml": {
      let obj = v;
      if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
        obj = Array.isArray(v) ? { items: v } : { value: v };
        notices.push("TOML needs a table at the top level, so the data was put under a key.");
      }
      let dropped = 0;
      const strip = (x: unknown): unknown => {
        if (Array.isArray(x)) return x.filter((y) => (y === null ? (dropped++, false) : true)).map(strip);
        if (x && typeof x === "object")
          return Object.fromEntries(Object.entries(x).filter(([, y]) => (y === null ? (dropped++, false) : true)).map(([k, y]) => [k, strip(y)]));
        return x;
      };
      obj = strip(obj);
      if (dropped) notices.push(`TOML has no null value; ${dropped} empty value${dropped === 1 ? " was" : "s were"} left out.`);
      try {
        return stringifyToml(obj as Record<string, unknown>) + "\n";
      } catch (e) {
        throw new ToolError(`This data can't be represented in TOML (${(e as Error).message}).`);
      }
    }
    case "xml":
      return toXml(v, indent, notices);
    case "csv":
    case "tsv": {
      const { head, rows } = flatten(v);
      const safe = opts.neutralize_formulas !== false;
      return Papa.unparse({ fields: head, data: rows.map((r) => r.map((c) => (c == null ? "" : safe ? neutralize(c) : c))) },
        { delimiter: fmt === "tsv" ? "\t" : ",", newline: "\n" }) + "\n";
    }
  }
  throw new ToolError(`Can't write ${fmt}.`);
}

export function convertData(text: string, source: string, target: string, options: Record<string, unknown>): ToolResult {
  if (!text.trim()) throw new ToolError("Paste some data to convert.");
  const notices: string[] = [];
  const v = parseAs(source, text);
  const output = dumpAs(target, v, options as { indent?: number }, notices);
  if (source === "xml" || target === "xml") notices.push("XML attributes map to “@name” keys and element text to “#text”.");
  return { output, notices };
}
