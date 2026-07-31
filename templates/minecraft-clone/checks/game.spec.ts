import { expect, test } from "@playwright/test";

// Deliberately behaviour-oriented and not tied to an implementation: what gets checked is
// that a 3D scene appears, that it keeps running for several seconds, and that the controls
// change the picture. How a model achieves that is its own business.
//
// IMPORTANT — why Playwright screenshots instead of reading pixels inside the page:
// `context.drawImage(webglCanvas, …)` and `canvas.toDataURL()` return an empty buffer for
// WebGL as soon as the browser discards the drawing buffer after compositing (that is the
// default; only `preserveDrawingBuffer: true` changes it). A check measuring that way would
// fail every correct solution — and the alternative would be to prescribe a renderer option
// to the model, i.e. exactly the implementation coupling this benchmark tries to avoid.
// Playwright screenshots go through the compositor and show what is really on screen.

const CANVAS = "canvas#game";

test("a canvas of sensible size exists", async ({ page }) => {
  await page.goto("/", { waitUntil: "load" });

  const canvas = page.locator(CANVAS);
  await expect(canvas).toBeVisible({ timeout: 15_000 });

  const box = await canvas.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(300);
  expect(box?.height ?? 0).toBeGreaterThan(300);
});

test("the scene renders for several seconds without an exception", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto("/", { waitUntil: "load" });
  await page.waitForTimeout(5_000);

  expect(errors, `page errors: ${errors.join(" | ")}`).toHaveLength(0);
});

test("the canvas shows a non-trivial scene", async ({ page }) => {
  await page.goto("/", { waitUntil: "load" });
  await page.waitForTimeout(3_000);

  const shot = await page.locator(CANVAS).screenshot();

  // Heuristic over PNG size: a flat colour compresses to a few kilobytes, a rendered scene
  // with edges and shading to a multiple of that. Crude, but it reliably separates "nothing
  // is being drawn" from "there is something" — without pulling a PNG decoder into the
  // checking environment.
  expect(
    shot.byteLength,
    `canvas screenshot is only ${shot.byteLength} bytes — looks like an empty surface`,
  ).toBeGreaterThan(12_000);
});

test("WASD changes the picture", async ({ page }) => {
  await page.goto("/", { waitUntil: "load" });
  await page.waitForTimeout(2_500);

  const canvas = page.locator(CANVAS);
  await canvas.click({ position: { x: 50, y: 50 } });

  const before = await canvas.screenshot();

  await page.keyboard.down("KeyW");
  await page.waitForTimeout(1_500);
  await page.keyboard.up("KeyW");
  await page.waitForTimeout(500);

  const after = await canvas.screenshot();

  expect(Buffer.compare(before, after), "the picture did not change after WASD").not.toBe(0);
});
