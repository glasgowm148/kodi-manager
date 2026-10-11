// Visual baselines of four key pages, desktop and phone. They skip until a baseline exists:
// generate them with `npx playwright test --update-snapshots` (see README.md).
const { test, expect, baselineMissing } = require("./fixtures");

const PAGES = [
  ["overview", "dashboard", ".tiles a.tile"],
  ["trends", "trends", "figure.chart svg.chart-canvas"],
  ["row-health", "rows", "#rowCards .row-card"],
  ["backups", "backups", "figure.chart svg.chart-canvas"],
];

for (const [name, route, ready] of PAGES) {
  test(`${name} looks the same`, async ({ page, app }, testInfo) => {
    test.skip(baselineMissing(testInfo, `${name}.png`), `No baseline for ${name} yet: run npx playwright test --update-snapshots`);
    await app.open(route);
    await expect(page.locator(ready).first()).toBeVisible();
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
    await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: true });
    expect(app.errors).toEqual([]);
  });
}
