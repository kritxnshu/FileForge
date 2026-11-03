import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export const FIXTURES = path.resolve(__dirname, "../fixtures/generated");
export const fixture = (name: string) => path.join(FIXTURES, name);

/** Real drag and drop: dispatch dragenter/dragover/drop with a DataTransfer holding the files. */
export async function dropFiles(page: Page, selector: string, files: { path: string; name?: string; type?: string }[]) {
  const payload = files.map((f) => ({
    b64: fs.readFileSync(f.path).toString("base64"),
    name: f.name ?? path.basename(f.path),
    type: f.type ?? "application/octet-stream",
  }));
  const dt = await page.evaluateHandle((items) => {
    const d = new DataTransfer();
    for (const it of items) {
      const bytes = Uint8Array.from(atob(it.b64), (c) => c.charCodeAt(0));
      d.items.add(new File([bytes], it.name, { type: it.type }));
    }
    return d;
  }, payload);
  for (const type of ["dragenter", "dragover", "drop"]) await page.dispatchEvent(selector, type, { dataTransfer: dt });
}

export async function waitReady(page: Page, count: number) {
  await expect(page.locator('[data-testid=file-row][data-status=ready]')).toHaveCount(count, { timeout: 30_000 });
}

export async function readDownload(page: Page, click: () => Promise<void>): Promise<{ name: string; bytes: Buffer }> {
  const [dl] = await Promise.all([page.waitForEvent("download"), click()]);
  const p = await dl.path();
  return { name: dl.suggestedFilename(), bytes: fs.readFileSync(p!) };
}

export const ROOT = path.resolve(__dirname, "../..");
export const PY = path.join(ROOT, "services/api/.venv/bin/python");

/** Entry names from a ZIP's central directory (independent of the app's own ZIP code). */
export function zipNames(buf: Buffer): string[] {
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65_557); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("not a ZIP: no end-of-central-directory record");
  let count = buf.readUInt16LE(eocd + 10);
  let off = buf.readUInt32LE(eocd + 16);
  if (count === 0xffff || off === 0xffffffff) {
    const loc = buf.readUInt32LE(eocd - 20) === 0x07064b50 ? Number(buf.readBigUInt64LE(eocd - 12)) : -1;
    if (loc < 0) throw new Error("ZIP64 locator missing");
    count = Number(buf.readBigUInt64LE(loc + 32));
    off = Number(buf.readBigUInt64LE(loc + 48));
  }
  const names: string[] = [];
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) throw new Error("bad central directory header");
    const nameLen = buf.readUInt16LE(off + 28);
    const extra = buf.readUInt16LE(off + 30);
    const comment = buf.readUInt16LE(off + 32);
    names.push(buf.subarray(off + 46, off + 46 + nameLen).toString("utf8"));
    off += 46 + nameLen + extra + comment;
  }
  return names;
}

/** Text of each page of a PDF, read with pypdf in the API's venv (an independent parser). */
export function pdfPageTexts(bytes: Buffer, dir: string): string[] {
  const p = path.join(dir, `check-${Date.now()}.pdf`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(p, bytes);
  const script = "import json,sys\nfrom pypdf import PdfReader\nprint(json.dumps([pg.extract_text() or '' for pg in PdfReader(sys.argv[1]).pages]))";
  const out = execFileSync(PY, ["-I", "-c", script, p], { encoding: "utf8" });
  return JSON.parse(out);
}
