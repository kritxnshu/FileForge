import { expect, test } from "@playwright/test";
import { dropFiles, fixture, readDownload, waitReady } from "./helpers";

test("drag a PNG onto the home page, convert to JPG, download it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("One Platform.");
  await dropFiles(page, "[data-testid=dropzone]", [{ path: fixture("image.png"), name: "holiday.png", type: "image/png" }]);
  await expect(page).toHaveURL(/\/convert$/);
  await waitReady(page, 1);
  await expect(page.getByTestId("file-row")).toContainText("PNG");

  await page.getByTestId("target-image.convert-jpg").click();
  await expect(page.getByTestId("options-form")).toContainText("Quality");
  await page.getByTestId("convert").click();

  const card = page.getByTestId("job-card");
  await expect(card).toHaveAttribute("data-state", "succeeded", { timeout: 30_000 });
  const { name, bytes } = await readDownload(page, () => page.getByTestId("download").first().click());
  expect(name).toBe("holiday.jpg");
  expect([...bytes.subarray(0, 3)]).toEqual([0xff, 0xd8, 0xff]);

  // Delete now removes results from the server
  await page.getByTestId("delete-now").click();
  await expect(page.getByTestId("job-card")).toHaveCount(0);
});
