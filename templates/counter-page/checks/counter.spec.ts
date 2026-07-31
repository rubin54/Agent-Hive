import { expect, test } from "@playwright/test";

// What gets checked is observable behaviour, not the implementation. A model may build the
// counter however it likes as long as the page does what the task asks. Checking the
// implementation would narrow the benchmark to a single acceptable solution.

test("page loads with an initial value of 0", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#value")).toHaveText("0");
});

test("the button increments the counter", async ({ page }) => {
  await page.goto("/");
  await page.locator("#increment").click();
  await expect(page.locator("#value")).toHaveText("1");

  await page.locator("#increment").click();
  await page.locator("#increment").click();
  await expect(page.locator("#value")).toHaveText("3");
});

test("reset restores 0", async ({ page }) => {
  await page.goto("/");
  await page.locator("#increment").click();
  await page.locator("#increment").click();
  await page.locator("#reset").click();
  await expect(page.locator("#value")).toHaveText("0");
});

test("no unhandled page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto("/");
  await page.locator("#increment").click();
  await page.locator("#reset").click();

  expect(errors, `page errors: ${errors.join(" | ")}`).toHaveLength(0);
});
