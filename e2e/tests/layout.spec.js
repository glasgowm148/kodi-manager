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
      const phone = page.viewportSize().width;
      // A mobile browser widens its layout viewport (innerWidth) to fit content that overflows, so
      // every width is compared with the phone's 390 px, not with innerWidth.
      const sizes = await page.evaluate(phone => ({
        page: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        view: window.innerWidth,
        // For the failure message: elements past the phone's right edge that no scroll box clips.
        // Overflow only clips descendants it contains, so a position:absolute element skips
        // static ancestors (the 0.7.11 bug: an .sr-only table heading escaping .table-scroll).
        wide: [...document.querySelectorAll("body *")].filter(el => {
          if (el.getBoundingClientRect().right <= phone + 1) return false;
          let escaping = ["absolute", "fixed"].includes(getComputedStyle(el).position);
          for (let up = el.parentElement; up && up !== document.body; up = up.parentElement) {
            const style = getComputedStyle(up);
            if (escaping && style.position === "static") continue;
            if (style.overflowX !== "visible") return false;
            escaping = ["absolute", "fixed"].includes(style.position);
          }
          return true;
        }).slice(0, 5).map(el => `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${[...el.classList].map(c => "." + c).join("")}`
            + ` (right edge ${Math.round(el.getBoundingClientRect().right)}px)`),
      }), phone);
      expect(phone).toBe(390);
      expect(Math.max(sizes.page, sizes.body, sizes.view), `#/${route} is wider than the phone; widest: ${sizes.wide.join(", ")}`)
        .toBeLessThanOrEqual(phone);
      expect(app.errors).toEqual([]);
    });
  }
});
