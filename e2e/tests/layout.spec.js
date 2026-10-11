// Every page fits a 390 px phone screen: nothing makes the page itself scroll sideways
// (wide tables and charts scroll inside their own boxes).
const { test, expect } = require("./fixtures");

// Every route of the side menu for the demo TV, an add-on's settings and a settings search.
const PAGES = ["dashboard", "trends", "health", "rows", "widgets", "cached-rows", "components", "skin", "tmdbhelper", "pov",
  "cocoscrapers", "addons", "pipeline", "playback-test", "install", "backups", "fixes", "accounts", "trakt", "kodi-logs", "logs",
  "diagnostics", "setup", "addon/plugin.video.pov", "search?q=torbox"];

test.describe("at phone width", () => {
  test.skip(({ isMobile }) => !isMobile, "Checked in the phone project (390 px)");

  test("the menu lists exactly the pages checked here", async ({ page, app }) => {
    await app.open("dashboard");
    const routes = await page.locator("#nav a[data-route]").evaluateAll(links => links.map(link => link.dataset.route.slice(2)));
    expect(routes.sort()).toEqual(PAGES.filter(route => !/[/?]/.test(route)).sort());
  });

  for (const route of PAGES) {
    test(`#/${route} has no horizontal overflow`, async ({ page, app }) => {
      await app.open(route);
      await expect(page.locator("#content .error-panel")).toHaveCount(0);
      const sizes = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        view: window.innerWidth,
        // For the failure message: the first few elements that reach past the right edge.
        wide: [...document.querySelectorAll("body *")].filter(el => el.getBoundingClientRect().right > window.innerWidth + 1)
          .slice(0, 5).map(el => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${[...el.classList].map(c => "." + c).join("")}`),
      }));
      expect(sizes.view).toBe(390);
      expect(Math.max(sizes.page, sizes.body), `#/${route} scrolls sideways; widest: ${sizes.wide.join(", ")}`).toBeLessThanOrEqual(sizes.view);
      expect(app.errors).toEqual([]);
    });
  }
});
