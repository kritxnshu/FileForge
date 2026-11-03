import { expect, test } from "@playwright/test";
import { dropFiles, fixture, waitReady } from "./helpers";

test("pages get a strict per-request CSP and nothing on them violates it", async ({ page, request }) => {
  const a = (await request.get("/")).headers()["content-security-policy"] ?? "";
  const b = (await request.get("/")).headers()["content-security-policy"] ?? "";
  const scriptSrc = a.split(";").map((d) => d.trim()).find((d) => d.startsWith("script-src")) ?? "";
  expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/=]{16,}'/);
  expect(scriptSrc).not.toContain("'unsafe-inline'");
  expect(a).toContain("object-src 'none'");
  expect(a).toContain("frame-ancestors 'none'");
  expect(a).not.toBe(b); // a fresh nonce every time

  const violations: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Refused to (execute|load|apply|evaluate)/i.test(m.text())) violations.push(m.text());
  });
  page.on("pageerror", (e) => violations.push(`pageerror: ${e.message}`));

  for (const p of ["/", "/tools", "/formats", "/docs"]) {
    await page.goto(p);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }

  // client-side tools run their libraries (Prettier, terser, QR) under the same policy
  await page.goto("/tools/json-formatter");
  await page.getByTestId("tool-input").fill('{"b":1,"a":[1,2]}');
  await expect(page.getByTestId("tool-output")).toHaveValue(/"b": 1/);
  await page.goto("/tools/code-formatter-css");
  await page.getByTestId("tool-input").fill("a{color:red;margin:0}");
  await expect(page.getByTestId("tool-output")).toHaveValue(/color: red;/);
  await page.goto("/tools/txt-to-png");
  await page.getByTestId("tool-input").fill("https://example.com");
  await expect(page.getByTestId("tool-preview")).toBeVisible();

  // the workspace: upload, convert, preview
  await page.goto("/convert/png-to-jpg");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("image.png"), type: "image/png" }]);
  await waitReady(page, 1);
  await page.getByTestId("convert").click();
  await expect(page.getByTestId("job-card")).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });

  expect(violations).toEqual([]);
});
