/* Shared settings presentation; API and save actions remain in app.js. */
function settingsBool(value) {
  if (value === true || value === false) return value;
  const text = String(value ?? "").trim().toLowerCase();
  if (["true", "1", "yes", "on"].includes(text)) return true;
  if (["false", "0", "no", "off"].includes(text)) return false;
  return null;
}

function settingPresentationState(setting) {
  const type = String(setting.type || "").toLowerCase();
  const boolean = ["bool", "boolean"].includes(type);
  const value = setting.value;
  const unset = value === undefined || value === null || String(value).trim() === "";
  const defaultKnown = typeof setting.default_known === "boolean" ? setting.default_known
    : Object.prototype.hasOwnProperty.call(setting, "default") && setting.raw?.source !== "raw"
      && !String(setting.warning || "").includes("Schema missing");
  const normalize = input => {
    if (boolean) return settingsBool(input) ?? String(input ?? "");
    if (["number", "integer", "int", "slider"].includes(type) && String(input ?? "").trim() !== "") {
      const number = Number(input);
      if (Number.isFinite(number)) return number;
    }
    return String(input ?? "");
  };
  const isDefault = !defaultKnown ? null : typeof setting.is_default === "boolean" ? setting.is_default
    : normalize(value) === normalize(setting.default);
  return {boolean, enabled: boolean ? settingsBool(value) : null, unset, defaultKnown,
    isDefault, changed: isDefault === false, readOnly: !setting.editable || !!setting.masked,
    secret: !!(setting.secret || setting.is_secret || setting.masked || type === "password"
      || /token|password|passwd|secret|api[._ -]?key|access[._ -]?key|oauth|authorization/i.test(setting.id || ""))};
}

function settingsValueLabel(setting, value, secret = false) {
  if (value === null || value === undefined || String(value).trim() === "") return "Not set";
  if (secret) return "Hidden";
  if (["boolean", "bool"].includes(String(setting.type).toLowerCase())) {
    const enabled = settingsBool(value);
    return enabled === null ? "Unknown" : enabled ? "On" : "Off";
  }
  const option = (setting.options || []).find(item => String(item.value) === String(value));
  return String(option?.label || value);
}

function settingsControlMarkup(setting, index, writeEnabled) {
  const presentation = settingPresentationState(setting);
  const value = String(setting.value ?? "");
  const source = String(setting.source || setting.raw?.source || "settings.xml");
  const normalizedSource = source.includes("settings.db") ? "settings.db" : source === "raw" ? "raw" : "settings.xml";
  const disabled = !setting.editable || !writeEnabled || !!setting.masked;
  const attrs = `id="setting-field-${index}" data-setting="${esc(setting.id)}" data-source="${esc(normalizedSource)}" data-original="${esc(value)}"${presentation.secret ? ' data-secret="true" autocomplete="off"' : ""}${disabled ? " disabled" : ""}`;
  if (presentation.boolean) {
    const onValue = presentation.enabled === true ? value : "true";
    const offValue = presentation.enabled === false ? value : "false";
    return `<select ${attrs}>${presentation.enabled === null ? `<option value="${esc(value)}" selected disabled>Unknown${presentation.unset ? " — not set" : " — current value"}</option>` : ""}<option value="${esc(onValue)}"${presentation.enabled === true ? " selected" : ""}>On</option><option value="${esc(offValue)}"${presentation.enabled === false ? " selected" : ""}>Off</option></select>`;
  }
  if (!presentation.secret && (setting.options || []).length) {
    const known = setting.options.some(option => String(option.value) === value);
    return `<select ${attrs}>${known ? "" : `<option value="${esc(value)}" selected disabled>${esc(value || "Not set")} — current value</option>`}${setting.options.map(option => `<option value="${esc(option.value)}"${String(option.value) === value ? " selected" : ""}>${esc(option.label || option.value)}</option>`).join("")}</select>`;
  }
  return `<div class="settings-control-input"><input ${attrs} type="${presentation.secret ? "password" : "text"}" value="${esc(value)}">${presentation.secret && !setting.masked ? `<button type="button" class="action settings-reveal" data-reveal="setting-field-${index}" aria-controls="setting-field-${index}" aria-pressed="false">Reveal</button>` : ""}</div>`;
}

function settingsRowMarkup(setting, index, writeEnabled) {
  const p = settingPresentationState(setting);
  const title = typeof friendlyName === "function" ? friendlyName(setting.id, setting.label) : setting.label || setting.id;
  const description = setting.description || "";
  const mode = p.isDefault === null ? "Default unknown" : p.isDefault ? "Default" : "Custom";
  const source = setting.value_source === "default" ? "Using add-on default" : ["user", "saved"].includes(setting.value_source) ? "Saved in Kodi" : "";
  const status = p.boolean ? p.enabled === null ? "Unknown" : p.enabled ? "On" : "Off" : p.unset ? "Not set" : "Set";
  return `<div class="settings-row" data-settings-index="${index}"><div class="settings-label"><label for="setting-field-${index}">${esc(title)}</label><div class="settings-row-badges"><span class="settings-state${p.boolean && p.enabled === true ? " settings-state-on" : ""}">${esc(status)}</span><span class="settings-origin${p.changed ? " settings-origin-custom" : ""}">${mode}</span><span class="settings-pending hidden">Unsaved</span></div>${description ? `<p>${esc(description)}</p>` : ""}<details class="settings-details"><summary>Details</summary><code>${esc(setting.id)}</code><p>${esc(source || "Value source unconfirmed")} · ${esc(setting.source || setting.raw?.source || "settings.xml")}</p>${setting.warning ? `<p class="warn">${esc(setting.warning)}</p>` : ""}</details></div><div class="settings-value">${settingsControlMarkup(setting, index, writeEnabled)}<p class="settings-default">Current: <strong data-current-label>${esc(settingsValueLabel(setting, setting.value, p.secret))}</strong> · Default: ${esc(p.defaultKnown ? settingsValueLabel(setting, setting.default, p.secret) : "Unknown")}</p>${setting.masked ? '<p class="muted">Hidden in source; edit in Kodi.</p>' : !setting.editable ? '<p class="muted">Read-only · use native Kodi settings.</p>' : ""}</div></div>`;
}

async function renderAddonSettingsView(aid) {
  if (Object.keys(state.dirtyChanges).length && !confirm("Discard unsaved settings changes?")) return;
  const status = await api("/api/status");
  const data = await api(`/api/addons/${encodeURIComponent(aid)}/settings`);
  state.writeEnabled = !!status.write_enabled;
  clearDirty();
  updateDirtyBar();
  const settings = [];
  const groups = (data.groups || []).map(group => {
    const rows = (group.settings || []).map(setting => {
      const index = settings.push(setting) - 1;
      return settingsRowMarkup(setting, index, state.writeEnabled);
    }).join("");
    return `<section class="settings-category"><h3>${esc(group.label || "Settings")}</h3><div class="settings-category-rows">${rows}</div><p class="settings-category-empty hidden muted">No matching settings in this category.</p></section>`;
  }).join("");
  out(`<div class="settings-page"><div class="panel settings-heading"><h2>${esc(data.name || aid)}</h2><p>See what is on, compare saved values with add-on defaults, and review changes before saving.</p><p class="${state.writeEnabled ? "muted" : "warn"}">${state.writeEnabled ? "Changes stay pending until you choose Save Changes above. A backup is created before saving." : esc(data.read_only_reason || "Read-only: Write Mode is disabled. Enable it in Kodi Manager service settings to edit.")}</p><div class="settings-toolbar"><label for="settings-search">Find a setting<input id="settings-search" type="search" placeholder="Search names, descriptions, or setting IDs"></label><label for="settings-filter">Show<select id="settings-filter"><option value="all">All settings</option><option value="enabled">Enabled booleans</option><option value="disabled">Disabled booleans</option><option value="changed">Changed from default</option><option value="unset">Unset values</option><option value="readonly">Read-only settings</option></select></label></div><p id="settings-match-count" class="muted" role="status" aria-live="polite"></p><p class="muted settings-filter-help">Enabled/Disabled apply to On/Off settings. Changed means the value differs from a known add-on default.</p></div>${groups || '<div class="panel muted">No settings found. Open this add-on’s settings in Kodi.</div>'}<p id="settings-no-matches" class="panel hidden">No settings match. Try All settings or clear your search.</p></div>`);
  const applyFilter = () => {
    const query = $("#settings-search").value.trim().toLowerCase();
    const filter = $("#settings-filter").value;
    let visible = 0;
    document.querySelectorAll(".settings-row[data-settings-index]").forEach(row => {
      const setting = settings[Number(row.dataset.settingsIndex)];
      const input = row.querySelector("[data-setting]");
      const p = settingPresentationState({...setting, value: input.value, is_default: undefined});
      const matches = filter === "all" || filter === "enabled" && p.boolean && p.enabled === true
        || filter === "disabled" && p.boolean && p.enabled === false || filter === "changed" && p.changed
        || filter === "unset" && p.unset || filter === "readonly" && p.readOnly;
      const searchText = `${setting.label || ""} ${setting.id || ""} ${setting.description || ""}`.toLowerCase();
      const show = matches && (!query || searchText.includes(query));
      row.classList.toggle("hidden", !show);
      if (show) visible++;
    });
    document.querySelectorAll(".settings-category").forEach(group => {
      const empty = !group.querySelector(".settings-row:not(.hidden)");
      group.classList.toggle("hidden", empty);
    });
    $("#settings-match-count").textContent = `${visible} of ${settings.length} settings · ${Object.keys(state.dirtyChanges).length} unsaved changes`;
    $("#settings-no-matches").classList.toggle("hidden", visible !== 0 || settings.length === 0);
  };
  $("#settings-search").addEventListener("input", applyFilter);
  $("#settings-filter").addEventListener("change", applyFilter);
  document.querySelectorAll(".settings-page [data-setting]").forEach(input => {
    const update = () => {
      setDirty(aid, input.dataset.setting, input.value, input.dataset.source);
      const row = input.closest(".settings-row");
      const setting = settings[Number(row.dataset.settingsIndex)];
      const p = settingPresentationState({...setting, value: input.value, is_default: undefined});
      row.querySelector(".settings-pending").classList.toggle("hidden", input.value === input.dataset.original);
      const origin = row.querySelector(".settings-origin");
      origin.textContent = p.isDefault === null ? "Default unknown" : p.isDefault ? "Default" : "Custom";
      origin.classList.toggle("settings-origin-custom", p.changed);
      const badge = row.querySelector(".settings-state");
      badge.textContent = p.boolean ? p.enabled === null ? "Unknown" : p.enabled ? "On" : "Off" : p.unset ? "Not set" : "Set";
      badge.classList.toggle("settings-state-on", p.boolean && p.enabled === true);
      row.querySelector("[data-current-label]").textContent = settingsValueLabel(setting, input.value, p.secret);
      $("#settings-match-count").textContent = `${document.querySelectorAll('.settings-row:not(.hidden)').length} of ${settings.length} settings · ${Object.keys(state.dirtyChanges).length} unsaved changes`;
    };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
  });
  document.querySelectorAll(".settings-reveal").forEach(button => button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.reveal);
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.textContent = reveal ? "Hide" : "Reveal";
    button.setAttribute("aria-pressed", String(reveal));
  }));
  applyFilter();
}
