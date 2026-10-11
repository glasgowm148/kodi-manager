// Browser tests of the dashboard against scripts/demo_server.py (synthetic data, frozen clock).
// See README.md for running them and for (re)generating the screenshot baselines.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  // Generous: on a cold machine the first page of a worker can take 20 s to load (see fixtures.js warmUp).
  timeout: 60_000,
  expect: {
    timeout: 7_000,
    // Small, anti-aliasing-tolerant threshold: a moved card or a changed colour still fails.
    toHaveScreenshot: { threshold: 0.2, maxDiffPixelRatio: 0.01, animations: "disabled", caret: "hide", scale: "css" },
  },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  // One baseline per page, project (desktop/phone) and platform: fonts differ between macOS and Linux.
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}-{platform}{ext}",
  use: {
    browserName: "chromium",
    // The full Chromium build (new headless mode), so an installed chromium-<revision> is enough.
    channel: "chromium",
    locale: "en-GB",
    timezoneId: "UTC",
    colorScheme: "light",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
  ],
});
