/* Dashboard views and routing. Shared helpers ($, esc, api, toast, dialogs, copyText) live in core.js. */
const badge = (v, y="yes", n="no") => `<span class="badge">${v === null || v === undefined ? "unknown" : (v ? y : n)}</span>`;
const card = (t,b) => `<div class="card"><h3>${esc(t)}</h3>${b}</div>`;
const state = {setup:{}, status:null, writeEnabled:false, dirtyAddon:"", dirtyChanges:{}, currentHash:"", navKey:""};

function consumeUrlToken(){
  const token = tokenFromHash(location.hash);
  if (!token) return false;
  storeToken(token);
  // Remove the token from the address bar and history straight away.
  history.replaceState(null, "", location.pathname + location.search + "#/dashboard");
  return true;
}
function writeAttrs(){ return state.writeEnabled ? "" : `disabled title="${esc(WRITE_HINT)}"`; }
function setWriteState(el){
  if (!el) return;
  el.disabled = !state.writeEnabled;
  el.title = state.writeEnabled ? "" : WRITE_HINT;
}
function out(html){ $("#content").innerHTML = html; }
function focusHeading(){
  const heading = document.querySelector("#content h2");
  if (!heading) return;
  heading.setAttribute("tabindex", "-1");
  heading.focus({preventScroll:true});
}
function homeLayoutSupported(status){ return status?.stack?.skin?.bingie_like === true; }
/* Pages grouped by household task (docs/ui.md). Items are [label, route] or [label, route, {sub:true}]
   for per-add-on pages, which the side menu indents and the section tabs leave out. */
function navGroups(status){
  const stack = status?.stack || {};
  const known = key => !status || !!stack[key]?.addon_id;
  const apps = [["Skin","#/skin","skin"],["TMDb Helper","#/tmdbhelper","tmdbhelper"],["Fen Light","#/fenlight","fenlight"],["Fen","#/fen","fen"],["POV","#/pov","pov"],["CocoScrapers","#/cocoscrapers","cocoscrapers"]]
    .filter(([, , key]) => known(key)).map(([label, route]) => [label, route, {sub:true}]);
  const trakt = !status || stack.trakt?.addon_id || stack.trakt_integration?.status === "configured";
  return [
    {key:"status", group:"Status", short:"Status", icon:"pulse", items:[["Overview","#/dashboard"],["Trends","#/trends"],["Health checks","#/health"]]},
    {key:"rows", group:"Home screen", short:"Rows", icon:"rows", items:[["Row health","#/rows"], ...(homeLayoutSupported(status) ? [["Home layout","#/widgets"]] : []), ["Cached rows","#/cached-rows"]]},
    {key:"addons", group:"Add-ons & settings", short:"Add-ons", icon:"box", items:[["Your add-ons","#/components"], ...apps, ["All add-ons","#/addons"], ["Playback setup","#/pipeline"], ["Playback test","#/playback-test"], ["Install add-on","#/install"]]},
    {key:"backups", group:"Backups & recovery", short:"Backups", icon:"history", items:[["Backups","#/backups"],["Custom fixes","#/fixes"]]},
    {key:"accounts", group:"Accounts", short:"Accounts", icon:"key", items:[["Accounts","#/accounts"], ...(trakt ? [["Trakt","#/trakt"]] : [])]},
    {key:"advanced", group:"Advanced", short:"Advanced", icon:"tools", items:[["Kodi log","#/kodi-logs"],["Service log","#/logs"],["Diagnostics","#/diagnostics"],["Connection","#/setup"]]}
  ];
}
const TABBAR = ["status", "rows", "addons", "backups"];
const ROUTE_ALIASES = {"#/widget-studio":"#/widgets", "#/overview":"#/dashboard", "#/":"#/dashboard", "":"#/dashboard"};
function currentRoute(){ const r = (location.hash || "#/dashboard").split("?")[0]; return ROUTE_ALIASES[r] || r; }
function routeGroup(route, groups){
  if (route.startsWith("#/addon/")) return groups.find(g => g.key === "addons") || null;
  return groups.find(g => g.items.some(item => item[1] === route)) || null;
}
function navLink(label, route, sub){ return `<a href="${esc(route)}" data-route="${esc(route)}"${sub ? ' class="nav-sub"' : ""}>${esc(label)}</a>`; }
function setNav(groups){
  state.navGroups = groups;
  const key = JSON.stringify(groups);
  if (key === state.navKey) return highlightNav();
  state.navKey = key;
  $("#nav").innerHTML = `<div class="nav-sheet-head"><span>All pages</span><button type="button" class="action" data-close-nav>Close</button></div>` + groups.map(group => `<div class="nav-section" data-group="${esc(group.key || "")}"><div class="nav-title">${dashboardIcon(group.icon || "help")}<span>${esc(group.group)}</span></div>${group.items.map(([label, route, opts]) => navLink(label, route, opts?.sub)).join("")}</div>`).join("");
  const tabbar = $("#tabbar");
  if (tabbar) tabbar.innerHTML = groups.filter(g => TABBAR.includes(g.key)).map(g => `<a href="${esc(g.items[0][1])}" data-tab-group="${esc(g.key)}">${dashboardIcon(g.icon)}<span>${esc(g.short || g.group)}</span></a>`).join("") + `<button type="button" id="tabMore" data-tab-group="more" aria-controls="nav" aria-expanded="false">${dashboardIcon("more")}<span>More</span></button>`;
  highlightNav();
}
function renderSubnav(group, route){
  const host = $("#subnav");
  if (!host) return;
  const items = group ? group.items.filter(item => !item[2]?.sub) : [];
  host.hidden = items.length < 2;
  host.innerHTML = items.length < 2 ? "" : `<ul>${items.map(([label, target]) => `<li><a href="${esc(target)}"${target === route || (route.startsWith("#/addon/") && target === "#/components") ? ' aria-current="page"' : ""}>${esc(label)}</a></li>`).join("")}</ul>`;
  // On a narrow screen keep the current tab in view.
  const list = host.querySelector?.("ul"), current = host.querySelector?.('[aria-current="page"]');
  if (list && current && list.scrollWidth > list.clientWidth) list.scrollLeft = Math.max(0, current.offsetLeft - (list.clientWidth - current.offsetWidth) / 2);
}
function highlightNav(){
  const current = currentRoute();
  document.querySelectorAll("#nav [data-route]").forEach(b => {
    const active = b.dataset.route === current;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  const group = routeGroup(current, state.navGroups || navGroups(state.status));
  const tabKey = group ? (TABBAR.includes(group.key) ? group.key : "more") : "";
  document.querySelectorAll("#tabbar [data-tab-group]").forEach(tab => {
    const on = tab.dataset.tabGroup === tabKey;
    tab.classList.toggle("active", on);
    if (on && tab.tagName === "A") tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
  });
  renderSubnav(group, current);
}
function toggleNav(open){
  const body = document.body;
  const next = typeof open === "boolean" ? open : !body.classList.contains("nav-open");
  body.classList.toggle("nav-open", next);
  $("#navToggle")?.setAttribute("aria-expanded", String(next));
  $("#tabMore")?.setAttribute("aria-expanded", String(next));
  if (next) document.querySelector("#nav a")?.focus?.();
}
/* The calm notice shown on every page when this Kodi profile is view-only (writes off). */
function viewOnlyBanner(status){
  if (status?.write_enabled !== false) return "";
  return `<div class="notice notice--view" role="note">${dashboardIcon("eye")}<div><p><b>View only.</b> Changes are off${state.profile ? ` for the ${esc(state.profile)} profile` : " for this Kodi profile"}, so anything that would change the TV is greyed out.</p><details><summary>How to allow changes</summary><p>On the TV, open <b>Add-ons → My add-ons → Services → Kodi Manager → Configure</b> and turn on <b>Enable writes</b>. It applies straight away.</p></details></div></div>`;
}
function applyStatus(status){
  state.status = status;
  state.writeEnabled = appCanWrite(status);
  setNav(navGroups(status));
  updateDirtyBar();
  $("#top").innerHTML = `<span class="conn-chip" title="Connected to Kodi Manager ${esc(status.service_version || "")}"><span class="conn-dot" aria-hidden="true"></span><span>Kodi ${esc(status["Kodi version"] || "")}</span></span>${status.write_enabled === false ? dashboardPill("muted", "View only", "eye") : ""}`;
  const banner = $("#banner");
  if (banner) banner.innerHTML = viewOnlyBanner(status);
}
function pageHead(title, lead, actions=""){
  return `<header class="page-head"><div><h2>${esc(title)}</h2>${lead ? `<p class="lead">${esc(lead)}</p>` : ""}</div>${actions ? `<div class="page-actions">${actions}</div>` : ""}</header>`;
}
function pageSkeleton(){
  return `<div class="page-skeleton" role="status" aria-label="Loading"><span class="skeleton-line title"></span><span class="skeleton-line"></span><div class="skeleton-block"></div><div class="skeleton-block"></div></div>`;
}
/* Arrow-key focus movement for TV remotes: pick the nearest control in that direction. */
function spatialPick(from, candidates, dir){
  const cx = r => (r.left + r.right) / 2, cy = r => (r.top + r.bottom) / 2;
  let best = null, bestScore = Infinity;
  for (const candidate of candidates) {
    const r = candidate.rect, dx = cx(r) - cx(from), dy = cy(r) - cy(from);
    let along, across;
    if (dir === "right") { if (r.left < from.right - 4 && dx <= 4) continue; along = dx; across = dy; }
    else if (dir === "left") { if (r.right > from.left + 4 && dx >= -4) continue; along = -dx; across = dy; }
    else if (dir === "down") { if (r.top < from.bottom - 4 && dy <= 4) continue; along = dy; across = dx; }
    else { if (r.bottom > from.top + 4 && dy >= -4) continue; along = -dy; across = dx; }
    if (along <= 0) continue;
    const score = along + 2.5 * Math.abs(across);
    if (score < bestScore) { bestScore = score; best = candidate; }
  }
  return best;
}
const SPATIAL_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
function spatialKey(event){
  const dir = {ArrowRight:"right", ArrowLeft:"left", ArrowDown:"down", ArrowUp:"up"}[event.key];
  if (!dir || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const active = document.activeElement;
  if (!active || active === document.body || active.closest?.("[data-chart-plot]")) return;
  const tag = active.tagName;
  if (tag === "SELECT" || tag === "TEXTAREA" || active.isContentEditable) return;
  if (tag === "INPUT" && (dir === "left" || dir === "right" || ["number", "range"].includes(active.type))) return;
  const scope = document.querySelector("dialog[open]") || document;
  const candidates = [...scope.querySelectorAll(SPATIAL_FOCUSABLE)].filter(el => el !== active && el.getClientRects().length && !el.closest("[hidden], .hidden")).map(el => ({el, rect:el.getBoundingClientRect()})).filter(c => c.rect.width && c.rect.height);
  const target = spatialPick(active.getBoundingClientRect(), candidates, dir);
  if (!target) return;
  event.preventDefault();
  target.el.focus({preventScroll:true});
  target.el.scrollIntoView?.({block:"nearest", inline:"nearest"});
}
function themeLabel(theme){ return {auto:"Theme: automatic", light:"Theme: light", dark:"Theme: dark"}[theme] || "Theme"; }
function renderThemeToggle(){
  const button = $("#themeToggle");
  if (!button) return;
  const theme = storedTheme();
  button.innerHTML = `${dashboardIcon(theme === "light" ? "sun" : theme === "dark" ? "moon" : "auto")}<span class="sr-only">${esc(themeLabel(theme))}</span>`;
  button.title = `${themeLabel(theme)}. Choose to switch.`;
}
async function loadStatus(){
  const status = await api("/api/status");
  applyStatus(status);
  return status;
}
function setDirty(addonId, settingId, value, source="settings.xml"){
  state.dirtyAddon = addonId;
  const el = [...document.querySelectorAll("[data-setting]")].find(x => x.dataset.setting === settingId);
  const original = el ? (el.dataset.original ?? "") : undefined;
  if (original !== undefined && String(value) === String(original)) delete state.dirtyChanges[settingId];
  else state.dirtyChanges[settingId] = {value, source};
  if (!Object.keys(state.dirtyChanges).length) state.dirtyAddon = "";
  updateDirtyBar();
}
function clearDirty(){
  state.dirtyAddon = "";
  state.dirtyChanges = {};
  updateDirtyBar();
}
function hasUnsavedChanges(){ return Object.keys(state.dirtyChanges || {}).length > 0; }
function updateDirtyBar(){
  const count = Object.keys(state.dirtyChanges).length;
  const label = $("#dirtyStatus"), btn = $("#saveChanges");
  if (!label || !btn) return;
  label.textContent = count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "No unsaved changes";
  btn.disabled = !count || !state.writeEnabled;
  btn.title = state.writeEnabled ? "" : WRITE_HINT;
  if (typeof document !== "undefined") document.body?.classList?.toggle("has-unsaved", count > 0);
}
/* Called before leaving a route. The hash has already changed, so restore it while asking. */
async function confirmLeave(target){
  if (!hasUnsavedChanges()) return true;
  history.replaceState(null, "", state.currentHash || "#/dashboard");
  const n = Object.keys(state.dirtyChanges).length;
  const ok = await confirmDialog({title:"Discard unsaved changes?", message:`You have ${n} unsaved setting change${n === 1 ? "" : "s"}. Leave this page and discard ${n === 1 ? "it" : "them"}?`, confirmLabel:"Discard changes", cancelLabel:"Keep editing", danger:true});
  if (!ok) return false;
  clearDirty();
  history.replaceState(null, "", target);
  return true;
}
async function onHashChange(){
  if (location.hash === state.currentHash) return;
  if (consumeUrlToken()) { await loadStatus().catch(reportError); return route(); }
  // In-page anchors (#section) are not routes: keep the current page.
  if (location.hash && !location.hash.startsWith("#/")) { history.replaceState(null, "", state.currentHash || "#/dashboard"); return; }
  if (!(await confirmLeave(location.hash))) return;
  await route();
}
function appSecretSetting(s){
  return s.secret === true || s.masked === true || String(s.type).toLowerCase() === "password" || /token|password|passwd|secret|oauth|authorization|api|key|client|(?:^|[._])refresh$/i.test(s.id || "");
}
function changePreview(id, original, value, secret=false){
  const display = v => secret ? (isUnset(v) ? "not set" : "••••••••") : String(v ?? "");
  return `${friendlyName(id, id)}\n  ${display(original)} -> ${display(value)}`;
}
const QUICK_UNDO_MS = 10000;
/* A refused batch names the setting to fix in details.setting_id; point at that field. */
function markInvalidSetting(id){
  document.querySelectorAll(".setting-invalid").forEach(el => { el.classList.remove("setting-invalid"); el.removeAttribute("aria-invalid"); });
  if (typeof id !== "string" || !id) return null;
  const el = [...document.querySelectorAll("[data-setting]")].find(x => x.dataset.setting === id);
  if (!el) return null;
  el.classList.add("setting-invalid");
  el.setAttribute("aria-invalid", "true");
  el.scrollIntoView?.({block:"center"});
  el.focus?.();
  return el;
}
async function saveDirty(){
  const changes = Object.entries(state.dirtyChanges).map(([id,item]) => ({id,value:item.value,source:item.source}));
  const addonId = state.dirtyAddon;
  if (!addonId || !changes.length || !state.writeEnabled) return;
  const preview = changes.map(ch => {
    const el = [...document.querySelectorAll("[data-setting]")].find(x => x.dataset.setting === ch.id);
    return changePreview(ch.id, el?.dataset.original ?? "", ch.value, el?.type === "password" || appSecretSetting({id:ch.id}));
  }).join("\n\n");
  if (!(await confirmDialog({title:`Save ${changes.length} change${changes.length === 1 ? "" : "s"}?`, message:"A backup of this add-on’s settings is created first.", detail:preview, confirmLabel:"Save"}))) return;
  let r;
  try { r = await apiMethod("PATCH", `/api/addons/${encodeURIComponent(addonId)}/settings`, {changes}); }
  catch (error) { markInvalidSetting(error?.details?.setting_id); throw error; }
  clearDirty();
  const savedAt = Date.now();
  // The backup is the whole add-on folder as it was before this save; a later tap asks first.
  toast(`Saved ${r.changed_count} change${r.changed_count === 1 ? "" : "s"}. Backup ${r.backup_id}.`, "ok", r.backup_id ? {actions:[{label:"Restore settings from before this save", run:() => restoreAddonBackup(addonId, r.backup_id, {confirmFirst:Date.now() - savedAt > QUICK_UNDO_MS})}]} : {});
  await route();
}
function isUnset(v){
  if (v === undefined || v === null) return true;
  const s = String(v).trim();
  return s === "" || ["none","null","undefined","empty_setting","not set","n/a"].includes(s.toLowerCase());
}
function settingIsSet(s){
  if (Object.prototype.hasOwnProperty.call(s, "configured")) return !!s.configured;
  return !isUnset(s.value);
}
function isReadOnlySetting(s){ return !s.editable; }
function settingFilterCounts(settings){
  const list = settings || [];
  return {
    all: list.length,
    set: list.filter(settingIsSet).length,
    unset: list.filter(s=>!settingIsSet(s)).length,
    readonly: list.filter(isReadOnlySetting).length
  };
}
function filterTabs(scope, settings){
  const c = settingFilterCounts(settings);
  const tab = (filter, label, count) => `<button type="button" data-filter="${filter}" aria-pressed="${filter === "set"}"${filter === "set" ? ' class="active"' : ""}>${label} ${count}</button>`;
  return `<div class="tabs" role="group" aria-label="Filter settings" data-scope="${esc(scope)}">${tab("all","All",c.all)}${tab("set","Set",c.set)}${tab("unset","Unset",c.unset)}${tab("readonly","Read-only",c.readonly)}</div>`;
}
function passesSettingFilter(s, filter){
  if (filter === "set") return settingIsSet(s);
  if (filter === "unset") return !settingIsSet(s);
  if (filter === "readonly") return isReadOnlySetting(s);
  return true;
}
function wireFilterTabs(){
  document.querySelectorAll(".tabs[data-scope]").forEach(tabs=>{
    const apply = btn => {
      tabs.querySelectorAll("button").forEach(b=>{ b.classList.remove("active"); b.setAttribute("aria-pressed","false"); });
      btn.classList.add("active");
      btn.setAttribute("aria-pressed","true");
      const scope = tabs.dataset.scope, filter = btn.dataset.filter;
      document.querySelectorAll(`[data-filter-scope="${scope}"]`).forEach(el=>{
        const set = el.dataset.set === "true", ro = el.dataset.readonly === "true";
        const show = filter === "all" || (filter === "set" && set) || (filter === "unset" && !set) || (filter === "readonly" && ro);
        el.classList.toggle("hidden", !show);
      });
    };
    tabs.querySelectorAll("button").forEach(btn=>btn.onclick=()=>apply(btn));
    apply(tabs.querySelector('[data-filter="set"]') || tabs.querySelector("button"));
  });
}
function settingPriority(s){
  const warning = String(s.warning || "");
  if (s.editable && !s.masked && !isUnset(s.value)) return 0;
  if (s.editable && !s.masked) return 1;
  if (!warning.includes("Schema missing") && !warning.includes("settings.db") && !isUnset(s.value)) return 2;
  if (!isUnset(s.value)) return 3;
  return 4;
}
function sortSettings(settings){ return [...(settings || [])].sort((a,b) => settingPriority(a) - settingPriority(b) || String(a.id || a.label).localeCompare(String(b.id || b.label))); }
function friendlyName(id, label){
  if (label && label !== id && !/^Label\s+\d+$/i.test(label)) return label;
  const aliases = {"default_addon_fanart":"Addon Fanart","auto_start_fenlight":"Auto-start Fen Light","limit_concurrent_threads":"Limit Threads","max_threads":"Max Threads","trakt.refresh_widgets":"Refresh Widgets After Trakt","store_resolved_to_cloud.torbox":"Save Resolved Links to TorBox","store_resolved_to_cloud.torbox_name":"TorBox Cloud Save Label"};
  if (aliases[id]) return aliases[id];
  return String(id || label || "").replace(/[._-]+/g," ").replace(/\b\w/g,c=>c.toUpperCase());
}
function describeSetting(id, label){
  const sid = String(id || "").toLowerCase();
  const providerMap = [["rd.","Real-Debrid"],["ad.","AllDebrid"],["pm.","Premiumize"],["tb.","TorBox"],["ed.","EasyDebrid"],["oc.","OffCloud"]];
  for (const [prefix, name] of providerMap) {
    if (sid.startsWith(prefix)) {
      if (sid.endsWith(".enabled")) return `Turn ${name} account integration on or off.`;
      if (sid.endsWith(".priority")) return `Order used when choosing ${name} results. Lower number usually means higher priority.`;
      if (sid.endsWith(".token")) return `${name} access token used by this add-on.`;
      if (sid.endsWith(".refresh")) return `${name} refresh token used to renew access.`;
      if (sid.endsWith(".secret")) return `${name} client secret used for authorization.`;
      if (sid.endsWith(".client_id")) return `${name} client ID used for authorization.`;
      if (sid.endsWith(".account_id")) return `${name} account name or account ID currently linked.`;
      if (sid.endsWith(".alt_api")) return `Alternative ${name} API key/token.`;
    }
  }
  const rules = [
    ["tmdb", "TMDb API/account setting used for metadata and lists."],
    ["trakt", "Trakt account or playback-history integration setting."],
    ["easynews_user", "EasyNews username."],
    ["easynews_password", "EasyNews password."],
    ["omdb", "OMDb API key used for ratings/metadata."],
    ["fanart", "Fanart.tv API key used for artwork."],
    ["tvdb", "TVDb token used for TV metadata."],
    ["mdblist", "MDBList API key used for list metadata."],
    ["prowlarr", "Prowlarr token used by scraper integration."],
    ["furk", "Furk account/API credential."],
    ["default_addon_fanart", "Artwork shown when no specific background exists."],
    ["autoplay", "Automatic playback behavior."],
    ["external", "Connects this add-on to an external helper/module."],
    ["scraper", "Controls scraper/provider integration."],
    ["provider", "Controls provider behavior or appearance."],
    ["timeout", "How long to wait before giving up."],
    ["thread", "Concurrency/performance setting."],
    ["quality", "Playback/source quality preference."],
    ["cache", "Cache behavior."],
    ["resume", "Resume playback behavior."]
  ];
  for (const [key, desc] of rules) if (sid.includes(key)) return desc;
  return "Kodi add-on setting. Change only if you know this behavior.";
}

function showTokenForm(message=""){
  clearInterval(state.dashboardTimer);
  state.currentHash = location.hash;
  out(`<div class="panel token-panel"><h2>Connect to Kodi Manager</h2>${message ? `<p class="warn" role="alert">${esc(message)}</p>` : ""}<p>Enter the access token for this Kodi. On the TV, open <b>Add-ons → Video add-ons → Kodi Manager → Open the dashboard on another device</b> to see the address and token.</p><form id="tokenForm" class="token-form"><label for="tokenInput">Access token<input id="tokenInput" type="password" autocomplete="off" spellcheck="false" required></label><button class="primary" type="submit">Connect</button></form></div>`);
  $("#tokenForm").onsubmit = withErrors(async event => {
    event.preventDefault();
    const token = $("#tokenInput").value.trim();
    if (!token) return;
    storeToken(token);
    await loadStatus();
    await route();
  });
  focusHeading();
  $("#tokenInput")?.focus();
}

async function boot(){
  consumeUrlToken();
  session.token = session.token || storedToken();
  session.onUnauthorized = () => showTokenForm("That access token was not accepted. Enter the current token to continue.");
  $("#saveChanges").onclick = withErrors(saveDirty);
  $("#runSearch").onclick = runGlobalSearch;
  $("#globalSearch").addEventListener("keydown", e => { if (e.key === "Enter") runGlobalSearch(); });
  $("#navToggle")?.addEventListener("click", () => toggleNav());
  $("#nav").addEventListener("click", event => {
    if (event.target.closest("[data-close-nav]")) return toggleNav(false);
    if (event.target.closest("a[data-route]")) toggleNav(false);
  });
  $("#tabbar")?.addEventListener("click", event => {
    if (event.target.closest("#tabMore")) return toggleNav();
    if (event.target.closest("a")) toggleNav(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) { toggleNav(false); $("#tabMore")?.focus(); return; }
    spatialKey(event);
  });
  renderThemeToggle();
  $("#themeToggle")?.addEventListener("click", () => { saveTheme(nextTheme(storedTheme())); renderThemeToggle(); });
  window.addEventListener("hashchange", () => onHashChange().catch(reportError));
  window.addEventListener("beforeunload", event => { if (hasUnsavedChanges()) { event.preventDefault(); event.returnValue = ""; } });
  setNav(navGroups(null));
  if (!location.hash) history.replaceState(null, "", location.pathname + location.search + "#/dashboard");
  if (!session.token) return showTokenForm();
  try { await loadStatus(); } catch (error) { if (error.code === "unauthorized") return; }
  await route();
}

function redactObj(obj, inheritedSecret=false){
  if (Array.isArray(obj)) return obj.map(value=>redactObj(value, inheritedSecret));
  if (!obj || typeof obj !== "object") return obj;
  const secret = inheritedSecret || appSecretSetting({...obj, id:obj.id || obj.setting_id || ""});
  return Object.fromEntries(Object.entries(obj).map(([key,value]) => [key,
    ((secret && /^(value|default|original)$/.test(key)) || /token|password|secret|authorization|api_key/i.test(key)) && value ? "••••••••" : redactObj(value, secret)]));
}
const ROUTES = {
  dashboard: () => overviewView(),
  overview: () => overviewView(),
  trends: () => trendsView(),
  rows: () => rowHealthView(),
  components: () => componentsView(),
  health: () => healthView(),
  fixes: () => fixesView(),
  pipeline: () => pipelineView(),
  widgets: () => widgetStudioView(),
  "widget-studio": () => widgetStudioView(),
  "playback-test": () => playbackTestView(),
  accounts: () => accountsView(),
  addons: () => allAddons(),
  install: () => installAddonView(),
  skin: () => pickAddon(["skin"]),
  tmdbhelper: () => pickAddon(["tmdbhelper"]),
  fenlight: () => pickAddon(["fenlight"]),
  fen: () => pickAddon(["fen"]),
  pov: () => pickAddon(["pov"]),
  cocoscrapers: () => pickAddon(["cocoscrapers"]),
  trakt: () => integrations(),
  backups: () => backups(),
  "cached-rows": () => cachedRowsView(),
  logs: () => logs(),
  "kodi-logs": () => kodiLogs(),
  setup: () => serviceSetup(),
  diagnostics: () => diagnostics()
};
async function route(){
  clearInterval(state.dashboardTimer);
  clearInterval(state.overviewTimer);
  state.overviewRequest = (state.overviewRequest || 0) + 1;
  state.logHistoryRequest = (state.logHistoryRequest || 0) + 1;
  state.dashboardController?.abort();
  state.dashboardRequest = (state.dashboardRequest || 0) + 1;
  state.dashboardLoading = false;
  state.currentHash = location.hash;
  if (typeof resetCharts === "function") resetCharts();
  try {
    highlightNav();
    out(pageSkeleton());
    const r = location.hash.replace(/^#\/?/, "") || "dashboard";
    if (r.startsWith("search")) await searchView(new URLSearchParams(r.split("?")[1] || "").get("q") || "");
    else if (r.split('?')[0] === 'kodi-logs') {
      const params = new URLSearchParams(r.split('?')[1] || '');
      await kodiLogs(params.get('level') || 'all', params.get('issue') || '');
    }
    else if (r.startsWith("addon/")) await addonSettings(decodeURIComponent(r.slice(6)));
    else await (ROUTES[r] || ROUTES.dashboard)();
    focusHeading();
  } catch(e) {
    if (e?.code === "unauthorized") return;
    const f = friendlyError(e);
    out(`<div class="panel error-panel" role="alert"><h2>Couldn’t load this page</h2><p>${esc(f.title)}</p>${f.hint ? `<p class="muted">${esc(f.hint)}</p>` : ""}${f.detail && f.detail !== f.title && f.detail !== f.hint ? `<details><summary>Details</summary><p>${esc(f.detail)}</p></details>` : ""}<button type="button" class="action" id="routeRetry">${dashboardIcon("refresh")}<span>Try again</span></button></div>`);
    const retry = $("#routeRetry");
    if (retry) retry.onclick = () => route();
    focusHeading();
  }
}
function dashboardIcon(name){
  const paths = {
    check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
    minus: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 .5c0 1.5-2.5 1.5-2.5 3M12 16h.01"/>',
    pause: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6m4-6v6"/>',
    alert: '<path d="m12 3 10 18H2L12 3Z M12 9v5m0 3h.01"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
    skin: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M9 9v11"/>',
    film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4m-4 8h4m10-8h4m-4 8h4"/>',
    layers: '<path d="m12 3 10 5-10 5L2 8l10-5Z M2 12l10 5 10-5M2 16l10 5 10-5"/>',
    history: '<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6m3-3v5l3 2"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M18 18A8 8 0 0 1 5 15"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    settings: '<path d="M4 7h16M4 17h16M8 4v6m8 4v6"/>',
    pulse: '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
    rows: '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/>',
    box: '<path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5v-7Z M4 8.5l8 4.5 8-4.5M12 13v7"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8m-3 3 2 2m-4 0 1.5 1.5"/>',
    tools: '<path d="M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.5 2.5-2.5-.5-.5-2.5 2.5-2.5Z"/>',
    more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.8"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2m0 15v2M2.5 12h2m15 0h2M5.3 5.3l1.4 1.4m10.6 10.6 1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/>',
    auto: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17Z" fill="currentColor"/>',
    tv: '<rect x="2.5" y="4.5" width="19" height="13" rx="2.5"/><path d="M8 21h8M12 17.5V21"/>',
    memory: '<rect x="4" y="6" width="16" height="12" rx="1.5"/><path d="M8 10v4m4-4v4m4-4v4M7 6V3.5M12 6V3.5M17 6V3.5M7 18v2.5m5-2.5v2.5m5-2.5v2.5"/>',
    wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.7 16a5 5 0 0 1 6.6 0"/><circle cx="12" cy="19.3" r="1" fill="currentColor"/>',
    shield: '<path d="M12 3 4.5 6v5.5c0 4.5 3.2 8 7.5 9.5 4.3-1.5 7.5-5 7.5-9.5V6L12 3Z"/><path d="m9 12 2.2 2.2L15.5 10"/>'
  };
  return `<svg class="dash-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.help}</svg>`;
}
function dashboardPill(tone, label, icon, title=label){
  return `<span class="dash-status dash-status--${esc(tone)}" title="${esc(title)}">${dashboardIcon(icon)}<span>${esc(label)}</span></span>`;
}
function dashboardFlag(value, yes, no, noTone="muted"){
  if (value === true) return dashboardPill("ok", yes, "check");
  if (value === false) return dashboardPill(noTone, no, noTone === "warn" ? "pause" : "minus");
  return dashboardPill("muted", "Unknown", "help", "Kodi has not confirmed this state.");
}
function dashboardStatus(addon){
  if (addon.active === true && addon.addon_id) return {tone:"ok", label:"Active", icon:"play", kind:"installed"};
  if (addon.installed === true) {
    if (addon.enabled === false) return {tone:"warn", label:"Disabled", icon:"pause", kind:"installed"};
    if (addon.enabled === true) return {tone:"ok", label:"Enabled", icon:"check", kind:"installed"};
    return {tone:"info", label:"Detected", icon:"check", kind:"installed"};
  }
  if (addon.config_present === true) return {tone:"warn", label:"Config only", icon:"alert", kind:"config"};
  if (addon.installed === false) return {tone:"muted", label:"Not found", icon:"minus", kind:"missing"};
  return {tone:"muted", label:"Unknown", icon:"help", kind:"unknown"};
}
function dashboardComponents(status, addons){
  const stack = status.stack || {};
  const definitions = [
    ["skin", "Skin", "Your Kodi interface", "skin", status.active_skin?.addon_id],
    ["tmdbhelper", "TMDb Helper", "Metadata & widgets", "film", "plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper"],
    ["fenlight", "Fen Light", "Playback provider", "play", "plugin.video.fenlight"],
    ["fen", "Fen", "Playback provider", "play", "plugin.video.fen"],
    ["pov", "POV", "Playback provider", "play", "plugin.video.pov"],
    ["cocoscrapers", "CocoScrapers", "Available scraper module; usage depends on player routing", "layers", "script.module.cocoscrapers"],
    ["trakt", "Trakt", "Account integration · optional standalone scrobbler", "history", "script.trakt"]
  ];
  return definitions.map(([key, label, detail, icon, ...ids]) => {
    const summary = stack[key];
    const record = (summary?.addon_id && addons.find(a => a.addon_id === summary.addon_id)) || addons.find(a => ids.filter(Boolean).includes(a.addon_id));
    const fallback = key === "skin" && status.active_skin?.addon_id ? {...status.active_skin, installed:true, enabled:true, config_present:null} : {installed:false, config_present:false};
    const addon = {...(summary || fallback), ...record};
    if (key === "skin") {
      addon.active = !!status.active_skin?.addon_id && status.active_skin.addon_id === addon.addon_id;
      if (addon.active) Object.assign(addon, {installed:true, enabled:true});
    }
    const integration = key === "trakt" ? (stack.trakt_integration || {}) : undefined;
    const componentStatus = integration ? {tone:integration.status === "configured" ? "info" : "muted", label:integration.status === "configured" ? "Credentials present" : "Account unknown", icon:integration.status === "configured" ? "check" : "help", kind:integration.status === "configured" ? "config" : "unknown"} : dashboardStatus(addon);
    return {key, label, detail, icon, addon, integration, status:componentStatus};
  });
}
function dashboardRow(row){
  const a = row.addon;
  const source = (a.detected_from || a.sources || []).join(", ");
  const canOpen = a.addon_id && (a.installed === true || a.config_present === true || a.active === true);
  if (row.key === "trakt") {
    const integration = row.integration || {};
    const providers = (integration.providers || []).filter(p=>p.status === "configured").map(p=>p.name || p.addon_id).join(", ");
    const credentialStatus = integration.status === "configured" ? "Credentials present" : "Account unknown";
    return `<tr data-component="trakt" data-state="${esc(row.status.kind)}" data-search="${esc(`trakt ${providers}`.toLowerCase())}"><th scope="row"><div class="dash-identity"><span class="dash-avatar dash-avatar--trakt">${dashboardIcon("history")}</span><span><span class="dash-name">Trakt integration</span><span class="dash-detail">${esc(providers || "Stored account settings")} · unverified</span></span></div></th><td data-label="Version">—</td><td data-label="Status">${dashboardPill("info", credentialStatus, "history", "Local credentials only; account access has not been verified")}</td><td data-label="Installation">${a.installed === true ? dashboardPill("muted", "Optional scrobbler installed", "check") : dashboardPill("muted", "Optional scrobbler absent", "minus")}</td><td data-label="Enabled">${a.installed === true ? dashboardFlag(a.enabled,"On","Off","warn") : "—"}</td><td data-label="Saved config">${esc(integration.refs_found ?? "—")} auth fields</td><td class="dash-action-cell"><a class="dash-settings" href="#/trakt" aria-label="Open Trakt integration">${dashboardIcon("settings")}<span>Integration</span></a></td></tr>`;
  }
  return `<tr data-component="${esc(row.key)}" data-state="${esc(row.status.kind)}" data-search="${esc(`${row.label} ${a.name || ""} ${a.addon_id || ""}`.toLowerCase())}">
    <th scope="row"><div class="dash-identity"><span class="dash-avatar dash-avatar--${esc(row.key)}">${dashboardIcon(row.icon)}</span><span><span class="dash-name" title="${esc(a.addon_id || row.label)}">${esc(row.label)}</span><span class="dash-detail">${esc(row.key === "skin" && a.name ? a.name : row.detail)}</span></span></div></th>
    <td data-label="Version"><span class="dash-version">${esc(a.version || "—")}</span></td>
    <td data-label="Status">${dashboardPill(row.status.tone, row.status.label, row.status.icon, source ? `Detected from ${source}` : row.status.label)}</td>
    <td data-label="Installation">${dashboardFlag(a.installed, "Installed", "Not found")}</td>
    <td data-label="Enabled">${dashboardFlag(a.enabled, "On", "Off", "warn")}</td>
    <td data-label="Saved config">${dashboardFlag(a.config_present, "Found", "Not found")}</td>
    <td class="dash-action-cell">${canOpen ? `<a class="dash-settings" href="#/addon/${esc(encodeURIComponent(a.addon_id))}" aria-label="Open ${esc(row.label)} settings">${dashboardIcon("settings")}<span>Settings</span></a>` : '<span class="dash-no-action" title="No detected add-on to configure">—</span>'}</td>
  </tr>`;
}
function filterDashboard(){
  const query = ($("#dashboardFilter").value || "").trim().toLowerCase();
  const kind = $("#dashboardState").value;
  state.dashboardFilter = $("#dashboardFilter").value;
  state.dashboardState = kind;
  const rows = [...document.querySelectorAll("#dashboardRows tr[data-component]")];
  let visible = 0;
  rows.forEach(row => {
    row.hidden = !row.dataset.search.includes(query) || (kind !== "all" && row.dataset.state !== kind);
    if (!row.hidden) visible++;
  });
  $("#dashboardEmpty").hidden = visible > 0;
  $("#dashboardMatches").textContent = `${visible} of ${rows.length} components`;
}
function dashboardVisible(){ return location.hash === "#/components"; }
function dashboardFixNotice(fixes){
  if (!fixes || typeof fixes.healthy !== 'boolean') return '';
  const label = fixes.healthy ? 'Custom fixes intact' : 'Custom fixes need attention';
  return `<div class="dash-table-panel dash-fix-notice">${dashboardPill(fixes.healthy?'ok':'warn',label,fixes.healthy?'check':'alert')} <a class="dash-settings" href="#/fixes">Check custom fixes</a></div>`;
}
async function componentsView(refresh=false){
  if (refresh && (state.dashboardLoading || !dashboardVisible())) return;
  const request = state.dashboardRequest = (state.dashboardRequest || 0) + 1;
  state.dashboardLoading = true;
  clearInterval(state.dashboardTimer);
  state.dashboardController?.abort();
  const controller = state.dashboardController = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  if (refresh) {
    $("#dashboardRefresh").disabled = true;
    $("#dashboardRefreshNote").textContent = "Checking Kodi…";
  } else out(`<div class="dashboard">${pageHead("Your add-ons", "The skin, players and helpers Kodi Manager found, and whether each one is installed and turned on.")}${pageSkeleton()}</div>`);
  try {
    const s = await api("/api/status", undefined, controller.signal);
    const [addons, backups, fixes] = await Promise.all([
      api("/api/addons", undefined, controller.signal),
      api("/api/stack/backups", undefined, controller.signal).catch(()=>null),
      api("/api/fixes", undefined, controller.signal).catch(()=>null)
    ]);
    if (request !== state.dashboardRequest) return;
    const focused = document.activeElement;
    const focusId = focused?.id;
    const selection = focused?.selectionStart;
    const scrollLeft = document.querySelector(".dash-table-scroll")?.scrollLeft || 0;
    const noticesOpen = !!document.querySelector(".dash-notices")?.open;
    applyStatus(s);
    const rows = dashboardComponents(s, addons);
    const installed = addons.filter(a => a.installed === true);
    const detected = rows.filter(r => r.addon.installed === true || r.addon.config_present === true || r.integration?.status === "configured").length;
    const warnings = s.stack?.warnings || [];
    const checkedAt = new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
    const writeLabel = s.write_enabled === true ? "Writes on" : s.write_enabled === false ? "Read only" : "Unknown";
    out(`<div class="dashboard">
      ${pageHead("Your add-ons", "The skin, players and helpers Kodi Manager found, and whether each one is installed and turned on.", `<button class="action" id="dashboardRefresh">${dashboardIcon("refresh")}<span>Check again</span></button>`)}
      <div class="dash-metrics" aria-label="Setup summary">
        <div><span class="dash-metric-label">Installed add-ons</span><strong>${installed.length}</strong><span class="dash-metric-detail">${installed.filter(a=>a.enabled === true).length} confirmed enabled</span></div>
        <div><span class="dash-metric-label">Core components</span><strong>${detected}<small> detected</small></strong><span class="dash-metric-detail">Skin, players & integrations</span></div>
        <div><span class="dash-metric-label">Checkpoints</span><strong>${backups ? (backups.backups || []).length : "—"}</strong><span class="dash-metric-detail">${backups ? "Saved config backups" : "Backup status unavailable"}</span></div>
        <div><span class="dash-metric-label">Changes</span><strong class="dash-metric-mode">${dashboardIcon(s.write_enabled === true ? "settings" : s.write_enabled === false ? "eye" : "help")}${writeLabel}</strong><span class="dash-metric-detail">${s.write_enabled === true ? "A backup is made before every change" : s.write_enabled === false ? "Turn on “Enable writes” to edit" : "Write permission unconfirmed"}</span></div>
      </div>
      ${warnings.length ? `<details class="dash-notices" ${noticesOpen ? "open" : ""}><summary>${dashboardIcon("alert")}<span>${warnings.length} setup notice${warnings.length === 1 ? "" : "s"}</span><span class="dash-notice-hint">View details</span></summary><ul>${warnings.map(w=>`<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
      ${dashboardFixNotice(fixes)}
      <div class="dash-table-panel"><div class="dash-table-heading"><div><h3>Core components</h3><span id="dashboardMatches" class="dash-detail" aria-live="polite"></span></div><div class="dash-filters"><label class="dash-search">${dashboardIcon("search")}<span class="sr-only">Filter components</span><input id="dashboardFilter" type="search" placeholder="Filter components…" value="${esc(state.dashboardFilter || "")}"></label><label><span class="sr-only">Filter by state</span><select id="dashboardState"><option value="all">All states</option><option value="installed">Installed</option><option value="config">Config only</option><option value="missing">Not found</option><option value="unknown">Unknown</option></select></label></div></div>
      <div class="dash-table-scroll" tabindex="0" role="region" aria-label="Core component statuses"><table class="dash-table"><caption class="sr-only">Installation, enabled and saved configuration states from the most recent Kodi check.</caption><thead><tr><th scope="col">Component</th><th scope="col">Version</th><th scope="col">Status</th><th scope="col">Installation</th><th scope="col">Enabled</th><th scope="col">Saved config</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody id="dashboardRows">${rows.map(dashboardRow).join("")}<tr id="dashboardEmpty" hidden><td colspan="7" class="dash-empty">No components match your filters.</td></tr></tbody></table></div>
      <div class="dash-table-footer"><span id="dashboardRefreshNote" role="status">Checked ${esc(checkedAt)}. Refreshes every 30 seconds.</span><a href="#/addons">View all add-ons ${dashboardIcon("arrow")}</a></div></div>
      <p class="dash-legend">${dashboardIcon("help")}<span><b>Unknown</b> means Kodi hasn’t confirmed that state. <b>Config only</b> means saved settings were found, but installation isn’t confirmed. Player rows show whether the add-on is enabled.</span></p>
    </div>`);
    $("#dashboardState").value = state.dashboardState || "all";
    filterDashboard();
    $("#dashboardFilter").oninput = filterDashboard;
    $("#dashboardState").onchange = filterDashboard;
    $("#dashboardRefresh").onclick = () => componentsView(true);
    document.querySelector(".dash-table-scroll").scrollLeft = scrollLeft;
    if (refresh && focusId) {
      const target = document.getElementById(focusId);
      target?.focus({preventScroll:true});
      if (typeof selection === "number" && target?.setSelectionRange) target.setSelectionRange(selection, selection);
    }
  } catch(e) {
    if (request !== state.dashboardRequest || e?.code === "unauthorized") return;
    const message = e.name === "AbortError" ? "Kodi did not respond in time" : e.message;
    if (refresh && $("#dashboardRefreshNote")) {
      $("#dashboardRefreshNote").textContent = `Refresh failed: ${message}. Showing previous check.`;
      $("#dashboardRefreshNote").classList.add("warn");
    } else out(`<div class="panel error-panel" role="alert"><h2>Couldn’t check Kodi</h2><p>${esc(e.name === "AbortError" ? message : friendlyMessage(e))}</p><button class="action" id="dashboardRetry">${dashboardIcon("refresh")}<span>Try again</span></button></div>`);
    if ($("#dashboardRetry")) $("#dashboardRetry").onclick = () => componentsView();
  } finally {
    clearTimeout(timeout);
    if (request === state.dashboardRequest) {
      state.dashboardLoading = false;
      if ($("#dashboardRefresh")) $("#dashboardRefresh").disabled = false;
      if (dashboardVisible()) state.dashboardTimer = setInterval(() => { if (!document.hidden) componentsView(!!$("#dashboardRefresh")); }, 30000);
    }
  }
}
const HEALTH_WORDS = {ok:"OK", warning:"Needs a look", error:"Problem"};
/* Where to look next for each health check. */
const HEALTH_LINKS = {logs:["#/kodi-logs","See the past 24 hours"], memory:["#/trends","See memory over time"], internet:["#/trends","See answer times"], nightly:["#/backups","Open backups"], trakt:["#/accounts","Open accounts"], torbox:["#/accounts","Open accounts"], stack:["#/components","See your add-ons"], write_mode:["#/setup","How changes are allowed"]};
const HEALTH_STATS = {addons:"Add-ons installed", enabled_addons:"Turned on", config_folders:"With saved settings", stack_detected:"Core add-ons found", kodi_log_errors:"Errors in Kodi’s log", kodi_log_warnings:"Warnings in Kodi’s log", kodi_memory_mb:"Memory used by Kodi"};
function healthTone(status){ return status === "ok" ? "ok" : status === "error" ? "bad" : "warn"; }
async function healthView(){
  const h = await api("/api/health");
  const checks = h.checks || [];
  const attention = checks.filter(c => c.status !== "ok");
  const tone = healthTone(h.status);
  const verdict = !attention.length ? "Every check passed" : `${attention.length} check${attention.length === 1 ? " needs" : "s need"} a look`;
  const statValue = (k, v) => k === "kodi_memory_mb" && v !== null && v !== undefined ? formatMB(Number(v)) : v ?? "—";
  out(`${pageHead("Health checks", "Everything Kodi Manager checks on the TV, in plain words, with a fix where there is one.")}
  <section class="verdict verdict--${tone}" aria-label="Summary">${dashboardIcon(tone === "ok" ? "check" : "alert")}<div><h3>${esc(verdict)}</h3><p>${esc(attention.length ? "The checks that need a look are listed first." : "Nothing needs doing right now.")}</p></div></section>
  <ul class="checklist">${[...attention, ...checks.filter(c => c.status === "ok")].map(c => `<li class="check check--${healthTone(c.status)}"><span class="check-icon">${dashboardIcon(c.status === "ok" ? "check" : "alert")}</span><div class="check-body"><div class="check-head"><b>${esc(c.label)}</b>${dashboardPill(healthTone(c.status), HEALTH_WORDS[c.status] || c.status, c.status === "ok" ? "check" : "alert")}</div><p class="muted">${esc(c.detail)}</p>${healthAction(c)}${HEALTH_LINKS[c.id] && c.status !== "ok" ? `<a class="check-link" href="${HEALTH_LINKS[c.id][0]}">${esc(HEALTH_LINKS[c.id][1])}</a>` : ""}</div></li>`).join("")}</ul>
  <section class="panel"><h3>At a glance</h3><dl class="facts-grid">${Object.entries(h.stats || {}).map(([k,v]) => `<div><dt>${esc(HEALTH_STATS[k] || k.replace(/_/g," "))}</dt><dd>${esc(statValue(k, v))}</dd></div>`).join("")}</dl></section>
  ${(h.log_issues || []).length ? `<section class="panel"><h3>Recorded issue groups</h3>${logIssueCards(h.log_issues, 'all', true)}</section>` : ''}
  <details class="panel log-problems"><summary>Latest recorded problems from the past 24 hours</summary><h4>Errors</h4><pre>${esc(logBlock(h.recent_errors))}</pre><h4>Warnings</h4><pre>${esc(logBlock(h.recent_warnings))}</pre><a href="#/kodi-logs">See all retained warnings and errors</a></details>`);
  bindHealthActions();
}
function healthAction(check){
  const action = check && check.action;
  if (!action || typeof action.path !== "string" || !action.path.startsWith("/api/")) return "";
  return `<button type="button" class="action check-action" data-health-action="${esc(action.path)}" data-health-label="${esc(check.label || "")}" data-health-detail="${esc(check.detail || "")}" ${writeAttrs()}>${esc(action.label || "Fix")}</button>`;
}
function bindHealthActions(){
  document.querySelectorAll("[data-health-action]").forEach(button => button.onclick = withErrors(async () => {
    if (!(await confirmDialog({title:`${button.textContent || "Fix"}: ${button.dataset.healthLabel || "this check"}?`, message:"The current values in the affected add-ons are overwritten with the expected ones. Stop playback first.", detail:button.dataset.healthDetail || "", confirmLabel:button.textContent || "Fix"}))) return;
    const r = await api(button.dataset.healthAction, {});
    const applied = (r && r.applied) ? r.applied.length : 0;
    const failed = (r && r.failed) ? r.failed.length : 0;
    toast(`${applied} setting${applied === 1 ? "" : "s"} re-applied${failed ? `, ${failed} failed` : ""}.${r && r.restart_required ? " Restart Kodi for add-on changes to take effect." : ""}`, failed ? "warn" : "ok");
    await healthView();
  }));
}
function logBlock(lines){ return (lines || []).slice().reverse().join("\n") || "None"; }
function runGlobalSearch(){
  const q = ($("#globalSearch").value || "").trim();
  if (!q) return;
  location.hash = "#/search?q=" + encodeURIComponent(q);
}
async function searchView(query){
  $("#globalSearch").value = query;
  if (!query) return out(`${pageHead("Search settings", "Find a setting in any add-on by name, description or ID.")}<div class="empty-state"><p>Type in the search box at the top of the page, for example <b>torbox</b> or <b>autoplay</b>.</p></div>`);
  const data = await api(`/api/search/config?q=${encodeURIComponent(query)}`);
  out(`${pageHead(`Settings matching “${query}”`, `${data.count ?? 0} setting${data.count === 1 ? "" : "s"} found across your add-ons.`)}<div class="panel">${(data.results || []).map(r => `<div class="card"><h3>${esc(r.addon_name || r.addon_id)} <span class="muted">${esc(r.version || "")}</span></h3><p><b title="${esc(r.id)}">${esc(friendlyName(r.id, r.label))}</b><br><span class="muted">${esc(r.description || describeSetting(r.id, r.label))}</span></p><p>${esc(r.masked ? "••••••••" : r.value)}</p><p>${r.editable ? "<span class='ok'>editable</span>" : "<span class='muted'>read-only</span>"} ${r.warning ? `<span class="warn">${esc(r.warning)}</span>` : ""}</p><a class="action" href="#/addon/${esc(encodeURIComponent(r.addon_id))}">Open add-on</a></div>`).join("")}</div>`);
}
function nodeCard(n){ return `<div class="pipe-node"><h3>${esc(n.label)}</h3><p>${esc(n.name || n.addon_id || (n.id === "kodi" || n.id === "kodi_player" ? "Kodi" : "Unknown"))}</p><p class="muted">${esc(n.status || "unknown")}${n.relationship ? ` · ${esc(n.relationship)}` : ""}</p><p class="muted">${esc((n.detected_from || []).join(", "))}</p></div>`; }
function pipelineEvidence(evidence){
  return (evidence || []).map(e => typeof e === "string" ? esc(e) : esc([e.component || e.addon_id, e.setting_id, e.path, e.source, e.dependency || e.module, ...(e.refs || [])].filter(Boolean).join(" · "))).filter(Boolean).join("<br>") || "No explicit evidence found.";
}
function integrationSummary(summary={}){
  const label = summary.status === "configured" ? "Credentials present" : summary.status === "not found" ? "No account credentials found" : "Account status unknown";
  const count = Number.isInteger(summary.refs_found) && summary.refs_found > 0 ? `${summary.refs_found} auth fields inspected. ` : "";
  return `<p>${label} · unverified</p>${summary.message ? `<p class="muted">${esc(summary.message)}</p>` : ""}${(summary.providers || []).map(p=>`<p><b>${esc(p.name || p.addon_id)}</b> · ${p.status === "configured" ? "credentials present" : "account status unknown"}<br><span class="muted">${pipelineEvidence(p.evidence)}</span></p>`).join("")}<p class="muted">${count}Account access has not been verified.</p>`;
}
function appBooleanOptions(value){
  const original = String(value ?? "");
  const text = original.trim().toLowerCase();
  const on = ["true", "1", "yes", "on"].includes(text);
  const off = ["false", "0", "no", "off"].includes(text);
  return `${!on && !off ? `<option value="${esc(original)}" disabled selected>Unknown</option>` : ""}<option value="${esc(on ? original : "true")}" ${on ? "selected" : ""}>On</option><option value="${esc(off ? original : "false")}" ${off ? "selected" : ""}>Off</option>`;
}
function appCanWrite(status){ return status?.write_enabled === true; }
function settingRank(s){
  const id = String(s.id || "").toLowerCase();
  if (id.includes("player") || id.includes("default") || id.includes("autoplay")) return 0;
  if (id.includes("scraper") || id.includes("provider") || id.includes("external")) return 1;
  if (id.includes("timeout") || id.includes("thread") || id.includes("quality")) return 2;
  return s.editable ? 3 : 9;
}
function controlFor(s, attrs){
  const disabled = !(s.editable && state.writeEnabled);
  const val = s.value ?? "";
  const meta = `${s.description || describeSetting(s.id, s.label)}${disabled ? " · read-only" : ""}`;
  const input = (String(s.type).toLowerCase()==="boolean" || String(s.type).toLowerCase()==="bool")
    ? `<select ${attrs} data-original="${esc(val)}" ${disabled?"disabled":""}>${appBooleanOptions(val)}</select>`
    : `<input type="${appSecretSetting(s) ? "password" : "text"}" ${attrs} data-original="${esc(val)}" value="${esc(val)}" ${disabled?"disabled":""}>`;
  return `<div class="setting-card"><label><span><b title="${esc(s.id)}">${esc(friendlyName(s.id, s.label))}</b><br><span class="muted">${esc(meta)}</span></span>${input}</label></div>`;
}
function settingRows(settings, scope){
  return `${filterTabs(scope, settings)}<div class="settings-grid">${[...(settings||[])].sort((a,b)=>settingRank(a)-settingRank(b)||String(a.label||a.id).localeCompare(String(b.label||b.id))).map(s=>`<div data-filter-scope="${esc(scope)}" data-set="${settingIsSet(s) ? "true" : "false"}" data-readonly="${isReadOnlySetting(s) ? "true" : "false"}">${controlFor(s, `data-pipe-component="${esc(s.component)}" data-pipe-setting="${esc(s.id)}" data-pipe-source="${esc(s.source)}"`)}</div>`).join("")}</div>`;
}
async function pipelineView(){
  const status = await api("/api/status");
  state.writeEnabled = appCanWrite(status);
  updateDirtyBar();
  const p = await api("/api/pipeline");
  const warnings = p.summary.health.warnings?.length ? `<div class="banner">${p.summary.health.warnings.map(esc).join("<br>")}</div>` : "";
  const primary = p.summary.primary_player || {};
  const scraper = p.summary.scraper_module || {};
  out(`${pageHead("Playback setup", "Which add-on plays what you pick, which scraper it uses, and the routing settings you can change here.")}${warnings}<div class="panel"><p>Primary player: <b>${esc(primary.name || primary.addon_id || "Unknown")}</b> · ${esc(primary.selection || "unknown")} · ${esc(primary.confidence || "unknown")} confidence</p><div class="grid">${p.nodes.map(nodeCard).join("")}</div><button class="action" id="rescanPipe">Rescan</button><button class="action" id="backupPipe" ${writeAttrs()}>Back up playback settings</button><button class="action" id="copyPipe">Copy debug report</button></div>
  <div class="panel"><h3>Current routing</h3><table class="addon-table"><thead><tr><th>Stage</th><th>Detected component</th><th>Config source</th><th>Status</th><th>Editable</th></tr></thead><tbody>
    ${Object.entries(p.routing).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v.value)}<br><span class="muted">${esc(v.addon_id)}</span></td><td>${esc(v.source)} ${esc(v.setting_id || "")}</td><td>${esc(v.confidence)}</td><td>${badge(v.editable)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="panel"><h3>Connections and evidence</h3><div class="grid">${p.edges.map(e=>card(`${p.nodes.find(n=>n.id===e.from)?.label || e.from}${(e.evidence || []).length ? " → " : " / "}${p.nodes.find(n=>n.id===e.to)?.label || e.to}`, `<p>${esc(e.label)} · ${esc(e.relationship || ((e.evidence || []).length ? "evidence found" : "unconfirmed"))}</p><p class="muted">${pipelineEvidence(e.evidence)}</p>`)).join("")}</div></div>
  <div class="panel"><h3>Scraper relationship</h3><p>${esc(scraper.name || "Unknown")} · ${esc(scraper.relationship || "unknown")} · ${scraper.used === true ? "linked to selected player" : "usage unconfirmed"}</p><p class="muted">${pipelineEvidence(scraper.evidence)}</p><h4>Available modules</h4>${(p.summary.available_scraper_modules || []).map(a=>`<p>${esc(a.name || a.addon_id)} · installed: ${badge(a.installed)} · enabled: ${badge(a.enabled)}</p>`).join("") || "<p class='muted'>No external scraper modules detected.</p>"}<p class="muted">Module installation and enablement do not establish which player uses it.</p></div>
  <div class="panel"><h3>Account integrations</h3><div class="grid">${["trakt","torbox","tmdb"].map(k=>card(ACCOUNT_NAMES[k], integrationSummary((p.summary.integrations || p.summary.accounts || {})[k]))).join("")}</div><a href="#/accounts">Edit account settings</a></div>
  <div class="panel"><h3>Playback controls</h3><p class="muted">Only routing and provider-link settings are shown here. Account keys are on the Accounts page.</p>${p.settings_groups.map((g,i)=>`<div class="group"><h4>${esc(g.label)}</h4>${settingRows(g.settings, `pipe-${i}`)}</div>`).join("") || "<p class='muted'>No safe playback controls detected. Use the add-on’s own settings for player-file routing.</p>"}</div>
  <div class="panel"><h3>Playback target</h3><p>Player-file routes are configured in helper settings.</p>${p.summary.helper?.addon_id ? `<a href="#/addon/${esc(encodeURIComponent(p.summary.helper.addon_id))}">Open helper settings</a>` : "<p class='muted'>No helper add-on detected.</p>"}</div>
  <div class="panel"><h3>Discovery evidence</h3><pre>${esc(JSON.stringify(redactObj(p.discovery), null, 2))}</pre></div>`);
  $("#rescanPipe").onclick = withErrors(() => pipelineView());
  setWriteState($("#backupPipe"));
  $("#backupPipe").onclick = withErrors(async () => {
    if (!state.writeEnabled) return;
    const r = await api("/api/pipeline/backup", {});
    toast(`Playback settings backed up as ${r.backup_id}.`, "ok");
  });
  $("#copyPipe").onclick = withErrors(() => copyWithNotice(JSON.stringify(redactObj(p), null, 2), "Debug report"));
  document.querySelectorAll("[data-pipe-setting]").forEach(el => el.onchange = withErrors(async () => {
    const preview = changePreview(el.dataset.pipeSetting, el.dataset.original, el.value, el.type === "password" || appSecretSetting({id:el.dataset.pipeSetting}));
    if (!(await confirmDialog({title:"Save this setting?", message:"A backup is created first.", detail:preview, confirmLabel:"Save"}))) { el.value = el.dataset.original; return; }
    try {
      const r = await apiMethod("PATCH", "/api/pipeline/settings", {changes:[{component:el.dataset.pipeComponent,setting_id:el.dataset.pipeSetting,source:el.dataset.pipeSource,value:el.value}]});
      toast(`Saved. Backup ${r.backup_id}.`, "ok");
    } catch (error) { el.value = el.dataset.original; throw error; }
    await pipelineView();
  }));
  wireFilterTabs();
}
function accountField(s){
  const canEdit = s.editable && state.writeEnabled;
  const isSet = settingIsSet(s);
  const ph = s.placeholder || (isSet ? "configured" : "not set");
  const type = String(s.type || "").toLowerCase();
  const input = (type === "boolean" || type === "bool")
    ? `<select data-account-component="${esc(s.component)}" data-account-setting="${esc(s.id)}" data-account-source="${esc(s.source)}" data-original="${esc(s.value ?? "")}" ${canEdit ? "" : "disabled"}>${appBooleanOptions(s.value)}</select>`
    : `<input type="${appSecretSetting(s) ? "password" : "text"}" autocomplete="off" data-account-component="${esc(s.component)}" data-account-setting="${esc(s.id)}" data-account-source="${esc(s.source)}" data-original="${esc(s.value ?? "")}" value="${esc(s.value || "")}" placeholder="${esc(ph)}" ${canEdit ? "" : "disabled"}>`;
  return `<div class="setting-card"><label><span><b title="${esc(s.id)}">${esc(friendlyName(s.id, s.label))}</b> ${isSet ? "<span class='badge'>set</span>" : "<span class='badge'>unset</span>"}<br><span class="muted">${esc(s.description || describeSetting(s.id, s.label))}${canEdit ? "" : " · read-only"}</span></span>${input}</label></div>`;
}
const ACCOUNT_NAMES = {trakt:"Trakt", torbox:"TorBox", tmdb:"TMDb", debrid:"Debrid services"};
/* Expiry and sign-in checks the service ran (twice a day while idle), above the editable fields. */
function accountHealthMarkup(accounts){
  if (!Array.isArray(accounts) || !accounts.length) return "";
  return `<ul class="checklist account-health" aria-label="Account checks">${accounts.map(a => { const tone = healthTone(a.status); return `<li class="check check--${tone}"><span class="check-icon">${dashboardIcon(tone === "ok" ? "check" : "alert")}</span><div class="check-body"><div class="check-head"><b>${esc(a.label)}</b>${dashboardPill(tone, finite(a.days_left) && !a.renews && a.days_left >= 0 ? `${a.days_left} day${a.days_left === 1 ? "" : "s"} left` : HEALTH_WORDS[a.status] || a.status, tone === "ok" ? "check" : "alert")}</div><p class="muted">${esc(a.detail || "")}</p></div></li>`; }).join("")}</ul>`;
}
async function accountsView(){
  const status = await api("/api/status");
  state.writeEnabled = appCanWrite(status);
  const [d, overview] = await Promise.all([api("/api/accounts"), api("/api/overview").catch(() => null)]);
  out(`${pageHead("Accounts", "The sign-ins and keys your add-ons use. Values are hidden until you reveal them; saving makes a backup first.")}${accountHealthMarkup(overview?.accounts)}<div class="panel"><div class="grid">${Object.entries(d.summary || {}).map(([k,v])=>card(ACCOUNT_NAMES[k] || k, integrationSummary(v))).join("")}</div><button class="primary" id="saveAccounts" ${writeAttrs()}>Save account changes</button></div>${(d.groups||[]).map((g,i)=>`<div class="group"><h3>${esc(g.label)}</h3>${filterTabs(`acct-${i}`, g.settings)}<div class="settings-grid">${g.settings.map(s=>`<div data-filter-scope="acct-${i}" data-set="${settingIsSet(s) ? "true" : "false"}" data-readonly="${isReadOnlySetting(s) ? "true" : "false"}">${accountField(s)}</div>`).join("")}</div></div>`).join("")}`);
  setWriteState($("#saveAccounts"));
  $("#saveAccounts").onclick = withErrors(async () => {
    if (!state.writeEnabled) return;
    const changes = [...document.querySelectorAll("[data-account-setting]")].filter(i=>!i.disabled).filter(i=>String(i.value) !== String(i.dataset.original ?? "")).map(i=>({component:i.dataset.accountComponent,setting_id:i.dataset.accountSetting,source:i.dataset.accountSource,value:i.value}));
    if (!changes.length) return toast("No account changes entered.", "info");
    const preview = changes.map(ch => {
      const el = [...document.querySelectorAll("[data-account-setting]")].find(x => x.dataset.accountSetting === ch.setting_id && x.dataset.accountComponent === ch.component);
      return `${ch.component} / ${changePreview(ch.setting_id, el?.dataset.original, ch.value, el?.type === "password" || appSecretSetting({id:ch.setting_id}))}`;
    }).join("\n\n");
    if (!(await confirmDialog({title:`Replace ${changes.length} account value${changes.length === 1 ? "" : "s"}?`, message:"A backup is created first.", detail:preview, confirmLabel:"Save"}))) return;
    const r = await apiMethod("PATCH","/api/accounts/settings",{changes});
    toast(`Saved ${r.changed_count}. Backup ${r.backup_id}.`, "ok");
    await accountsView();
  });
  wireFilterTabs();
}
function smartGroupKey(s){
  const id = String(s.id || "").toLowerCase();
  const label = String(s.label || "").toLowerCase();
  const t = `${id} ${label}`;
  if (/token|secret|api|key|oauth|auth|password|account|client|rd\.|ad\.|pm\.|tb\.|trakt|torbox|debrid|easynews|premiumize/.test(t)) return "Accounts";
  if (/player|default|autoplay|fallback|resume/.test(t)) return "Playback";
  if (/scraper|provider|external|cocoscraper|source|quality|timeout|thread|filter/.test(t)) return "Sources / Providers";
  if (/fanart|poster|artwork|thumbnail|image|landscape/.test(t)) return "Artwork";
  if (/library|folder|path|sync|update/.test(t)) return "Library / Sync";
  if (!s.editable) return "Read-only / Native";
  return "General";
}
function smartGroups(groups){
  const buckets = {};
  (groups || []).forEach(g => (g.settings || []).forEach(s => {
    const key = smartGroupKey(s);
    (buckets[key] ||= []).push(s);
  }));
  const order = ["Accounts","Playback","Sources / Providers","Artwork","Library / Sync","General","Read-only / Native"];
  return order.filter(k => buckets[k]?.length).map(k => ({id:k.toLowerCase().replaceAll(" ","_"), label:k, settings:buckets[k]}));
}
function integrationRows(rows){
  return rows.map(r=>`<div class="row"><span><b>${esc(friendlyName(r.setting_id || r.id, r.setting_id || r.id))}</b><br><span class="muted">${esc(r.source || "settings.xml")}</span></span><span>${r.configured === true ? "credentials present" : "not configured"} · unverified</span></div>`).join("") || "<p class='muted'>No auth fields detected.</p>";
}
async function integrations(){
  const [accounts, stack] = await Promise.all([api("/api/accounts"), api("/api/stack")]);
  const standalone = stack.trakt || {};
  const trakt = accounts.summary?.trakt || stack.trakt_integration || {};
  out(`${pageHead("Trakt", "Player and metadata add-ons can each keep their own Trakt sign-in.")}<div class="panel">${integrationSummary(trakt)}<a href="#/accounts">Edit account settings</a></div><div class="panel"><h3>Optional standalone scrobbler</h3><p>${standalone.installed === true ? `script.trakt is installed · enabled: ${badge(standalone.enabled)}` : "script.trakt is absent. Add-on account integration can operate independently."}</p>${standalone.installed === true || standalone.config_present === true ? '<a href="#/addon/script.trakt">Open standalone scrobbler settings</a>' : ""}</div><div class="panel"><h3>TorBox integration</h3>${integrationSummary(accounts.summary?.torbox)}<a href="#/accounts">Edit TorBox settings</a></div>`);
}
async function pickAddon(keys){ const s=await api("/api/stack"); for (const k of keys){ const aid=s[k]?.addon_id; if(aid) return addonSettings(aid); } out(`${pageHead("Not installed", "No matching add-on was found on this Kodi.")}<div class="empty-state"><a class="action" href="#/components">See your add-ons</a></div>`); }
async function addonSettings(aid){
  return renderAddonSettingsView(aid);
}

/* Backups and restores. Restores may answer 409 while Kodi is busy; the user can then force them. */
function undoTargets(result, addonId){
  if (result?.undo_backups && typeof result.undo_backups === "object") return Object.entries(result.undo_backups).map(([id, backupId]) => ({addonId:id, backupId}));
  if (result?.undo_backup_id && addonId) return [{addonId, backupId:result.undo_backup_id}];
  return [];
}
async function postWithForce(path, body, action="Restore"){
  try { return await api(path, body); }
  catch (error) {
    if (error.status !== 409) throw error;
    const ok = await confirmDialog({title:"Kodi is busy", message:error.message || "Kodi reports that something is playing or an add-on is busy.", detail:`${action} now could interrupt playback, or the add-on could overwrite the restored settings when it next saves.`, confirmLabel:`${action} anyway`, danger:true});
    if (!ok) return null;
    return api(path, {...body, force:true});
  }
}
function restoreSummary(result, undo){
  const restored = Array.isArray(result?.restored) ? `${result.restored.length} add-on${result.restored.length === 1 ? "" : "s"} restored` : "Restored";
  const skipped = (result?.skipped || []).length ? ` · ${result.skipped.length} skipped` : "";
  const ids = undo.map(u => u.backupId).join(", ");
  return `${restored}${skipped}.${ids ? ` Undo backup${undo.length === 1 ? "" : "s"}: ${ids}.` : ""}${result?.restart_required ? " If an add-on doesn’t pick up the change, restart Kodi." : ""}`;
}
function announceRestore(result, addonId){
  if (!result) return;
  const undo = undoTargets(result, addonId);
  const shownAt = Date.now();
  toast(restoreSummary(result, undo), "ok", undo.length ? {actions:[{label:"Undo restore", run:() => undoRestore(undo, {confirmFirst:Date.now() - shownAt > QUICK_UNDO_MS})}]} : {});
}
async function undoRestore(targets, {confirmFirst=false}={}){
  if (confirmFirst && !(await confirmDialog({title:"Undo this restore?", message:"Settings go back to how they were just before the restore.", detail:targets.map(t => t.backupId).join(", "), confirmLabel:"Undo restore"}))) return;
  for (const target of targets) {
    const r = await postWithForce(`/api/addons/${encodeURIComponent(target.addonId)}/restore`, {backup_id:target.backupId}, "Undo");
    if (!r) return;
  }
  toast("Restore undone.", "ok");
  await route();
}
async function restoreAddonBackup(addonId, backupId, {confirmFirst=true}={}){
  if (confirmFirst && !(await confirmDialog({title:"Restore this backup?", message:`The current settings of ${addonId} are backed up first, so you can undo this.`, detail:backupId, confirmLabel:"Restore"}))) return null;
  const result = await postWithForce(`/api/addons/${encodeURIComponent(addonId)}/restore`, {backup_id:backupId});
  announceRestore(result, addonId);
  if (result) await route();
  return result;
}
function formatBackupTime(value){
  const m = /^(\d{4})(\d{2})(\d{2})[-T_]?(\d{2})(\d{2})(\d{2})/.exec(String(value || ""));
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : String(value || "");
}
function addonBackupsMarkup(addonId, backups){
  if (!backups.length) return `<p class="muted">No backups for this add-on yet. Kodi Manager makes one automatically before every change.</p>`;
  return `<table class="addon-table backups-table"><thead><tr><th>Backup</th><th>Taken</th><th>Add-on version</th><th>Files</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>${backups.map(b => `<tr><td><code>${esc(b.backup_id)}</code></td><td>${esc(formatBackupTime(b.timestamp || b.backup_id))}</td><td>${esc(b.addon_version || "—")}</td><td>${esc(b.files_copied ?? "—")}</td><td><button type="button" class="action" data-addon-restore="${esc(b.backup_id)}" data-addon-id="${esc(addonId)}" ${writeAttrs()}>Restore</button></td></tr>`).join("")}</tbody></table>`;
}
async function renderAddonBackups(addonId, container){
  container.innerHTML = '<p class="muted" role="status">Loading backups…</p>';
  const data = await api(`/api/addons/${encodeURIComponent(addonId)}/backups`);
  container.innerHTML = `<div class="toolbar"><button type="button" class="action" data-addon-backup="${esc(addonId)}" ${writeAttrs()}>Back up now</button></div>${addonBackupsMarkup(addonId, Array.isArray(data?.backups) ? data.backups : [])}`;
  container.querySelectorAll("[data-addon-restore]").forEach(button => button.onclick = withErrors(() => restoreAddonBackup(button.dataset.addonId, button.dataset.addonRestore)));
  container.querySelector("[data-addon-backup]").onclick = withErrors(async () => {
    const r = await api(`/api/addons/${encodeURIComponent(addonId)}/backup`, {});
    toast(`Backup ${r.backup_id} created.`, "ok");
    await renderAddonBackups(addonId, container);
  });
}
function backupKind(item){
  if (item.kind === "pipeline") return {key:"pipeline", label:"Playback settings", cls:"s3"};
  if (item.note === "nightly") return {key:"nightly", label:"Nightly", cls:"s1"};
  return {key:"manual", label:"Manual", cls:"s2"};
}
/* Checkpoints per day for the last `days` days, split by kind (stacked columns). */
function backupChartSpec(items, now, days = 30){
  const kinds = [["nightly","Nightly","s1"],["manual","Manual","s2"],["pipeline","Playback settings","s3"]];
  const perDay = checkpointsPerDay([], now, days);
  const values = Object.fromEntries(kinds.map(([k]) => [k, perDay.t.map(() => 0)]));
  for (const item of items || []) {
    const time = parseStamp(item.timestamp || item.backup_id);
    if (!finite(time)) continue;
    const d = new Date(time * 1000); d.setHours(12, 0, 0, 0);
    const i = perDay.t.indexOf(Math.floor(d.getTime() / 1000));
    if (i >= 0) values[backupKind(item).key][i]++;
  }
  const total = Object.values(values).reduce((sum, list) => sum + list.reduce((a, b) => a + b, 0), 0);
  const missed = values.nightly.slice(-7).filter(v => !v).length;
  return {title:`Checkpoints, last ${days} days`, kind:"columns", slot:86400, t:perDay.t, yMin:0, height:170, xName:"Day", xLabel:formatDay,
    format:v => String(Math.round(v)), tickFormat:v => Number.isInteger(v) ? String(v) : "",
    columnLabels:(t, w) => t.filter((_, i) => i % (w < 420 ? 10 : 5) === (t.length - 1) % (w < 420 ? 10 : 5)).map(time => ({t:time, label:formatDay(time)})),
    summary:total ? `${total} checkpoint${total === 1 ? "" : "s"} in ${days} days.${missed ? ` No nightly checkpoint on ${missed} of the last 7 nights (the TV was busy or off).` : " One every night this week."}` : "",
    series:kinds.map(([k, name, cls]) => ({name, values:values[k], cls})), empty:"No checkpoints in this period."};
}
function backupRow(x){
  const kind = backupKind(x), id = x.backup_id || x.name || "", time = parseStamp(x.timestamp || id);
  const size = finite(x.total_bytes) ? formatBytes(x.total_bytes) : "";
  return `<li class="backup-row"><span class="key key-${kind.cls} key-box" aria-hidden="true"></span><div class="backup-main"><b>${esc(time ? formatWhen(time) : formatBackupTime(id))}</b><span class="muted">${esc(kind.label)}. ${esc(x.component_count || 0)} add-on${x.component_count === 1 ? "" : "s"} saved${x.skipped_count ? `, ${esc(x.skipped_count)} skipped` : ""}${size ? `, ${esc(size)}` : ""}.</span><code class="backup-id">${esc(id)}</code></div>${x.kind === "pipeline" ? `<button class="action" disabled title="Playback-setting backups are restored by hand: see docs/recovery.md">Restore</button>` : `<button class="action" data-restore="${esc(id)}" ${writeAttrs()}>Restore</button>`}</li>`;
}
async function backups(){
  const [t, addons] = await Promise.all([api("/api/backups/timeline"), api("/api/addons").catch(() => [])]);
  const items = t.items || [];
  const withConfig = (addons || []).filter(a => a.config_present === true).sort((a,b) => String(a.name || a.addon_id).localeCompare(String(b.name || b.addon_id)));
  resetCharts();
  out(`${pageHead("Backups", "A checkpoint saves the settings of your skin, players and helpers together. Restoring backs up the current settings first, so every restore can be undone.", `<button class="primary" id="stackBackup" ${writeAttrs()}>Create checkpoint</button>`)}
  ${items.length ? `<div class="chart-grid chart-grid--one">${chartFigure(backupChartSpec(items, Math.floor(Date.now() / 1000)))}</div>` : ""}
  <section class="panel"><h3>Checkpoints</h3>${items.length ? `<ul class="backup-list">${items.slice(0, 8).map(backupRow).join("")}</ul>${items.length > 8 ? `<details class="more-list"><summary>Show ${items.length - 8} older checkpoint${items.length === 9 ? "" : "s"}</summary><ul class="backup-list">${items.slice(8).map(backupRow).join("")}</ul></details>` : ""}` : `<div class="empty-state"><p>No checkpoints yet. Create one before changing anything, so you can always go back. Kodi Manager also takes one each night while the TV is idle.</p></div>`}</section>
  <section class="panel"><h3>Single add-on backups</h3><p class="muted">Kodi Manager backs up an add-on’s settings before every change it makes.</p><label for="backupAddon">Add-on<select id="backupAddon"><option value="">Choose an add-on…</option>${withConfig.map(a => `<option value="${esc(a.addon_id)}">${esc(a.name || a.addon_id)}</option>`).join("")}</select></label><div id="addonBackups"></div></section>`);
  mountCharts(document);
  $("#stackBackup").onclick = withErrors(async () => {
    const r = await api("/api/stack/backup", {});
    toast(`Checkpoint ${r.backup_id} created.`, "ok");
    await backups();
  });
  document.querySelectorAll("[data-restore]").forEach(b => b.onclick = withErrors(async () => {
    if (!(await confirmDialog({title:"Restore this checkpoint?", message:"Each add-on’s current settings are backed up first, so you can undo this.", detail:b.dataset.restore, confirmLabel:"Restore"}))) return;
    const r = await postWithForce("/api/stack/restore", {backup_id:b.dataset.restore});
    announceRestore(r);
    if (r) await backups();
  }));
  $("#backupAddon").onchange = withErrors(async () => {
    const id = $("#backupAddon").value;
    if (!id) { $("#addonBackups").innerHTML = ""; return; }
    await renderAddonBackups(id, $("#addonBackups"));
  });
}

/* Optional widget cache: rows a skin widget can read from a local copy. */
function formatAge(seconds){
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return "—";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
function cachedRowStatus(entry){
  if (!entry) return {tone:"muted", label:"Not cached yet", icon:"minus"};
  if (entry.stale) return {tone:"warn", label:"Stale", icon:"pause"};
  return {tone:"ok", label:"Fresh", icon:"check"};
}
function cachedRowMarkup(row, entry, index){
  const status = cachedRowStatus(entry);
  return `<tr><th scope="row"><b>${esc(row.label)}</b><br><span class="muted cached-source">${esc(row.source)}</span>${row.hide_watched ? '<br><span class="badge">hides watched</span>' : ""}</th><td data-label="Status">${dashboardPill(status.tone, status.label, status.icon)}</td><td data-label="Items">${esc(entry ? entry.items : "—")}</td><td data-label="Updated">${esc(entry ? formatAge(entry.age_seconds) : "—")}</td><td class="row-actions"><button type="button" class="action" data-copy-row="${index}">Copy URL</button><button type="button" class="action" data-remove-row="${esc(row.id)}" ${writeAttrs()}>Remove</button></td></tr>`;
}
function cacheSourceLabel(source){
  try {
    const url = new URL(String(source).replace(/^plugin:/, "http:"));
    const name = url.searchParams.get("name") || url.searchParams.get("list_name") || url.searchParams.get("title");
    if (name) return name;
    const mode = url.searchParams.get("mode") || url.searchParams.get("action") || url.searchParams.get("info") || url.pathname.replace(/\//g, " ").trim();
    return `${url.hostname}${mode ? ` · ${mode}` : ""}`;
  } catch (_) { return String(source); }
}
function cachedEntryMarkup(entry){
  const status = cachedRowStatus(entry);
  return `<tr><th scope="row"><b>${esc(entry.title || cacheSourceLabel(entry.source))}</b><br><span class="muted cached-source">${esc(entry.source)}</span></th><td data-label="Status">${dashboardPill(status.tone, status.label, status.icon)}</td><td data-label="Items">${esc(entry.items)}</td><td data-label="Updated">${esc(formatAge(entry.age_seconds))}</td></tr>`;
}
async function cachedRowsView(){
  const [rowData, cache] = await Promise.all([api("/api/widget-cache/rows"), api("/api/widget-cache").catch(() => null)]);
  const rows = Array.isArray(rowData) ? rowData : [];
  const entries = new Map((cache?.entries || []).map(entry => [entry.source, entry]));
  const listed = new Set(rows.map(row => row.source));
  const others = (cache?.entries || []).filter(entry => !listed.has(entry.source));
  const othersPanel = others.length ? `<div class="panel"><h3>Cached for your skin's widgets</h3><p>Widgets already pointed at Kodi Manager's cached URL (by you, by automatic row caching, or by a skin setting). Kodi Manager refreshes these in the background.</p><table class="addon-table cached-rows"><thead><tr><th scope="col">Row</th><th scope="col">Status</th><th scope="col">Items</th><th scope="col">Updated</th></tr></thead><tbody>${others.map(cachedEntryMarkup).join("")}</tbody></table></div>` : "";
  out(`${pageHead("Cached rows", "Kodi Manager can keep a copy of an add-on folder so a home-screen row shows straight away instead of waiting for the add-on.")}<div class="panel"><p>Point a widget at a row’s cached URL, or choose it in your skin’s widget picker under <b>Video add-ons → Kodi Manager → Cached rows</b>. <a href="#/rows">See how each row is doing</a>.</p><div class="toolbar"><button type="button" class="action" id="cacheRefresh">Refresh all now</button><span class="muted">${cache ? `${esc(cache.queued ?? 0)} queued for refresh` : "Cache status unavailable"}</span></div>
  <table class="addon-table cached-rows"><thead><tr><th scope="col">Row</th><th scope="col">Status</th><th scope="col">Items</th><th scope="col">Updated</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows.map((row, i) => cachedRowMarkup(row, entries.get(row.source), i)).join("") || `<tr><td colspan="5" class="muted">${others.length ? "No rows added here yet. Your skin's cached widgets are listed below." : "No cached rows yet."}</td></tr>`}</tbody></table></div>${othersPanel}
  <div class="panel"><h3>Add a row</h3><p>Paste an add-on folder path (it starts with <code>plugin://</code>). In Kodi you can also open any video add-on folder and choose <b>Add to Kodi Manager cached rows</b> from its context menu.</p><form id="cacheAdd" class="grid"><label>Name<input id="cacheLabel" required maxlength="80"></label><label>Add-on folder path<input id="cacheSource" required placeholder="plugin://plugin.video.example/?mode=…" spellcheck="false"></label><label>Pages to cache<input id="cachePages" type="number" min="1" max="5" placeholder="Automatic"></label><label class="check-label"><span><input id="cacheHideWatched" type="checkbox"> Hide watched items</span></label><div><button class="primary" type="submit" ${writeAttrs()}>Add row</button></div></form></div>`);
  $("#cacheRefresh").onclick = withErrors(async () => {
    const r = await api("/api/widget-cache/refresh", {});
    toast(`${r.queued ?? 0} row${r.queued === 1 ? "" : "s"} queued for refresh.`, "ok");
    await cachedRowsView();
  });
  document.querySelectorAll("[data-copy-row]").forEach(button => button.onclick = withErrors(async () => {
    const row = rows[Number(button.dataset.copyRow)];
    let url = row.widget_url;
    if (!url) url = (await api(`/api/widget-cache/url?source=${encodeURIComponent(row.source)}${row.pages ? `&pages=${encodeURIComponent(row.pages)}` : ""}${row.hide_watched ? "&hide_watched=true" : ""}`)).url;
    await copyWithNotice(url, "Cached URL");
  }));
  document.querySelectorAll("[data-remove-row]").forEach(button => button.onclick = withErrors(async () => {
    if (!(await confirmDialog({title:"Remove this cached row?", message:"Widgets that use its cached URL will show the add-on folder directly again.", confirmLabel:"Remove", danger:true}))) return;
    await api("/api/widget-cache/rows/remove", {id:button.dataset.removeRow});
    toast("Cached row removed.", "ok");
    await cachedRowsView();
  }));
  $("#cacheAdd").onsubmit = withErrors(async event => {
    event.preventDefault();
    if (!state.writeEnabled) return;
    const pages = $("#cachePages").value.trim();
    await api("/api/widget-cache/rows", {label:$("#cacheLabel").value.trim(), source:$("#cacheSource").value.trim(), ...(pages ? {pages:Number(pages)} : {}), hide_watched:$("#cacheHideWatched").checked});
    toast("Cached row added. It fills in the background.", "ok");
    await cachedRowsView();
  });
}

async function playbackTestView(){
  const pipe = await api("/api/pipeline");
  const players = [pipe.summary.primary_player, ...(pipe.summary.secondary_players || [])].filter(x=>x && x.addon_id);
  out(`${pageHead("Playback test", "A safe dry run: checks routing, the player, the scraper module and whether something is playing. It never starts playback.")}<div class="panel"><div class="grid"><label>Target player<select id="testPlayer">${players.map(p=>`<option value="${esc(p.addon_id)}">${esc(p.name || p.addon_id)}</option>`).join("")}</select></label><label>Optional plugin URL<input id="testUrl" placeholder="plugin://..."></label></div><button class="primary" id="runPlaybackTest">Run test</button><div id="playbackSteps"></div><pre id="playbackOut" hidden></pre></div>`);
  $("#runPlaybackTest").onclick = withErrors(async () => {
    const r = await api("/api/playback/test", {target_player_addon_id:$("#testPlayer").value, plugin_url:$("#testUrl").value});
    $("#playbackSteps").innerHTML = `<ul class="steps">${(r.steps || []).map(step => `<li class="${step.ok ? "ok" : "bad"}">${step.ok ? "✓" : "✗"} ${esc(step.step)} <span class="muted">${esc(step.detail ?? "")}</span></li>`).join("")}</ul>`;
    $("#playbackOut").hidden = false;
    $("#playbackOut").textContent = JSON.stringify(r, null, 2);
  });
}
function logLevel(line){ const s=String(line).toLowerCase(); if (s.includes(" error") || s.includes("error:") || s.includes(" exception") || s.includes("traceback")) return "error"; if (s.includes(" warning") || s.includes("warn:") || s.includes("deprecated")) return "warn"; return "info"; }
function renderLogs(title, lines){
  out(`${pageHead(title, title === "Kodi log" ? "The newest lines of Kodi’s own log, newest first. Tokens and keys are masked." : "What Kodi Manager itself has been doing, newest first.")}<div class="panel"><div class="tabs" role="group" aria-label="Filter log lines">${[["all","All"],["info","Info"],["warn","Warnings"],["error","Errors"]].map(([level,label]) => `<button type="button" data-level="${level}" aria-pressed="false">${label}</button>`).join("")}</div><div id="logBox" class="log-view"></div></div>`);
  const newest = [...(lines || [])].reverse();
  const draw = level => {
    document.querySelectorAll("[data-level]").forEach(b => { const on = b.dataset.level === level; b.classList.toggle("active", on); b.setAttribute("aria-pressed", String(on)); });
    $("#logBox").innerHTML = newest.filter(l => level === "all" || logLevel(l) === level).map(l => `<div class="log-line log-${logLevel(l)}">${esc(l)}</div>`).join("");
  };
  document.querySelectorAll("[data-level]").forEach(b => b.onclick = () => draw(b.dataset.level));
  draw("all");
}
async function logs(){ const l=await api("/api/logs"); renderLogs("Service log", l.lines || []); }
function logIssueRecurrence(issue){
  if (issue.since_baseline === null || issue.since_baseline === undefined) return 'Comparison point not yet recorded';
  if (issue.reviewed_at) return issue.since_baseline ? `${issue.since_baseline} new entries since review` : 'No new entries since review';
  return issue.since_baseline ? `${issue.since_baseline} entries since this Manager version began recording` : 'Retained entries from before this recording baseline';
}
function logIssueCards(issues, level='all', compact=false){
  return (issues || []).map(issue => {
    const owner = issue.owner || {}, href = `#/kodi-logs?issue=${encodeURIComponent(issue.id)}&level=${encodeURIComponent(level)}`;
    const source = owner.addon_id ? `<a href="#/addon/${esc(encodeURIComponent(owner.addon_id))}">${esc(owner.label || owner.addon_id)}</a>` : esc(owner.label || 'Source unconfirmed');
    return `<article class="log-issue"><div class="log-issue-head"><h3>${esc(issue.title)}</h3><span class="muted">${esc(issue.count)} recorded entries · ${esc(issue.level)}</span></div>
      <p>Source: ${source}</p><p class="muted">${esc(logIssueRecurrence(issue))}</p>
      ${compact ? '' : `<dl class="facts"><dt>First seen</dt><dd>${esc(new Date(issue.first_seen * 1000).toLocaleString())}</dd><dt>Last seen</dt><dd>${esc(new Date(issue.last_seen * 1000).toLocaleString())}</dd>${issue.baseline_at ? `<dt>Compared from</dt><dd>${esc(new Date(issue.baseline_at * 1000).toLocaleString())}</dd>` : ''}</dl><details><summary>What this means and next steps</summary><p>${esc(issue.explanation)}</p><p><b>Suggested next step:</b> ${esc(issue.next_step)}</p></details><details><summary>Latest recorded entry</summary><pre>${esc(issue.sample)}</pre></details>`}
      <div class="actions"><a href="${esc(href)}">View this issue’s entries</a>${compact ? '' : `<button type="button" class="action" data-review-issue="${esc(issue.id)}" ${state.writeEnabled ? '' : 'disabled'}>Mark reviewed</button>`}</div></article>`;
  }).join('');
}
function logHistoryMarkup(history, level, rawOpen=false){
  const c = history.counts || {};
  const note = !history.available ? "Collection is unavailable. Saved entries are shown below." : history.catching_up ? "Importing the available log files. Counts may still increase." : "New entries are collected in the background. Entries expire after 24 hours.";
  return `${pageHead("Kodi log", "Warnings and errors from the past 24 hours, retained across Kodi restarts and profile changes. Tokens and keys are masked.")}
    <div class="panel"><p>${esc(c.errors ?? 0)} errors · ${esc(c.warnings ?? 0)} warnings · ${esc(c.notices ?? 0)} known notices</p><p class="muted" role="status">${esc(note)}</p>
    <details><summary>History and comparison points</summary><p class="muted">History started ${esc(history.tracking_started_at ? new Date(history.tracking_started_at * 1000).toLocaleString() : "collecting just now")}. Earlier entries are recovered from the log files still available.</p>
    <p class="muted">${history.recording_version ? `Comparison baseline: Manager ${esc(history.recording_version.version)} began recording at ${esc(new Date(history.recording_version.at * 1000).toLocaleString())}.` : 'No Manager-version comparison baseline has been recorded yet.'} A review point lets you check for recurrence after checking or fixing an issue.</p></details>
    <div class="tabs" role="group" aria-label="Filter retained log entries">${[["all","All"],["error","Errors"],["warning","Warnings"],["notice","Known notices"]].map(([key,label]) => `<button type="button" data-history-level="${key}" aria-pressed="${String(key === level)}" class="${key === level ? "active" : ""}">${label}</button>`).join("")}</div>
    ${history.selected_issue ? '<p><a href="#/kodi-logs">Back to all issues</a></p>' : ''}
    <section aria-label="Issue groups"><h3>${esc(history.issue_total ?? 0)} issue groups</h3>${history.issues_ready === false ? '<p class="muted" role="status">Grouping older retained entries. Group counts may still increase.</p>' : ''}<div id="logIssueGroups">${logIssueCards(history.issues, level)}</div><button type="button" class="action" id="moreLogIssues" ${history.groups_has_more ? '' : 'hidden'}>Load more issue groups</button><p class="muted">Review points preserve the original entries and counts.${state.writeEnabled ? ' Mark an issue reviewed after checking or fixing it.' : ' Enable writes in Connection to record a review point.'}</p></section>
    <details class="original-log-entries" ${history.selected_issue || rawOpen ? 'open' : ''}><summary>Original retained entries</summary>
    <div id="historyLogBox" class="log-view">${logHistoryEntries(history.entries)}</div>
    <p id="historyLogCount" class="muted">${esc((history.entries || []).length)} of ${esc(history.total ?? 0)} entries shown</p>
    <button type="button" class="action" id="olderLogEntries" ${history.has_more ? "" : "hidden"}>Load older entries</button>
    </details><button type="button" class="action" id="refreshLogHistory">Refresh history</button></div>
    <details class="panel"><summary>Current raw log tail</summary><p class="muted">The newest 500 lines, including info messages. The warning/error history above is retained separately.</p><button type="button" id="loadRawKodiLog">Load current tail</button><pre id="rawKodiLog"></pre></details>`;
}
function logHistoryEntries(entries){
  return (entries || []).length ? entries.map(e => `<div class="log-line log-${e.level === "error" ? "error" : e.level === "warning" ? "warn" : "info"}"><time>${esc(new Date(e.timestamp * 1000).toLocaleString())}</time> ${esc(e.line)}</div>`).join("") : '<p class="muted">No retained entries in this filter.</p>';
}
async function kodiLogs(level="all", issue=''){
  const rawOpen = !!document.querySelector('.original-log-entries')?.open;
  const request = (state.logHistoryRequest || 0) + 1;
  state.logHistoryRequest = request;
  const query = `level=${encodeURIComponent(level)}&issue=${encodeURIComponent(issue)}`;
  const h = await api(`/api/kodi/logs/history?${query}`);
  if (request !== state.logHistoryRequest) return;
  out(logHistoryMarkup(h, level, rawOpen));
  document.querySelectorAll("[data-history-level]").forEach(b => b.onclick = withErrors(() => kodiLogs(b.dataset.historyLevel, issue)));
  $("#refreshLogHistory").onclick = withErrors(() => kodiLogs(level, issue));
  const bindReviews = () => document.querySelectorAll('[data-review-issue]').forEach(b => b.onclick = withErrors(async () => {
    b.disabled = true;
    try {
      await api('/api/kodi/logs/review', {issue:b.dataset.reviewIssue});
      if (b.isConnected) await kodiLogs(level, issue);
    } finally { if (b.isConnected) b.disabled = !state.writeEnabled; }
  }));
  bindReviews();
  let groupOffset = (h.group_offset || 0) + (h.issues || []).length;
  const seenGroups = new Set((h.issues || []).map(g => g.id));
  $('#moreLogIssues').onclick = withErrors(async () => {
    const button = $('#moreLogIssues'), box = $('#logIssueGroups');
    button.disabled = true;
    try {
      const more = await api(`/api/kodi/logs/history?${query}&group_offset=${groupOffset}&limit=1`);
      if (!box.isConnected) return;
      box.insertAdjacentHTML('beforeend', logIssueCards((more.issues || []).filter(g => !seenGroups.has(g.id)), level));
      (more.issues || []).forEach(g => seenGroups.add(g.id));
      groupOffset += (more.issues || []).length;
      button.hidden = !more.groups_has_more;
      bindReviews();
    } finally { button.disabled = false; }
  });
  let before = h.next_before, shown = (h.entries || []).length;
  $("#olderLogEntries").onclick = withErrors(async () => {
    const button = $("#olderLogEntries"), box = $("#historyLogBox");
    button.disabled = true;
    try {
      const older = await api(`/api/kodi/logs/history?${query}&before=${encodeURIComponent(before)}`);
      if (!box.isConnected) return;
      box.insertAdjacentHTML("beforeend", (older.entries || []).length ? logHistoryEntries(older.entries) : "");
      shown += (older.entries || []).length; before = older.next_before;
      $("#historyLogCount").textContent = `${shown} of ${older.total ?? shown} entries shown`;
      button.hidden = !older.has_more;
    } finally { button.disabled = false; }
  });
  $("#loadRawKodiLog").onclick = withErrors(async () => {
    const box = $("#rawKodiLog"), raw = await api("/api/kodi/logs");
    if (box.isConnected) box.textContent = (raw.lines || []).join("\n");
  });
}
function addonUsageMarkup(addon){
  const used = addon.required_by || [];
  if (!used.length) return '<span class="muted">No declared dependents found</span>';
  return `<ul class="addon-dependents">${used.map(a => `<li><a href="#/addon/${esc(encodeURIComponent(a.addon_id))}">${esc(a.name || a.addon_id)}</a>${a.enabled === false ? ' <span class="muted">(disabled)</span>' : a.enabled !== true ? ' <span class="muted">(state unknown)</span>' : ''}${a.optional ? ' <span class="muted">(optional)</span>' : ''}</li>`).join('')}</ul>`;
}
function addonExplanationMarkup(info){
  if (!info?.purpose) return '';
  return `<section class="panel addon-explanation"><h3>What this add-on does</h3><p>${esc(info.purpose)}</p><p class="muted">${esc(info.role_label || 'Type unconfirmed')}${info.has_service === true ? ' · Has a background service when enabled' : ''}</p><h4>Before removing it</h4><p><b>${esc(info.cleanup?.label || 'Check usage')}</b> — ${esc(info.cleanup?.detail || 'Check integrations and other profiles.')}</p>${addonUsageMarkup(info)}${info.description && info.description !== info.purpose ? `<details><summary>Add-on description</summary><p>${esc(info.description)}</p></details>` : ''}</section>`;
}
function filteredAddons(addons, query='', role='all', review='all'){
  const q = query.trim().toLowerCase();
  return addons.filter(a => {
    const text = [a.addon_id, a.name, a.purpose, a.summary, a.role_label, ...(a.required_by || []).map(d => `${d.addon_id} ${d.name}`)].join(' ').toLowerCase();
    if (!text.includes(q) || (role !== 'all' && a.role !== role)) return false;
    return review === 'all' || (review === 'disabled' && a.enabled === false)
      || (review === 'service' && a.has_service === true)
      || (review === 'dependency' && (a.required_by || []).length > 0)
      || a.cleanup?.code === review;
  }).sort((a,b) => String(a.name || a.addon_id).localeCompare(String(b.name || b.addon_id)));
}
function addonRowMarkup(a){
  const status = a.installed !== true ? 'Installation unconfirmed' : a.enabled === true ? 'Enabled' : a.enabled === false ? 'Disabled' : 'Enabled state unknown';
  return `<tr><td class="addon-name"><b>${esc(a.name || a.addon_id)}</b><code>${esc(a.addon_id)}</code><span class="muted">${esc(a.version || 'Version unknown')} · ${status}</span><span>${esc(a.role_label || 'Type unconfirmed')}</span>${a.has_service === true ? '<span class="addon-service">Background service when enabled</span>' : ''}</td><td class="addon-purpose" data-label="What it does">${esc(a.purpose || a.summary || 'Description unavailable; open the add-on for details.')}</td><td data-label="Declared dependents">${addonUsageMarkup(a)}</td><td class="addon-cleanup" data-label="Removal guidance"><b>${esc(a.cleanup?.label || 'Check usage')}</b><p class="muted">${esc(a.cleanup?.detail || 'Check other profiles, widgets and player settings before removing.')}</p></td><td><a class="action" href="#/addon/${esc(encodeURIComponent(a.addon_id))}">Open</a></td></tr>`;
}
async function allAddons(){
  const addons = await api("/api/addons");
  const system = addons.filter(a => a.role === 'system').length;
  out(`${pageHead("All add-ons", `${addons.length} entries, including ${system} Kodi components. Libraries and resource packs support other add-ons.`)}
    <div class="panel addon-guide"><p><b>Review disabled</b> highlights possible cleanup candidates. <b>Check dependents</b> means another installed add-on declares a dependency. Keep Kodi components and your active skin.</p><details><summary>Before uninstalling</summary><p class="muted">This view checks the current profile. Installed files may be shared across profiles. Undeclared uses in widgets, skin actions and player settings are not detected. Removing disabled add-ons mainly frees storage; enabled background services may also use RAM.</p></details></div>
    <div class="panel"><div class="addon-filters"><label>Search<input id="filter" type="search" placeholder="Name, purpose or dependent"></label><label>Type<select id="addonRole"><option value="all">All types</option>${[['system','Kodi components'],['skin','Skins'],['library','Shared libraries'],['repository','Update repositories'],['resource','Resource packs'],['video','Video add-ons'],['service','Services'],['other','Other add-ons']].map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select></label><label>Review<select id="addonReview"><option value="all">All entries</option><option value="review_disabled">Review disabled</option><option value="disabled">All disabled</option><option value="service">Background services</option><option value="dependency">Declared dependents</option><option value="config_only">Saved config only</option></select></label></div><p id="addonMatches" class="muted" role="status"></p><div id="addonList" class="table-scroll" tabindex="0" role="region" aria-label="Add-on descriptions and dependencies"></div></div>`);
  const render = () => {
    const rows = filteredAddons(addons, $("#filter").value, $("#addonRole").value, $("#addonReview").value);
    $("#addonMatches").textContent = `${rows.length} of ${addons.length} entries`;
    $("#addonList").innerHTML = `<table class="addon-table addon-catalog"><thead><tr><th scope="col">Add-on</th><th scope="col">What it does</th><th scope="col">Declared dependents</th><th scope="col">Removal guidance</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows.map(addonRowMarkup).join('') || '<tr><td colspan="5">No add-ons match these filters.</td></tr>'}</tbody></table>`;
  };
  $("#filter").oninput = render;
  $("#addonRole").onchange = render;
  $("#addonReview").onchange = render;
  render();
}
async function installAddonView(){
  out(`${pageHead("Install an add-on", "Opens Kodi’s own Install from zip file dialog on the TV. Choose the ZIP there with the remote.")}<div class="panel"><p>Kodi has no way to install a ZIP from a path, so this opens the dialog on the TV, and Kodi applies its normal unknown-sources check. Nothing opens while something is playing.</p><button class="primary" id="installZip" ${writeAttrs()}>Open “Install from zip file” on the TV</button><p id="installOut" role="status"></p></div>`);
  $("#installZip").onclick = withErrors(async () => {
    const r = await api("/api/addons/install", {});
    $("#installOut").textContent = r.opened ? r.next_step : (r.error || "Kodi did not open the dialog.");
  });
}
function isLoopbackHost(host){ return /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|::1)$/i.test(String(host || "")); }
async function serviceSetup(){
  const status = await api("/api/status");
  const onOff = v => v === true ? "On" : v === false ? "Off" : "Unknown";
  const loopback = isLoopbackHost(location.hostname);
  const masked = dashboardLink(location.origin, "••••••••");
  const share = !status.allow_lan
    ? `<p>Turn on <b>Allow LAN access</b> in Kodi Manager’s settings on the TV first. It applies straight away.</p>`
    : loopback
      ? `<p>This browser reaches Kodi Manager through ${esc(location.hostname)}, which other devices can’t use. On the TV, open <b>Add-ons → Video add-ons → Kodi Manager → Open the dashboard on another device</b> to see the network address.</p>`
      : `<p>This link opens the dashboard and signs in straight away. It contains your access token, so only open it on your own devices.</p><p><code class="token-link">${esc(masked)}</code></p><button type="button" class="action" id="copyLink">Copy sign-in link</button>`;
  out(`${pageHead("Connection", "How this browser reaches Kodi Manager, and the access token it uses.")}<div class="panel"><p>Kodi Manager runs inside Kodi. Change its settings on the TV under <b>Add-ons → My add-ons → Services → Kodi Manager → Configure</b>. Changes apply straight away.</p><dl class="facts"><dt>Allow LAN access</dt><dd>${onOff(status.allow_lan)}</dd><dt>Enable writes</dt><dd>${onOff(status.write_enabled)}</dd><dt>Dashboard address</dt><dd>${esc(location.origin)}</dd><dt>Service version</dt><dd>${esc(status.service_version || "unknown")}</dd></dl></div>
  <div class="panel"><h3>Open the dashboard on another device</h3>${share}</div>
  <div class="panel"><h3>Access token</h3><p>Token saved in this browser: ${badge(!!session.token)}. The token is stored on the TV in the active Kodi profile’s <code>addon_data/service.kodi.addonadmin/settings.xml</code>. Keep it private.</p><button type="button" class="action" id="replaceToken">Use a different token</button><button type="button" class="action" id="forgetToken">Forget token in this browser</button></div>`);
  if ($("#copyLink")) $("#copyLink").onclick = withErrors(() => copyWithNotice(dashboardLink(location.origin, session.token), "Sign-in link"));
  $("#replaceToken").onclick = () => showTokenForm();
  $("#forgetToken").onclick = withErrors(async () => {
    if (!(await confirmDialog({title:"Forget the token?", message:"This browser will ask for the token again next time.", confirmLabel:"Forget token"}))) return;
    storeToken("");
    showTokenForm();
  });
}
async function diagnostics(){
  out(`${pageHead("Diagnostics", "Detailed reports for troubleshooting. They are redacted, but still describe your setup: share them only where you trust the reader.")}<div class="panel"><button class="action" id="diagPaths">Path diagnostics</button><button class="action" id="diagRaw">Raw add-on detection</button><button class="action" id="diagPipe">Playback setup debug</button><button class="action" id="diagCopy">Copy full report</button><pre id="diag"></pre></div>`);
  const report = {};
  const show = value => { $("#diag").textContent = JSON.stringify(redactObj(value), null, 2); };
  $("#diagPaths").onclick = withErrors(async () => { report.paths = await api("/api/debug/paths"); show(report.paths); });
  $("#diagRaw").onclick = withErrors(async () => { report.raw = await api("/api/debug/stack-raw"); show(report.raw); });
  $("#diagPipe").onclick = withErrors(async () => { report.pipeline = await api("/api/pipeline/debug"); show(report.pipeline); });
  $("#diagCopy").onclick = withErrors(async () => {
    report.status = await api("/api/status");
    report.paths = report.paths || await api("/api/debug/paths");
    report.raw = report.raw || await api("/api/debug/stack-raw");
    report.pipeline = report.pipeline || await api("/api/pipeline/debug");
    show(report);
    await copyWithNotice(JSON.stringify(redactObj(report), null, 2), "Debug report");
  });
}

async function fixesView(){
  const [status, fixes] = await Promise.all([api('/api/status'), api('/api/fixes')]);
  state.writeEnabled = appCanWrite(status);
  if (fixes.bundled === false) {
    out(`${pageHead("Custom fixes", "Checks your custom playback, navigation and skin fixes against their tested copies.")}<div class="panel"><p>${esc(fixes.detail)}</p><p>Version-checked repair manifests can be supplied separately. Kodi Manager manages your existing setup without installing third-party patch payloads.</p></div>`);
    return;
  }
  const labels = {ok:'Protected', changed:'Files replaced', version_changed:'Update needs review'};
  out(`${pageHead("Custom fixes", "Checks your custom playback, navigation and skin fixes against their tested copies.")}<div class="panel"><p>${esc(fixes.detail)}</p>
    <table class="addon-table"><thead><tr><th>Fix</th><th>Status</th><th>Add-on version</th></tr></thead><tbody>${(fixes.groups || []).map(g=>`<tr><td>${esc(g.label)}</td><td>${dashboardPill(g.status==='ok'?'ok':'warn', labels[g.status] || g.status, g.status==='ok'?'check':'help')}</td><td>${esc(g.installed_version || 'Missing')} · tested ${esc(g.tested_version)}</td></tr>`).join('')}</tbody></table>
    ${fixes.healthy?'<p>All custom fixes are intact.</p>':'<p>Known older files can be restored from the verified copy. A new version or an unrecognised change needs review.</p>'}
    <button id="restoreFixes" class="primary" ${!state.writeEnabled ? writeAttrs() : fixes.repairable ? '' : 'disabled title="Nothing here can be restored automatically."'}>Restore tested fixes</button><p class="muted">Creates a backup before restoring. Stop playback first; restart Kodi afterwards.</p><p id="fixResult" role="status"></p></div>`);
  $('#restoreFixes').onclick = withErrors(async () => {
    if (!(await confirmDialog({title:"Restore tested fixes?", message:"Changed add-on files are overwritten with their tested copies. A backup is created first. Stop playback first; restart Kodi afterwards.", detail:(fixes.groups || []).filter(g => g.status !== "ok").map(g => g.label).join("\n"), confirmLabel:"Restore fixes"}))) return;
    const result = await api('/api/fixes/repair', {});
    $('#fixResult').textContent = result.detail;
  });
}
boot().catch(e => out(`<div class="panel bad" role="alert"><h2>Couldn’t start</h2><p>${esc(e.message)}</p></div>`));
