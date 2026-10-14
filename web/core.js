/* Shared browser helpers: escaping, API requests, notices, dialogs, clipboard and theme.
   Loaded first, in <head>. Apart from applying a saved light/dark choice, nothing here
   touches the page until called. */
const $ = s => document.querySelector(s);
const ESCAPES = {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;","`":"&#96;"};
const esc = s => String(s ?? "").replace(/[&<>"'`]/g, c => ESCAPES[c]);
const WRITE_HINT = "Turn on “Enable writes” in Kodi Manager’s add-on settings in Kodi to make changes.";
const TOKEN_KEY = "bsa_token";
const session = {token: "", onUnauthorized: null};

class ApiError extends Error {
  constructor(message, {status = 0, code = "", details = null, operation = null, outcome = "failed"} = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.operation = operation;
    this.outcome = operation?.outcome || outcome;
  }
}

function storedToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
}
function storeToken(token) {
  session.token = token || "";
  try { if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY); } catch (_) {}
}
/* A dashboard link may carry the token in the fragment only: fragments are never sent to the server. */
function tokenFromHash(hash) {
  const match = /^#token=([^&]+)/.exec(String(hash || ""));
  if (!match) return "";
  try { return decodeURIComponent(match[1]); } catch (_) { return ""; }
}
function dashboardLink(origin, token) {
  return `${String(origin).replace(/\/+$/, "")}/#token=${encodeURIComponent(token || "")}`;
}

const REQUEST_TIMEOUT_MS = 60000;
async function request(method, path, body, signal) {
  const headers = {"Content-Type": "application/json"};
  let correlation = "";
  if (globalThis.crypto?.getRandomValues) {
    correlation = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
    headers["X-Correlation-ID"] = correlation;
  }
  const mayWrite = method !== "GET";
  const sentToken = session.token;
  if (sentToken) headers.Authorization = "Bearer " + sentToken;
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal?.aborted) cancel();
  else signal?.addEventListener("abort", cancel, {once:true});
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; cancel(); }, REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal:controller.signal});
    let json = null;
    try { json = await res.json(); } catch (error) {
      if (controller.signal.aborted) throw error;
    }
    if (res.status === 401) {
      // A late reply from an old profile/token must not sign out a newly authenticated browser.
      if (sentToken !== session.token) {
        const error = new Error("Sign-in changed while the request was running.");
        error.name = "AbortError";
        throw error;
      }
      storeToken("");
      const error = new ApiError(json?.error?.message || "The access token is missing or no longer valid.", {status: 401, code: "unauthorized", operation: json?.operation});
      if (typeof session.onUnauthorized === "function") session.onUnauthorized(error);
      throw error;
    }
    if (!json || typeof json !== "object" || typeof json.ok !== "boolean" || (json.ok && !("data" in json))) {
      throw new ApiError(`Kodi Manager sent an unexpected response (HTTP ${res.status}).`, {status: res.status, code: mayWrite ? "invalid_response" : "bad_response", outcome: mayWrite ? "unknown" : "failed", operation: {correlation_id: correlation, outcome: mayWrite ? "unknown" : "failed"}});
    }
    if (!json.ok) {
      throw new ApiError(json.error?.message || `Request failed (HTTP ${res.status}).`, {status: res.status, code: json.error?.code || "", details: json.error?.details || null, operation: json.operation});
    }
    return json.data;
  } catch (error) {
    if (timedOut) throw new ApiError("Kodi Manager took too long to reply. Kodi may still be working; check the current state before trying a change again.", {code: mayWrite ? "outcome_unknown" : "timeout", outcome: mayWrite ? "unknown" : "failed", operation: {correlation_id: correlation, outcome: mayWrite ? "unknown" : "failed"}});
    if (error instanceof ApiError) throw error;
    if (error && error.name === "AbortError") throw error;
    throw new ApiError("Couldn’t reach Kodi Manager. Check that Kodi is running and this device is on the same network.", {code: mayWrite ? "outcome_unknown" : "network", outcome: mayWrite ? "unknown" : "failed", operation: {correlation_id: correlation, outcome: mayWrite ? "unknown" : "failed"}});
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
function api(path, body, signal) { return request(body ? "POST" : "GET", path, body, signal); }
function apiMethod(method, path, body) { return request(method, path, body); }

function hasDocument() {
  return typeof document !== "undefined" && !!document.body && typeof document.createElement === "function";
}

const ACTION_TOAST_MS = 60000;
function toast(message, tone = "info", options = {}) {
  if (!hasDocument()) return null;
  let host = document.getElementById("toasts");
  if (!host) {
    host = document.createElement("div");
    host.id = "toasts";
    host.className = "toasts";
    host.setAttribute("aria-live", "polite");
    document.body.append(host);
  }
  const node = document.createElement("div");
  node.className = `toast toast-${tone}`;
  node.setAttribute("role", tone === "error" ? "alert" : "status");
  const text = document.createElement("span");
  text.textContent = message;
  node.append(text);
  const actions = options.actions || [];
  // Action toasts (Undo…) expire: a stray tap much later must not roll back newer changes.
  const timeout = options.timeout ?? (actions.length ? ACTION_TOAST_MS : tone === "error" ? 0 : 6000);
  const shownAt = Date.now();
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "action";
    button.textContent = action.label;
    // Timers can fire late in a suspended tab; an expired action does nothing.
    button.addEventListener("click", withErrors(async () => { node.remove(); if (timeout && Date.now() - shownAt > timeout) return; await action.run(); }));
    node.append(button);
  }
  if (actions.length && typeof window !== "undefined" && typeof window.addEventListener === "function") window.addEventListener("hashchange", () => node.remove(), {once:true});
  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "×";
  close.addEventListener("click", () => node.remove());
  node.append(close);
  host.append(node);
  if (timeout) setTimeout(() => node.remove(), timeout);
  return node;
}

/* Plain-English explanations for API error codes: what happened and what to do next. */
const ERROR_TEXT = {
  playback_active: ["Something is playing on the TV.", "Try again when viewing has finished. Kodi Manager never interrupts what’s on screen."],
  write_disabled: ["Changes are switched off for this Kodi profile.", WRITE_HINT],
  unauthorized: ["This browser isn’t signed in to Kodi Manager.", "Enter the access token shown on the TV."],
  network: ["Couldn’t reach the TV.", "Check that Kodi is running and that this device is on the same home network."],
  timeout: ["Kodi Manager took too long to reply.", "Kodi may still be working. Check the current state before trying a change again."],
  host_not_allowed: ["Open the dashboard by the TV’s IP address.", "Use http://<TV address>:8765 or a .local name rather than another host name."],
  origin_mismatch: ["That request came from another web page and was blocked.", "Use the dashboard itself to make changes."],
  forbidden: ["Only devices on your home network can use this dashboard.", ""],
  addon_not_allowed: ["Kodi Manager only edits the add-ons in your playback setup.", "To edit another add-on, add it under “Also allow editing these add-ons” in Kodi Manager’s settings on the TV."],
  trakt_unavailable: ["The Trakt add-on isn’t installed or is turned off.", "Install or enable script.trakt in Kodi, then try again."],
  server_error: ["Kodi Manager hit a problem doing that.", "Inspect current state and the support bundle before retrying a change."],
  outcome_unknown: ["The change may already have completed.", "Inspect current state and recovery references before retrying. Do not repeat the write automatically."],
  invalid_response: ["Manager sent an invalid reply.", "Inspect current state before retrying a change."],
  bad_response: ["The TV sent a reply the dashboard didn’t understand.", "Reload this page. If Kodi Manager was just updated, restart Kodi."]
};
const ERROR_ACCEPTS_DETAIL = new Set(["bad_request", "invalid_pipeline_setting", "account_write_blocked", "switch_player_blocked", "not_found"]);
function friendlyError(error) {
  const code = String(error?.code || "");
  const raw = String(error?.message || error || "Something went wrong.");
  if (ERROR_TEXT[code]) return {code, title:ERROR_TEXT[code][0], hint:ERROR_TEXT[code][1], detail:raw};
  if (ERROR_ACCEPTS_DETAIL.has(code)) return {code, title:code === "not_found" ? "Kodi Manager couldn’t find that." : "That change wasn’t accepted.", hint:raw, detail:raw};
  return {code, title:raw, hint:"", detail:raw};
}
function friendlyMessage(error) {
  const f = friendlyError(error);
  const unknown = error?.outcome === "unknown" && error?.code !== "outcome_unknown" ? " The change may already have completed. Inspect current state before retrying." : "";
  const op = error?.operation;
  const id = /^[0-9a-f]{32}$/.test(op?.operation_id || "") ? op.operation_id : /^[0-9a-f]{32}$/.test(op?.correlation_id || "") ? op.correlation_id : "";
  return (f.hint ? `${f.title} ${f.hint}` : f.title) + unknown + (id ? ` Operation reference: ${id}.` : "");
}

function reportError(error) {
  if (!error || error.name === "AbortError") return;
  const message = friendlyMessage(error);
  if (!toast(message, "error") && typeof console !== "undefined") console.error(message);
}

/* Wrap an async event handler: failures become a visible notice and the clicked button is busy meanwhile. */
function withErrors(fn) {
  return async function handler(event, ...rest) {
    const target = event && event.currentTarget;
    const button = target && target.tagName === "BUTTON" && !target.disabled ? target : null;
    if (button) button.disabled = true;
    try {
      return await fn.call(this, event, ...rest);
    } catch (error) {
      reportError(error);
      return undefined;
    } finally {
      if (button) button.disabled = false;
    }
  };
}

function openDialog(markup, focusSelector) {
  const dialog = document.createElement("dialog");
  dialog.className = "km-dialog";
  dialog.innerHTML = markup;
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector(focusSelector)?.focus();
  return dialog;
}

function confirmDialog({title = "Are you sure?", message = "", detail = "", confirmLabel = "Continue", cancelLabel = "Cancel", danger = false} = {}) {
  if (!hasDocument() || typeof HTMLDialogElement === "undefined") {
    return Promise.resolve(typeof confirm === "function" ? !!confirm([title, message, detail].filter(Boolean).join("\n\n")) : false);
  }
  return new Promise(resolve => {
    const dialog = openDialog(`<form method="dialog"><h2>${esc(title)}</h2>${message ? `<p>${esc(message)}</p>` : ""}${detail ? `<pre>${esc(detail)}</pre>` : ""}<div class="km-dialog-actions"><button value="ok" class="primary${danger ? " danger" : ""}">${esc(confirmLabel)}</button><button value="cancel" class="action">${esc(cancelLabel)}</button></div></form>`, 'button[value="cancel"]');
    dialog.addEventListener("close", () => { resolve(dialog.returnValue === "ok"); dialog.remove(); }, {once: true});
  });
}

function promptDialog({title = "", label = "", value = "", confirmLabel = "OK", type = "text"} = {}) {
  if (!hasDocument() || typeof HTMLDialogElement === "undefined") {
    return Promise.resolve(typeof prompt === "function" ? prompt(label || title, value) : null);
  }
  return new Promise(resolve => {
    const dialog = openDialog(`<form method="dialog"><h2>${esc(title)}</h2><label>${esc(label)}<input name="value" type="${type === "password" ? "password" : "text"}" autocomplete="off" value="${esc(value)}"></label><div class="km-dialog-actions"><button value="ok" class="primary">${esc(confirmLabel)}</button><button value="cancel" class="action" formnovalidate>Cancel</button></div></form>`, "input");
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "ok" ? dialog.querySelector("input").value : null);
      dialog.remove();
    }, {once: true});
  });
}

/* navigator.clipboard only exists on secure origins; the dashboard is usually plain HTTP on the LAN. */
async function copyText(text, label = "Text") {
  const value = String(text ?? "");
  try {
    const secure = typeof isSecureContext === "undefined" || isSecureContext;
    if (secure && typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return "clipboard";
    }
  } catch (_) {}
  try {
    if (hasDocument() && typeof document.execCommand === "function") {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.top = "0";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      if (copied) return "execCommand";
    }
  } catch (_) {}
  showCopyFallback(value, label);
  return "manual";
}

function showCopyFallback(text, label) {
  if (!hasDocument() || typeof HTMLDialogElement === "undefined") return;
  const dialog = openDialog(`<form method="dialog"><h2>Copy ${esc(label.toLowerCase())}</h2><p>Your browser blocked automatic copying. Select this text and copy it (Ctrl+C or ⌘C).</p><pre class="copy-fallback" tabindex="0">${esc(text)}</pre><div class="km-dialog-actions"><button value="close" class="primary">Done</button></div></form>`, ".copy-fallback");
  const pre = dialog.querySelector(".copy-fallback");
  try {
    const range = document.createRange();
    range.selectNodeContents(pre);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  } catch (_) {}
  dialog.addEventListener("close", () => dialog.remove(), {once: true});
}

async function copyWithNotice(text, label) {
  const how = await copyText(text, label);
  if (how !== "manual") toast(`${label} copied.`, "ok");
  return how;
}

/* Light/dark theme: "auto" follows the device. The choice is remembered in this browser only. */
const THEME_KEY = "km_theme";
const THEMES = ["auto", "light", "dark"];
function storedTheme() {
  try { const value = localStorage.getItem(THEME_KEY); return THEMES.includes(value) ? value : "auto"; } catch (_) { return "auto"; }
}
function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : "auto";
  if (typeof document !== "undefined" && document.documentElement && typeof document.documentElement.setAttribute === "function") {
    if (value === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", value);
  }
  return value;
}
function nextTheme(theme) { return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]; }
function saveTheme(theme) {
  const value = applyTheme(theme);
  try { if (value === "auto") localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, value); } catch (_) {}
  return value;
}
applyTheme(storedTheme());
