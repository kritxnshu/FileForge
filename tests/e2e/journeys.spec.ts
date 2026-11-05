import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { dropFiles, fixture, pdfPageTexts, readDownload, waitReady, zipNames } from "./helpers";

test("convert a batch of 3 mixed files and download them as one ZIP", async ({ page }) => {
  await page.goto("/convert");
  await dropFiles(page, "[data-testid=dropzone]", [
    { path: fixture("image.png"), name: "photo.png", type: "image/png" },
    { path: fixture("document.docx"), name: "report.docx" },
    { path: fixture("data.csv"), name: "table.csv", type: "text/csv" },
  ]);
  await waitReady(page, 3);

  // mixed batch: one picker per input type
  await expect(page.getByTestId("group-png")).toBeVisible();
  await page.getByTestId("target-image.convert-jpg").click();
  await page.getByTestId("target-doc.office-pdf").click();
  await page.getByTestId("target-data.convert-json").click();
  await expect(page.getByTestId("convert")).toContainText("Convert 3 files");
  await page.getByTestId("convert").click();

  const cards = page.getByTestId("job-card");
  await expect(cards).toHaveCount(3);
  for (let i = 0; i < 3; i++) await expect(cards.nth(i)).toHaveAttribute("data-state", "succeeded", { timeout: 90_000 });

  const { name, bytes } = await readDownload(page, () => page.getByTestId("download-zip").click());
  expect(name).toMatch(/\.zip$/);
  expect(zipNames(bytes).sort()).toEqual(["photo.jpg", "report.pdf", "table.json"]);
});

test("an unsupported pair explains itself and suggests what does work", async ({ page }) => {
  // a direct link to a conversion that doesn't exist
  const res = await page.goto("/convert/mp3-to-docx");
  expect(res?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("MP3 to DOCX isn't supported");
  const box = page.getByTestId("unsupported");
  await expect(box).toContainText("We can't turn MP3");
  await expect(box.getByTestId("alternatives").getByRole("link", { name: "WAV" })).toHaveAttribute("href", "/convert/mp3-to-wav");

  // a file that doesn't fit the page it was dropped on
  await page.goto("/convert/png-to-jpg");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("tone.mp3"), name: "song.mp3", type: "audio/mpeg" }]);
  await waitReady(page, 1);
  await expect(page.getByTestId("preset-mismatch")).toContainText("can't be converted to JPG");
  await expect(page.getByTestId("target-image.convert-jpg")).toHaveCount(0);
  await expect(page.getByTestId("target-audio.convert-wav")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("convert")).toHaveCount(0); // nothing is picked, so there's nothing to run

  // nonsense paths still get a useful page
  const missing = await page.goto("/convert/not-a-real-thing");
  expect(missing?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
  await expect(page.getByRole("link", { name: "Browse all tools" })).toBeVisible();

  // a file whose content can't be identified is rejected with a reason
  await page.goto("/convert");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("garbage.bin"), name: "mystery.bin" }]);
  await expect(page.locator("[data-testid=file-row][data-status=rejected]")).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByTestId("file-row").getByRole("alert")).not.toBeEmpty();
});

test("a spreadsheet result previews its first rows as a table", async ({ page }) => {
  await page.goto("/convert/csv-to-xlsx");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("data.csv"), name: "fruit.csv", type: "text/csv" }]);
  await waitReady(page, 1);
  await page.getByTestId("convert").click();
  const card = page.getByTestId("job-card");
  await expect(card).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });
  const table = card.getByTestId("table-preview");
  await expect(table.locator("tr").first()).toContainText("Name");
  await expect(table.locator("tr", { hasText: "Banana" })).toContainText("12");
  await expect(table.locator("caption")).toContainText("4 rows");
  await expect(table.locator("tr", { hasText: "Dürüm" })).toHaveCount(1);
});

test("merge PDFs after reordering them, with page thumbnails on the result", async ({ page }, info) => {
  await page.goto("/convert/merge-pdf");
  await dropFiles(page, "[data-testid=dropzone]", [
    { path: fixture("document.pdf"), name: "report.pdf", type: "application/pdf" },
    { path: fixture("other.pdf"), name: "cover.pdf", type: "application/pdf" },
  ]);
  await waitReady(page, 2);
  await expect(page.getByTestId("target-pdf.merge-pdf")).toHaveAttribute("aria-checked", "true");

  // put cover.pdf first
  await page.getByRole("button", { name: "Move cover.pdf up" }).click();
  await expect(page.getByTestId("file-row").first()).toContainText("cover.pdf");
  await page.getByTestId("convert").click();

  const card = page.getByTestId("job-card");
  await expect(card).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  await expect(card.getByTestId("pdf-thumbs").locator("img")).toHaveCount(5, { timeout: 30_000 });
  await expect(card.getByTestId("pdf-thumbs").locator("img").first()).toHaveJSProperty("complete", true);

  const { bytes } = await readDownload(page, () => page.getByTestId("download").first().click());
  const pages = pdfPageTexts(bytes, info.outputPath());
  expect(pages).toHaveLength(5);
  // cover.pdf (2 pages, no table) then report.pdf (3 pages, table on page 1)
  expect(pages[0]).toContain("Quarterly Report");
  expect(pages[0]).not.toContain("Banana");
  expect(pages[1]).toContain("Page 2 marker text");
  expect(pages[2]).toContain("Banana");
  expect(pages[4]).toContain("Page 3 marker text");
});

test("reorder pages using thumbnails (buttons and drag and drop)", async ({ page }, info) => {
  await page.goto("/convert/reorder-pdf-pages");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("document.pdf"), name: "report.pdf", type: "application/pdf" }]);
  await waitReady(page, 1);

  const cards = page.getByTestId("page-card");
  await expect(cards).toHaveCount(3, { timeout: 30_000 });
  await expect(cards.locator("img").first()).toHaveJSProperty("complete", true);
  // page 3 to the front with the keyboard-accessible buttons → 3,1,2
  await page.getByRole("button", { name: "Move page 3 earlier" }).click();
  await page.getByRole("button", { name: "Move page 3 earlier" }).click();
  await expect(cards.first()).toHaveAttribute("data-page", "3");
  // then drag page 2 (last) onto the second slot → 3,2,1
  await cards.nth(2).dragTo(cards.nth(1));
  await expect(cards.nth(1)).toHaveAttribute("data-page", "2");
  await expect(cards.nth(2)).toHaveAttribute("data-page", "1");

  await page.getByTestId("convert").click();
  await expect(page.getByTestId("job-card")).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  await expect(page.getByTestId("job-card")).toContainText("Reorder pages");
  await expect(page.getByTestId("job-card")).not.toContainText("to Reorder pages"); // a tool, not a target format
  const { bytes } = await readDownload(page, () => page.getByTestId("download").first().click());
  const pages = pdfPageTexts(bytes, info.outputPath());
  expect(pages).toHaveLength(3);
  expect(pages[0]).toContain("Page 3 marker text");
  expect(pages[1]).toContain("Page 2 marker text");
  expect(pages[2]).toContain("Quarterly Report");
});

test("convert video to MP3 with real, visible progress", async ({ page }, info) => {
  // A long, tiny video so the engine reports progress several times while it works.
  const dir = info.outputPath();
  fs.mkdirSync(dir, { recursive: true });
  const video = path.join(dir, "lecture.mp4");
  execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "color=c=0x0b7f6a:s=32x32:r=1", "-f", "lavfi", "-i", "sine=f=440:sample_rate=44100",
    "-t", "900", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "48k", "-shortest", video]);

  await page.goto("/convert/mp4-to-mp3");
  await page.getByTestId("file-input").setInputFiles(video);
  await waitReady(page, 1);
  await expect(page.getByTestId("target-video.extract_audio-mp3")).toHaveAttribute("aria-checked", "true");

  // record every progress value the page renders
  await page.evaluate(() => {
    const seen: number[] = [];
    (window as unknown as { __progress: number[] }).__progress = seen;
    new MutationObserver(() => {
      document.querySelectorAll("[role=progressbar][aria-valuenow]").forEach((el) => seen.push(Number(el.getAttribute("aria-valuenow"))));
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["aria-valuenow"] });
  });
  await page.getByTestId("convert").click();
  await expect(page.getByTestId("job-stage")).toBeVisible();
  const card = page.getByTestId("job-card");
  await expect(card).toHaveAttribute("data-state", "succeeded", { timeout: 120_000 });

  const seen = await page.evaluate(() => (window as unknown as { __progress: number[] }).__progress);
  const midway = [...new Set(seen.filter((v) => v > 0 && v < 100))];
  expect(midway.length, `progress values seen: ${seen.join(",")}`).toBeGreaterThanOrEqual(2);
  expect([...midway].sort((a, b) => a - b)).toEqual(midway); // only ever goes forward

  await expect(card.locator("audio")).toHaveCount(1);
  const { name, bytes } = await readDownload(page, () => page.getByTestId("download").first().click());
  expect(name).toBe("lecture.mp3");
  const id3 = bytes.subarray(0, 3).toString("latin1") === "ID3";
  const frameSync = bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0;
  expect(id3 || frameSync).toBe(true);
});

test("switch to dark mode and keep it across reloads", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const paper = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const light = await paper();

  await page.getByTestId("theme-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByTestId("theme-dark")).toHaveAttribute("aria-checked", "true");
  const dark = await paper();
  expect(dark).not.toBe(light);
  expect(dark).toBe("rgb(9, 9, 11)");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await paper()).toBe("rgb(9, 9, 11)");

  // "System" follows the OS preference
  await page.getByTestId("theme-system").click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
  expect(await paper()).toBe(light);
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await paper()).toBe("rgb(9, 9, 11)");
});

test.describe("mobile (390 px)", () => {
  test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

  test("homepage and workspace fit the screen", async ({ page }, info) => {
    const shots = path.resolve(__dirname, "../../.data/screenshots");
    fs.mkdirSync(shots, { recursive: true });
    const noSideScroll = async () => {
      const w = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(w, "page is wider than the screen").toBeLessThanOrEqual(390);
    };

    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await noSideScroll();
    await page.screenshot({ path: path.join(shots, "home-390.png"), fullPage: true });
    await info.attach("home-390", { path: path.join(shots, "home-390.png"), contentType: "image/png" });

    await page.goto("/convert/png-to-jpg");
    await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("image.png"), name: "a-photo-with-a-rather-long-file-name.png", type: "image/png" }]);
    await waitReady(page, 1);
    await page.getByTestId("convert").click();
    await expect(page.getByTestId("job-card")).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });
    await noSideScroll();
    await page.screenshot({ path: path.join(shots, "workspace-390.png"), fullPage: true });
    await info.attach("workspace-390", { path: path.join(shots, "workspace-390.png"), contentType: "image/png" });

    for (const p of ["/tools", "/formats", "/docs", "/privacy"]) {
      await page.goto(p);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await noSideScroll();
    }
  });
});

test("history keeps metadata only, marks expired results and can be cleared", async ({ page }) => {
  await page.goto("/convert/png-to-jpg");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("image.png"), name: "holiday.png", type: "image/png" }]);
  await waitReady(page, 1);
  await page.getByTestId("convert").click();
  await expect(page.getByTestId("job-card")).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });

  const history = page.getByTestId("history");
  await expect(history).toContainText("holiday.png");
  await expect(history.getByRole("link", { name: "PNG to JPG" })).toHaveAttribute("href", "/convert/png-to-jpg");
  const stored = await page.evaluate(() => localStorage.getItem("uc-history") ?? "");
  const [entry] = JSON.parse(stored);
  expect(Object.keys(entry).sort()).toEqual(["at", "expiresAt", "fileName", "jobId", "label", "operation", "outputs", "source", "target", "tool"]);
  expect(stored.length).toBeLessThan(1000); // names and formats, never file contents

  // an older conversion whose files have been deleted shows as expired, with no download link
  await page.evaluate(() => {
    const list = JSON.parse(localStorage.getItem("uc-history") ?? "[]");
    list.push({ jobId: "0".repeat(32), at: Date.now() - 7_200_000, fileName: "old-scan.pdf", operation: "pdf.to_images",
      label: "PNG", source: "pdf", target: "png", outputs: 1, expiresAt: Date.now() / 1000 - 3600 });
    localStorage.setItem("uc-history", JSON.stringify(list));
  });
  await page.reload();
  const old = history.locator("li", { hasText: "old-scan.pdf" });
  await expect(old).toHaveAttribute("data-expired", "true");
  await expect(old).toContainText("Expired");
  await expect(old.getByRole("link", { name: "Download" })).toHaveCount(0);

  await page.getByTestId("clear-history").click();
  await expect(page.getByTestId("history")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("uc-history"))).toBe("[]");
});
