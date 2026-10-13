// The dashboard's main journeys, run against the demo server (desktop and phone projects).
const { test, expect, startDemo, waitForPage, TOKEN } = require("./fixtures");

const heading = page => page.locator("#content .page-head h2");

test("a #token= link signs in and drops the token from the address bar", async ({ page }) => {
  await page.goto(`/#token=${TOKEN}`);
  await waitForPage(page);
  await expect(page).toHaveURL(/#\/dashboard$/);
  expect(await page.evaluate(() => localStorage.getItem("bsa_token"))).toBe(TOKEN);
});

test("without a token the dashboard asks for one", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#tokenForm")).toBeVisible();
  await page.locator("#tokenInput").fill("wrong-token");
  await page.locator('#tokenForm button[type="submit"]').click();
  await expect(page.locator(".token-panel [role=alert]")).toContainText("not accepted");
  await page.locator("#tokenInput").fill(TOKEN);
  await page.locator('#tokenForm button[type="submit"]').click();
  await expect(page.locator("#screenTitle")).toBeVisible();
});

test("overview leads with clickable chart cards, then attention, history and tasks", async ({ page, app }) => {
  await app.open("dashboard");
  await expect(page.locator(".screen-state")).toContainText("Idle");
  await expect(page.locator("#screenTitle")).toHaveText("Overview");
  await expect(page.locator(".screen-meta")).toContainText("Living room");
  await expect(page.locator(".task-grid a")).toHaveCount(6);
  await expect(page.locator("#attentionTitle")).toHaveText("Needs attention");
  await expect(page.locator(".log-summary")).toContainText("123 warnings");
  const tiles = page.locator(".tiles a.tile[data-tile]");
  await expect(tiles).toHaveCount(6);
  const chartTop = (await tiles.first().boundingBox()).y;
  expect(chartTop).toBeLessThan((await page.locator('#attentionTitle').boundingBox()).y);
  expect(chartTop).toBeLessThan((await page.locator('#manageTitle').boundingBox()).y);
  await expect(page.locator('.log-since')).toContainText('0 errors · 29 warnings · 1 known notice');
  for (const key of ["memory", "internet", "rows", "backups", "protection", "accounts"]) {
    await expect(page.locator(`.tile[data-tile="${key}"]`)).toBeVisible();
  }
  await expect(page.locator('.tile[data-tile="memory"] svg.spark')).toBeVisible();
  await expect(page.locator("#top")).toContainText("Kodi 22.0");
  await page.locator('.tile[data-tile="rows"]').click();
  await waitForPage(page);
  await expect(heading(page)).toHaveText("Row health");
  expect(app.errors).toEqual([]);
});

test("the side menu and section tabs move between pages", async ({ page, app }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "The side menu is the desktop and tablet layout");
  await app.open("dashboard");
  await expect(page.locator("#nav")).toBeVisible();
  await expect(page.locator("#tabbar")).toBeHidden();
  await page.locator('#nav a[data-route="#/trends"]').click();
  await waitForPage(page);
  await expect(page).toHaveURL(/#\/trends$/);
  await expect(heading(page)).toHaveText("Trends");
  await expect(page.locator('#nav a[data-route="#/trends"]')).toHaveAttribute("aria-current", "page");
  await page.locator('#subnav a[href="#/health"]').click();
  await waitForPage(page);
  await expect(heading(page)).toHaveText("Health checks");
  await expect(page.locator('#subnav a[href="#/health"]')).toHaveAttribute("aria-current", "page");
  await page.locator('#nav [data-group="backups"] > summary').click();
  await page.locator('#nav a[data-route="#/backups"]').click();
  await waitForPage(page);
  await expect(heading(page)).toHaveText("Backups");
  await page.locator('#nav [data-group="addons"] > summary').click();
  await page.locator('#nav a[data-route="#/addons"]').click();
  await waitForPage(page);
  await expect(heading(page)).toHaveText("All add-ons");
  expect(app.errors).toEqual([]);
});

test("the phone bottom bar and its More menu move between pages", async ({ page, app }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "The bottom bar is the phone layout");
  await app.open("dashboard");
  await expect(page.locator("#nav")).toBeHidden();
  await expect(page.locator("#tabbar [data-tab-group]")).toHaveCount(5);
  await expect(page.locator('#tabbar [data-tab-group="status"]')).toHaveClass(/\bactive\b/);
  await page.locator('#tabbar a[data-tab-group="rows"]').click();
  await waitForPage(page);
  await expect(page).toHaveURL(/#\/rows$/);
  await expect(heading(page)).toHaveText("Row health");
  await expect(page.locator('#tabbar [data-tab-group="rows"]')).toHaveClass(/\bactive\b/);
  await page.locator("#tabMore").click();
  await expect(page.locator("#nav")).toBeVisible();
  await expect(page.locator("#tabMore")).toHaveAttribute("aria-expanded", "true");
  await page.locator('#nav [data-group="accounts"] > summary').click();
  await page.locator('#nav a[data-route="#/accounts"]').click();
  await waitForPage(page);
  await expect(page.locator("#nav")).toBeHidden();
  await expect(heading(page)).toHaveText("Accounts");
  await expect(page.locator("#tabMore")).toHaveClass(/\bactive\b/);
  await page.locator("#tabMore").click();
  await expect(page.locator("#nav")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#nav")).toBeHidden();
  expect(app.errors).toEqual([]);
});

test("Trends draws its charts, switches range and reads values", async ({ page, app }) => {
  await app.open("trends");
  const charts = page.locator("figure.chart");
  await expect(charts).toHaveCount(3);
  await expect(page.locator("figure.chart svg.chart-canvas")).toHaveCount(3);
  await expect(page.locator("figure.chart svg.chart-canvas path").first()).toBeAttached();
  await page.locator('[data-range="1"]').click();
  await expect(page.locator('[data-range="1"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("figure.chart svg.chart-canvas")).toHaveCount(3);
  const plot = page.locator("[data-chart-plot]").first();
  await plot.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(plot.locator(".chart-tip")).toBeVisible();
  await expect(plot.locator(".chart-tip .tip-row").first()).toBeVisible();
  expect(app.errors).toEqual([]);
});

test("Row health filters, searches and sorts the rows", async ({ page, app }) => {
  await app.open("rows");
  const count = page.locator("#rowCount");
  const cards = page.locator("#rowCards .row-card");
  await expect(count).toHaveText("Showing 15 of 15 rows");
  await expect(cards.first().locator("h3")).toHaveText("Family movie night");   // keeps failing: first
  for (const [filter, shown, states] of [["failing", 2, ["persistent", "failing"]], ["attention", 3, ["persistent", "failing", "empty"]],
    ["stale", 2, ["stale"]], ["fresh", 9, ["fresh"]]]) {
    await page.locator(`[data-row-filter="${filter}"]`).click();
    await expect(page.locator(`[data-row-filter="${filter}"]`)).toHaveAttribute("aria-pressed", "true");
    await expect(count).toHaveText(`Showing ${shown} of 15 rows`);
    for (const state of await cards.evaluateAll(nodes => nodes.map(node => node.dataset.rowState))) expect(states).toContain(state);
  }
  await page.locator('[data-row-filter="all"]').click();
  await page.locator("#rowSearch").fill("kids");
  await expect(count).toHaveText("Showing 1 of 15 rows");
  await expect(cards.locator("h3")).toHaveText(["Kids TV"]);
  await page.locator("#rowSearch").fill("no such row");
  await expect(page.locator("#rowCards .empty-inline")).toBeVisible();
  await page.locator("#rowSearch").fill("");
  await page.locator("#rowSort").selectOption("name");
  await expect(cards.first().locator("h3")).toHaveText("Animation");
  expect(app.errors).toEqual([]);
});

test("a settings change is reviewed, saved and backed up", async ({ page, app }) => {
  await app.open("addon/plugin.video.pov");
  await expect(page.locator("#content h2").first()).toHaveText("POV");
  const save = page.locator("#saveChanges");
  await expect(save).toBeHidden();
  await page.locator('[data-setting="results.quality"]').selectOption("720p");
  await expect(page.locator("#dirtyStatus")).toHaveText("1 unsaved change");
  await expect(save).toBeEnabled();
  await save.click();
  const dialog = page.locator("dialog.km-dialog[open]");
  await expect(dialog.locator("h2")).toHaveText("Save 1 change?");
  await expect(dialog.locator("pre")).toContainText("720p");
  await dialog.locator('button[value="ok"]').click();
  await expect(page.locator(".toast-ok")).toContainText("Saved 1 change. Backup 20261011-120000-demo.");
  await expect(page.locator(".toast-ok button.action")).toHaveText("Restore settings from before this save");
  await expect(page.locator("#dirtyStatus")).toHaveText("No unsaved changes");
  expect(app.errors).toEqual([]);
});

test("while something plays, a checkpoint is refused in plain words", async ({ page, app }) => {
  const playing = await startDemo(["--playing"]);
  try {
    await page.goto(playing.url + "/#/dashboard");
    await waitForPage(page);
    await expect(page.locator(".screen-state")).toContainText("Playing now");
    await expect(page.locator(".screen-detail")).toContainText("“Paper Planets: The Comet” is playing.");
    await page.goto(playing.url + "/#/backups");
    await waitForPage(page);
    await page.locator("#stackBackup").click();
    const error = page.locator(".toast-error");
    await expect(error).toHaveAttribute("role", "alert");
    await expect(error).toContainText("Something is playing on the TV. Try again when viewing has finished.");
    expect(app.errors).toEqual([]);
  } finally {
    await playing.stop();
  }
});

test("a view-only profile disables changes and says why", async ({ page, app }) => {
  const readOnly = await startDemo(["--read-only"]);
  try {
    await page.goto(readOnly.url + "/#/backups");
    await waitForPage(page);
    await expect(page.locator("#banner .notice--view")).toContainText("View only.");
    await expect(page.locator("#stackBackup")).toBeDisabled();
    await expect(page.locator("[data-restore]").first()).toBeDisabled();
    expect(app.errors).toEqual([]);
  } finally {
    await readOnly.stop();
  }
});

test("restoring a checkpoint asks first and can be cancelled", async ({ page, app }) => {
  await app.open("backups");
  await expect(page.locator("figure.chart svg.chart-canvas")).toHaveCount(1);
  const restore = page.locator("[data-restore]").first();
  const id = await restore.getAttribute("data-restore");
  const dialog = page.locator("dialog.km-dialog[open]");
  await restore.click();
  await expect(dialog.locator("h2")).toHaveText("Restore this checkpoint?");
  await expect(dialog.locator("pre")).toHaveText(id);
  await expect(dialog.locator('button[value="cancel"]')).toBeFocused();
  await dialog.locator('button[value="cancel"]').click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".toast")).toHaveCount(0);
  await restore.click();
  await dialog.locator('button[value="ok"]').click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".toast-ok")).toContainText("1 add-on restored. Undo backup: 20261011-120000-undo.");
  await expect(page.locator(".toast-ok button.action")).toHaveText("Undo restore");
  expect(app.errors).toEqual([]);
});

test("the theme button cycles automatic, light and dark and is remembered", async ({ page, app }) => {
  await app.open("dashboard");
  const html = page.locator("html");
  const toggle = page.locator("#themeToggle");
  const background = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await expect(html).not.toHaveAttribute("data-theme", /.+/);
  expect(await background()).toBe("rgb(243, 244, 248)");
  await toggle.click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await expect(toggle).toHaveAttribute("title", /^Theme: light/);
  await toggle.click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(toggle).toHaveAttribute("title", /^Theme: dark/);
  expect(await background()).toBe("rgb(18, 21, 39)");
  await page.reload();
  await waitForPage(page);
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await background()).toBe("rgb(18, 21, 39)");
  await toggle.click();
  await expect(html).not.toHaveAttribute("data-theme", /.+/);
  expect(await page.evaluate(() => localStorage.getItem("km_theme"))).toBeNull();
  expect(app.errors).toEqual([]);
});


test("Kodi log retains 24 hours with pagination, filters and a separate raw tail", async ({ page, app }) => {
  await app.open("kodi-logs");
  await expect(page.locator("#content")).toContainText("past 24 hours");
  await expect(page.locator("#historyLogBox .log-line")).toHaveCount(100);
  await page.locator('.original-log-entries > summary').click();
  await page.locator("#olderLogEntries").click();
  await expect(page.locator("#historyLogBox .log-line")).toHaveCount(124);
  await expect(page.locator("#olderLogEntries")).toBeHidden();
  await page.locator('[data-history-level="error"]').click();
  await expect(page.locator("#historyLogBox")).toContainText("No retained entries");
  await page.locator('[data-history-level="notice"]').click();
  await expect(page.locator("#historyLogBox .log-line")).toHaveCount(1);
  await page.locator('summary').filter({hasText:'Current raw log tail'}).click();
  await page.locator("#loadRawKodiLog").click();
  await expect(page.locator("#rawKodiLog")).toContainText("info");
  expect(app.errors).toEqual([]);
});


test("home tasks reach management pages and preserve keyboard focus on refresh", async ({page, app}) => {
  await app.open("dashboard");
  const task = page.locator('[data-overview-link="task-0"]');
  await task.focus();
  await page.clock.runFor(61000);
  await expect(task).toBeFocused();
  await task.click();
  await waitForPage(page);
  await expect(heading(page)).toHaveText("All add-ons");
  await app.open("health");
  await expect(page.locator('#healthAttention')).toHaveText('Needs attention now');
  await expect(page.locator('#healthLogs')).toHaveText('Recorded logs · past 24 hours');
  await expect(page.locator('#passedChecks')).not.toHaveAttribute('open', '');
  await page.locator('#passedChecks > summary').click();
  await expect(page.locator('#passedChecks .check').first()).toBeVisible();
  expect(app.errors).toEqual([]);
});


test("overview refresh updates read-only state and opens direct add-on navigation", async ({page, app}) => {
  await app.open('dashboard');
  await page.request.get('/demo/writes');
  await page.clock.runFor(61000);
  await expect(page.locator('#top')).toContainText('View only');
  await expect(page.locator('.screen-meta')).toContainText('View only');
  await expect(page.locator('.screen-detail')).toContainText('changes are off');
  await app.open('pov');
  await expect(page.locator('#nav [data-group="addons"]')).toHaveAttribute('open','');
  await expect(page.locator('#nav .nav-shortcuts')).toHaveAttribute('open','');
  expect(app.errors).toEqual([]);
});


test("chart and section links keep keyboard focus through refresh", async ({page, app}) => {
  await app.open('dashboard');
  for (const selector of ['[data-tile="memory"]', '[data-overview-link="trends"]', '[data-overview-link="health"]']) {
    const link = page.locator(selector);
    await link.focus();
    await page.clock.runFor(61000);
    await expect(link).toBeFocused();
  }
});
