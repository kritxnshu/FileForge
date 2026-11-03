import { expect, type Page } from "@playwright/test";
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
