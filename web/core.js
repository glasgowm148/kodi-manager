/* Shared browser helpers: escaping, API requests, notices, dialogs and clipboard.
   Loaded before every other script. Nothing here touches the page until called. */
const $ = s => document.querySelector(s);
const ESCAPES = {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;","`":"&#96;"};
const esc = s => String(s ?? "").replace(/[&<>"'`]/g, c => ESCAPES[c]);
const WRITE_HINT = "Turn on “Enable writes” in Kodi Manager’s add-on settings in Kodi to make changes.";
const TOKEN_KEY = "bsa_token";
const session = {token: "", onUnauthorized: null};

class ApiError extends Error {
  constructor(message, {status = 0, code = "", details = null} = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
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

async function request(method, path, body, signal) {
  const headers = {"Content-Type": "application/json"};
  if (session.token) headers.Authorization = "Bearer " + session.token;
  let res;
  try {
    res = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal});
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new ApiError("Couldn’t reach Kodi Manager. Check that Kodi is running and this device is on the same network.", {code: "network"});
  }
  let json = null;
  try { json = await res.json(); } catch (_) { json = null; }
  if (res.status === 401) {
    storeToken("");
    const error = new ApiError(json?.error?.message || "The access token is missing or no longer valid.", {status: 401, code: "unauthorized"});
    if (typeof session.onUnauthorized === "function") session.onUnauthorized(error);
    throw error;
  }
  if (!json || typeof json !== "object") {
    throw new ApiError(`Kodi Manager sent an unexpected response (HTTP ${res.status}).`, {status: res.status, code: "bad_response"});
  }
  if (!json.ok) {
    throw new ApiError(json.error?.message || `Request failed (HTTP ${res.status}).`, {status: res.status, code: json.error?.code || "", details: json.error?.details || null});
  }
  return json.data;
}
function api(path, body, signal) { return request(body ? "POST" : "GET", path, body, signal); }
function apiMethod(method, path, body) { return request(method, path, body); }

function hasDocument() {
  return typeof document !== "undefined" && !!document.body && typeof document.createElement === "function";
}

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
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "action";
    button.textContent = action.label;
    button.addEventListener("click", withErrors(async () => { node.remove(); await action.run(); }));
    node.append(button);
  }
  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "×";
  close.addEventListener("click", () => node.remove());
  node.append(close);
  host.append(node);
  const timeout = options.timeout ?? (tone === "error" || actions.length ? 0 : 6000);
  if (timeout) setTimeout(() => node.remove(), timeout);
  return node;
}

function reportError(error) {
  if (!error || error.name === "AbortError") return;
  const message = error.message || String(error);
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
