import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { dropFiles, fixture, waitReady } from "./helpers";

/** WCAG 2.1 A + AA rules from axe-core; any violation fails with a readable summary. */
async function audit(page: Page, label: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = r.violations.map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.slice(0, 4).map((n) => n.target.join(" ")).join("\n    ")}`);
  expect(summary, `${label}\n${summary.join("\n")}`).toEqual([]);
}

const PAGES = ["/", "/convert", "/tools", "/formats", "/docs", "/privacy", "/terms", "/convert/png-to-jpg",
  "/convert/mp3-to-docx", "/tools/json-formatter", "/tools/color-converter", "/tools/txt-to-png", "/nope",
  "/pdf", "/pdf/edit-pdf", "/pdf/scan-to-pdf"];

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.use({ colorScheme: theme });

    test("every page passes WCAG 2.1 AA checks", async ({ page }) => {
      for (const p of PAGES) {
        await page.goto(p);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await audit(page, `${theme} ${p}`);
      }
    });

    test("the workspace passes WCAG 2.1 AA checks with files, options and results", async ({ page }) => {
      await page.goto("/convert");
      await dropFiles(page, "[data-testid=dropzone]", [
        { path: fixture("image.png"), name: "a.png", type: "image/png" },
        { path: fixture("document.pdf"), name: "b.pdf", type: "application/pdf" },
      ]);
      await waitReady(page, 2);
      await page.getByTestId("target-image.convert-webp").click();
      await page.getByTestId("target-pdf.reorder-pdf").click();
      await expect(page.getByTestId("page-card")).toHaveCount(3, { timeout: 30_000 });
      await page.getByRole("button", { name: "Advanced" }).first().click();
      await audit(page, `${theme} workspace with options`);
      await page.getByTestId("convert").click();
      for (const c of await page.getByTestId("job-card").all()) await expect(c).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });
      await expect(page.getByTestId("pdf-thumbs").locator("img")).toHaveCount(3, { timeout: 30_000 });
      await audit(page, `${theme} workspace with results`);
    });

    test("the PDF editor, signature dialog and organizer pass WCAG 2.1 AA checks", async ({ page }) => {
      await page.goto("/pdf/sign-pdf");
      await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("document.pdf"), name: "b.pdf", type: "application/pdf" }]);
      await waitReady(page, 1);
      await expect(page.getByTestId("editor-page")).toHaveJSProperty("complete", true, { timeout: 30_000 });
      await page.getByTestId("sign-date").click(); // something selected, so the properties panel shows
      await expect(page.getByTestId("convert")).toHaveCSS("opacity", "1"); // let its fade-in from disabled finish
      await audit(page, `${theme} sign editor`);
      await page.getByTestId("sign-place").click();
      await expect(page.getByTestId("signature-pad")).toBeVisible();
      await audit(page, `${theme} signature dialog`);

      await page.goto("/pdf/organize-pdf");
      await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("document.pdf"), name: "b.pdf", type: "application/pdf" }]);
      await waitReady(page, 1);
      await expect(page.getByTestId("organize-card")).toHaveCount(3, { timeout: 30_000 });
      await audit(page, `${theme} organizer`);
    });
  });
}

test("the drop zone and controls work from the keyboard, with visible focus", async ({ page }) => {
  await page.goto("/");
  // first Tab reaches the skip link, which jumps to the main content
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();

  // Tab through to "Browse files"; Enter opens the file chooser
  const browse = page.getByRole("button", { name: "Browse files" });
  for (let i = 0; i < 15 && !(await browse.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const ring = await browse.evaluate((el) => {
    const s = getComputedStyle(el);
    return { outline: s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2, shadow: s.boxShadow !== "none" };
  });
  expect(ring.outline || ring.shadow, "focused control has no visible focus indicator").toBe(true);
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.keyboard.press("Enter")]);
  expect(chooser.isMultiple()).toBe(true);
  await chooser.setFiles(fixture("image.png"));
  await expect(page).toHaveURL(/\/convert$/);
  await waitReady(page, 1);

  // pick a target and convert without the mouse; progress and results are announced
  await page.getByTestId("target-image.convert-jpg").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("target-image.convert-jpg")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("convert").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("job-card")).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });
  await expect(page.locator("[aria-live=polite]").first()).toHaveText(/succeeded|done/i);
});
