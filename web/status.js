/* Status pages: Overview (the first screen), Trends and Row health.
   Pure helpers (tile and verdict builders, row grouping) come first so they can be tested;
   the views below them only fetch, render and wire. Depends on core.js, charts.js and app.js helpers. */
const STATUS_TONES = {ok:["ok", "check"], warning:["warn", "alert"], error:["bad", "alert"], unknown:["muted", "help"]};
function toneOf(status) { return (STATUS_TONES[status] || STATUS_TONES.unknown)[0]; }
function tonePill(tone, label) {
  const icon = {ok:"check", warn:"alert", bad:"alert", info:"help", muted:"minus"}[tone] || "help";
  return dashboardPill(tone, label, icon);
}
const TONE_WORD = {ok:"All good", warn:"Needs a look", bad:"Problem", muted:"Not checked", info:"Info"};
const TONE_RANK = {bad:3, warn:2, info:1, muted:0, ok:0};

/* History helpers ----------------------------------------------------------------------- */
function historyGap(history) { return 3 * (history?.resolution_seconds || 900); }
/* Only the samples that hold a new internet check, with the median answer time across services. */
function probeSeries(history) {
  const s = history?.series || {}, t = s.t || [], status = s.network_status || [];
  const hosts = history?.hosts || [], latency = history?.latency_ms || {};
  const out = {t:[], status:[], median:[], hosts:Object.fromEntries(hosts.map(h => [h, []]))};
  t.forEach((time, i) => {
    if (!status[i]) return;
    out.t.push(time); out.status.push(status[i]);
    const values = hosts.map(h => latency[h]?.[i]);
    hosts.forEach((h, k) => out.hosts[h].push(finite(values[k]) ? values[k] : null));
    out.median.push(median(values.filter(finite)));
  });
  return out;
}
/* Checkpoints per local day over the last `days` days (oldest first). */
function checkpointsPerDay(stamps, now, days = 14) {
  const end = new Date(now * 1000); end.setHours(12, 0, 0, 0);
  const t = [], counts = [];
  for (let i = days - 1; i >= 0; i--) { const d = new Date(end); d.setDate(end.getDate() - i); t.push(Math.floor(d.getTime() / 1000)); counts.push(0); }
  for (const stamp of stamps || []) {
    const time = typeof stamp === "number" ? stamp : parseStamp(stamp);
    if (!finite(time)) continue;
    const d = new Date(time * 1000); d.setHours(12, 0, 0, 0);
    const index = t.indexOf(Math.floor(d.getTime() / 1000));
    if (index >= 0) counts[index]++;
  }
  return {t, counts};
}

/* Overview tiles: each returns {key, name, icon, tone, value, text, href, spark} ---------------- */
function memoryTile(memory, history) {
  const m = memory || {};
  const s = history?.series || {};
  const spark = sparkline(s.t || [], s.memory_available_mb || [], {label:"Free memory over the last 7 days", maxGap:historyGap(history), min:0});
  if (!finite(m.available_mb)) return {key:"memory", name:"Memory", icon:"memory", tone:"muted", value:"Unknown", text:m.detail || "This device doesn’t report memory figures.", href:"#/trends", spark};
  const tone = toneOf(m.status);
  const swapFull = finite(m.swap_used_pct) && m.swap_used_pct >= 90;
  const text = m.pressure === "tight" ? "Memory is tight: swap is nearly full. Android may close Kodi when it’s in the background (screensaver or another app). Restarting Kodi frees memory."
    : tone !== "ok" ? "Running low. Close apps you’re not using, or restart Kodi if add-ons start timing out."
    : `Kodi is using ${formatMB(m.kodi_mb)} of ${formatMB(m.total_mb)}.${swapFull ? " Swap is nearly full, which is normal on Android." : ""}`;
  return {key:"memory", name:"Memory", icon:"memory", tone, value:`${formatMB(m.available_mb)} free`, text, href:"#/trends", spark};
}
function internetTile(internet, history) {
  const probes = probeSeries(history);
  const spark = sparkline(probes.t, probes.median, {label:"Median answer time of streaming services over the last 7 days", maxGap:historyGap(history) * 2, min:0});
  if (!internet) return {key:"internet", name:"Internet", icon:"wifi", tone:"muted", value:"Not checked yet", text:"The first check runs a few minutes after Kodi starts, while the TV is idle.", href:"#/trends", spark};
  const hosts = internet.hosts || [];
  const failed = hosts.filter(h => h.seconds === null || h.seconds === undefined).map(h => h.name);
  const slowest = Math.max(0, ...hosts.filter(h => finite(h.seconds)).map(h => h.seconds));
  const tone = toneOf(internet.status);
  const value = failed.length ? `${failed.length} of ${hosts.length} not answering` : hosts.length ? `${formatMs(slowest * 1000)} slowest` : "Checked";
  const text = failed.length ? `${failed.join(" and ")} didn’t answer. If streams fail, restart the TV or router.` : hosts.length ? `${hosts.map(h => h.name).join(", ")} answered.` : internet.detail || "";
  return {key:"internet", name:"Internet", icon:"wifi", tone, value, text:`${text} Checked ${formatRelative(internet.age_seconds)}.`, href:"#/trends", spark};
}
function rowsTile(rows, history) {
  const r = rows || {cached:0, failing:0, persistent:0};
  const s = history?.series || {};
  const spark = sparkline(s.t || [], s.rows_failing || [], {label:"Rows failing over the last 7 days", maxGap:historyGap(history), min:0, kind:"bars"});
  if (!r.cached) return {key:"rows", name:"Home rows", icon:"rows", tone:"muted", value:"No cached rows", text:"Rows load straight from your add-ons. Cached rows make the home screen fill in instantly.", href:"#/rows", spark};
  const tone = r.persistent ? "bad" : r.failing ? "warn" : "ok";
  const value = r.failing ? `${r.failing} of ${r.cached} failing` : `${r.cached} row${r.cached === 1 ? "" : "s"}, all working`;
  const stale = finite(r.stale) ? r.stale : 0, empty = finite(r.empty) ? r.empty : 0;
  const parts = [];
  if (r.failing) parts.push(`${r.failing === 1 ? "One row isn’t" : `${r.failing} rows aren’t`} refreshing; the last good copy is still shown. Tap to see which.`);
  else if (stale) parts.push(`${r.cached - stale} fresh; ${stale} refresh${stale === 1 ? "es" : ""} the next time the TV is idle.`);
  else if (finite(r.stale)) parts.push("All fresh.");
  else parts.push("None failed on its last refresh.");
  if (empty) parts.push(`${empty} came back empty.`);
  const text = parts.join(" ");
  return {key:"rows", name:"Home rows", icon:"rows", tone, value, text, href:"#/rows", spark};
}
function backupsTile(backups, now) {
  const b = backups || {count:0};
  const perDay = checkpointsPerDay(b.times || [], now, 14);
  const spark = b.count ? sparkline(perDay.t, perDay.counts, {label:"Checkpoints per day over the last 14 days", min:0, kind:"bars"}) : "";
  const last = b.last ? parseStamp(b.last.timestamp || b.last.backup_id) : null;
  if (!last) return {key:"backups", name:"Backups", icon:"history", tone:"warn", value:"No checkpoints yet", text:"Create one before changing anything, so you can always go back.", href:"#/backups", spark};
  const age = now - last;
  const nightlyFailed = b.nightly?.status === "error";
  const tone = nightlyFailed || age > 3 * 86400 ? "warn" : "ok";
  const text = nightlyFailed ? "Last night’s checkpoint failed. Open Backups to take one now." : `${b.count} kept. A new one is taken each night after 3am while the TV is idle.`;
  return {key:"backups", name:"Backups", icon:"history", tone, value:`Last one ${formatRelative(age)}`, text, href:"#/backups", spark};
}
function protectionTile(protection) {
  const fixes = protection?.fixes || {}, baseline = protection?.baseline;
  const parts = [];
  let tone = "ok";
  if (fixes.healthy === false) { tone = "warn"; parts.push(`${fixes.attention || "Some"} custom fix${fixes.attention === 1 ? "" : "es"} changed`); }
  else if (fixes.healthy === true) parts.push("Custom fixes intact");
  if (baseline && baseline.drifted) { tone = "warn"; parts.push(`${baseline.drifted} protected setting${baseline.drifted === 1 ? "" : "s"} changed`); }
  else if (baseline && baseline.total) parts.push(`${baseline.total} protected setting${baseline.total === 1 ? "" : "s"} as you set ${baseline.total === 1 ? "it" : "them"}`);
  if (!parts.length) return {key:"protection", name:"Protection", icon:"shield", tone:"muted", value:"Nothing protected", text:"Protect a setting from Health checks to have it re-applied after add-on updates.", href:"#/health"};
  const href = fixes.healthy === false ? "#/fixes" : "#/health";
  return {key:"protection", name:"Protection", icon:"shield", tone, value:tone === "ok" ? "Intact" : "Changed", text:`${parts.join(". ")}.${tone === "ok" ? "" : " Usually after an update: re-apply from Health checks."}`, href};
}
function accountsTile(accounts) {
  const list = (accounts || []).filter(a => a && a.label);
  if (!list.length) return {key:"accounts", name:"Accounts", icon:"key", tone:"muted", value:"Not checked yet", text:"Trakt and TorBox are checked twice a day while the TV is idle.", href:"#/accounts"};
  const worst = list.reduce((a, b) => (TONE_RANK[toneOf(b.status)] > TONE_RANK[toneOf(a.status)] ? b : a));
  const expiring = list.filter(a => finite(a.days_left) && !a.renews).sort((a, b) => a.days_left - b.days_left)[0];
  const tone = toneOf(worst.status);
  const name = a => String(a.label).replace(/\s*\(.*\)$/, "");
  let value, text;
  const short = a => name(a).replace(/\s+(subscription|sign-in)$/i, "");
  if (tone !== "ok" && finite(worst.days_left) && worst.days_left >= 0 && !worst.renews) { value = `${short(worst)} ends in ${worst.days_left} day${worst.days_left === 1 ? "" : "s"}`; text = worst.detail || ""; }
  else if (tone !== "ok") { value = name(worst); text = worst.detail || "Needs attention."; }
  else if (expiring) { value = `${expiring.days_left} days left`; text = `${name(expiring)} runs until then. ${list.length > 1 ? "Other accounts are fine." : ""}`.trim(); }
  else { value = "Signed in"; text = `${list.map(name).join(" and ")} ${list.length === 1 ? "is" : "are"} fine.`; }
  return {key:"accounts", name:"Accounts", icon:"key", tone, value, text, href:"#/accounts"};
}
function overviewTiles(o, history, now) {
  return [memoryTile(o.memory, history), internetTile(o.internet, history), rowsTile(o.rows, history),
    backupsTile(o.backups, now), protectionTile(o.protection), accountsTile(o.accounts)];
}
/* One sentence for the whole TV, plus links to whatever needs a look. */
function overviewVerdict(o, tiles) {
  const issues = tiles.filter(t => t.tone === "warn" || t.tone === "bad");
  const headline = !issues.length ? "All good" : issues.length === 1 ? `${issues[0].name} needs a look` : `${issues.length} things need a look`;
  const tone = issues.some(t => t.tone === "bad") ? "bad" : issues.length ? "warn" : "ok";
  const playing = o.playback?.active === true;
  const what = o.playback?.title ? `“${o.playback.title}” is playing.` : "Something is playing.";
  const detail = playing ? `${what} Anything that would restart or reload Kodi waits until viewing has finished.`
    : o.playback?.active === false ? "Nothing is playing, so it’s a good time to make changes." : "Kodi didn’t say whether something is playing.";
  return {tone, headline, detail, playing, issues:issues.map(t => ({name:t.name, href:t.href, value:t.value}))};
}
function tileMarkup(tile) {
  return `<a class="tile tile--${esc(tile.tone)}" href="${esc(tile.href)}" data-tile="${esc(tile.key)}"><span class="tile-head">${dashboardIcon(tile.icon)}<span class="tile-name">${esc(tile.name)}</span>${tonePill(tile.tone, TONE_WORD[tile.tone] || "")}</span><strong class="tile-value">${esc(tile.value)}</strong><span class="tile-text">${esc(tile.text)}</span>${tile.spark ? `<span class="tile-spark">${tile.spark}</span>` : ""}</a>`;
}
function screenMarkup(o, verdict, checkedAt) {
  const uptime = finite(o.kodi_started_at) && finite(o.generated_at) ? o.generated_at - o.kodi_started_at : null;
  const chips = [o.profile ? `Profile: ${o.profile}` : "", o.kodi_version ? `Kodi ${o.kodi_version}` : "", finite(uptime) && uptime >= 0 ? `Kodi started ${formatRelative(uptime)}` : "", o.write_enabled ? "Changes allowed" : "View only"].filter(Boolean);
  return `<section class="screen screen--${esc(verdict.tone)}${verdict.playing ? " screen--playing" : ""}" aria-labelledby="screenTitle">
    <div class="screen-glass"><p class="screen-state">${dashboardIcon(verdict.playing ? "play" : "tv")}<span>${verdict.playing ? "Playing now" : o.playback?.active === false ? "Idle" : "State unknown"}</span></p>
    <h2 id="screenTitle">${esc(verdict.headline)}</h2><p class="screen-detail">${esc(verdict.detail)}</p>
    ${verdict.issues.length ? `<ul class="screen-issues">${verdict.issues.map(i => `<li><a href="${esc(i.href)}">${esc(i.name)}: ${esc(i.value)}</a></li>`).join("")}</ul>` : ""}</div>
    <div class="screen-stand" aria-hidden="true"></div>
    <ul class="screen-meta" aria-label="This TV">${chips.map(c => `<li>${esc(c)}</li>`).join("")}<li class="screen-checked">Checked ${esc(checkedAt)}</li></ul>
  </section>`;
}
function overviewSkeleton() {
  return `<div class="overview" aria-busy="true"><section class="screen screen--muted"><div class="screen-glass"><p class="screen-state">${dashboardIcon("tv")}<span>Checking the TV…</span></p><h2>Your TV</h2><p class="screen-detail skeleton-line"></p></div><div class="screen-stand" aria-hidden="true"></div></section><div class="tiles">${Array.from({length:6}, () => '<div class="tile tile--skeleton"><span class="skeleton-line short"></span><span class="skeleton-line"></span><span class="skeleton-line"></span></div>').join("")}</div></div>`;
}

async function overviewView(refresh = false) {
  const request = state.overviewRequest = (state.overviewRequest || 0) + 1;
  clearInterval(state.overviewTimer);
  if (!refresh) out(overviewSkeleton());
  let o, history;
  try {
    [o, history] = await Promise.all([api("/api/overview"), api("/api/metrics/history?days=7").catch(() => null)]);
  } catch (error) {
    if (request !== state.overviewRequest) return;
    // An older service on the TV has no overview: show the add-on summary instead.
    if (error?.code === "not_found") { out(`<div class="notice">${esc("Update Kodi Manager on the TV to see the overview. Showing your add-ons instead.")}</div>`); return componentsView(); }
    if (refresh) { const note = $("#overviewNote"); if (note) note.textContent = `Couldn’t refresh: ${friendlyMessage(error)} Showing the previous check.`; scheduleOverview(); return; }
    throw error;
  }
  if (request !== state.overviewRequest || !overviewVisible()) return;
  state.profile = o.profile || "";
  const banner = $("#banner");
  if (banner && state.status) banner.innerHTML = viewOnlyBanner(state.status);
  const now = o.generated_at || Math.floor(Date.now() / 1000);
  const tiles = overviewTiles(o, history, now);
  const verdict = overviewVerdict(o, tiles);
  const checkedAt = formatClock(now);
  resetCharts();
  // A refresh keeps focus where it was (TV remotes and keyboards would otherwise lose their place).
  const focused = refresh ? (document.activeElement?.dataset?.tile ? `[data-tile="${document.activeElement.dataset.tile}"]` : document.activeElement?.id ? `#${document.activeElement.id}` : "") : "";
  out(`<div class="overview">${screenMarkup(o, verdict, checkedAt)}<h3 class="sr-only">Details</h3><div class="tiles">${tiles.map(tileMarkup).join("")}</div>
    <div class="overview-foot"><span id="overviewNote" role="status">Updates every minute while this page is open.</span><button type="button" class="action" id="overviewRefresh">${dashboardIcon("refresh")}<span>Check now</span></button></div></div>`);
  $("#overviewRefresh").onclick = withErrors(() => overviewView(true));
  if (focused) document.querySelector(focused)?.focus({preventScroll:true});
  scheduleOverview();
}
function overviewVisible() { return !location.hash || ["#/dashboard", "#dashboard", "#/overview"].includes(location.hash); }
function scheduleOverview() {
  clearInterval(state.overviewTimer);
  if (overviewVisible()) state.overviewTimer = setInterval(() => { if (!document.hidden && overviewVisible()) overviewView(true).catch(() => {}); }, 60000);
}

/* Trends ------------------------------------------------------------------------------------ */
const RANGES = [[1, "24 hours"], [3, "3 days"], [7, "7 days"]];
function memoryChartSpec(history) {
  const s = history?.series || {};
  const free = s.memory_available_mb || [], kodi = s.kodi_mb || [];
  const total = Math.max(0, ...(s.memory_total_mb || []).filter(finite));
  const low = free.reduce((best, v, i) => finite(v) && (best < 0 || v < free[best]) ? i : best, -1);
  const now = [...free].reverse().find(finite);
  const starts = (history?.kodi_starts || []).filter(finite);
  const restarts = starts.length ? ` Kodi started ${starts.length === 1 ? "once" : `${starts.length} times`} in this period (marked): ${starts.slice(-3).map(formatWhen).join("; ")}.` : "";
  const summary = low < 0 ? "" : `Free memory now ${formatMB(now)}. Lowest ${formatMB(free[low])}, ${formatWhen(s.t[low])}.${restarts}`;
  const gb = values => values.map(v => finite(v) ? v / 1024 : v);
  const formatGB = v => v >= 1 ? `${v.toFixed(1)} GB` : `${Math.round(v * 1024)} MB`;
  return {title:"Memory", summary, t:s.t || [], format:formatGB, tickFormat:v => `${Number.isInteger(v) ? v : v.toFixed(1)} GB`, yMin:0, yMax:total ? total / 1024 : undefined, maxGap:historyGap(history),
    series:[{name:"Free", values:gb(free), cls:"s1", area:true}, {name:"Used by Kodi", values:gb(kodi), cls:"s2"}], events:starts.map(t => ({t, label:"Kodi started"})),
    empty:"No memory samples yet. The TV records one every 15 minutes while it’s idle."};
}
function internetChartSpec(history) {
  const probes = probeSeries(history);
  const hosts = Object.keys(probes.hosts).slice(0, 3);
  const timeouts = [];
  hosts.forEach((h, k) => probes.hosts[h].forEach((v, i) => { if (v === null) timeouts.push({t:probes.t[i], cls:`s${k + 1}`, host:h}); }));
  const med = median(probes.median);
  const span = probes.t.length ? probes.t[probes.t.length - 1] - probes.t[0] : 0;
  // Over more than a day, plot the typical (median) time per 2 hours so single slow checks don't hide the trend.
  const bucket = span > 36 * 3600 ? 7200 : 0;
  const plotted = bucket ? bucketMedian(probes.t, hosts.map(h => probes.hosts[h]), bucket) : {t:probes.t, values:hosts.map(h => probes.hosts[h])};
  const summary = probes.t.length ? `${hosts.join(", ")} answered in a median of ${formatMs(med)}${bucket ? " (lines show the median per 2 hours)" : ""}. ${timeouts.length ? `${timeouts.length} check${timeouts.length === 1 ? "" : "s"} timed out, marked along the top.` : "No checks timed out."}` : "";
  return {title:"Streaming services: answer time", summary, t:plotted.t, format:formatMs, yMin:0, maxGap:Math.max(historyGap(history) * 2, bucket * 2),
    series:hosts.map((h, k) => ({name:h, values:plotted.values[k], cls:`s${k + 1}`, missing:bucket ? "no answer" : "timed out"})), markers:timeouts,
    empty:"No internet checks recorded yet. They run every 10 minutes while the TV is idle."};
}
function rowsChartSpec(history) {
  const s = history?.series || {};
  const failing = s.rows_failing || [];
  const peak = Math.max(0, ...failing.filter(finite));
  const cached = [...(s.rows_cached || [])].reverse().find(finite);
  const summary = (s.t || []).length ? `${peak ? `At most ${peak} row${peak === 1 ? "" : "s"} failing at once` : "No rows failed"}${finite(cached) ? ` out of ${cached} cached` : ""}.` : "";
  return {title:"Home rows failing", summary, t:s.t || [], format:v => String(Math.round(v)), tickFormat:v => Number.isInteger(v) ? String(v) : "", yMin:0, yMax:Math.max(2, peak), step:true, maxGap:historyGap(history),
    series:[{name:"Failing", values:failing, cls:"s1"}, {name:"Failing 3 or more times", values:s.rows_persistent || [], cls:"s2"}],
    empty:"No row samples yet."};
}
async function trendsView(days = state.trendsDays || 7) {
  state.trendsDays = days;
  const history = await api(`/api/metrics/history?days=${encodeURIComponent(days)}`);
  resetCharts();
  const range = `<div class="segmented" role="group" aria-label="Time range">${RANGES.map(([d, label]) => `<button type="button" data-range="${d}" aria-pressed="${d === days}">${esc(label)}</button>`).join("")}</div>`;
  const note = history.count ? `${history.count} samples, one every ${Math.round((history.resolution_seconds || 900) / 60)} minutes while the TV was idle. Gaps are times the TV was busy or off.` : "The TV records a sample every 15 minutes while it’s idle. Check back in an hour.";
  out(`${pageHead("Trends", "How memory, the internet connection and the home-screen rows have behaved recently.", range)}<p class="muted page-note">${esc(note)}</p><div class="chart-grid">${chartFigure(memoryChartSpec(history))}${chartFigure(internetChartSpec(history))}${chartFigure(rowsChartSpec(history))}</div>`);
  document.querySelectorAll("[data-range]").forEach(b => b.onclick = withErrors(() => trendsView(Number(b.dataset.range))));
  mountCharts(document);
}

/* Row health --------------------------------------------------------------------------------- */
const ROW_REASONS = {unavailable:"The add-on didn’t answer or reported an error.", unexpected_empty:"The add-on sent an empty list, so the last good copy is kept."};
function rowHealthState(entry) {
  if (!entry) return "waiting";
  const failures = Number(entry.health?.failures || 0);
  if (failures >= 3) return "persistent";
  if (failures >= 1) return "failing";
  if (entry.stale) return "stale";
  if (!entry.items) return "empty";
  return "fresh";
}
const ROW_STATES = {
  persistent:{tone:"bad", label:"Keeps failing", rank:0}, failing:{tone:"warn", label:"Failed last time", rank:1},
  stale:{tone:"info", label:"Refreshes soon", rank:2}, empty:{tone:"muted", label:"Empty", rank:3},
  waiting:{tone:"muted", label:"Not cached yet", rank:4}, fresh:{tone:"ok", label:"Fresh", rank:5}
};
function rowCards(cache, savedRows) {
  const saved = new Map((Array.isArray(savedRows) ? savedRows : []).map(r => [r.source, r]));
  const seen = new Set();
  const cards = (cache?.entries || []).map(entry => {
    seen.add(entry.source);
    const row = saved.get(entry.source);
    return {source:entry.source, label:row?.label || entry.title || cacheSourceLabel(entry.source), addon:entry.addon_name || "", where:Array.isArray(entry.where) ? entry.where : [], saved:!!row, entry, state:rowHealthState(entry)};
  });
  for (const row of saved.values()) if (!seen.has(row.source)) cards.push({source:row.source, label:row.label, addon:"", where:[], saved:true, entry:null, state:"waiting"});
  return cards;
}
function sortRowCards(cards, sort = "attention") {
  const list = [...cards];
  const name = (a, b) => String(a.label).localeCompare(String(b.label));
  if (sort === "name") return list.sort(name);
  if (sort === "items") return list.sort((a, b) => (b.entry?.items || 0) - (a.entry?.items || 0) || name(a, b));
  if (sort === "oldest") return list.sort((a, b) => (b.entry?.age_seconds ?? Infinity) - (a.entry?.age_seconds ?? Infinity) || name(a, b));
  return list.sort((a, b) => ROW_STATES[a.state].rank - ROW_STATES[b.state].rank || (b.entry?.health?.failures || 0) - (a.entry?.health?.failures || 0) || name(a, b));
}
function filterRowCards(cards, filter = "all", query = "") {
  const q = String(query || "").trim().toLowerCase();
  const groups = {attention:["persistent", "failing", "empty"], failing:["persistent", "failing"], fresh:["fresh"], stale:["stale"]};
  return cards.filter(c => (filter === "all" || (groups[filter] || []).includes(c.state)) && (!q || `${c.label} ${c.source}`.toLowerCase().includes(q)));
}
function rowAddonName(source) {
  try { return new URL(String(source).replace(/^plugin:/, "http:")).hostname.replace(/^plugin\.video\./, ""); } catch (_) { return ""; }
}
function posterStrip(preview) {
  const items = (preview || []).slice(0, 6);
  if (!items.length) return '<div class="row-posters row-posters--empty" aria-hidden="true"></div>';
  return `<ul class="row-posters" aria-label="First titles in this row">${items.map(p => {
    const url = typeof widgetPoster === "function" ? widgetPoster({art:{poster:p.poster}}) : "";
    return `<li title="${esc(p.title)}">${url ? `<img src="${esc(url)}" alt="${esc(p.title)}" loading="lazy" referrerpolicy="no-referrer">` : `<span class="poster-blank">${esc(p.title || "Untitled")}</span>`}</li>`;
  }).join("")}</ul>`;
}
function rowCardMarkup(card, now) {
  const e = card.entry, st = ROW_STATES[card.state];
  const h = e?.health || {};
  const facts = [];
  if (e) {
    facts.push(["Updated", formatRelative(e.age_seconds)], ["Titles", String(e.items ?? "—")]);
    if (h.failures) {
      facts.push(["Failed", `${h.failures} time${h.failures === 1 ? "" : "s"} in a row`]);
      if (finite(h.last_failure)) facts.push(["Last failure", formatRelative(now - h.last_failure)]);
      if (finite(h.retry_at)) facts.push(["Next try", h.retry_at > now ? formatRelative(now - h.retry_at) : "soon"]);
    }
  }
  const reason = h.failures ? (ROW_REASONS[h.reason] || "The last refresh failed; the last good copy is kept.") : card.state === "stale" ? "Older than its refresh interval: nothing is wrong, it refreshes the next time the TV is idle." : card.state === "waiting" ? "Saved here, but no widget has asked for it yet." : "";
  return `<article class="row-card row-card--${esc(st.tone)}" data-row-state="${esc(card.state)}">${posterStrip(e?.preview)}<div class="row-card-body"><div class="row-card-head"><h3>${esc(card.label)}</h3>${tonePill(st.tone, st.label)}</div><p class="row-card-source">${esc([card.where.length ? card.where.join(", ") : "", card.addon || rowAddonName(card.source) || "Kodi"].filter(Boolean).join(" · "))}${card.saved ? " (added here)" : ""}</p>${reason ? `<p class="row-card-reason">${esc(reason)}</p>` : ""}${facts.length ? `<dl class="row-facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}<details class="row-path"><summary>Add-on path</summary><code>${esc(card.source)}</code></details></div></article>`;
}
function rowSummaryBar(cards) {
  const count = s => cards.filter(c => s.includes(c.state)).length;
  const parts = [["Fresh", count(["fresh"]), "ok"], ["Refresh soon", count(["stale"]), "info"], ["Failing", count(["failing", "persistent"]), "bad"], ["Empty or waiting", count(["empty", "waiting"]), "muted"]];
  const total = cards.length;
  return `<div class="stackbar" role="img" aria-label="${esc(parts.map(([l, n]) => `${l} ${n}`).join(", "))}">${parts.filter(p => p[1]).map(([label, n, tone]) => `<span class="stackbar-seg stackbar--${tone}" style="flex-grow:${n}" title="${esc(`${label}: ${n}`)}"></span>`).join("")}</div><ul class="stackbar-legend">${parts.map(([label, n, tone]) => `<li>${tonePill(tone, `${n} ${label.toLowerCase()}`)}</li>`).join("")}</ul><p class="sr-only">${esc(`${total} rows in total.`)}</p>`;
}
async function rowHealthView() {
  const [cache, saved, history] = await Promise.all([api("/api/widget-cache"), api("/api/widget-cache/rows").catch(() => []), api("/api/metrics/history?days=7").catch(() => null)]);
  const now = Math.floor(Date.now() / 1000);
  const cards = rowCards(cache, saved);
  resetCharts();
  const head = pageHead("Row health", "Each row on the TV’s home screen that Kodi Manager keeps a copy of: what’s on it, when it last refreshed and whether it’s failing.", `<button type="button" class="action" id="rowsRefresh">${dashboardIcon("refresh")}<span>Refresh all rows</span></button>`);
  if (!cards.length) {
    out(`${head}<div class="empty-state"><h3>No cached rows yet</h3><p>Your home-screen rows load straight from the add-ons. Kodi Manager can keep a copy of a row so it appears instantly and survives an add-on being slow.</p><a class="primary" href="#/cached-rows">Set up cached rows</a></div>`);
  } else {
    const trend = history?.count ? chartFigure({...rowsChartSpec(history), height:150}) : "";
    out(`${head}<section class="panel row-summary" aria-label="Summary">${rowSummaryBar(cards)}</section>${trend ? `<div class="chart-grid chart-grid--one">${trend}</div>` : ""}
      <div class="filterbar"><label class="search-field">${dashboardIcon("search")}<span class="sr-only">Find a row</span><input id="rowSearch" type="search" placeholder="Find a row" value="${esc(state.rowQuery || "")}"></label>
      <div class="segmented" role="group" aria-label="Show">${[["all", "All"], ["attention", "Needs a look"], ["failing", "Failing"], ["stale", "Refresh soon"], ["fresh", "Fresh"]].map(([v, l]) => `<button type="button" data-row-filter="${v}" aria-pressed="${(state.rowFilter || "all") === v}">${esc(l)}</button>`).join("")}</div>
      <label class="sort-field">Sort<select id="rowSort"><option value="attention">Needs a look first</option><option value="name">Name</option><option value="items">Most titles</option><option value="oldest">Least recently updated</option></select></label></div>
      <p id="rowCount" class="muted" role="status"></p><div id="rowCards" class="row-cards"></div>`);
    const draw = () => {
      const shown = sortRowCards(filterRowCards(cards, state.rowFilter || "all", state.rowQuery || ""), state.rowSort || "attention");
      $("#rowCards").innerHTML = shown.map(c => rowCardMarkup(c, now)).join("") || '<p class="empty-inline">No rows match. Try All, or clear the search.</p>';
      $("#rowCount").textContent = `Showing ${shown.length} of ${cards.length} rows`;
    };
    $("#rowSort").value = state.rowSort || "attention";
    $("#rowSort").onchange = () => { state.rowSort = $("#rowSort").value; draw(); };
    $("#rowSearch").oninput = () => { state.rowQuery = $("#rowSearch").value; draw(); };
    document.querySelectorAll("[data-row-filter]").forEach(b => b.onclick = () => {
      state.rowFilter = b.dataset.rowFilter;
      document.querySelectorAll("[data-row-filter]").forEach(o => o.setAttribute("aria-pressed", String(o === b)));
      draw();
    });
    draw();
    mountCharts(document);
  }
  $("#rowsRefresh").onclick = withErrors(async () => {
    const r = await api("/api/widget-cache/refresh", {});
    toast(`${r.queued ?? 0} row${r.queued === 1 ? "" : "s"} queued. They refresh one at a time while the TV is idle.`, "ok");
  });
}
