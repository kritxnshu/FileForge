// Test titles start with registry keys ("<op>:<src>-><dst>" or "neg:<op>");
// scripts/merge_vitest_results.py turns these results into verified.json evidence.
import * as yaml from "js-yaml";
import { parse as parseToml } from "smol-toml";
import { describe, expect, it } from "vitest";
import { TOOLS, ToolError } from "../tools";
import { convertData, parseAs } from "../tools/data";

const run = async (op: string, text: string, source: string, target: string, options: Record<string, unknown> = {}) =>
  TOOLS[op]({ text, source, target, options });

const SAMPLE = { config: { name: "Ünïcode app", version: 3, enabled: true, ratio: 0.5, tags: ["a", "b"], owner: { id: 7 } } };
const FORMATS = ["json", "xml", "yaml", "toml"] as const;

function asText(fmt: string, v: unknown): string {
  return convertData(JSON.stringify(v), "json", fmt, {}).output;
}

// XML carries no types, so compare after normalising scalars to strings.
const strs = (v: unknown): unknown =>
  Array.isArray(v) ? v.map(strs) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, strs(x)])) : String(v);

describe("data conversion", () => {
  for (const s of FORMATS)
    for (const t of FORMATS) {
      if (s === t) continue;
      it(`dev.data_convert:${s}->${t} preserves content`, async () => {
        const input = asText(s, SAMPLE);
        const out = (await run("dev.data_convert", input, s, t)).output;
        const back = parseAs(t, out);
        if (s === "xml" || t === "xml") expect(strs(back)).toEqual(strs(SAMPLE));
        else expect(back).toEqual(SAMPLE);
        // independent parsers accept the output
        if (t === "json") JSON.parse(out);
        if (t === "yaml") yaml.load(out);
        if (t === "toml") parseToml(out);
      });
    }

  it("dev.data_convert:xml->json maps attributes and text", async () => {
    const out = (await run("dev.data_convert", '<root a="1"><item>x</item><item>y</item><n b="2">t</n></root>', "xml", "json")).output;
    expect(JSON.parse(out)).toEqual({ root: { "@a": "1", item: ["x", "y"], n: { "@b": "2", "#text": "t" } } });
  });

  it("dev.data_convert:json->xml wraps non-rooted data", async () => {
    const r = await run("dev.data_convert", '[{"a":1},{"a":2}]', "json", "xml");
    expect(r.output).toContain("<root>");
    expect(r.notices?.join(" ")).toContain("wrapped in <root>");
  });

  it("dev.data_convert:csv->json and dev.data_convert:json->csv round-trip with flattening", async () => {
    const csv = (await run("dev.data_convert", '[{"name":"Ann","addr":{"city":"Oslo"},"tags":[1,2]},{"name":"=cmd"}]', "json", "csv")).output;
    expect(csv.split("\n")[0]).toBe("name,addr.city,tags");
    expect(csv).toContain("'=cmd");
    const back = JSON.parse((await run("dev.data_convert", csv, "csv", "json")).output);
    expect(back[0]).toEqual({ name: "Ann", "addr.city": "Oslo", tags: "[1,2]" });
  });

  it("dev.data_convert:tsv->json and dev.data_convert:json->tsv", async () => {
    const back = JSON.parse((await run("dev.data_convert", "a\tb\n1\t2\n", "tsv", "json")).output);
    expect(back).toEqual([{ a: "1", b: "2" }]);
    expect((await run("dev.data_convert", JSON.stringify(back), "json", "tsv")).output).toBe("a\tb\n1\t2\n");
  });

  it("neg:dev.data_convert reports position and rejects unsafe input", async () => {
    await expect(run("dev.data_convert", '{"a": 1,\n  "b": }', "json", "yaml")).rejects.toThrow(/line 2, column \d+/);
    expect(() => parseAs("xml", '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')).toThrow(/DTDs/);
    const bomb = "a: &a [x,x,x,x,x,x,x,x,x]\n" + Array.from({ length: 8 }, (_, i) => `${"bcdefghi"[i]}: &${"bcdefghi"[i]} [${Array(9).fill("*" + (i ? "bcdefghi"[i - 1] : "a")).join(",")}]`).join("\n");
    expect(() => parseAs("yaml", bomb)).toThrow(/too many values/);
    await expect(run("dev.data_convert", "1", "json", "csv")).rejects.toThrow(/array of objects/);
  });
});

describe("JSON formatter", () => {
  it("dev.json_format:json->json formats, minifies, validates, sorts", async () => {
    expect((await run("dev.json_format", '{"b":1,"a":[1,2]}', "json", "json", { mode: "format", indent: 2, sort_keys: true })).output)
      .toBe('{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n');
    expect((await run("dev.json_format", '{ "a" : [1, 2] }', "json", "json", { mode: "minify" })).output).toBe('{"a":[1,2]}');
    expect((await run("dev.json_format", "[1,2]", "json", "json", { mode: "validate" })).notices?.[0]).toBe("Valid JSON: an array of 2 items.");
  });
  it("neg:dev.json_format gives line and column", async () => {
    try {
      await run("dev.json_format", '{\n  "a": 1\n  "b": 2\n}', "json", "json");
      throw new Error("should fail");
    } catch (e) {
      expect(e).toBeInstanceOf(ToolError);
      expect((e as ToolError).where?.line).toBe(3);
    }
  });
});

describe("code formatter", () => {
  it("dev.code_format:css->css beautifies and minifies", async () => {
    const pretty = (await run("dev.code_format", "a{color:red;margin:0 0}", "css", "css", { mode: "beautify" })).output;
    expect(pretty).toBe("a {\n  color: red;\n  margin: 0 0;\n}\n");
    expect((await run("dev.code_format", pretty, "css", "css", { mode: "minify" })).output).toBe("a{color:red;margin:0}"); // csso folds the equivalent "0 0" to "0"
  });
  it("dev.code_format:js->js beautifies and minifies (still runs)", async () => {
    const src = "function add(a,b){return a+b}\nconsole.log(add(2,3))";
    const pretty = (await run("dev.code_format", src, "js", "js", { mode: "beautify" })).output;
    expect(pretty).toContain("function add(a, b) {\n  return a + b;\n}");
    const min = (await run("dev.code_format", "function add(first,second){return first+second}; globalThis.r = add(2,3)", "js", "js", { mode: "minify" })).output;
    expect(min.length).toBeLessThan(70);
    new Function(min)();
    expect((globalThis as { r?: number }).r).toBe(5);
  });
  it("dev.code_format:sql->sql beautifies and minifies keeping strings", async () => {
    const pretty = (await run("dev.code_format", "select a,b from t where c='x  y' -- note\n and d=1", "sql", "sql", { mode: "beautify" })).output;
    expect(pretty).toMatch(/^SELECT\n  a,\n  b\nFROM\n  t\nWHERE/);
    expect((await run("dev.code_format", pretty, "sql", "sql", { mode: "minify" })).output).toBe("SELECT a,b FROM t WHERE c='x  y' AND d=1");
  });
  it("dev.code_format:xml->xml beautifies and minifies", async () => {
    const pretty = (await run("dev.code_format", "<a><b>1</b><c/></a>", "xml", "xml", { mode: "beautify" })).output;
    expect(pretty).toBe("<a>\n  <b>1</b>\n  <c/>\n</a>\n");
    expect((await run("dev.code_format", pretty, "xml", "xml", { mode: "minify" })).output).toBe("<a><b>1</b><c/></a>");
  });
  it("neg:dev.code_format reports syntax errors", async () => {
    await expect(run("dev.code_format", "function (", "js", "js", {})).rejects.toThrow(/couldn't be parsed at line 1/);
    await expect(run("dev.code_format", "<a><b></a>", "xml", "xml", {})).rejects.toThrow(/couldn't be parsed/);
  });
});

describe("HTML ↔ Markdown", () => {
  it("dev.html_markdown:md->html and dev.html_markdown:html->md round-trip", async () => {
    const md = "# Title\n\nSome **bold** text and a [link](https://example.com).\n\n- one\n- two\n";
    const html = (await run("dev.html_markdown", md, "md", "html")).output;
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain('<a href="https://example.com">link</a>');
    const back = (await run("dev.html_markdown", html, "html", "md")).output;
    expect(back).toContain("# Title");
    expect(back).toContain("**bold**");
    expect(back).toMatch(/\* one|- one/);
  });
  it("neg:dev.html_markdown rejects empty input", async () => {
    await expect(run("dev.html_markdown", "  ", "html", "md")).rejects.toThrow(/Paste some HTML/);
  });
});

describe("CSV → SQL", () => {
  it("dev.csv_to_sql:csv->sql and dev.csv_to_sql:tsv->sql quote safely", async () => {
    const out = (await run("dev.csv_to_sql", "id,name\n1,O'Brien\n2,\n", "csv", "sql", { table: "people", dialect: "mysql" })).output;
    expect(out).toContain("CREATE TABLE `people` (\n  `id` BIGINT,\n  `name` TEXT\n);");
    expect(out).toContain("(1, 'O''Brien'),\n  (2, NULL);");
    expect((await run("dev.csv_to_sql", "a\tb\n1\tx\n", "tsv", "sql", { create_table: false })).output)
      .toBe('INSERT INTO "my_table" ("a", "b") VALUES\n  (1, \'x\');\n');
  });
  it("neg:dev.csv_to_sql rejects bad table names", async () => {
    await expect(run("dev.csv_to_sql", "a\n1", "csv", "sql", { table: "x; DROP TABLE y" })).rejects.toThrow(/letters, numbers/);
  });
});

describe("Base64 / URL / timestamps", () => {
  it("dev.base64:txt->txt round-trips text, bytes and URL-safe", async () => {
    const enc = (await run("dev.base64", "héllo wörld ✓", "txt", "txt", { direction: "encode" })).output;
    expect(enc).toBe("aMOpbGxvIHfDtnJsZCDinJM=");
    expect((await run("dev.base64", enc, "txt", "txt", { direction: "decode" })).output).toBe("héllo wörld ✓");
    const bytes = new Uint8Array([0, 255, 251, 16, 128]);
    const b = await TOOLS["dev.base64"]({ text: "", bytes, source: "txt", target: "txt", options: { direction: "encode", url_safe: true } });
    expect(b.output).toBe("AP_7EIA");
    const back = await run("dev.base64", b.output, "txt", "txt", { direction: "decode" });
    expect([...back.bytes!]).toEqual([...bytes]);
  });
  it("neg:dev.base64 rejects invalid input", async () => {
    await expect(run("dev.base64", "not base64!!", "txt", "txt", { direction: "decode" })).rejects.toThrow(/valid Base64/);
  });
  it("dev.url:txt->txt encodes and decodes", async () => {
    expect((await run("dev.url", "a b&c=d/é", "txt", "txt", { direction: "encode" })).output).toBe("a%20b%26c%3Dd%2F%C3%A9");
    expect((await run("dev.url", "https://x.com/a b?q=1&r=é", "txt", "txt", { direction: "encode", mode: "full" })).output)
      .toBe("https://x.com/a%20b?q=1&r=%C3%A9");
    expect((await run("dev.url", "a%20b%26c", "txt", "txt", { direction: "decode" })).output).toBe("a b&c");
  });
  it("neg:dev.url reports malformed escapes", async () => {
    await expect(run("dev.url", "%E0%A4%A", "txt", "txt", { direction: "decode" })).rejects.toThrow(/malformed/);
  });
  it("dev.timestamp:txt->txt handles seconds, milliseconds, ISO and time zones", async () => {
    const s = (await run("dev.timestamp", "1700000000", "txt", "txt", { timezone: "UTC" })).output;
    expect(s).toContain("ISO 8601 (UTC):    2023-11-14T22:13:20.000Z");
    const ms = await run("dev.timestamp", "1700000000123", "txt", "txt", { timezone: "Asia/Kolkata" });
    expect(ms.output).toContain("Unix seconds:      1700000000");
    expect(ms.output).toMatch(/15 November 2023 at 03:43:20/);
    expect((await run("dev.timestamp", "2023-11-14T22:13:20Z", "txt", "txt", {})).output).toContain("Unix seconds:      1700000000");
  });
  it("neg:dev.timestamp rejects nonsense and bad zones", async () => {
    await expect(run("dev.timestamp", "next tuesday-ish", "txt", "txt", {})).rejects.toThrow(/recognize/);
    await expect(run("dev.timestamp", "1", "txt", "txt", { timezone: "Mars/Olympus" })).rejects.toThrow(/Unknown time zone/);
  });
});
