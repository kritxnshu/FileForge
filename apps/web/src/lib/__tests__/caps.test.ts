import { describe, expect, it } from "vitest";
import type { Capabilities, Operation } from "../api";
import { formatBytes, searchTools, sizeDelta, toolEntries } from "../caps";
import { cleanOptions, defaultsOf, visibleFields } from "../../components/OptionsForm";

const fmt = (label: string, family: string, exts: string[]) => ({ label, family, exts, mime: "x" });
const op = (id: string, pairs: [string, string][], extra: Partial<Operation> = {}): Operation => ({
  id, category: "documents", label: id, description: "", cardinality: "one_to_one", runtime: "server",
  resource_class: "fast", support: "full", limitations: [], options_schema: { type: "object", properties: {} },
  min_inputs: 1, max_inputs: null, keywords: [],
  pairs: pairs.map(([s, t]) => ({ source: s, target: t, support: "full", limitations: [], slug: `${s}-to-${t}`, primary: true })),
  ...extra,
});

const caps: Capabilities = {
  version: 1,
  categories: [{ id: "documents", label: "Documents" }],
  formats: {
    docx: fmt("Word (DOCX)", "document", ["docx"]),
    pdf: fmt("PDF", "pdf", ["pdf"]),
    heic: fmt("HEIC", "image", ["heic", "heif"]),
    jpg: fmt("JPG", "image", ["jpg", "jpeg"]),
    xlsx: fmt("Excel (XLSX)", "spreadsheet", ["xlsx"]),
  },
  operations: [
    op("doc.convert", [["docx", "pdf"], ["pdf", "docx"], ["xlsx", "pdf"]]),
    op("image.convert", [["heic", "jpg"], ["jpg", "heic"]], { category: "images" }),
  ],
  limits: { max_file_size_mb: 1, max_video_size_mb: 1, max_batch_files: 1, max_batch_total_mb: 1, max_image_megapixels: 1, retention_minutes: 60, jobs_per_10min: 1 },
};
const entries = toolEntries(caps);
const top = (q: string) => searchTools(entries, q)[0]?.slug;

describe("tool search", () => {
  it("matches natural phrasing and extensions", () => {
    expect(top("word to pdf")).toBe("docx-to-pdf");
    expect(top("docx pdf")).toBe("docx-to-pdf");
    expect(top("heic jpg")).toBe("heic-to-jpg");
  });
  it("respects direction", () => {
    expect(top("pdf to word")).toBe("pdf-to-docx");
    expect(top("jpg heic")).toBe("jpg-to-heic");
  });
  it("tolerates a typo and aliases", () => {
    expect(top("wrod to pdf")).toBe("docx-to-pdf");
    expect(top("jpeg")).toMatch(/jpg/);
    expect(top("excel pdf")).toBe("xlsx-to-pdf");
  });
  it("returns nothing for unrelated words", () => {
    expect(searchTools(entries, "spaceship")).toHaveLength(0);
  });
});

describe("formatting helpers", () => {
  it("formats bytes in decimal units", () => {
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1500)).toBe("1.5 KB");
    expect(formatBytes(25_000_000)).toBe("25 MB");
  });
  it("describes size change", () => {
    expect(sizeDelta(1000, 500)).toEqual({ text: "50% smaller", smaller: true });
    expect(sizeDelta(1000, 1500).text).toBe("50% larger");
  });
});

describe("schema-driven options", () => {
  const schema = {
    type: "object",
    properties: {
      quality: { type: "integer", default: 85, "x-targets": ["jpg", "webp"] },
      background: { type: "string", default: "#ffffff", "x-targets": ["jpg"] },
      strip: { type: "boolean", default: false },
    },
  };
  it("collects defaults", () => expect(defaultsOf(schema)).toEqual({ quality: 85, background: "#ffffff", strip: false }));
  it("hides fields that don't apply to the target", () => {
    expect(visibleFields(schema, "png").map(([k]) => k)).toEqual(["strip"]);
  });
  it("sends only changed, applicable values", () => {
    expect(cleanOptions(schema, "webp", { quality: 50, background: "#000000", strip: false })).toEqual({ quality: 50 });
  });
});
