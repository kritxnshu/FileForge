import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { dropFiles, fixture, pdfPageTexts, PY, readDownload, waitReady } from "./helpers";

/** Run a short pypdf check on a downloaded PDF in the API's venv (an independent parser) and return its JSON. */
function pdfCheck(bytes: Buffer, dir: string, body: string): unknown {
  const p = path.join(dir, `check-${Date.now()}.pdf`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(p, bytes);
  const script = `import json,sys\nfrom pypdf import PdfReader\nr=PdfReader(sys.argv[1])\nprint(json.dumps(${body}))`;
  return JSON.parse(execFileSync(PY, ["-I", "-c", script, p], { encoding: "utf8" }));
}

async function openTool(page: Page, slug: string, file = "document.pdf") {
  await page.goto(`/pdf/${slug}`);
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture(file), name: file, type: "application/pdf" }]);
  await waitReady(page, 1);
}

async function runAndDownload(page: Page) {
  await page.getByTestId("convert").click();
  const card = page.getByTestId("job-card");
  await expect(card).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  return (await readDownload(page, () => card.getByTestId("download").first().click())).bytes;
}

test("the PDF hub lists, searches and filters its tools", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("home-pdf").getByTestId("pdf-tool")).not.toHaveCount(0);
  await page.getByTestId("nav-pdf").click();
  await expect(page).toHaveURL(/\/pdf$/);

  const hub = page.getByTestId("pdf-hub");
  const cards = hub.getByTestId("pdf-tool");
  const total = await cards.count();
  expect(total).toBeGreaterThan(30);
  await expect(hub.locator('[data-slug="pdf-to-pdfa"]')).toHaveCount(0); // AGPL engines are off by default
  await expect(hub.getByRole("heading", { name: "Not offered here" })).toBeVisible();

  await page.getByTestId("pdf-hub-search").fill("sign");
  await expect(hub.locator('[data-slug="sign-pdf"]')).toBeVisible();
  await expect(hub.locator('[data-slug="merge-pdf"]')).toHaveCount(0);
  await page.getByTestId("pdf-hub-search").fill("zzzz");
  await expect(hub).toContainText("No PDF tool matches");

  await page.getByTestId("pdf-hub-search").fill("");
  await page.getByTestId("pdf-group-security").click();
  await expect(hub.locator('[data-slug="protect-pdf"]')).toBeVisible();
  await expect(hub.locator('[data-slug="merge-pdf"]')).toHaveCount(0);
  await page.getByTestId("pdf-group-all").click();
  await expect(cards).toHaveCount(total);

  await hub.locator('[data-slug="compress-pdf"]').click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Compress PDF");
  expect((await page.goto("/pdf/not-a-tool"))?.status()).toBe(404);
});

test("edit a PDF: add text and a rectangle where they were placed", async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 2400 }); // the whole page fits, so raw mouse drags land on it
  await openTool(page, "edit-pdf");
  const editor = page.getByTestId("pdf-editor");
  await expect(editor.getByTestId("editor-page")).toHaveJSProperty("complete", true, { timeout: 30_000 });
  const overlay = editor.getByTestId("editor-overlay");
  const box = (await overlay.boundingBox())!;

  await editor.getByTestId("tool-text").click();
  await overlay.click({ position: { x: box.width * 0.1, y: box.height * 0.5 } });
  await editor.getByTestId("text-input").fill("Approved by e2e");

  await editor.getByTestId("tool-rect").click();
  const b = (await overlay.boundingBox())!; // measured again: the properties panel shifts the page
  await page.mouse.move(b.x + b.width * 0.6, b.y + b.height * 0.6);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.8, b.y + b.height * 0.7, { steps: 5 });
  await page.mouse.up();
  await expect(editor.getByTestId("editor-items").locator("li")).toHaveCount(2);

  const pages = pdfPageTexts(await runAndDownload(page), info.outputPath());
  expect(pages).toHaveLength(3);
  expect(pages[0]).toContain("Approved by e2e");
  expect(pages[1]).not.toContain("Approved by e2e");
});

test("sign a PDF with a typed signature and the date", async ({ page }, info) => {
  await openTool(page, "sign-pdf");
  const editor = page.getByTestId("pdf-editor");
  await expect(editor.getByTestId("editor-page")).toHaveJSProperty("complete", true, { timeout: 30_000 });
  await editor.getByTestId("sign-place").click();
  const pad = page.getByTestId("signature-pad");
  await pad.getByRole("tab", { name: "Type" }).click();
  await pad.getByTestId("signature-name").fill("Asha Verma");
  await pad.getByTestId("signature-use").click();
  await expect(pad).toBeHidden();
  await editor.getByTestId("sign-date").click();
  await expect(editor.getByTestId("editor-items").locator("li")).toHaveCount(2);

  const bytes = await runAndDownload(page);
  const year = String(new Date().getFullYear());
  expect(pdfPageTexts(bytes, info.outputPath())[0]).toContain(year);
  // the signature is an image on page 1 only
  expect(pdfCheck(bytes, info.outputPath(), "[len(p.images) for p in r.pages]")).toEqual([1, 0, 0]);
});

test("redact a word everywhere it appears", async ({ page }, info) => {
  await openTool(page, "redact-pdf");
  await page.getByLabel("Words to redact").fill("Banana");
  const pages = pdfPageTexts(await runAndDownload(page), info.outputPath());
  expect(pages).toHaveLength(3);
  expect(pages.join(" ")).not.toContain("Banana");
  expect(pages[1]).toContain("Page 2 marker text"); // untouched pages keep their text
});

test("organize pages: delete, rotate and duplicate on one screen", async ({ page }, info) => {
  await openTool(page, "organize-pdf");
  const cards = page.getByTestId("organize-card");
  await expect(cards).toHaveCount(3, { timeout: 30_000 });
  await cards.nth(1).getByTestId("organize-delete").click(); // drop page 2 → 1,3
  await cards.nth(0).getByTestId("organize-rotate").click(); // page 1 turned 90°
  await cards.nth(1).getByTestId("organize-duplicate").click(); // → 1,3,3
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toHaveAttribute("data-rotate", "90");

  const bytes = await runAndDownload(page);
  const pages = pdfPageTexts(bytes, info.outputPath());
  expect(pages).toHaveLength(3);
  expect(pages[0]).toContain("Quarterly Report");
  expect(pages[1]).toContain("Page 3 marker text");
  expect(pages[2]).toContain("Page 3 marker text");
  expect(pages.join(" ")).not.toContain("Page 2 marker text");
  expect(pdfCheck(bytes, info.outputPath(), "[p.rotation % 360 for p in r.pages]")).toEqual([90, 0, 0]);
});

test("fill a PDF form's fields", async ({ page }, info) => {
  await openTool(page, "fill-pdf-form", "form.pdf");
  const form = page.getByTestId("pdf-form-fill");
  await form.locator('[data-field="full_name"]').fill("Ravi Kumar", { timeout: 30_000 });
  await form.locator('[data-field="subscribe"]').check();
  await form.locator('[data-field="country"]').selectOption("Japan");

  const values = pdfCheck(await runAndDownload(page), info.outputPath(),
    "{k: str(v.get('/V')) for k, v in (r.get_fields() or {}).items()}") as Record<string, string>;
  expect(values.full_name).toBe("Ravi Kumar");
  expect(values.country).toBe("Japan");
  expect(values.subscribe).not.toBe("/Off");
});
