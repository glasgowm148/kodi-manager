const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const badge = (v, y="yes", n="no") => `<span class="badge">${v === null || v === undefined ? "unknown" : (v ? y : n)}</span>`;
const card = (t,b) => `<div class="card"><h3>${esc(t)}</h3>${b}</div>`;
const state = {token: localStorage.getItem("bsa_token") || "", setup:{}, writeEnabled:false, dirtyAddon:"", dirtyChanges:{}};

function mode(){ return "service"; }
function consumeUrlToken(){
  const params = new URLSearchParams(location.search);
  let token = params.get("token");
  if (!token && location.hash.startsWith("#token=")) token = decodeURIComponent(location.hash.slice(7));
  if (token) {
    state.token = token;
    localStorage.setItem("bsa_token", token);
    history.replaceState(null, "", location.pathname);
  }
}
async function api(path, body, signal){
  const headers = {"Content-Type":"application/json"};
  if (mode() === "service" && state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(path, {method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined, signal});
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message || "Request failed");
  return json.data;
}
async function apiMethod(method, path, body){
  const headers = {"Content-Type":"application/json"};
  if (mode() === "service" && state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(path, {method, headers, body: body ? JSON.stringify(body) : undefined});
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message || "Request failed");
  return json.data;
}
function out(html){ $("#content").innerHTML = html; }
function navButton(label, route){ return `<button data-route="${route}">${label}</button>`; }
function setNav(items){
  $("#nav").innerHTML = items.map(item => {
    if (Array.isArray(item)) return navButton(item[0], item[1]);
    return `<div class="nav-section"><div class="nav-title">${esc(item.group)}</div>${item.items.map(([label, route]) => navButton(label, route)).join("")}</div>`;
  }).join("");
  $("#nav").querySelectorAll("button").forEach(b => b.onclick = () => location.hash = b.dataset.route);
  highlightNav();
}
function highlightNav(){
  const current = location.hash || "#/dashboard";
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("active", b.dataset.route === current));
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
function updateDirtyBar(){
  const count = Object.keys(state.dirtyChanges).length;
  const label = $("#dirtyStatus"), btn = $("#saveChanges");
  if (!label || !btn) return;
  label.textContent = count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "No unsaved changes";
  btn.disabled = !count || !state.writeEnabled;
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
  if (!state.dirtyAddon || !changes.length) return;
  const preview = changes.map(ch => {
    const el = [...document.querySelectorAll("[data-setting]")].find(x => x.dataset.setting === ch.id);
    return changePreview(ch.id, el?.dataset.original ?? "", ch.value, el?.type === "password" || appSecretSetting({id:ch.id}));
  }).join("\n\n");
  if (!confirm(`Save ${changes.length} change(s)? A backup will be created first.\n\n${preview}`)) return;
  const r = await apiMethod("PATCH", `/api/addons/${encodeURIComponent(state.dirtyAddon)}/settings`, {changes});
  alert(`Saved ${r.changed_count}. Backup ${r.backup_id}.`);
  clearDirty();
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
  return `<div class="tabs" data-scope="${esc(scope)}"><button data-filter="all">All ${c.all}</button><button class="active" data-filter="set">Set ${c.set}</button><button data-filter="unset">Unset ${c.unset}</button><button data-filter="readonly">Read-only ${c.readonly}</button></div>`;
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
      tabs.querySelectorAll("button").forEach(b=>b.classList.remove("active"));
      btn.classList.add("active");
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
async function boot(){
  consumeUrlToken();
  return bootService();
}

async function bootService(){
  if (!state.token) state.token = prompt("Enter Kodi Manager token") || "";
  if (state.token) localStorage.setItem("bsa_token", state.token);
  $("#saveChanges").onclick = () => saveDirty().catch(e => alert(e.message));
  $("#runSearch").onclick = () => runGlobalSearch();
  $("#globalSearch").addEventListener("keydown", e => { if (e.key === "Enter") runGlobalSearch(); });
  setNav([
    {group:"Overview",items:[["Dashboard","#/dashboard"],["Health","#/health"],["Custom fixes","#/fixes"],["Pipeline","#/pipeline"],["Playback Test","#/playback-test"]]},
    {group:"Apps",items:[["Skin / Bingie","#/skin"],["TMDb Helper","#/tmdbhelper"],["Fen Light","#/fenlight"],["Fen","#/fen"],["POV","#/pov"],["CocoScrapers","#/cocoscrapers"],["Trakt Integration","#/trakt"]]},
    {group:"Manage",items:[["Bingie Studio","#/widgets"],["Accounts","#/accounts"],["All Add-ons","#/addons"],["Install Add-on","#/install"],["Backups","#/backups"]]},
    {group:"System",items:[["Kodi Logs","#/kodi-logs"],["Service Logs","#/logs"],["Setup","#/setup"],["Diagnostics","#/diagnostics"]]}
  ]);
  $("#top").textContent = window.KODI_DESKTOP_READONLY ? "Desktop · read only" : "Connected to service";
  if (window.KODI_DESKTOP_READONLY) {
    ["#/health", "#/playback-test", "#/install", "#/backups", "#/kodi-logs", "#/logs", "#/setup", "#/diagnostics"].forEach(path => document.querySelector(`#nav [data-route="${path}"]`)?.remove());
    document.querySelectorAll("#nav .nav-section").forEach(group => { if (!group.querySelector("button")) group.remove(); });
    $("#globalSearch").disabled = true;
    $("#globalSearch").placeholder = "Config search requires Shield service";
    $("#runSearch").disabled = true;
  }
  window.addEventListener("hashchange", route);
  if (!location.hash || location.hash.startsWith("#token=")) location.hash = "#/dashboard";
  await route();
}

async function renderSetup(){
  const status = await api("/api/status");
  out(`<div class="panel"><h2>Service access</h2><p>Kodi Manager runs inside Kodi. Change its network and write permissions under Kodi → Add-ons → My add-ons → Services → Kodi Manager → Configure.</p><p>LAN access: ${status.allow_lan ? "enabled" : "disabled"}. Changes: ${status.write_enabled ? "enabled" : "read only"}.</p><p>The generated bearer token is stored in the active Kodi profile's addon_data/service.kodi.addonadmin/settings.xml. Keep it private.</p><button class="action" id="replaceToken">Use a different token</button></div>`);
  $("#replaceToken").onclick = async()=>{ const token=prompt("Enter Kodi Manager token"); if(token){state.token=token;localStorage.setItem("bsa_token",token);await route();} };
}
function showRaw(obj){ $("#raw").textContent = JSON.stringify(redactObj(obj), null, 2); }
function redactObj(obj, inheritedSecret=false){
  if (Array.isArray(obj)) return obj.map(value=>redactObj(value, inheritedSecret));
  if (!obj || typeof obj !== "object") return obj;
  const secret = inheritedSecret || appSecretSetting({...obj, id:obj.id || obj.setting_id || ""});
  return Object.fromEntries(Object.entries(obj).map(([key,value]) => [key,
    ((secret && /^(value|default|original)$/.test(key)) || /token|password|secret|authorization|api_key/i.test(key)) && value ? "••••••••" : redactObj(value, secret)]));
}
async function route(){
  clearInterval(state.dashboardTimer);
  state.dashboardController?.abort();
  state.dashboardRequest = (state.dashboardRequest || 0) + 1;
  state.dashboardLoading = false;
  try {
    highlightNav();
    const r = location.hash.replace(/^#\/?/, "") || "dashboard";
    if (r === "dashboard") return dashboard();
    if (r === "health") return healthView();
    if (r === "fixes") return fixesView();
    if (r === "pipeline") return pipelineView();
    if (r === "widgets" || r === "widget-studio") return widgetStudioView();
    if (r === "playback-test") return playbackTestView();
    if (r === "accounts") return accountsView();
    if (r.startsWith("search")) return searchView(new URLSearchParams(r.split("?")[1] || "").get("q") || "");
    if (r === "stack") return stack();
    if (r === "addons") return allAddons();
    if (r === "install") return installAddonView();
    if (r.startsWith("addon/")) return addonSettings(decodeURIComponent(r.slice(6)));
    if (r === "skin") return pickAddon(["skin"]);
    if (r === "tmdbhelper") return pickAddon(["tmdbhelper"]);
    if (r === "fenlight") return pickAddon(["fenlight"]);
    if (r === "fen") return pickAddon(["fen"]);
    if (r === "pov") return pickAddon(["pov"]);
    if (r === "cocoscrapers") return pickAddon(["cocoscrapers"]);
    if (r === "trakt") return integrations();
    if (r === "backups") return backups();
    if (r === "logs") return logs();
    if (r === "kodi-logs") return kodiLogs();
    if (r === "setup") return serviceSetup();
    if (r === "diagnostics") return diagnostics();
    return dashboard();
  } catch(e) { out(`<div class="panel bad">${esc(e.message)}</div>`); }
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
  return `<span class="dash-status dash-status--${tone}" title="${esc(title)}">${dashboardIcon(icon)}<span>${esc(label)}</span></span>`;
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
    return `<tr data-component="trakt" data-state="${row.status.kind}" data-search="${esc(`trakt ${providers}`.toLowerCase())}"><th scope="row"><div class="dash-identity"><span class="dash-avatar dash-avatar--trakt">${dashboardIcon("history")}</span><span><span class="dash-name">Trakt integration</span><span class="dash-detail">${esc(providers || "Stored account settings")} · unverified</span></span></div></th><td>—</td><td>${dashboardPill("info", credentialStatus, "history", "Local credentials only; account access has not been verified")}</td><td>${a.installed === true ? dashboardPill("muted", "Optional scrobbler installed", "check") : dashboardPill("muted", "Optional scrobbler absent", "minus")}</td><td>${a.installed === true ? dashboardFlag(a.enabled,"On","Off","warn") : "—"}</td><td>${esc(integration.refs_found ?? "—")} auth fields</td><td class="dash-action-cell"><a class="dash-settings" href="#/trakt" aria-label="Open Trakt integration">${dashboardIcon("settings")}<span>Integration</span></a></td></tr>`;
  }
  return `<tr data-component="${row.key}" data-state="${row.status.kind}" data-search="${esc(`${row.label} ${a.name || ""} ${a.addon_id || ""}`.toLowerCase())}">
    <th scope="row"><div class="dash-identity"><span class="dash-avatar dash-avatar--${row.key}">${dashboardIcon(row.icon)}</span><span><span class="dash-name" title="${esc(a.addon_id || row.label)}">${esc(row.label)}</span><span class="dash-detail">${esc(row.key === "skin" && a.name ? a.name : row.detail)}</span></span></div></th>
    <td><span class="dash-version">${esc(a.version || "—")}</span></td>
    <td>${dashboardPill(row.status.tone, row.status.label, row.status.icon, source ? `Detected from ${source}` : row.status.label)}</td>
    <td>${dashboardFlag(a.installed, "Installed", "Not found")}</td>
    <td>${dashboardFlag(a.enabled, "On", "Off", "warn")}</td>
    <td>${dashboardFlag(a.config_present, "Found", "Not found")}</td>
    <td class="dash-action-cell">${canOpen ? `<a class="dash-settings" href="#/addon/${encodeURIComponent(a.addon_id)}" aria-label="Open ${esc(row.label)} settings">${dashboardIcon("settings")}<span>Settings</span></a>` : '<span class="dash-no-action" title="No detected add-on to configure">—</span>'}</td>
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
  return `<div class="dash-table-panel" style="padding:16px;margin-bottom:16px">${dashboardPill(fixes.healthy?'ok':'warn',label,fixes.healthy?'check':'alert')} <a class="dash-settings" href="#/fixes">Check custom fixes</a></div>`;
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
  } else out('<div class="dashboard dash-loading" role="status">Checking your Kodi setup…</div>');
  try {
    const s = await api("/api/status", undefined, controller.signal);
    const [addons, backups, fixes] = await Promise.all([
      api("/api/addons", undefined, controller.signal),
      window.KODI_DESKTOP_READONLY ? null : api("/api/stack/backups", undefined, controller.signal).catch(()=>null),
      api("/api/fixes", undefined, controller.signal).catch(()=>null)
    ]);
    if (request !== state.dashboardRequest) return;
    const focused = document.activeElement;
    const focusId = focused?.id;
    const selection = focused?.selectionStart;
    const scrollLeft = document.querySelector(".dash-table-scroll")?.scrollLeft || 0;
    const noticesOpen = !!document.querySelector(".dash-notices")?.open;
    state.writeEnabled = s.write_enabled === true;
    updateDirtyBar();
    $("#top").innerHTML = `Kodi ${esc(s["Kodi version"])} ${dashboardFlag(s.write_enabled, "Write enabled", "Read only")}`;
    const rows = dashboardComponents(s, addons);
    const installed = addons.filter(a => a.installed === true);
    const detected = rows.filter(r => r.addon.installed === true || r.addon.config_present === true || r.integration?.status === "configured").length;
    const warnings = s.stack?.warnings || [];
    const checkedAt = new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
    const writeLabel = s.write_enabled === true ? "Write enabled" : s.write_enabled === false ? "Read only" : "Unknown";
    out(`<div class="dashboard">
      <div class="dash-heading"><div><p class="dash-eyebrow">Overview</p><h2>Your Kodi setup</h2><p class="dash-subtitle">A clear view of your add-ons and their current state.</p></div><button class="dash-refresh" id="dashboardRefresh">${dashboardIcon("refresh")}<span>Refresh status</span></button></div>
      <div class="dash-metrics" aria-label="Setup summary">
        <div><span class="dash-metric-label">Installed add-ons</span><strong>${installed.length}</strong><span class="dash-metric-detail">${installed.filter(a=>a.enabled === true).length} confirmed enabled</span></div>
        <div><span class="dash-metric-label">Core components</span><strong>${detected}<small> detected</small></strong><span class="dash-metric-detail">Skin, players & integrations</span></div>
        <div><span class="dash-metric-label">Checkpoints</span><strong>${backups ? (backups.backups || []).length : "—"}</strong><span class="dash-metric-detail">${backups ? "Saved config backups" : "Backup status unavailable"}</span></div>
        <div><span class="dash-metric-label">Changes</span><strong class="dash-metric-mode">${dashboardIcon(s.write_enabled === true ? "settings" : s.write_enabled === false ? "pause" : "help")}${writeLabel}</strong><span class="dash-metric-detail">${s.write_enabled === true ? "Backup before every write" : s.write_enabled === false ? "Settings changes disabled" : "Write permission unconfirmed"}</span></div>
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
    if (request !== state.dashboardRequest) return;
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
  <div class="panel"><h2>Checks</h2><div class="table">${(h.checks||[]).map(c=>`<div class="row"><span><b>${esc(c.label)}</b><br><span class="muted">${esc(c.detail)}</span></span><span class="${c.status === "ok" ? "ok" : c.status === "error" ? "bad" : "warn"}">${esc(c.status)}</span></div>`).join("")}</div></div>
  <div class="panel"><h2>Recent log problems</h2><h3>Errors</h3><pre>${esc((h.recent_errors||[]).slice().reverse().join("\\n") || "None")}</pre><h3>Warnings</h3><pre>${esc((h.recent_warnings||[]).slice().reverse().join("\\n") || "None")}</pre></div>`);
}
async function runGlobalSearch(){
  const q = ($("#globalSearch").value || "").trim();
  if (!q) return;
  location.hash = "#/search?q=" + encodeURIComponent(q);
}
async function searchView(query){
  $("#globalSearch").value = query;
  if (!query) return out(`<div class="panel"><h2>Search configs</h2><p>Enter search text in top bar.</p></div>`);
  const data = await api(`/api/search/config?q=${encodeURIComponent(query)}`);
  out(`<div class="panel"><h2>Config search: ${esc(query)}</h2><p>${data.count} result(s)</p>${data.results.map(r => `<div class="card"><h3>${esc(r.addon_name || r.addon_id)} <span class="muted">${esc(r.version || "")}</span></h3><p><b title="${esc(r.id)}">${esc(friendlyName(r.id, r.label))}</b><br><span class="muted">${esc(r.description || describeSetting(r.id, r.label))}</span></p><p>${esc(r.value)}</p><p>${r.editable ? "<span class='ok'>editable</span>" : "<span class='muted'>read-only</span>"} ${r.warning ? `<span class="warn">${esc(r.warning)}</span>` : ""}</p><button class="action" onclick="location.hash='#/addon/${encodeURIComponent(r.addon_id)}'">Open add-on</button></div>`).join("")}</div>`);
}
function statusBody(a={}, showActive=false){
  return `<p>${esc(a.name || a.addon_id || "missing")}</p><p class="muted">${esc(a.version || "")}</p><p>installed ${badge(a.installed)}</p><p>config ${badge(a.config_present)}</p>${showActive || a.active ? `<p>active ${badge(!!a.active)}</p>` : ""}<p class="muted">detected from ${(a.detected_from || a.sources || []).map(esc).join(", ")}</p><p>${esc(a.adapter || "")} ${esc(a.variant || "")}</p>`;
}
async function stack(){ const s=await api("/api/stack"); out(`<div class="panel"><h2>Bingie Build</h2><pre>${esc(JSON.stringify(s.bingie_build,null,2))}</pre></div>`); }
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
function appCanWrite(status){
  return status.write_enabled === true && !(typeof window !== "undefined" && window.KODI_DESKTOP_READONLY);
}
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
  out(`${warnings}<div class="panel"><h2>Playback setup</h2><p>Primary player: <b>${esc(primary.name || primary.addon_id || "Unknown")}</b> · ${esc(primary.selection || "unknown")} · ${esc(primary.confidence || "unknown")} confidence</p><div class="grid">${p.nodes.map(nodeCard).join("")}</div><button class="action" id="rescanPipe">Rescan pipeline</button><button class="action" id="backupPipe">Create Pipeline Backup</button><button class="action" id="copyPipe">Copy pipeline debug report</button></div>
  <div class="panel"><h2>Current routing</h2><table class="addon-table"><thead><tr><th>Stage</th><th>Detected component</th><th>Config source</th><th>Status</th><th>Editable</th></tr></thead><tbody>
    ${Object.entries(p.routing).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v.value)}<br><span class="muted">${esc(v.addon_id)}</span></td><td>${esc(v.source)} ${esc(v.setting_id || "")}</td><td>${esc(v.confidence)}</td><td>${badge(v.editable)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="panel"><h2>Connections and evidence</h2><div class="grid">${p.edges.map(e=>card(`${p.nodes.find(n=>n.id===e.from)?.label || e.from}${(e.evidence || []).length ? " → " : " / "}${p.nodes.find(n=>n.id===e.to)?.label || e.to}`, `<p>${esc(e.label)} · ${esc(e.relationship || ((e.evidence || []).length ? "evidence found" : "unconfirmed"))}</p><p class="muted">${pipelineEvidence(e.evidence)}</p>`)).join("")}</div></div>
  <div class="panel"><h2>Scraper relationship</h2><p>${esc(scraper.name || "Unknown")} · ${esc(scraper.relationship || "unknown")} · ${scraper.used === true ? "linked to selected player" : "usage unconfirmed"}</p><p class="muted">${pipelineEvidence(scraper.evidence)}</p><h3>Available modules</h3>${(p.summary.available_scraper_modules || []).map(a=>`<p>${esc(a.name || a.addon_id)} · installed: ${badge(a.installed)} · enabled: ${badge(a.enabled)}</p>`).join("") || "<p class='muted'>No external scraper modules detected.</p>"}<p class="muted">Module installation and enablement do not establish which player uses it.</p></div>
  <div class="panel"><h2>Account integrations</h2><div class="grid">${["trakt","torbox","tmdb"].map(k=>card(k, integrationSummary((p.summary.integrations || p.summary.accounts || {})[k]))).join("")}</div><a href="#/accounts">Edit account settings</a></div>
  <div class="panel"><h2>Pipeline controls only</h2><p class="muted">Only routing/provider-link settings shown here. Account keys moved to Accounts tab.</p>${state.writeEnabled ? "" : "<p class='warn'>Write Mode is disabled. Enable it in service settings to change configuration.</p>"}${p.settings_groups.map((g,i)=>`<div class="group"><h3>${esc(g.label)}</h3>${settingRows(g.settings, `pipe-${i}`)}</div>`).join("") || "<p class='muted'>No safe pipeline controls detected. Use native settings for player-file routing.</p>"}</div>
  <div class="panel"><h2>Playback target</h2><p>Player-file routes are configured in helper settings.</p>${p.summary.helper?.addon_id ? `<a href="#/addon/${encodeURIComponent(p.summary.helper.addon_id)}">Open helper settings</a>` : "<p class='muted'>No helper add-on detected.</p>"}</div>
  <div class="panel"><h2>Discovery evidence</h2><pre>${esc(JSON.stringify(redactObj(p.discovery), null, 2))}</pre></div>`);
  $("#rescanPipe").onclick = async()=>pipelineView();
  $("#backupPipe").disabled = !state.writeEnabled;
  $("#backupPipe").onclick = async()=>{ if (!state.writeEnabled) return; const r=await api("/api/pipeline/backup",{}); alert("Pipeline backup "+r.backup_id); };
  $("#copyPipe").onclick = async()=>{ await navigator.clipboard.writeText(JSON.stringify(redactObj(p), null, 2)); alert("Pipeline debug copied"); };
  document.querySelectorAll("[data-pipe-setting]").forEach(el=>el.onchange=async()=>{ const preview=changePreview(el.dataset.pipeSetting, el.dataset.original, el.value, el.type === "password" || appSecretSetting({id:el.dataset.pipeSetting})); if(!confirm(`Save pipeline setting? Backup will be created first.\n\n${preview}`)) return; const r=await apiMethod("PATCH","/api/pipeline/settings",{changes:[{component:el.dataset.pipeComponent,setting_id:el.dataset.pipeSetting,source:el.dataset.pipeSource,value:el.value}]}); alert("Saved. Backup "+r.backup_id); pipelineView(); });
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
  out(`<div class="panel"><h2>Accounts</h2><p>Account credentials use password fields. Saving creates a backup first.</p>${state.writeEnabled ? "" : "<p class='warn'>Write Mode is disabled. Account editing disabled.</p>"}<div class="grid">${Object.entries(d.summary || {}).map(([k,v])=>card(k, integrationSummary(v))).join("")}</div><button class="primary" id="saveAccounts">Save Account Changes</button></div>${(d.groups||[]).map((g,i)=>`<div class="group"><h3>${esc(g.label)}</h3>${filterTabs(`acct-${i}`, g.settings)}<div class="settings-grid">${g.settings.map(s=>`<div data-filter-scope="acct-${i}" data-set="${settingIsSet(s) ? "true" : "false"}" data-readonly="${isReadOnlySetting(s) ? "true" : "false"}">${accountField(s)}</div>`).join("")}</div></div>`).join("")}`);
  $("#saveAccounts").disabled = !state.writeEnabled;
  $("#saveAccounts").onclick = async()=>{
    if (!state.writeEnabled) return;
    const changes = [...document.querySelectorAll("[data-account-setting]")].filter(i=>!i.disabled).filter(i=>String(i.value) !== String(i.dataset.original ?? "")).map(i=>({component:i.dataset.accountComponent,setting_id:i.dataset.accountSetting,source:i.dataset.accountSource,value:i.value}));
    if (!changes.length) return alert("No account changes entered.");
    const preview = changes.map(ch => {
      const el = [...document.querySelectorAll("[data-account-setting]")].find(x => x.dataset.accountSetting === ch.setting_id && x.dataset.accountComponent === ch.component);
      return `${ch.component} / ${changePreview(ch.setting_id, el?.dataset.original, ch.value, el?.type === "password" || appSecretSetting({id:ch.setting_id}))}`;
    }).join("\n\n");
    if (!confirm(`Replace ${changes.length} account value(s)? Backup will be created first.\n\n${preview}`)) return;
    const r = await apiMethod("PATCH","/api/accounts/settings",{changes});
    alert(`Saved ${r.changed_count}. Backup ${r.backup_id}.`);
    accountsView();
  };
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
  out(`<div class="panel"><h2>Trakt integration</h2><p>POV, Fen and metadata helpers can store their own Trakt authorization.</p>${integrationSummary(trakt)}<a href="#/accounts">Edit account settings</a></div><div class="panel"><h2>Optional standalone scrobbler</h2><p>${standalone.installed === true ? `script.trakt is installed · enabled: ${badge(standalone.enabled)}` : "script.trakt is absent. Add-on account integration can operate independently."}</p>${standalone.installed === true || standalone.config_present === true ? '<a href="#/addon/script.trakt">Open standalone scrobbler settings</a>' : ""}</div><div class="panel"><h2>TorBox integration</h2>${integrationSummary(accounts.summary?.torbox)}<a href="#/accounts">Edit TorBox settings</a></div>`);
}
async function pickAddon(keys){ const s=await api("/api/stack"); for (const k of keys){ const aid=s[k]?.addon_id; if(aid) return addonSettings(aid); } out("<div class='panel warn'>No matching add-on found.</div>"); }
function settingControl(addonId, x){
  const disabled = (!x.editable || !state.writeEnabled) ? "disabled" : "";
  const value = x.value ?? "";
  const rawSource = String(x.raw?.source || "");
  const source = rawSource.includes("settings.db") ? "settings.db" : (rawSource === "raw" ? "raw" : "settings.xml");
  let control = `<input data-setting="${esc(x.id)}" data-source="${esc(source)}" data-original="${esc(value)}" value="${esc(value)}" ${disabled}>`;
  const type = String(x.type || "").toLowerCase();
  if (type === "bool" || type === "boolean") {
    control = `<select data-setting="${esc(x.id)}" data-source="${esc(source)}" data-original="${esc(value)}" ${disabled}><option value="true" ${String(value)==="true"?"selected":""}>On</option><option value="false" ${String(value)==="false"?"selected":""}>Off</option></select>`;
  } else if ((x.options || []).length) {
    control = `<select data-setting="${esc(x.id)}" data-source="${esc(source)}" data-original="${esc(value)}" ${disabled}>${x.options.map(o => `<option value="${esc(o.value)}" ${String(o.value)===String(value)?"selected":""}>${esc(o.label || o.value)}</option>`).join("")}</select>`;
  }
  const status = isUnset(value) ? `<span class="badge">unset</span>` : `<span class="badge">set</span>`;
  const title = friendlyName(x.id, x.label);
  return `<div class="setting-card"><label><span><b title="${esc(x.id)}">${esc(title)}</b> ${status}<br><span class="muted">${esc(x.description || describeSetting(x.id, x.label))}${x.editable ? "" : " · read-only"}</span></span>${control}</label>${x.warning ? `<p class="warn">${esc(x.warning)}</p>` : ""}</div>`;
}
async function addonSettings(aid){
  return renderAddonSettingsView(aid);
}
async function backups(){
  const t=await api("/api/backups/timeline");
  const items = t.items || [];
  out(`<div class="panel"><h2>Checkpoint Timeline</h2><p>Checkpoint saves current Kodi Manager stack config. Restore puts config folders back and may need Kodi restart.</p><button class="primary" id="stackBackup">Create Checkpoint</button><div class="timeline">${items.map(x=>`<div class="card"><h3>${esc(x.backup_id || x.name || "")}</h3><p><span class="badge">${esc(x.kind || "stack")}</span> <span class="badge">${esc(x.component_count || 0)} included</span> <span class="badge">${esc(x.skipped_count || 0)} skipped</span></p><p class="muted">Kodi ${esc(x["Kodi version"] || "")}</p><button class="action" data-restore="${esc(x.backup_id || x.name || "")}" ${x.kind === "pipeline" ? "disabled title='Pipeline backups are restore-manual in this MVP'" : ""}>Restore</button></div>`).join("") || "<p>No checkpoints yet.</p>"}</div></div>`);
  $("#stackBackup").onclick=async()=>{ const r=await api("/api/stack/backup",{}); alert("Checkpoint "+r.backup_id); backups(); };
  document.querySelectorAll("[data-restore]").forEach(b=>b.onclick=async()=>{ if(!confirm("Restore checkpoint? Current config will be backed up first.")) return; const r=await api("/api/stack/restore",{backup_id:b.dataset.restore}); alert("Restored. Kodi restart may be needed."); backups(); });
}
async function playbackTestView(){
  const pipe = await api("/api/pipeline");
  const players = [pipe.summary.primary_player, ...(pipe.summary.secondary_players || [])].filter(x=>x && x.addon_id);
  out(`<div class="panel"><h2>Playback Test Runner</h2><p>Safe dry run. Checks routing, detected player, scraper module, and current Kodi player state. It does not start media.</p><div class="grid"><label>Target player<select id="testPlayer">${players.map(p=>`<option value="${esc(p.addon_id)}">${esc(p.name || p.addon_id)}</option>`).join("")}</select></label><label>Optional plugin URL<input id="testUrl" placeholder="plugin://..."></label></div><button class="primary" id="runPlaybackTest">Run Test</button><pre id="playbackOut"></pre></div>`);
  $("#runPlaybackTest").onclick = async()=>{
    const r = await api("/api/playback/test", {target_player_addon_id:$("#testPlayer").value, plugin_url:$("#testUrl").value});
    $("#playbackOut").textContent = JSON.stringify(r, null, 2);
  };
}
function logLevel(line){ const s=String(line).toLowerCase(); if (s.includes(" error") || s.includes("error:") || s.includes(" exception") || s.includes("traceback")) return "error"; if (s.includes(" warning") || s.includes("warn:") || s.includes("deprecated")) return "warn"; return "info"; }
function renderLogs(title, lines){
  out(`<div class="panel"><h2>${esc(title)}</h2><button class="action" data-level="all">All</button><button class="action" data-level="info">Info</button><button class="action" data-level="warn">Warn</button><button class="action" data-level="error">Error</button><div id="logBox" class="log-view"></div></div>`);
  const newest = [...(lines || [])].reverse();
  const draw = level => { $("#logBox").innerHTML = newest.filter(l => level === "all" || logLevel(l) === level).map(l => `<div class="log-line log-${logLevel(l)}">${esc(l)}</div>`).join(""); };
  document.querySelectorAll("[data-level]").forEach(b => b.onclick = () => draw(b.dataset.level));
  draw("all");
}
async function logs(){ const l=await api("/api/logs"); renderLogs("Service Logs", l.lines || []); }
async function kodiLogs(){ const l=await api("/api/kodi/logs"); renderLogs("Kodi Logs", l.lines || []); }
async function allAddons(){
  const addons = await api("/api/addons");
  out(`<div class="panel"><h2>All Add-ons</h2><input id="filter" placeholder="Filter add-ons"><div id="addonList"></div></div>`);
  const render = () => {
    const q = ($("#filter").value || "").toLowerCase();
    $("#addonList").innerHTML = `<table class="addon-table"><thead><tr><th>Name</th><th>ID</th><th>Version</th><th>Enabled</th><th>Config</th><th></th></tr></thead><tbody>${addons.filter(a => `${a.addon_id} ${a.name}`.toLowerCase().includes(q)).map(a => `<tr><td>${esc(a.name || a.addon_id)}</td><td>${esc(a.addon_id)}</td><td>${esc(a.version || "")}</td><td>${badge(a.enabled)}</td><td>${badge(a.config_present)}</td><td><button class="action" onclick="location.hash='#/addon/${encodeURIComponent(a.addon_id)}'">Open</button></td></tr>`).join("")}</tbody></table>`;
  };
  $("#filter").oninput = render; render();
}
async function installAddonView(){
  out(`<div class="panel"><h2>Install Add-on / Repository</h2><p class="warn">Kodi repositories are add-ons too. Install a local repository ZIP here, then use Kodi's normal repository browser. Remote repository URLs are not supported here because Kodi JSON-RPC has no safe add-repo-url endpoint, and this tool avoids source/repo URL management.</p><label>Local ZIP path on Kodi filesystem<input id="zipPath" placeholder="special://home/addons/packages/repository.example.zip"></label><button class="primary" id="installZip">Install local ZIP</button><pre id="installOut"></pre></div>`);
  $("#installZip").onclick = async()=>{ try { const r=await api("/api/addons/install",{source_path:$("#zipPath").value}); $("#installOut").textContent=JSON.stringify(r,null,2); } catch(e){ $("#installOut").textContent=e.message; } };
}
async function serviceSetup(){ out(`<div class="panel"><h2>Setup</h2><p>Service URL: ${esc(location.origin)}</p><p>Token stored: ${badge(!!state.token)}</p><button class="action" onclick="localStorage.removeItem('bsa_token');location.reload()">Forget token</button></div>`); }
async function diagnostics(){
  out(`<div class="panel"><h2>Diagnostics</h2><button class="action" id="paths">Run Path Diagnostics</button><button class="action" id="raw">Run Raw Stack Detection</button><button class="action" id="pipeDebug">Run Pipeline Debug</button><button class="action" id="copy">Copy Debug Report</button><pre id="diag"></pre></div>`);
  let report = {};
  $("#paths").onclick = async()=>{ report.paths = await api("/api/debug/paths"); $("#diag").textContent = JSON.stringify(report.paths,null,2); };
  $("#raw").onclick = async()=>{ report.raw = await api("/api/debug/stack-raw"); $("#diag").textContent = JSON.stringify(report.raw,null,2); };
  $("#pipeDebug").onclick = async()=>{ report.pipeline = await api("/api/pipeline/debug"); $("#diag").textContent = JSON.stringify(redactObj(report.pipeline),null,2); };
  $("#copy").onclick = async()=>{ report.status = await api("/api/status"); report.paths = report.paths || await api("/api/debug/paths"); report.raw = report.raw || await api("/api/debug/stack-raw"); report.pipeline = report.pipeline || await api("/api/pipeline/debug"); navigator.clipboard.writeText(JSON.stringify(redactObj(report),null,2)); $("#diag").textContent = JSON.stringify(redactObj(report),null,2); };
}

async function fixesView(){
  const [status, fixes] = await Promise.all([api('/api/status'), api('/api/fixes')]);
  if (fixes.bundled === false) {
    out(`<div class="panel"><h2>Custom fixes</h2><p>${esc(fixes.detail)}</p><p>Version-checked repair manifests can be supplied separately. This companion manages your existing setup without installing third-party patch payloads.</p></div>`);
    return;
  }
  const labels = {ok:'Protected', changed:'Files replaced', version_changed:'Update needs review'};
  out(`<div class="panel"><h2>Custom fixes</h2><p>Checks the TV’s playback, navigation and skin fixes against their tested copies.</p><p>${esc(fixes.detail)}</p>
    <table><thead><tr><th>Fix</th><th>Status</th><th>Add-on version</th></tr></thead><tbody>${fixes.groups.map(g=>`<tr><td>${esc(g.label)}</td><td>${dashboardPill(g.status==='ok'?'ok':'warn', labels[g.status], g.status==='ok'?'check':'help')}</td><td>${esc(g.installed_version || 'Missing')} · tested ${esc(g.tested_version)}</td></tr>`).join('')}</tbody></table>
    ${fixes.healthy?'<p>All custom fixes are intact.</p>':'<p>Known older files can be restored from the verified copy. A new version or an unrecognised change needs review.</p>'}
    <button id="restoreFixes" class="primary" ${fixes.repairable && appCanWrite(status)?'':'disabled'}>Restore tested fixes</button><p class="muted">Creates a backup before restoring. Stop playback first; restart Kodi afterwards.</p><div id="fixResult"></div></div>`);
  $('#restoreFixes').onclick = async()=>{
    $('#restoreFixes').disabled = true;
    try { const result = await api('/api/fixes/repair', {}); $('#fixResult').textContent = result.detail; }
    catch(error) { $('#fixResult').textContent = error.message; $('#restoreFixes').disabled = false; }
  };
}
boot().catch(e => out(`<div class="panel bad">${esc(e.message)}</div>`));
