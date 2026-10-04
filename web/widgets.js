/* Live Kodi folders and a local draft. TV changes require a separate preview/apply. */
function familyWidgetPath(source, maxRating = "12A") {
  return "plugin://service.kodi.addonadmin/?" + new URLSearchParams({mode:"family", source, max_rating:maxRating, family_only:"true"});
}
function widgetPoster(item) {
  let value = item.art?.poster || item.thumbnail || "";
  if (value.startsWith("image://")) {
    try { value = decodeURIComponent(value.slice(8).replace(/\/$/, "")); } catch (_) { return ""; }
  }
  try { const url = new URL(value); return url.protocol === "https:" && ["image.tmdb.org", "images.trakt.tv", "assets.fanart.tv", "artworks.thetvdb.com"].includes(url.hostname) ? url.href : ""; } catch (_) { return ""; }
}
function widgetSource(row) {
  let path = row.path || "", filtered = !!row.filtered, maxRating = row.maxRating || "12A";
  try { const url = new URL(path); if (url.hostname === "service.kodi.addonadmin" && url.searchParams.get("mode") === "family") { path = url.searchParams.get("source") || ""; filtered = url.searchParams.get("family_only") === "true"; maxRating = url.searchParams.get("max_rating") || "12A"; } } catch (_) {}
  return {...row, path, filtered, maxRating};
}
function widgetOutputPath(row) { return row.filtered ? familyWidgetPath(row.path, row.maxRating || "12A") : row.path; }
function widgetPlan(draft) {
  return {version:2,section_id:draft.section_id,label:draft.label,max_rating:draft.maxRating || "12A",family_only:false,
    rows:draft.rows.map(row => ({...row,source_path:row.path,path:widgetOutputPath({...row,maxRating:row.maxRating || draft.maxRating})})),
    instructions:"Import into Bingie Studio, select the target section, then review changes before applying."};
}
function parseWidgetPlan(plan) {
  const cap = plan?.max_rating || "12A";
  if (!plan || typeof plan.label !== "string" || !plan.label.trim() || !["U","PG","12A","15"].includes(cap) || !Array.isArray(plan.rows) || !plan.rows.length || plan.rows.length > 20) throw new Error("Choose a valid plan with 1–20 rows.");
  const rows = plan.rows.map(row => {
    if (!row || typeof row.label !== "string" || !row.label.trim()) throw new Error("Every row needs a name.");
    const source = row.source_path;
    if (typeof source !== "string" || !/^plugin:\/\/plugin\.video\.[A-Za-z0-9_.-]+(?:[/?]|$)/.test(source) || source.length > 12000 || /[\u0000-\u001f]/.test(source)) throw new Error("Each imported row needs its original video add-on source path.");
    const parsed = {label:row.label,path:source,filtered:row.filtered === true || (row.filtered === undefined && plan.family_only === true),breadcrumb:Array.isArray(row.breadcrumb) ? row.breadcrumb.filter(x => typeof x === "string") : []};
    if (row.maxRating) { if (!["U","PG","12A","15"].includes(row.maxRating)) throw new Error("Unknown family rating."); parsed.maxRating = row.maxRating; }
    return parsed;
  });
  return {label:plan.label.trim(),maxRating:cap,rows};
}
function widgetLayoutBody(draft) {
  const body = {label:draft.label,rows:draft.rows.map(row => ({...(row.id ? {id:row.id} : {}),label:row.label,path:widgetOutputPath(row),...(row.action ? {action:row.action} : {})}))};
  if (draft.section_id && draft.section_id !== "new") body.section_id = draft.section_id;
  return body;
}
function widgetMediaItems(result) {
  return (result?.items || []).filter(item => item.classification ? ["media","series","episode"].includes(item.classification) : item.year || item.mpaa || (item.genre || []).length || ["movie","tvshow","episode","musicvideo"].includes(item.type));
}
function widgetVisibleSections(layout) {
  const sections = (layout.sections || []).map(s => ({...s,rows:s.rows || []}));
  if (Array.isArray(layout.menu_entries)) return layout.menu_entries.filter(m => !m.disabled).map(m => {
    const source=sections.find(s => s.id === m.target_section_id);
    return source ? {...source,label:m.label,kind:m.kind,menu_id:m.id} : null;
  }).filter(Boolean);
  const menu=sections.find(s => s.id === "mainmenu")?.rows || [];
  return sections.filter(s => s.id !== "mainmenu" && s.in_menu !== false && s.disabled !== true).sort((a,b) => {
    const order=s=>{const n=menu.findIndex(m=>m.action===s.action);return n<0 ? 999 : n;};return order(a)-order(b);
  });
}
function widgetSourceDescription(row) {
  if (row.path?.startsWith("special://videoplaylists/")) return "Kodi · Video playlists";
  if (row.path?.startsWith("addons://sources/video/")) return "Kodi · Installed video add-ons";
  if (/FavouritesBrowser/i.test(row.action || "")) return "Kodi · Favourites";
  if (/\$(VAR|INFO)\[/.test(row.path || row.action || "") && !row.path?.startsWith("plugin://")) return "Bingie · Skin-defined source";
  return "";
}
function widgetRecommendedSources(sources) {
  const useful = sources.filter(s => s.enabled === true && (s.addon_id === "plugin.video.pov" || /^plugin\.video\.(?:tmdb\.bingie\.helper|themoviedb\.helper)$/.test(s.addon_id)));
  return (useful.length ? useful : sources.filter(s => s.enabled === true && !/fen/i.test(s.addon_id))).map(s => s.addon_id);
}
function widgetCatalogueObservation(result, status = "loaded", checkedAt = Date.now()) {
  const count = widgetMediaItems(result).length;
  const kind = status === "error" || result?.status && result.status !== "ok" ? "error" : status === "skipped" ? "skipped" : count ? "media" : result ? (result.items?.length || result.children?.length ? "folder" : "empty") : "unknown";
  return {kind,count,checkedAt};
}
function widgetCatalogueTier(observation) { return {media:3,unknown:2,folder:1,empty:0,error:0,skipped:0}[observation?.kind] ?? 2; }
function widgetCatalogueCache(raw, now = Date.now()) {
  try {
    const saved = JSON.parse(raw), entries = Array.isArray(saved?.entries) ? saved.entries : [];
    return new Map(entries.filter(([path,value]) => typeof path === "string" && path.startsWith("plugin://") && path.length <= 12000 && value && ["media","folder","empty","error","skipped"].includes(value.kind) && Number.isFinite(value.checkedAt) && value.checkedAt <= now && now-value.checkedAt < (["error","skipped"].includes(value.kind) ? 900000 : 21600000)).slice(-600));
  } catch (_) { return new Map(); }
}
async function widgetStudioView() {
  out(`<section class="bingie-studio"><div class="bs-heading"><div><p class="dash-eyebrow">Your TV, laid out</p><h2>Bingie Studio</h2><p>Your current sections above. Browse useful source folders below, one page at a time.</p></div><a class="bs-jump" href="#bs-catalogue" id="bs-jump-catalogue">Browse source rows ↓</a></div><div id="bs-notice" role="status"></div><section class="bs-tv" aria-label="Bingie layout preview"><div class="bs-tv-top"><span class="bs-tv-label">BINGIE <small>layout preview</small></span><span id="bs-connection">Reading your TV layout…</span></div><div id="bs-sections" class="bs-sections" role="tablist" aria-label="TV sections"></div><details class="bs-hub-help" id="bs-hub-help"><summary>Sections, hubs and adding another screen</summary><p id="bs-hub-help-text"></p><div id="bs-inactive-sections"></div></details><div class="bs-section-heading"><div><h3 id="bs-section-name">Loading sections…</h3><p id="bs-section-detail"></p></div><div class="bs-actions"><button id="bs-add-row" class="primary">+ Add a row</button><button id="bs-rename-section" class="action">Rename section</button><button id="bs-review" class="bs-save" disabled>Review changes</button></div></div><div id="bs-current-rows"></div><div class="bs-layout-footer"><span id="bs-draft-status">Reading current configuration…</span><button id="bs-reset" class="action" disabled>Discard draft</button><button id="bs-reload-layout" class="action">Refresh from TV</button><details class="bs-tools"><summary>Import, export &amp; presets</summary><div><button class="action" id="bs-export">Export section</button><button class="action" id="bs-import">Import rows</button><button class="action" id="bs-preset">Add family starter rows</button></div><p>Imports and presets add rows to the selected section. Existing rows stay in place.</p></details><input id="bs-import-file" type="file" accept=".json,application/json" hidden></div></section><section id="bs-catalogue" class="bs-catalogue"><div class="bs-catalogue-heading"><div><p class="dash-eyebrow">Available to add</p><h3>Source catalogue</h3><p>12 folders per page, ranked by likely usefulness. Only this page’s previews load.</p></div><button id="bs-refresh-catalogue" class="action">Refresh catalogue</button></div><div class="bs-catalogue-toolbar"><fieldset class="bs-source-picker"><legend>Source add-ons</legend><div class="bs-source-picker-top"><span id="bs-source-summary">Loading sources…</span><div class="bs-source-shortcuts"><button class="action" data-source-choice="recommended">Recommended</button><button class="action" data-source-choice="all">All</button><button class="action" data-source-choice="none">None</button></div></div><div id="bs-source-options" class="bs-source-options"></div><p>Your selection is saved in this browser. Fen is off by default.</p><p>Trakt lists are inside POV (My Lists / Trakt Lists) and TMDb Helper (Trakt), rather than a separate video source. Select those add-ons to browse your lists.</p></fieldset><label class="bs-search">Find a folder<input id="bs-search" type="search" placeholder="Popular, animation, watchlist…"></label><label>Sort by<select id="bs-sort"><option value="usefulness">Most useful first</option><option value="name">Folder name A–Z</option></select></label></div><div id="bs-destination" class="bs-destination"></div><div id="bs-progress" role="status" class="bs-progress">Connecting to Kodi…</div><nav class="bs-pagination" aria-label="Catalogue pages"><button class="action" data-page-step="-1">← Previous</button><span class="bs-page-label"></span><button class="action" data-page-step="1">Next →</button></nav><div id="bs-folders"></div><div id="bs-catalogue-empty" class="bs-empty" hidden>No discovered folders match. Select a source add-on or change your search.</div><nav class="bs-pagination" aria-label="Catalogue pages, bottom"><button class="action" data-page-step="-1">← Previous</button><span class="bs-page-label"></span><button class="action" data-page-step="1">Next →</button></nav><p class="bs-ranking-note">Most useful puts checked media rows first, untested folders next, and checked empty or unavailable folders last. Each preview batch updates the order once; newly promoted folders wait for Load preview. Checks are saved in this browser for up to six hours. Refresh catalogue checks them again.</p></section><dialog id="bs-review-dialog" class="bs-dialog"><div id="bs-review-content"></div></dialog></section>`);
  const root = document.querySelector(".bingie-studio"), $b = s => root.querySelector(s);
  const abort = new AbortController(), storageKey = "bingie_studio_drafts_v2";
  let layout = null, sources = [], selected = "", replaceIndex = null, drafts = {}, savedDrafts = {}, review = null;
  let entries = [], seen = new Map(), cache = new Map(), refreshCatalog = false, epoch = 0, pageRun = 0, page = 1, pageEntries = [], indexing = false, catalogueOrder = [], catalogueKey = "";
  const pageSize = 12;
  const sourceKey = "bingie_studio_sources_v1", observationKey = "bingie_studio_catalogue_checks_v1";
  let chosenSources = new Set(), savedSources = null, observations = new Map();
  try { const saved = JSON.parse(localStorage.getItem(sourceKey)); if (Array.isArray(saved) && saved.every(id => typeof id === "string")) savedSources = saved; } catch (_) {}
  try { observations = widgetCatalogueCache(localStorage.getItem(observationKey)); } catch (_) {}
  try { savedDrafts = JSON.parse(localStorage.getItem(storageKey)) || {}; } catch (_) {}
  const active = () => root.isConnected && !abort.signal.aborted;
  const section = () => [...(layout?.sections || []),...(layout?.inactive_sections || [])].find(s => s.id === selected);
  const draft = () => drafts[selected];
  function notice(text, error = false) { if (!active()) return; $b("#bs-notice").textContent = text; $b("#bs-notice").className = text ? "bs-notice" + (error ? " bs-error" : "") : ""; }
  function saveDrafts() { review = null; try { localStorage.setItem(storageKey, JSON.stringify(drafts)); } catch (_) {} renderDraftStatus(); }
  function dirty() { const current = draft(); return !!current && JSON.stringify(widgetLayoutBody(current)) !== current.base; }
  function canEdit() { return selected === "new" ? !!layout?.new_section?.available : section()?.editable === true; }
  function renderDraftStatus() {
    $b("#bs-draft-status").textContent = dirty() ? "Unsaved draft · your TV changes only after review and apply" : "Showing saved TV configuration";
    $b("#bs-review").disabled = !dirty() || !canEdit() || !draft()?.rows.length; $b("#bs-reset").disabled = !dirty();
    $b("#bs-add-row").disabled = !draft() || !canEdit(); $b("#bs-rename-section").disabled = !canEdit() || section()?.can_rename === false;
    $b("#bs-preset").disabled = !canEdit(); $b("#bs-import").disabled = !canEdit();
    renderDestination();
  }
  function renderDestination() {
    const row = draft()?.rows[replaceIndex];
    $b("#bs-destination").innerHTML = `<div><b>${row ? `Replacing “${esc(row.label)}” in ${esc(draft().label)}` : draft() ? `Adding to ${esc(draft().label)}` : "Choose a TV section above"}</b><span>${row ? "Choose a source row below. Its content preview shows what will replace this row." : "Use the Add button beside a folder’s preview. You can rename and reorder it above."}</span></div>${row ? '<button class="action" id="bs-cancel-replace">Cancel replacement</button>' : ""}`;
    if ($b("#bs-cancel-replace")) $b("#bs-cancel-replace").onclick = () => { replaceIndex = null; renderDestination(); updateAddButtons(); };
    updateAddButtons();
  }
  function updateAddButtons() { root.querySelectorAll("[data-add-source]").forEach(button => { button.textContent = replaceIndex !== null ? "Replace selected row" : `+ Add to ${draft()?.label || "section"}`; button.disabled = !canEdit() || (!Number.isInteger(replaceIndex) && (draft()?.rows.length || 0) >= (layout?.max_rows || 20)); }); }
  function posters(items, small = false) {
    return `<div class="bs-posters${small ? " bs-posters-small" : ""}">${items.slice(0,12).map(item => { const url = widgetPoster(item); return `<div class="bs-poster" title="${esc(item.plot || item.label || item.title)}">${url ? `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<div class="bs-poster-placeholder" aria-hidden="true">▤</div>'}<b>${esc(item.label || item.title || "Untitled")}</b><small>${esc([item.year || "",item.mpaa || ""].filter(Boolean).join(" · "))}</small></div>`; }).join("")}</div>`;
  }
  function remember(path, result, status = "loaded") {
    if (!path.startsWith("plugin://")) return;
    observations.delete(path); observations.set(path,widgetCatalogueObservation(result,status));
    while (observations.size > 600) observations.delete(observations.keys().next().value);
    try { localStorage.setItem(observationKey,JSON.stringify({version:1,entries:[...observations]})); } catch (_) {}
  }
  function renderSources() {
    $b("#bs-source-options").innerHTML = sources.map(source => `<label class="bs-source-option"><input type="checkbox" data-catalogue-source="${esc(source.addon_id)}" ${chosenSources.has(source.addon_id) ? "checked" : ""}><span>${esc(source.label)}${source.enabled !== true ? '<small>Disabled in Kodi</small>' : ""}</span></label>`).join("");
    $b("#bs-source-summary").textContent = `${chosenSources.size} of ${sources.length} sources selected`;
  }
  function chooseSources(ids) {
    chosenSources = new Set(ids.filter(id => sources.some(source => source.addon_id === id)));
    try { localStorage.setItem(sourceKey,JSON.stringify([...chosenSources])); } catch (_) {}
    renderSources(); startCatalogue();
  }
  async function readFolder(path, refresh = false) {
    if (!refresh && cache.has(path)) return cache.get(path);
    const promise = api("/api/widgets/browse", {path,limit:100,family_preview:false,refresh:refresh || refreshCatalog}, abort.signal);
    cache.set(path, promise);
    try { const result = await promise; remember(path,result); return result; } catch (error) { cache.delete(path); remember(path,null,"error"); throw error; }
  }
  function sourceName(path) { try { const id = new URL(path).hostname; return sources.find(s => s.addon_id === id)?.label || id.replace("plugin.video.", ""); } catch (_) { return "Native Kodi source"; } }
  function renderCurrent() {
    if (!draft()) return;
    const value = draft(), current = section();
    $b("#bs-section-name").textContent = value.label;
    const reason = (current?.reasons || []).join(" ");
    $b("#bs-section-detail").textContent = `${current?.disabled ? "Disabled in TV menu · " : ""}${current?.kind === "destination" ? "Menu shortcut" : current?.kind === "home" ? "Home screen" : "Widget hub"} · ${value.rows.length} ${current?.kind === "destination" ? "destination" : "rows"}${current?.shared_menu_labels?.length > 1 ? " · shared by " + current.shared_menu_labels.join(", ") : ""}${!canEdit() ? " · View only. " + (reason || "This layout is not supported for direct editing.") : " · Select a row to change its source, or add another below."}`;
    $b("#bs-current-rows").innerHTML = value.rows.map((row,i) => `<article class="bs-tv-row${replaceIndex === i ? " bs-row-target" : ""}" data-current-row="${i}"><div class="bs-row-heading"><div><div class="bs-row-title"><span class="bs-row-number">${String(i+1).padStart(2,"0")}</span><h4 data-row-label="${i}">${esc(row.label || "Untitled row")}</h4>${!row.id ? '<span class="bs-tag">New</span>' : ""}</div><p class="bs-source-description">${esc((row.breadcrumb || []).join(" › ") || widgetSourceDescription(row) || sourceName(row.path))}${row.filtered ? ` · Family up to ${esc(row.maxRating)}` : ""}</p></div><div class="bs-row-actions"><button class="action" data-replace-row="${i}" ${!canEdit() ? "disabled" : ""}>Replace source</button><button class="action" data-rename-row="${i}" ${!canEdit() ? "disabled" : ""}>Rename</button><button class="bs-icon-button" data-move-row="${i},-1" aria-label="Move ${esc(row.label)} up" ${!canEdit() || i === 0 ? "disabled" : ""}>↑</button><button class="bs-icon-button" data-move-row="${i},1" aria-label="Move ${esc(row.label)} down" ${!canEdit() || i === value.rows.length-1 ? "disabled" : ""}>↓</button><button class="bs-icon-button" data-remove-row="${i}" aria-label="Remove ${esc(row.label)}" ${!canEdit() ? "disabled" : ""}>×</button></div></div><div class="bs-current-preview" data-preview-row="${i}"><span class="bs-preview-loading">Loading the titles in this row…</span></div><details class="bs-row-details"><summary>Source path &amp; filter</summary><div class="bs-detail-fields"><label>Exact widget path<input readonly value="${esc(widgetOutputPath(row) || row.action || "Unknown source")}"></label><label>Content filter<select data-row-filter="${i}" ${!canEdit() || !row.path.startsWith("plugin://plugin.video.") ? "disabled" : ""}><option value="none" ${!row.filtered ? "selected" : ""}>No additional filter</option>${["U","PG","12A","15"].map(r => `<option value="${r}" ${row.filtered && row.maxRating === r ? "selected" : ""}>Family · up to ${r}</option>`).join("")}</select></label></div><p>Family filters require Family/Kids genres and hide unknown ratings. Unfiltered rows use the original add-on directory.</p></details></article>`).join("") || `<div class="bs-empty">${canEdit() ? 'This section has no rows yet. Choose <b>Add a row</b>, then use any source preview below.' : 'This section has no configured widget rows, or uses a native layout that cannot be read as widgets.'}</div>`;
    const selectedAtRender = selected, rowsAtRender = value.rows;
    value.rows.forEach(async (row, i) => {
      const node = $b(`[data-preview-row="${i}"]`);
      const original = current?.rows.find(r => r.id === row.id);
      const saved = !!row.id && original && widgetOutputPath(row) === original.path && original.action === row.action;
      if (!saved && !row.path.startsWith("plugin://plugin.video.")) { node.textContent = "Choose a video add-on folder to preview this draft row."; return; }
      try {
        let result;
        if (saved) {
          const key=`saved:${selectedAtRender}:${row.id}:${layout.revision}`;
          if (!cache.has(key)) cache.set(key,api("/api/widgets/row-preview",{section_id:selectedAtRender,row_id:row.id,limit:48},abort.signal));
          try { result=await cache.get(key); } catch(error) { cache.delete(key); throw error; }
        } else result=await readFolder(row.path);
        if (!active() || selected !== selectedAtRender || draft().rows !== rowsAtRender || !node.isConnected) return;
        if (row.filtered && !saved) result = await api("/api/widgets/browse",{path:row.path,limit:48,family_preview:true,max_rating:row.maxRating},abort.signal).then(r => ({...r,items:r.family_preview?.files || []}));
        if (!node.isConnected) return;
        if (result.resolved_label && /\$VAR\[/.test(row.label)) $b(`[data-row-label="${i}"]`).textContent=result.resolved_label;
        const items = widgetMediaItems(result);
        node.innerHTML = result.status && result.status !== "ok" ? `<div class="bs-preview-empty">${esc(result.reason)}</div>` : items.length ? posters(items,true) + (result.reason ? `<p class="bs-sample">${esc(result.reason)}</p>` : "") : (result.items || []).length ? `<div class="bs-subfolders">${result.items.slice(0,20).map(item=>`<span>▱ ${esc(item.label || item.title)}</span>`).join("")}</div><p class="bs-sample">${esc(result.reason || "Folder contents from Kodi. These are destinations, rather than a media row.")}</p>` : `<div class="bs-preview-empty">${esc(result.reason || "No titles returned by this source.")}</div>`;
      } catch (error) { if (node.isConnected) node.innerHTML = `<div class="bs-preview-empty">Preview unavailable: ${esc(error.message)}</div>`; }
    });
    renderDraftStatus();
  }
  function selectSection(id) {
    selected = id; replaceIndex = null;
    const source = section();
    if (!drafts[id] && source) {
      const value = {section_id:id,label:source.label,rows:(source.rows || []).map(widgetSource),revision:layout.revision};
      value.base = JSON.stringify(widgetLayoutBody(value));
      const saved = savedDrafts[id];
      drafts[id] = saved?.base === value.base && Array.isArray(saved.rows) ? saved : value;
    }
    renderSections(); renderCurrent();
  }
  function renderSections() {
    $b("#bs-sections").innerHTML = (layout?.sections || []).map(s => `<button role="tab" aria-selected="${selected === s.id}" data-section="${esc(s.id)}">${esc(drafts[s.id]?.label || s.label)}<small>${drafts[s.id]?.rows.length ?? s.rows.length}</small></button>`).join("") + (drafts.new ? `<button role="tab" aria-selected="${selected === "new"}" data-section="new">${esc(drafts.new.label)}<small>draft</small></button>` : "") + `<button id="bs-new-section" class="bs-new-section" ${!layout?.new_section?.available ? "disabled" : ""} title="${esc(layout?.new_section?.reason || "Create an independent section")}">+ Independent hub</button>`;
    $b("#bs-new-section").onclick = () => { const label = prompt("Name the new independent section:", "New section"); if (!label?.trim()) return; const value = {section_id:"new",label:label.trim(),rows:[],base:"",revision:layout.revision}; drafts.new = value; selected = "new"; saveDrafts(); renderSections(); renderCurrent(); };
  }
  async function loadLayout(discard = false) {
    const result = await api("/api/widgets/layout", undefined, abort.signal); if (!active()) return;
    layout = result;
    // Older service versions can still display their real Custom Hub, without invented defaults.
    if (!Array.isArray(layout.sections)) layout.sections = [{id:"hub:customhub",label:(layout.customhub_menu_labels || [])[0] || "Custom Hub",rows:(layout.customhub || []).map((r,i) => ({...r,id:"legacy-"+i,path:""})),editable:false,reasons:["Update the Shield service to read and edit all Bingie sections."]}];
    layout.sections = widgetVisibleSections(layout);
    const inactive = layout.inactive_sections || [];
    $b("#bs-hub-help-text").textContent = "Tabs follow your TV's enabled menu entries. Movies, Shows and Favorites open widget hubs; Recently Watched is a row within a hub. Menu shortcuts such as iPlayer open a directory. " + (layout.customhub_occupied ? `Bingie's built-in Custom hub is already used by ${(layout.customhub_menu_labels || ["Favorites"]).join(", ")}. Extra menu shortcuts can be added in Kodi; another independent widget hub requires a skin extension.` : "Bingie provides one built-in Custom hub. An unused one can be configured here.");
    $b("#bs-inactive-sections").innerHTML=inactive.length ? `<p>Other skin hubs, outside your enabled TV menu:</p>${inactive.map(s=>`<button class="action" data-inactive-section="${esc(s.id)}">${esc(s.label)}${s.disabled ? " · disabled" : ""}</button>`).join("")}` : "";
    if (!layout.new_section) layout.new_section = {available:layout.new_section_available ?? (layout.can_apply && !layout.customhub_occupied),reason:(layout.new_section_reasons || []).join(" ") || (layout.customhub_occupied ? "The independent Custom Hub is already used by " + (layout.customhub_menu_labels || ["another section"]).join(", ") : (layout.reasons || []).join(" "))};
    if (discard) { drafts = {}; savedDrafts = {}; saveDrafts(); }
    $b("#bs-connection").textContent = layout.read_only ? "Layout read only" : "Connected to Shield";
    const available = layout.sections.filter(s => s.rows.length);
    selectSection([...layout.sections,...(layout.inactive_sections || [])].some(s => s.id === selected) ? selected : (available.find(s => s.editable) || available[0] || layout.sections[0])?.id || "");
    notice("");
  }
  function jumpCatalogue() { $b("#bs-catalogue").scrollIntoView({behavior:"smooth",block:"start"}); renderDestination(); }
  function register(path, label, addon, crumbs, depth = 0, skip = "", usefulness = null) {
    if (seen.has(path) || entries.length >= 1200) return seen.get(path);
    const entry = {id:entries.length,path,label,addon,crumbs,depth,status:skip ? "skipped" : "queued",reason:skip,result:null,usefulness};
    seen.set(path,entry); entries.push(entry); return entry;
  }
  function discover(entry, result) {
    for (const child of result.children || []) {
      if (child.traversable) register(child.path,child.label,entry.addon,[...entry.crumbs,child.label],entry.depth+1,entry.depth >= 7 ? "Depth limit reached; use this path in Kodi." : "",child.usefulness);
    }
    for (const [i,item] of (result.items || []).entries()) {
      if (item.filetype === "directory" && item.skip_reason && ["blocked","navigation"].includes(item.classification) && !item.year && !item.mpaa && !(item.genre || []).length && !/pagination/i.test(item.skip_reason)) register(item.path || entry.path+"#blocked-"+i,item.label,entry.addon,[...entry.crumbs,item.label],entry.depth+1,item.skip_reason,item.usefulness);
    }
  }
  function ranking(entry) {
    const current = (layout?.sections || []).some(s => s.rows.some(row => widgetSource(row).path === entry.path));
    const fallback = /popular|trending/i.test(entry.label) ? 105 : /latest|recent|premieres/i.test(entry.label) ? 100 : /watchlist|continue watching|next episode/i.test(entry.label) ? 80 : /recommend|top rated/i.test(entry.label) ? 70 : /genre|year|language|network|studio|people/i.test(entry.label) ? 5 : 20;
    const observation = entry.result || ["error","skipped"].includes(entry.status) ? widgetCatalogueObservation(entry.result,entry.status) : observations.get(entry.path) || {kind:"unknown"};
    const score = (entry.usefulness?.score ?? fallback + (entry.addon.addon_id === "plugin.video.pov" ? 10 : 0)) + (current ? 20 : 0);
    return {score,tier:widgetCatalogueTier(observation),kind:observation.kind,reason:observation.kind === "empty" ? (entry.result ? "Checked: this folder is empty" : "Previously empty · preview to check again") : observation.kind === "error" ? "Preview unavailable" : observation.kind === "skipped" ? "Requires a manual step in Kodi" : current ? "Already used on your TV" : /popular|trending|most watched/i.test(entry.label) ? "Popular discovery list" : /latest|recent|premieres/i.test(entry.label) ? "Fresh releases" : /watchlist|continue watching|next episode/i.test(entry.label) ? "Your saved or ongoing viewing" : /recommend/i.test(entry.label) ? "Recommendations" : /top rated/i.test(entry.label) ? "Highly rated titles" : /family|kids|children/i.test(entry.label) ? "Family browsing" : "More specialised browsing"};
  }
  function filteredEntries() {
    const query = $b("#bs-search").value.trim().toLowerCase();
    return entries.filter(e => (e.depth > 0 || e.status === "error" || e.status === "skipped" || e.result?.can_use_as_widget) && chosenSources.has(e.addon.addon_id) && (!query || e.crumbs.join(" ").toLowerCase().includes(query))).sort((a,b) => ($b("#bs-sort").value === "name" ? 0 : ranking(b).tier-ranking(a).tier || ranking(b).score-ranking(a).score) || a.crumbs.join(" / ").localeCompare(b.crumbs.join(" / ")) || a.id-b.id);
  }
  function orderedCatalogue() {
    const matches = filteredEntries();
    if (indexing) return matches;
    const key = [[...chosenSources].sort().join("|"),$b("#bs-search").value.trim().toLowerCase(),$b("#bs-sort").value].join("\n");
    if (key !== catalogueKey) { catalogueOrder=[]; catalogueKey=key; }
    const included = new Set(catalogueOrder.map(e => e.id));
    // Keep page boundaries stable as deeper folders are discovered.
    catalogueOrder.push(...matches.filter(e => !included.has(e.id)));
    return catalogueOrder;
  }
  function renderEntry(entry) {
    const element = $b(`#bs-folder-${entry.id}`); if (!element) return;
    const result = entry.result, items = widgetMediaItems(result), usable = result?.can_use_as_widget === true;
    const pathDescription = entry.crumbs.join(" › "), rank = ranking(entry);
    let contents;
    if (entry.status === "error") contents = `<p class="bs-preview-empty bs-error">${esc(entry.reason)} <button class="action" data-retry-folder="${entry.id}">Retry</button></p>`;
    else if (entry.status === "skipped") contents = `<p class="bs-preview-empty">${esc(entry.reason)}</p>`;
    else if (!result) contents = `<div class="bs-skeleton"><span></span><span></span><span></span><span></span><p>${entry.status === "loading" ? "Reading live folder…" : "Preview not checked yet"}${entry.status !== "loading" ? ` <button class="action" data-load-folder="${entry.id}">Load preview</button>` : ""}</p></div>`;
    else if (items.length) contents = posters(items) + `<p class="bs-sample">${esc(result.sample?.message || `Preview of ${Math.min(items.length,12)} titles from this folder.`)}${items.length > 12 ? ` Showing ${Math.min(items.length,12)} here.` : ""}</p>`;
    else if ((result.items || []).length) contents = `<div class="bs-subfolders">${result.items.slice(0,40).map(item => `<span class="${item.traversable ? "" : "bs-muted-chip"}">▱ ${esc(item.label)}</span>`).join("")}</div><p class="bs-sample">Subfolders are listed separately in the catalogue. Search by name to find one.${result.items.length > 40 ? " More entries are available in Kodi." : ""}</p>`;
    else contents = '<p class="bs-preview-empty">This folder returned no items.</p>';
    element.innerHTML = `<div class="bs-folder-heading"><div><p class="bs-breadcrumb">${esc(pathDescription)}</p><h4>${esc(entry.label)}${result ? `<span class="bs-folder-type">${items.length ? "Media row" : "Folder"}</span>` : ""}</h4><p class="bs-rank-reason">${esc(rank.reason)}${entry.addon.addon_id === "plugin.video.pov" ? " · POV" : ""}</p></div><div class="bs-actions">${usable ? `<button class="bs-add-source" data-add-source="${entry.id}"></button>` : ""}<button class="action" data-copy-folder="${entry.id}" aria-label="Copy path for ${esc(entry.label)}">Copy path</button></div></div>${contents}<details class="bs-path-details"><summary>Exact path &amp; manual navigation</summary><p>Add-ons → Video add-ons → ${esc(pathDescription)}</p><code>${esc(entry.path)}</code>${(result?.skips || []).length ? `<p>Not auto-expanded: ${esc(result.skips.map(s => `${s.label} (${s.reason || s.skip_reason || "not a menu folder"})`).join("; "))}</p>` : ""}</details>`;
    updateAddButtons();
  }
  function progress() {
    if (!active()) return;
    const total = orderedCatalogue().length, pages = Math.max(1,Math.ceil(total/pageSize));
    const pending = pageEntries.filter(e => ["queued","loading"].includes(e.status)).length;
    $b("#bs-progress").textContent = indexing ? `Reading folder names from add-on menus · ${total} discovered. Media previews wait until the index is ready.` : `${total} folders discovered · ${pending ? pending + " previews not checked yet on this page" : "This page is ready"}${entries.length >= 1200 ? " · Catalogue limit reached" : ""}`;
    root.querySelectorAll(".bs-page-label").forEach(node => { node.textContent = total ? `Page ${page} of ${pages} · ${Math.min((page-1)*pageSize+1,total)}–${Math.min((page-1)*pageSize+pageEntries.length,total)} of ${total}` : "No folders"; });
    root.querySelectorAll("[data-page-step]").forEach(button => { button.disabled = indexing || (+button.dataset.pageStep < 0 ? page <= 1 : page >= pages); });
  }
  async function previewPage(run, catalogRun) {
    const batch = [...pageEntries];
    for (const entry of batch) {
      if (!active() || run !== pageRun || catalogRun !== epoch) return;
      if (entry.result || ["skipped","error"].includes(entry.status)) continue;
      entry.status = "loading"; renderEntry(entry); progress();
      try {
        const result = await readFolder(entry.path); if (!active() || catalogRun !== epoch) return;
        entry.result = result; entry.status = "loaded"; discover(entry,result);
      } catch (error) { if (!active() || catalogRun !== epoch) return; entry.status = "error"; entry.reason = error.message; }
      if (run !== pageRun) return;
      renderEntry(entry); progress();
    }
    finishPreviewBatch(run,catalogRun);
  }
  function finishPreviewBatch(run,catalogRun) {
    if (!active() || run !== pageRun || catalogRun !== epoch || $b("#bs-sort").value === "name") return;
    // One stable rebucket per explicit action. Newly promoted unknown folders
    // remain unrequested, preventing empty rows from triggering a fetch loop.
    catalogueOrder = orderedCatalogue().map((entry,index) => ({entry,index})).sort((a,b) => ranking(b.entry).tier-ranking(a.entry).tier || a.index-b.index).map(value => value.entry);
    showPage(page,false,false);
  }
  function showPage(next = 1, scroll = false, loadPreviews = true) {
    const list = orderedCatalogue(); page = Math.min(Math.max(1,next),Math.max(1,Math.ceil(list.length/pageSize)));
    pageEntries = list.slice((page-1)*pageSize,page*pageSize); pageRun++;
    $b("#bs-folders").innerHTML = "";
    for (const entry of pageEntries) { const element=document.createElement("article");element.id=`bs-folder-${entry.id}`;element.className="bs-folder-row";$b("#bs-folders").append(element);renderEntry(entry); }
    $b("#bs-catalogue-empty").hidden = !!list.length || indexing; progress();
    if (scroll) $b("#bs-catalogue").scrollIntoView({behavior:"smooth",block:"start"});
    if (!indexing && loadPreviews) previewPage(pageRun,epoch);
  }
  async function startCatalogue(refresh = false) {
    const run = ++epoch; pageRun++; entries=[]; seen=new Map(); pageEntries=[]; catalogueOrder=[]; catalogueKey=""; page=1; indexing=true;
    refreshCatalog=refresh; if(refresh){cache.clear();observations.clear();try{localStorage.removeItem(observationKey);}catch(_){}} $b("#bs-folders").innerHTML=""; $b("#bs-catalogue-empty").hidden=true;
    const ordered = sources.filter(source => chosenSources.has(source.addon_id)).sort((a,b) => Number(b.addon_id === "plugin.video.pov")-Number(a.addon_id === "plugin.video.pov"));
    // Read a bounded menu index, never a recursive catalogue of every media list.
    for (const source of ordered) {
      if (!active() || run !== epoch) return;
      const entry=register(source.path,source.label,source,[source.label],0,source.enabled !== true ? "This add-on is disabled or its state is unknown." : source.traversable === false ? source.skip_reason || "Open this add-on in Kodi." : "",source.usefulness);
      if (!entry || entry.status === "skipped") continue;
      try {
        const result=await readFolder(entry.path); if(!active() || run!==epoch)return;
        entry.result=result;entry.status="loaded";discover(entry,result);progress();
        const menus=(result.children || []).filter(child=>child.traversable && /^(movies|tv shows|shows|my lists|my movies|my tv shows)$/i.test(child.label)).slice(0,3);
        for (const child of menus) {
          const menu=seen.get(child.path); if(!menu || menu.result)continue;
          try { const data=await readFolder(menu.path);if(!active() || run!==epoch)return;menu.result=data;menu.status="loaded";discover(menu,data); }
          catch(error) { if(!active() || run!==epoch)return;menu.status="error";menu.reason=error.message; }
          progress();
        }
      } catch(error) { if(!active() || run!==epoch)return;entry.status="error";entry.reason=error.message; }
    }
    // Saved widget sources need not appear in an add-on's top-level menus.
    for (const s of layout?.sections || []) for (const row of s.rows) {
      const original=widgetSource(row), source=ordered.find(a=>original.path.startsWith("plugin://"+a.addon_id+"/"));
      if(source)register(original.path,row.label,source,[source.label,"On your TV",row.label],1,source.enabled !== true ? "This add-on is disabled or its state is unknown." : "");
    }
    indexing=false; showPage(1);
  }
  function mutateRow(index, operation) { if (!canEdit()) return; operation(draft().rows,index); replaceIndex = null; saveDrafts(); renderSections(); renderCurrent(); }
  root.addEventListener("click", async event => {
    const button = event.target.closest("button"); if (!button) return;
    try {
      if (button.dataset.section) selectSection(button.dataset.section);
      if (button.dataset.inactiveSection) selectSection(button.dataset.inactiveSection);
      if (button.dataset.sourceChoice) { chooseSources(button.dataset.sourceChoice === "all" ? sources.map(source => source.addon_id) : button.dataset.sourceChoice === "none" ? [] : widgetRecommendedSources(sources)); return; }
      if (button.dataset.pageStep !== undefined && !indexing) showPage(page + Number(button.dataset.pageStep),true);
      if (button.dataset.replaceRow !== undefined) { replaceIndex = +button.dataset.replaceRow; renderCurrent(); jumpCatalogue(); }
      if (button.dataset.renameRow !== undefined) { const i = +button.dataset.renameRow, label = prompt("Row name:", draft().rows[i].label); if (label?.trim()) mutateRow(i, rows => { rows[i].label = label.trim(); }); }
      if (button.dataset.moveRow !== undefined) { const [i,delta] = button.dataset.moveRow.split(",").map(Number); mutateRow(i, rows => { [rows[i],rows[i+delta]] = [rows[i+delta],rows[i]]; }); }
      if (button.dataset.removeRow !== undefined) mutateRow(+button.dataset.removeRow,(rows,i) => rows.splice(i,1));
      if (button.dataset.addSource !== undefined && canEdit()) {
        const entry = entries[+button.dataset.addSource]; if (!entry.result?.can_use_as_widget) return;
        const row = {label:entry.label,path:entry.path,breadcrumb:entry.crumbs,filtered:false,maxRating:"12A"};
        if (replaceIndex !== null) { const old = draft().rows[replaceIndex]; draft().rows[replaceIndex] = {...old,path:row.path,breadcrumb:row.breadcrumb}; }
        else if (draft().rows.length < (layout.max_rows || 20)) draft().rows.push(row);
        const message = replaceIndex !== null ? "Source replaced in your draft." : `“${entry.label}” added to ${draft().label}.`;
        replaceIndex = null; saveDrafts(); renderSections(); renderCurrent(); notice(message + " Review changes above to save to the TV.");
      }
      if (button.dataset.copyFolder !== undefined) { const entry = entries[+button.dataset.copyFolder]; try { await navigator.clipboard.writeText(entry.path); notice("Exact folder path copied."); } catch (_) { const node = $b(`#bs-folder-${entry.id} details`); node.open = true; notice("Select and copy the exact path shown in the expanded details."); } }
      if (button.dataset.retryFolder !== undefined) { const entry = entries[+button.dataset.retryFolder]; cache.delete(entry.path); entry.status = "queued"; entry.result = null; showPage(page); }
      if (button.dataset.loadFolder !== undefined) {
        const entry = entries[+button.dataset.loadFolder], run = ++pageRun, catalogRun = epoch;
        if (!entry || entry.status === "loading") return;
        entry.status="loading";renderEntry(entry);progress();
        try {const result=await readFolder(entry.path);if(!active() || catalogRun!==epoch)return;entry.result=result;entry.status="loaded";discover(entry,result);}
        catch(error){if(!active() || catalogRun!==epoch)return;entry.status="error";entry.reason=error.message;}
        if(run===pageRun){renderEntry(entry);finishPreviewBatch(run,catalogRun);progress();}
      }
    } catch (error) { notice(error.message,true); }
  });
  root.addEventListener("change", event => { const source = event.target.closest("[data-catalogue-source]"); if (source) { const ids=new Set(chosenSources);source.checked ? ids.add(source.dataset.catalogueSource) : ids.delete(source.dataset.catalogueSource);chooseSources([...ids]);return; } const select = event.target.closest("[data-row-filter]"); if (!select) return; mutateRow(+select.dataset.rowFilter,(rows,i) => { rows[i].filtered = select.value !== "none"; rows[i].maxRating = select.value === "none" ? "12A" : select.value; }); });
  $b("#bs-add-row").onclick = () => { replaceIndex = null; jumpCatalogue(); };
  $b("#bs-jump-catalogue").onclick = event => { event.preventDefault(); jumpCatalogue(); };
  $b("#bs-rename-section").onclick = () => { const name = prompt("Section name:",draft().label); if (name?.trim()) { draft().label = name.trim(); saveDrafts(); renderSections(); renderCurrent(); } };
  $b("#bs-reset").onclick = () => { if (!confirm("Discard this section’s unsaved draft and reload its saved TV rows?")) return; delete drafts[selected]; delete savedDrafts[selected]; if (selected === "new") selected = layout.sections[0]?.id; selectSection(selected); saveDrafts(); };
  $b("#bs-reload-layout").onclick = async () => { if (Object.values(drafts).some(d => JSON.stringify(widgetLayoutBody(d)) !== d.base) && !confirm("Discard unsaved drafts and refresh the TV layout?")) return; try { await loadLayout(true); } catch(error) { notice(error.message,true); } };
  let searchTimer;
  $b("#bs-search").oninput = () => { clearTimeout(searchTimer); searchTimer=setTimeout(()=>showPage(1),250); };
  $b("#bs-sort").onchange = () => showPage(1);
  $b("#bs-refresh-catalogue").onclick = () => startCatalogue(true);
  $b("#bs-export").onclick = () => { if (!draft()) return; const url = URL.createObjectURL(new Blob([JSON.stringify(widgetPlan(draft()),null,2)],{type:"application/json"})); const a = document.createElement("a"); a.href=url; a.download="bingie-section.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); };
  $b("#bs-import").onclick = () => $b("#bs-import-file").click();
  $b("#bs-import-file").onchange = async event => { const file=event.target.files[0]; if (!file || !canEdit()) return; try { if(file.size>300000) throw Error("Plan file is too large."); const plan = parseWidgetPlan(JSON.parse(await file.text())); if(draft().rows.length+plan.rows.length>20) throw Error("This would exceed the 20-row limit. Remove some rows first."); draft().rows.push(...plan.rows.map(r => ({...r,maxRating:r.maxRating || plan.maxRating}))); saveDrafts(); renderSections(); renderCurrent(); notice(`${plan.rows.length} rows imported into ${draft().label}. Review before applying.`); } catch(error) { notice(error.message,true); } finally { event.target.value=""; } };
  $b("#bs-preset").onclick = async event => { const button=event.currentTarget; if(!canEdit()) return; button.disabled=true; try { const result=await api("/api/widgets/suggestions",{},abort.signal); if(draft().rows.length+result.rows.length>20) throw Error("This preset would exceed the 20-row limit."); draft().rows.push(...result.rows.map(r => ({...r,maxRating:"12A"}))); saveDrafts(); renderSections(); renderCurrent(); notice("Family starter rows added to the draft. Their previews show the filtered content."); } catch(error) { notice(error.message,true); } finally { button.disabled=!canEdit(); } };
  $b("#bs-review").onclick = async event => {
    if (!dirty() || !canEdit()) return; const button=event.currentTarget;button.disabled=true;
    try { const body=widgetLayoutBody(draft()), result=await api("/api/widgets/layout/preview",body,abort.signal); if(!active()) return; review={body,result,section:selected};
      $b("#bs-review-content").innerHTML=`<div class="bs-dialog-heading"><div><p class="dash-eyebrow">Review TV changes</p><h3>${esc(draft().label)}</h3></div><button class="bs-icon-button" id="bs-close-review" aria-label="Close review">×</button></div><p>${section()?.rows.length || 0} saved rows → ${draft().rows.length} proposed rows. Only this section will be changed.</p><ol>${draft().rows.map(row => `<li><b>${esc(row.label)}</b><span>${esc((row.breadcrumb || []).join(" › ") || widgetSourceDescription(row) || sourceName(row.path))}${row.filtered ? " · Family " + esc(row.maxRating) : ""}</span></li>`).join("")}</ol>${result.reasons?.length ? `<div class="bs-notice bs-error">${result.reasons.map(esc).join("<br>")}</div>` : ""}<p class="muted">A backup is created first. Existing rows omitted from this draft will be removed from this section.</p><div class="bs-actions"><button class="bs-save" id="bs-apply" ${!result.can_apply ? "disabled" : ""}>Apply to TV</button><button class="action" id="bs-cancel-review">Keep editing</button></div><p id="bs-apply-result" role="status"></p>`;
      const dialog=$b("#bs-review-dialog");dialog.showModal(); $b("#bs-close-review").onclick=()=>dialog.close();$b("#bs-cancel-review").onclick=()=>dialog.close();
      $b("#bs-apply").onclick=async applyEvent=>{ const applyButton=applyEvent.currentTarget;applyButton.disabled=true;try { const result=await api("/api/widgets/layout/apply",{...review.body,expected_revision:review.result.revision},abort.signal); delete drafts[review.section];delete savedDrafts[review.section];saveDrafts();dialog.close();await loadLayout();notice(`Section saved. Backup ${result.backup_id}. Rebuild Bingie to show the changes on your TV.`);
        const rebuild=document.createElement("button");rebuild.className="action";rebuild.textContent="Rebuild Bingie menu";$b("#bs-notice").append(rebuild);
        rebuild.onclick=async()=>{rebuild.disabled=true;try{const started=await api("/api/widgets/layout/rebuild",{},abort.signal);if(!started.started)throw Error("Kodi did not start the rebuild.");notice("Rebuild requested. Bingie will refresh after its menu has been generated.");}catch(error){notice(error.message+" You can also restart Kodi to rebuild the menu.",true);}}; } catch(error) { $b("#bs-apply-result").textContent=error.message+" Close this preview and review again before retrying."; } };
    } catch(error) { notice(error.message,true); } finally { renderDraftStatus(); }
  };
  window.addEventListener("hashchange",() => { abort.abort();clearTimeout(searchTimer);epoch++;pageRun++; },{once:true});
  const results=await Promise.allSettled([api("/api/widgets/sources",undefined,abort.signal),loadLayout()]);
  if(!active()) return;
  if(results[0].status==="fulfilled") { sources=results[0].value.sources || []; chosenSources=new Set((savedSources ?? widgetRecommendedSources(sources)).filter(id => sources.some(source => source.addon_id === id)));renderSources();startCatalogue();if(draft())renderCurrent(); }
  else notice("Could not load source add-ons: "+results[0].reason.message,true);
  if(results[1].status==="rejected") { $b("#bs-section-name").textContent="TV layout unavailable"; $b("#bs-section-detail").textContent=results[1].reason.message; notice("Source browsing still works. Connect to the Shield service to read your current sections.",true); }
}
