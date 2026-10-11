// Shared fixtures: a demo server per worker (scripts/demo_server.py on a free port, clock frozen,
// TZ=UTC), a signed-in page with the browser clock frozen to the same instant, and console errors.
const { test: base, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const TOKEN = "demo-token-0000";
const NOW = "2026-10-11T12:00:00";

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/* Start scripts/demo_server.py with extra flags (for example --playing or --read-only). */
async function startDemo(args = []) {
  const port = await freePort();
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const child = spawn(python, [path.join(ROOT, "scripts", "demo_server.py"), "--port", String(port), "--now", NOW, ...args],
    { env: { ...process.env, TZ: "UTC", PYTHONDONTWRITEBYTECODE: "1" }, stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  child.stderr.on("data", chunk => { stderr += chunk; });
  const url = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 15_000;
  for (;;) {
    if (child.exitCode !== null) throw new Error(`The demo server exited: ${stderr}`);
    try {
      const response = await fetch(url + "/");
      if (response.ok) break;
    } catch (_) { /* not listening yet */ }
    if (Date.now() > deadline) {
      child.kill();
      throw new Error(`The demo server did not start: ${stderr}`);
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const stop = () => new Promise(resolve => {
    if (child.exitCode !== null) return resolve();
    child.once("exit", () => resolve());
    child.kill();
  });
  return { url, port, stop };
}

/* A page has loaded when its heading is shown and no skeleton is left. */
async function waitForPage(page) {
  await expect(page.locator("#content h2").first()).toBeVisible();
  await expect(page.locator('#content .page-skeleton, #content [aria-busy="true"]')).toHaveCount(0);
}

/* Screenshot tests skip until their baseline exists, unless this run writes baselines
   (npx playwright test --update-snapshots); see README.md. */
function baselineMissing(testInfo, name) {
  const updating = ["all", "changed"].includes(testInfo.config.updateSnapshots);
  return !updating && !fs.existsSync(testInfo.snapshotPath(name, { kind: "screenshot" }));
}

const test = base.extend({
  demo: [async ({}, use) => {
    const demo = await startDemo();
    await use(demo);
    await demo.stop();
  }, { scope: "worker" }],

  baseURL: async ({ demo }, use) => { await use(demo.url); },

  /* Browser console errors and uncaught exceptions seen by this test. An API refusal the test
     provokes (401, 409 …) is logged by Chromium as a failed resource and is not an error here. */
  consoleErrors: async ({ page }, use) => {
    const errors = [];
    page.on("console", message => {
      if (message.type() !== "error") return;
      const refusal = /\/api\//.test(message.location().url || "") && /status of 4\d\d/.test(message.text());
      if (!refusal) errors.push(message.text());
    });
    page.on("pageerror", error => errors.push(String(error)));
    await use(errors);
  },

  /* Signed in (token in localStorage, as after opening a #token= link) with the clock frozen. */
  app: async ({ page, consoleErrors }, use) => {
    await page.clock.setFixedTime(new Date(NOW + "Z"));
    await page.addInitScript(token => {
      try { if (!localStorage.getItem("bsa_token")) localStorage.setItem("bsa_token", token); } catch (_) { /* storage blocked */ }
    }, TOKEN);
    const app = {
      errors: consoleErrors,
      async open(route) {
        await page.goto("/#/" + route.replace(/^#?\/?/, ""));
        await waitForPage(page);
      },
    };
    await use(app);
  },
});

module.exports = { test, expect, startDemo, waitForPage, baselineMissing, TOKEN, NOW };
