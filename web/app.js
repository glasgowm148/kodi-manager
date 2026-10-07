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
function navGroups(status){
  const stack = status?.stack || {};
  const known = key => !status || !!stack[key]?.addon_id;
  const apps = [["Skin","#/skin","skin"],["TMDb Helper","#/tmdbhelper","tmdbhelper"],["Fen Light","#/fenlight","fenlight"],["Fen","#/fen","fen"],["POV","#/pov","pov"],["CocoScrapers","#/cocoscrapers","cocoscrapers"]]
    .filter(([, , key]) => known(key)).map(([label, route]) => [label, route]);
  if (!status || stack.trakt?.addon_id || stack.trakt_integration?.status === "configured") apps.push(["Trakt","#/trakt"]);
  const manage = [...(homeLayoutSupported(status) ? [["Home layout","#/widgets"]] : []), ["Accounts","#/accounts"], ["All add-ons","#/addons"], ["Install add-on","#/install"], ["Backups","#/backups"], ["Cached rows","#/cached-rows"]];
  return [
    {group:"Overview",items:[["Dashboard","#/dashboard"],["Health","#/health"],["Custom fixes","#/fixes"],["Playback setup","#/pipeline"],["Playback test","#/playback-test"]]},
    ...(apps.length ? [{group:"Detected add-ons",items:apps}] : []),
    {group:"Manage",items:manage},
    {group:"System",items:[["Kodi log","#/kodi-logs"],["Service log","#/logs"],["Setup","#/setup"],["Diagnostics","#/diagnostics"]]}
  ];
}
function navButton(label, route){ return `<button type="button" data-route="${esc(route)}">${esc(label)}</button>`; }
function setNav(items){
  const key = JSON.stringify(items);
  if (key === state.navKey) return highlightNav();
  state.navKey = key;
  $("#nav").innerHTML = items.map(item => {
    if (Array.isArray(item)) return navButton(item[0], item[1]);
    return `<div class="nav-section"><div class="nav-title">${esc(item.group)}</div>${item.items.map(([label, route]) => navButton(label, route)).join("")}</div>`;
  }).join("");
  highlightNav();
}
function highlightNav(){
  const current = (location.hash || "#/dashboard").split("?")[0];
  document.querySelectorAll("#nav button").forEach(b => {
    const active = b.dataset.route === current;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
}
function toggleNav(open){
  const body = document.body;
  const next = typeof open === "boolean" ? open : !body.classList.contains("nav-open");
  body.classList.toggle("nav-open", next);
  $("#navToggle")?.setAttribute("aria-expanded", String(next));
}
function applyStatus(status){
  state.status = status;
  state.writeEnabled = appCanWrite(status);
  setNav(navGroups(status));
  updateDirtyBar();
  $("#top").innerHTML = `Kodi ${esc(status["Kodi version"] || "")} ${dashboardFlag(status.write_enabled, "Writes on", "Read only")}`;
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
async function saveDirty(){
  const changes = Object.entries(state.dirtyChanges).map(([id,item]) => ({id,value:item.value,source:item.source}));
  const addonId = state.dirtyAddon;
  if (!addonId || !changes.length || !state.writeEnabled) return;
  const preview = changes.map(ch => {
    const el = [...document.querySelectorAll("[data-setting]")].find(x => x.dataset.setting === ch.id);
    return changePreview(ch.id, el?.dataset.original ?? "", ch.value, el?.type === "password" || appSecretSetting({id:ch.id}));
  }).join("\n\n");
  if (!(await confirmDialog({title:`Save ${changes.length} change${changes.length === 1 ? "" : "s"}?`, message:"A backup of this add-on’s settings is created first.", detail:preview, confirmLabel:"Save"}))) return;
  const r = await apiMethod("PATCH", `/api/addons/${encodeURIComponent(addonId)}/settings`, {changes});
  clearDirty();
  toast(`Saved ${r.changed_count} change${r.changed_count === 1 ? "" : "s"}. Backup ${r.backup_id}.`, "ok", r.backup_id ? {actions:[{label:"Undo", run:() => restoreAddonBackup(addonId, r.backup_id, {confirmFirst:false})}]} : {});
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
    const button = event.target.closest("button[data-route]");
    if (!button) return;
    toggleNav(false);
    location.hash = button.dataset.route;
  });
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
  dashboard: () => dashboard(),
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
  state.dashboardController?.abort();
  state.dashboardRequest = (state.dashboardRequest || 0) + 1;
  state.dashboardLoading = false;
  state.currentHash = location.hash;
  try {
    highlightNav();
    const r = location.hash.replace(/^#\/?/, "") || "dashboard";
    if (r.startsWith("search")) await searchView(new URLSearchParams(r.split("?")[1] || "").get("q") || "");
    else if (r.startsWith("addon/")) await addonSettings(decodeURIComponent(r.slice(6)));
    else await (ROUTES[r] || ROUTES.dashboard)();
    focusHeading();
  } catch(e) {
    if (e?.code === "unauthorized") return;
    out(`<div class="panel bad" role="alert"><h2>Couldn’t load this page</h2><p>${esc(e.message)}</p></div>`);
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
    settings: '<path d="M4 7h16M4 17h16M8 4v6m8 4v6"/>'
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
function dashboardVisible(){ return !location.hash || location.hash === "#/dashboard" || location.hash === "#dashboard"; }
function dashboardFixNotice(fixes){
  if (!fixes || typeof fixes.healthy !== 'boolean') return '';
  const label = fixes.healthy ? 'Custom fixes intact' : 'Custom fixes need attention';
  return `<div class="dash-table-panel dash-fix-notice">${dashboardPill(fixes.healthy?'ok':'warn',label,fixes.healthy?'check':'alert')} <a class="dash-settings" href="#/fixes">Check custom fixes</a></div>`;
}
async function dashboard(refresh=false){
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
  } else out('<div class="dashboard dash-loading" role="status"><h2>Your Kodi setup</h2><p>Checking your Kodi setup…</p></div>');
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
      <div class="dash-heading"><div><p class="dash-eyebrow">Overview</p><h2>Your Kodi setup</h2><p class="dash-subtitle">A clear view of your add-ons and their current state.</p></div><button class="dash-refresh" id="dashboardRefresh">${dashboardIcon("refresh")}<span>Refresh status</span></button></div>
      <div class="dash-metrics" aria-label="Setup summary">
        <div><span class="dash-metric-label">Installed add-ons</span><strong>${installed.length}</strong><span class="dash-metric-detail">${installed.filter(a=>a.enabled === true).length} confirmed enabled</span></div>
        <div><span class="dash-metric-label">Core components</span><strong>${detected}<small> detected</small></strong><span class="dash-metric-detail">Skin, players & integrations</span></div>
        <div><span class="dash-metric-label">Checkpoints</span><strong>${backups ? (backups.backups || []).length : "—"}</strong><span class="dash-metric-detail">${backups ? "Saved config backups" : "Backup status unavailable"}</span></div>
        <div><span class="dash-metric-label">Changes</span><strong class="dash-metric-mode">${dashboardIcon(s.write_enabled === true ? "settings" : s.write_enabled === false ? "pause" : "help")}${writeLabel}</strong><span class="dash-metric-detail">${s.write_enabled === true ? "Backup before every write" : s.write_enabled === false ? "Turn on “Enable writes” to edit" : "Write permission unconfirmed"}</span></div>
      </div>
      ${warnings.length ? `<details class="dash-notices" ${noticesOpen ? "open" : ""}><summary>${dashboardIcon("alert")}<span>${warnings.length} setup notice${warnings.length === 1 ? "" : "s"}</span><span class="dash-notice-hint">View details</span></summary><ul>${warnings.map(w=>`<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
      ${dashboardFixNotice(fixes)}
      <div class="dash-table-panel"><div class="dash-table-heading"><div><h3>Core components</h3><span id="dashboardMatches" class="dash-detail" aria-live="polite"></span></div><div class="dash-filters"><label class="dash-search">${dashboardIcon("search")}<span class="sr-only">Filter components</span><input id="dashboardFilter" type="search" placeholder="Filter components…" value="${esc(state.dashboardFilter || "")}"></label><label><span class="sr-only">Filter by state</span><select id="dashboardState"><option value="all">All states</option><option value="installed">Installed</option><option value="config">Config only</option><option value="missing">Not found</option><option value="unknown">Unknown</option></select></label></div></div>
      <div class="dash-table-scroll" tabindex="0" role="region" aria-label="Core component statuses"><table class="dash-table"><caption class="sr-only">Installation, enabled and saved configuration states from the most recent Kodi check.</caption><thead><tr><th scope="col">Component</th><th scope="col">Version</th><th scope="col">Status</th><th scope="col">Installation</th><th scope="col">Enabled</th><th scope="col">Saved config</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody id="dashboardRows">${rows.map(dashboardRow).join("")}<tr id="dashboardEmpty" hidden><td colspan="7" class="dash-empty">No components match your filters.</td></tr></tbody></table></div>
      <div class="dash-table-footer"><span id="dashboardRefreshNote" role="status">Checked ${esc(checkedAt)} · Refreshes every 30 seconds</span><a href="#/addons">View all add-ons ${dashboardIcon("arrow")}</a></div></div>
      <p class="dash-legend">${dashboardIcon("help")}<span><b>Unknown</b> means Kodi hasn’t confirmed that state. <b>Config only</b> means saved settings were found, but installation isn’t confirmed. Player rows show whether the add-on is enabled.</span></p>
    </div>`);
    $("#dashboardState").value = state.dashboardState || "all";
    filterDashboard();
    $("#dashboardFilter").oninput = filterDashboard;
    $("#dashboardState").onchange = filterDashboard;
    $("#dashboardRefresh").onclick = () => dashboard(true);
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
    } else out(`<div class="dashboard dash-error" role="alert"><h2>Couldn’t check Kodi</h2><p>${esc(message)}</p><button class="dash-refresh" id="dashboardRetry">${dashboardIcon("refresh")}Retry</button></div>`);
    if ($("#dashboardRetry")) $("#dashboardRetry").onclick = () => dashboard();
  } finally {
    clearTimeout(timeout);
    if (request === state.dashboardRequest) {
      state.dashboardLoading = false;
      if ($("#dashboardRefresh")) $("#dashboardRefresh").disabled = false;
      if (dashboardVisible()) state.dashboardTimer = setInterval(() => { if (!document.hidden) dashboard(!!$("#dashboardRefresh")); }, 30000);
    }
  }
}
async function healthView(){
  const h = await api("/api/health");
  const tone = h.status === "ok" ? "ok" : h.status === "error" ? "bad" : "warn";
  out(`<div class="panel"><h2>Health</h2><p class="${tone}">Overall: ${esc(h.status)}</p><div class="stats">${Object.entries(h.stats || {}).map(([k,v])=>card(k.replace(/_/g," "), `<p class="big">${esc(v)}</p>`)).join("")}</div></div>
  <div class="panel"><h3>Checks</h3><div class="table">${(h.checks||[]).map(c=>`<div class="row"><span><b>${esc(c.label)}</b><br><span class="muted">${esc(c.detail)}</span></span><span class="${c.status === "ok" ? "ok" : c.status === "error" ? "bad" : "warn"}">${esc(c.status)}</span></div>`).join("")}</div></div>
  <div class="panel"><h3>Recent log problems</h3><h4>Errors</h4><pre>${esc(logBlock(h.recent_errors))}</pre><h4>Warnings</h4><pre>${esc(logBlock(h.recent_warnings))}</pre></div>`);
}
function logBlock(lines){ return (lines || []).slice().reverse().join("\n") || "None"; }
function runGlobalSearch(){
  const q = ($("#globalSearch").value || "").trim();
  if (!q) return;
  location.hash = "#/search?q=" + encodeURIComponent(q);
}
async function searchView(query){
  $("#globalSearch").value = query;
  if (!query) return out(`<div class="panel"><h2>Search settings</h2><p>Type in the search box at the top of the page.</p></div>`);
  const data = await api(`/api/search/config?q=${encodeURIComponent(query)}`);
  out(`<div class="panel"><h2>Settings matching “${esc(query)}”</h2><p>${esc(data.count ?? 0)} result(s)</p>${(data.results || []).map(r => `<div class="card"><h3>${esc(r.addon_name || r.addon_id)} <span class="muted">${esc(r.version || "")}</span></h3><p><b title="${esc(r.id)}">${esc(friendlyName(r.id, r.label))}</b><br><span class="muted">${esc(r.description || describeSetting(r.id, r.label))}</span></p><p>${esc(r.masked ? "••••••••" : r.value)}</p><p>${r.editable ? "<span class='ok'>editable</span>" : "<span class='muted'>read-only</span>"} ${r.warning ? `<span class="warn">${esc(r.warning)}</span>` : ""}</p><a class="action" href="#/addon/${esc(encodeURIComponent(r.addon_id))}">Open add-on</a></div>`).join("")}</div>`);
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
  out(`${warnings}<div class="panel"><h2>Playback setup</h2><p>Primary player: <b>${esc(primary.name || primary.addon_id || "Unknown")}</b> · ${esc(primary.selection || "unknown")} · ${esc(primary.confidence || "unknown")} confidence</p><div class="grid">${p.nodes.map(nodeCard).join("")}</div><button class="action" id="rescanPipe">Rescan</button><button class="action" id="backupPipe" ${writeAttrs()}>Back up playback settings</button><button class="action" id="copyPipe">Copy debug report</button></div>
  <div class="panel"><h3>Current routing</h3><table class="addon-table"><thead><tr><th>Stage</th><th>Detected component</th><th>Config source</th><th>Status</th><th>Editable</th></tr></thead><tbody>
    ${Object.entries(p.routing).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v.value)}<br><span class="muted">${esc(v.addon_id)}</span></td><td>${esc(v.source)} ${esc(v.setting_id || "")}</td><td>${esc(v.confidence)}</td><td>${badge(v.editable)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="panel"><h3>Connections and evidence</h3><div class="grid">${p.edges.map(e=>card(`${p.nodes.find(n=>n.id===e.from)?.label || e.from}${(e.evidence || []).length ? " → " : " / "}${p.nodes.find(n=>n.id===e.to)?.label || e.to}`, `<p>${esc(e.label)} · ${esc(e.relationship || ((e.evidence || []).length ? "evidence found" : "unconfirmed"))}</p><p class="muted">${pipelineEvidence(e.evidence)}</p>`)).join("")}</div></div>
  <div class="panel"><h3>Scraper relationship</h3><p>${esc(scraper.name || "Unknown")} · ${esc(scraper.relationship || "unknown")} · ${scraper.used === true ? "linked to selected player" : "usage unconfirmed"}</p><p class="muted">${pipelineEvidence(scraper.evidence)}</p><h4>Available modules</h4>${(p.summary.available_scraper_modules || []).map(a=>`<p>${esc(a.name || a.addon_id)} · installed: ${badge(a.installed)} · enabled: ${badge(a.enabled)}</p>`).join("") || "<p class='muted'>No external scraper modules detected.</p>"}<p class="muted">Module installation and enablement do not establish which player uses it.</p></div>
  <div class="panel"><h3>Account integrations</h3><div class="grid">${["trakt","torbox","tmdb"].map(k=>card(k, integrationSummary((p.summary.integrations || p.summary.accounts || {})[k]))).join("")}</div><a href="#/accounts">Edit account settings</a></div>
  <div class="panel"><h3>Playback controls</h3><p class="muted">Only routing and provider-link settings are shown here. Account keys are on the Accounts page.</p>${state.writeEnabled ? "" : `<p class='warn'>${esc(WRITE_HINT)}</p>`}${p.settings_groups.map((g,i)=>`<div class="group"><h4>${esc(g.label)}</h4>${settingRows(g.settings, `pipe-${i}`)}</div>`).join("") || "<p class='muted'>No safe playback controls detected. Use the add-on’s own settings for player-file routing.</p>"}</div>
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
async function accountsView(){
  const status = await api("/api/status");
  state.writeEnabled = appCanWrite(status);
  const d = await api("/api/accounts");
  out(`<div class="panel"><h2>Accounts</h2><p>Account credentials use password fields. Saving creates a backup first.</p>${state.writeEnabled ? "" : `<p class='warn'>${esc(WRITE_HINT)}</p>`}<div class="grid">${Object.entries(d.summary || {}).map(([k,v])=>card(k, integrationSummary(v))).join("")}</div><button class="primary" id="saveAccounts" ${writeAttrs()}>Save account changes</button></div>${(d.groups||[]).map((g,i)=>`<div class="group"><h3>${esc(g.label)}</h3>${filterTabs(`acct-${i}`, g.settings)}<div class="settings-grid">${g.settings.map(s=>`<div data-filter-scope="acct-${i}" data-set="${settingIsSet(s) ? "true" : "false"}" data-readonly="${isReadOnlySetting(s) ? "true" : "false"}">${accountField(s)}</div>`).join("")}</div></div>`).join("")}`);
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
  out(`<div class="panel"><h2>Trakt integration</h2><p>Player and metadata add-ons can store their own Trakt authorization.</p>${integrationSummary(trakt)}<a href="#/accounts">Edit account settings</a></div><div class="panel"><h3>Optional standalone scrobbler</h3><p>${standalone.installed === true ? `script.trakt is installed · enabled: ${badge(standalone.enabled)}` : "script.trakt is absent. Add-on account integration can operate independently."}</p>${standalone.installed === true || standalone.config_present === true ? '<a href="#/addon/script.trakt">Open standalone scrobbler settings</a>' : ""}</div><div class="panel"><h3>TorBox integration</h3>${integrationSummary(accounts.summary?.torbox)}<a href="#/accounts">Edit TorBox settings</a></div>`);
}
async function pickAddon(keys){ const s=await api("/api/stack"); for (const k of keys){ const aid=s[k]?.addon_id; if(aid) return addonSettings(aid); } out("<div class='panel warn'><h2>Not found</h2><p>No matching add-on was found on this Kodi.</p></div>"); }
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
  toast(restoreSummary(result, undo), "ok", undo.length ? {actions:[{label:"Undo restore", run:() => undoRestore(undo)}]} : {});
}
async function undoRestore(targets){
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
async function backups(){
  const [t, addons] = await Promise.all([api("/api/backups/timeline"), api("/api/addons").catch(() => [])]);
  const items = t.items || [];
  const withConfig = (addons || []).filter(a => a.config_present === true).sort((a,b) => String(a.name || a.addon_id).localeCompare(String(b.name || b.addon_id)));
  out(`<div class="panel"><h2>Backups</h2><p>A checkpoint saves the settings folders of your skin, players and helpers together. Restoring backs up the current settings first, so every restore can be undone.</p><button class="primary" id="stackBackup" ${writeAttrs()}>Create checkpoint</button><div class="timeline">${items.map(x=>`<div class="card"><h3>${esc(x.backup_id || x.name || "")}</h3><p><span class="badge">${esc(x.kind || "stack")}</span> <span class="badge">${esc(x.component_count || 0)} included</span> <span class="badge">${esc(x.skipped_count || 0)} skipped</span></p><p class="muted">Kodi ${esc(x["Kodi version"] || "")}</p>${x.kind === "pipeline" ? `<button class="action" disabled title="Playback-setting backups are restored by hand: see docs/recovery.md">Restore</button>` : `<button class="action" data-restore="${esc(x.backup_id || x.name || "")}" ${writeAttrs()}>Restore</button>`}</div>`).join("") || "<p>No checkpoints yet.</p>"}</div></div>
  <div class="panel"><h3>Add-on backups</h3><p>Kodi Manager backs up an add-on’s settings before every change it makes.</p><label for="backupAddon">Add-on<select id="backupAddon"><option value="">Choose an add-on…</option>${withConfig.map(a => `<option value="${esc(a.addon_id)}">${esc(a.name || a.addon_id)}</option>`).join("")}</select></label><div id="addonBackups"></div></div>`);
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
async function cachedRowsView(){
  const [rowData, cache] = await Promise.all([api("/api/widget-cache/rows"), api("/api/widget-cache").catch(() => null)]);
  const rows = Array.isArray(rowData) ? rowData : [];
  const entries = new Map((cache?.entries || []).map(entry => [entry.source, entry]));
  out(`<div class="panel"><h2>Cached rows</h2><p>Optional. Kodi Manager can keep a local copy of an add-on folder so a home-screen widget shows it straight away instead of waiting for the add-on. Point a widget at a row’s cached URL, or choose it in your skin’s widget picker under <b>Video add-ons → Kodi Manager → Cached rows</b>.</p><div class="toolbar"><button type="button" class="action" id="cacheRefresh">Refresh all now</button><span class="muted">${cache ? `${esc(cache.queued ?? 0)} queued for refresh` : "Cache status unavailable"}</span></div>
  <table class="addon-table cached-rows"><thead><tr><th scope="col">Row</th><th scope="col">Status</th><th scope="col">Items</th><th scope="col">Updated</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows.map((row, i) => cachedRowMarkup(row, entries.get(row.source), i)).join("") || '<tr><td colspan="5" class="muted">No cached rows yet.</td></tr>'}</tbody></table></div>
  <div class="panel"><h3>Add a row</h3><p>Paste an add-on folder path (it starts with <code>plugin://</code>). In Kodi you can also open any video add-on folder and choose <b>Add to Kodi Manager cached rows</b> from its context menu.</p>${state.writeEnabled ? "" : `<p class="warn">${esc(WRITE_HINT)}</p>`}<form id="cacheAdd" class="grid"><label>Name<input id="cacheLabel" required maxlength="80"></label><label>Add-on folder path<input id="cacheSource" required placeholder="plugin://plugin.video.example/?mode=…" spellcheck="false"></label><label>Pages to cache<input id="cachePages" type="number" min="1" max="50" placeholder="Automatic"></label><label class="check-label"><span><input id="cacheHideWatched" type="checkbox"> Hide watched items</span></label><div><button class="primary" type="submit" ${writeAttrs()}>Add row</button></div></form></div>`);
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
  out(`<div class="panel"><h2>Playback test</h2><p>A safe dry run. Checks routing, the detected player, the scraper module and Kodi’s current player state. It never starts playback.</p><div class="grid"><label>Target player<select id="testPlayer">${players.map(p=>`<option value="${esc(p.addon_id)}">${esc(p.name || p.addon_id)}</option>`).join("")}</select></label><label>Optional plugin URL<input id="testUrl" placeholder="plugin://..."></label></div><button class="primary" id="runPlaybackTest">Run test</button><div id="playbackSteps"></div><pre id="playbackOut" hidden></pre></div>`);
  $("#runPlaybackTest").onclick = withErrors(async () => {
    const r = await api("/api/playback/test", {target_player_addon_id:$("#testPlayer").value, plugin_url:$("#testUrl").value});
    $("#playbackSteps").innerHTML = `<ul class="steps">${(r.steps || []).map(step => `<li class="${step.ok ? "ok" : "bad"}">${step.ok ? "✓" : "✗"} ${esc(step.step)} <span class="muted">${esc(step.detail ?? "")}</span></li>`).join("")}</ul>`;
    $("#playbackOut").hidden = false;
    $("#playbackOut").textContent = JSON.stringify(r, null, 2);
  });
}
function logLevel(line){ const s=String(line).toLowerCase(); if (s.includes(" error") || s.includes("error:") || s.includes(" exception") || s.includes("traceback")) return "error"; if (s.includes(" warning") || s.includes("warn:") || s.includes("deprecated")) return "warn"; return "info"; }
function renderLogs(title, lines){
  out(`<div class="panel"><h2>${esc(title)}</h2><div class="tabs" role="group" aria-label="Filter log lines">${[["all","All"],["info","Info"],["warn","Warnings"],["error","Errors"]].map(([level,label]) => `<button type="button" data-level="${level}" aria-pressed="false">${label}</button>`).join("")}</div><div id="logBox" class="log-view"></div></div>`);
  const newest = [...(lines || [])].reverse();
  const draw = level => {
    document.querySelectorAll("[data-level]").forEach(b => { const on = b.dataset.level === level; b.classList.toggle("active", on); b.setAttribute("aria-pressed", String(on)); });
    $("#logBox").innerHTML = newest.filter(l => level === "all" || logLevel(l) === level).map(l => `<div class="log-line log-${logLevel(l)}">${esc(l)}</div>`).join("");
  };
  document.querySelectorAll("[data-level]").forEach(b => b.onclick = () => draw(b.dataset.level));
  draw("all");
}
async function logs(){ const l=await api("/api/logs"); renderLogs("Service log", l.lines || []); }
async function kodiLogs(){ const l=await api("/api/kodi/logs"); renderLogs("Kodi log", l.lines || []); }
async function allAddons(){
  const addons = await api("/api/addons");
  out(`<div class="panel"><h2>All add-ons</h2><label for="filter" class="sr-only">Filter add-ons</label><input id="filter" type="search" placeholder="Filter add-ons"><div id="addonList"></div></div>`);
  const render = () => {
    const q = ($("#filter").value || "").toLowerCase();
    $("#addonList").innerHTML = `<table class="addon-table"><thead><tr><th>Name</th><th>ID</th><th>Version</th><th>Enabled</th><th>Config</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>${addons.filter(a => `${a.addon_id} ${a.name}`.toLowerCase().includes(q)).map(a => `<tr><td>${esc(a.name || a.addon_id)}</td><td>${esc(a.addon_id)}</td><td>${esc(a.version || "")}</td><td>${badge(a.enabled)}</td><td>${badge(a.config_present)}</td><td><a class="action" href="#/addon/${esc(encodeURIComponent(a.addon_id))}">Open</a></td></tr>`).join("")}</tbody></table>`;
  };
  $("#filter").oninput = render; render();
}
async function installAddonView(){
  out(`<div class="panel"><h2>Install add-on or repository</h2><p>Kodi has no API to install a ZIP from a path, so this opens Kodi’s own <b>Install from zip file</b> dialog on the TV. Choose the ZIP there with the remote; Kodi applies its normal unknown-sources check. Nothing opens while something is playing.</p>${state.writeEnabled ? "" : `<p class="warn">${esc(WRITE_HINT)}</p>`}<button class="primary" id="installZip" ${writeAttrs()}>Open “Install from zip file” on the TV</button><p id="installOut" role="status"></p></div>`);
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
  out(`<div class="panel"><h2>Setup</h2><p>Kodi Manager runs inside Kodi. Change its settings on the TV under <b>Add-ons → My add-ons → Services → Kodi Manager → Configure</b>. Changes apply straight away.</p><dl class="facts"><dt>Allow LAN access</dt><dd>${onOff(status.allow_lan)}</dd><dt>Enable writes</dt><dd>${onOff(status.write_enabled)}</dd><dt>Dashboard address</dt><dd>${esc(location.origin)}</dd><dt>Service version</dt><dd>${esc(status.service_version || "unknown")}</dd></dl></div>
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
  out(`<div class="panel"><h2>Diagnostics</h2><p>Reports are redacted, but can still describe your setup. Share them only where you trust the reader.</p><button class="action" id="diagPaths">Path diagnostics</button><button class="action" id="diagRaw">Raw add-on detection</button><button class="action" id="diagPipe">Playback setup debug</button><button class="action" id="diagCopy">Copy full report</button><pre id="diag"></pre></div>`);
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
    out(`<div class="panel"><h2>Custom fixes</h2><p>${esc(fixes.detail)}</p><p>Version-checked repair manifests can be supplied separately. Kodi Manager manages your existing setup without installing third-party patch payloads.</p></div>`);
    return;
  }
  const labels = {ok:'Protected', changed:'Files replaced', version_changed:'Update needs review'};
  out(`<div class="panel"><h2>Custom fixes</h2><p>Checks your custom playback, navigation and skin fixes against their tested copies.</p><p>${esc(fixes.detail)}</p>
    <table class="addon-table"><thead><tr><th>Fix</th><th>Status</th><th>Add-on version</th></tr></thead><tbody>${(fixes.groups || []).map(g=>`<tr><td>${esc(g.label)}</td><td>${dashboardPill(g.status==='ok'?'ok':'warn', labels[g.status] || g.status, g.status==='ok'?'check':'help')}</td><td>${esc(g.installed_version || 'Missing')} · tested ${esc(g.tested_version)}</td></tr>`).join('')}</tbody></table>
    ${fixes.healthy?'<p>All custom fixes are intact.</p>':'<p>Known older files can be restored from the verified copy. A new version or an unrecognised change needs review.</p>'}
    <button id="restoreFixes" class="primary" ${!state.writeEnabled ? writeAttrs() : fixes.repairable ? '' : 'disabled title="Nothing here can be restored automatically."'}>Restore tested fixes</button><p class="muted">Creates a backup before restoring. Stop playback first; restart Kodi afterwards.</p><p id="fixResult" role="status"></p></div>`);
  $('#restoreFixes').onclick = withErrors(async () => {
    const result = await api('/api/fixes/repair', {});
    $('#fixResult').textContent = result.detail;
  });
}
boot().catch(e => out(`<div class="panel bad" role="alert"><h2>Couldn’t start</h2><p>${esc(e.message)}</p></div>`));
