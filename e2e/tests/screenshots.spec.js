// Visual baselines of four key pages, desktop and phone. They skip until a baseline exists:
// generate them with `npx playwright test --update-snapshots` (see README.md).
const { test, expect, baselineMissing } = require("./fixtures");

/* Wait until the page height stops changing (two reads 400 ms apart agree). */
async function waitForStableHeight(page) {
  const height = () => page.evaluate(() => document.documentElement.scrollHeight);
  let previous = -1;
  for (let i = 0; i < 20; i++) {
    const current = await height();
    if (current === previous) return;
    previous = current;
    await page.waitForTimeout(400);
  }
}

const PAGES = [
  ["overview", "dashboard", ".tiles a.tile"],
  ["health", "health", "#healthAttention"],
  ["trends", "trends", "figure.chart svg.chart-canvas"],
  ["row-health", "rows", "#rowCards .row-card"],
  ["backups", "backups", "figure.chart svg.chart-canvas"],
];

for (const [name, route, ready] of PAGES) {
  test(`${name} looks the same`, async ({ page, app }, testInfo) => {
    test.skip(baselineMissing(testInfo, `${name}.png`), `No baseline for ${name} yet: run npx playwright test --update-snapshots`);
    await app.open(route);
    await expect(page.locator(ready).first()).toBeVisible();
    // Let late panels and web fonts settle: on a phone the page grows after the first card appears.
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await waitForStableHeight(page);
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
    await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: true });
    expect(app.errors).toEqual([]);
  });
}
