"""Protected settings: values you rely on that an add-on or Kodi update can silently reset.

The list lives in the active profile's addon_data (baseline.json). Kodi Manager
compares it with the live values after start-up and every few hours, notifies
when something drifted, and re-applies on request. Three kinds of item:

* ``addon_setting`` – an add-on setting (``addon``, ``id``, ``value``)
* ``kodi_setting``  – a Kodi setting via JSON-RPC (``id``, ``value``)
* ``addon_xml``     – a simple element in an installed add-on's addon.xml,
  e.g. POV's ``reuselanguageinvoker`` (``addon``, ``tag``, ``value``); takes
  effect after Kodi restarts.
"""
import json
import math
import os
import re

try:
    from .fsutil import atomic_write_json, atomic_write_text, path_lock
except ImportError:
    from fsutil import atomic_write_json, atomic_write_text, path_lock

KINDS = ("addon_setting", "kodi_setting", "addon_xml")
_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
SELF_ID = "service.kodi.addonadmin"
LABEL_MAX = 80
# Kodi settings that may be protected: playback, subtitle and library preferences an update
# can reset. Network, add-on sources, security, display and output-device settings are not:
# a value given to capture would be re-applied silently (proxy, unknown sources, a blank TV).
KODI_SETTINGS_ALLOWED = ("general.addonupdates", "general.addonnotifications", "videoplayer.", "subtitles.",
                         "locale.audiolanguage", "locale.subtitlelanguage", "pvrplayback.", "videolibrary.",
                         "musicplayer.", "audiooutput.passthrough", "audiooutput.ac3passthrough",
                         "audiooutput.eac3passthrough", "audiooutput.dtspassthrough",
                         "audiooutput.truehdpassthrough", "audiooutput.dtshdpassthrough")
KODI_SETTINGS_REFUSED = ("videoplayer.adjustrefreshrate",)


def kodi_setting_allowed(setting_id):
    if setting_id in KODI_SETTINGS_REFUSED:
        return False
    return any(setting_id == entry or (entry.endswith(".") and setting_id.startswith(entry))
               for entry in KODI_SETTINGS_ALLOWED)


def item_key(item):
    if item["kind"] == "kodi_setting":
        return "kodi:%s" % item["id"]
    if item["kind"] == "addon_xml":
        return "xml:%s:%s" % (item["addon"], item["tag"])
    return "setting:%s:%s" % (item["addon"], item["id"])


def validate_item(item):
    if not isinstance(item, dict) or item.get("kind") not in KINDS:
        raise ValueError("Each protected setting needs a kind: %s" % ", ".join(KINDS))
    names = {"addon_setting": ("addon", "id"), "kodi_setting": ("id",), "addon_xml": ("addon", "tag")}[item["kind"]]
    for name in names:
        if not isinstance(item.get(name), str) or not _ID.match(item[name]):
            raise ValueError("Invalid %s for a protected setting" % name)
    if item["kind"] in ("addon_setting", "addon_xml") and item["addon"] == SELF_ID:
        raise ValueError("Kodi Manager's own settings cannot be protected here")
    if item["kind"] == "addon_xml" and item["addon"].startswith("skin."):
        raise ValueError("A skin's addon.xml cannot be protected here")
    if item["kind"] == "kodi_setting" and not kodi_setting_allowed(item["id"]):
        raise ValueError("%s cannot be protected here: only playback, subtitle and library settings can"
                         % item["id"])
    label = item.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > LABEL_MAX
                              or re.search(r"[\x00-\x1f\x7f]", label)):
        raise ValueError("A protected setting's label must be one line of at most %d characters" % LABEL_MAX)
    return item


def check_xml_value(value):
    """A value written into addon.xml as element text: no markup, one line.

    ``<``, ``>`` or ``&`` would leave addon.xml malformed (Kodi then drops the
    add-on) or inject elements into it.
    """
    text = str(value)
    if len(text) > 200 or re.search(r"[<>&\r\n]", text):
        raise ValueError("An addon.xml value must be plain text on one line, without < > or &")
    return text


def check_value(value):
    """A value given to protect: one plain JSON scalar (never an object, list or NaN)."""
    if isinstance(value, float) and not math.isfinite(value) or not isinstance(value, (str, bool, int, float)):
        raise ValueError("A protected setting's value must be text, a number or true/false")
    return value


def _same(expected, current):
    if isinstance(expected, bool) or isinstance(current, bool):
        return str(expected).lower() == str(current).lower()
    return str(expected) == str(current)


class Baseline:
    def __init__(self, path, kodi, addon_path=lambda addon_id: ""):
        self.path, self.kodi, self.addon_path = path, kodi, addon_path

    # --- storage ---------------------------------------------------------------
    def items(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        return [item for item in data.get("items", []) if isinstance(item, dict) and item.get("kind") in KINDS]

    def save(self, items):
        with path_lock(self.path):
            atomic_write_json(self.path, {"version": 1, "items": items}, indent=2)

    # --- reading and writing live values -----------------------------------------
    def _xml_file(self, addon_id):
        folder = self.addon_path(addon_id)
        return os.path.join(folder, "addon.xml") if folder else ""

    def current(self, item):
        kind = item["kind"]
        if kind == "addon_setting":
            return self.kodi.get_addon_setting(item["addon"], item["id"])
        if kind == "kodi_setting":
            result = self.kodi.jsonrpc("Settings.GetSettingValue", {"setting": item["id"]})
            return (result.get("result") or {}).get("value")
        path = self._xml_file(item["addon"])
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, TypeError):
            return None
        match = re.search(r"<%s>\s*([^<]*?)\s*</%s>" % (re.escape(item["tag"]), re.escape(item["tag"])), text)
        return match.group(1) if match else None

    def _write(self, item):
        kind = item["kind"]
        if kind == "addon_setting":
            self.kodi.set_addon_setting(item["addon"], item["id"], str(item["value"]))
            return False
        if kind == "kodi_setting":
            result = self.kodi.jsonrpc("Settings.SetSettingValue", {"setting": item["id"], "value": item["value"]})
            if "error" in result:
                raise ValueError("Kodi refused %s" % item["id"])
            return False
        path = self._xml_file(item["addon"])
        tag = re.escape(item["tag"])
        value = check_xml_value(item["value"])   # baseline.json may have been edited by hand
        with path_lock(path):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            new, count = re.subn(r"(<%s>)\s*[^<]*?\s*(</%s>)" % (tag, tag),
                                 lambda m: m.group(1) + value + m.group(2), text, count=1)
            if not count:
                raise ValueError("%s has no <%s> element" % (item["addon"], item["tag"]))
            atomic_write_text(path, new)
        return True   # addon.xml is read when Kodi starts

    # --- public -------------------------------------------------------------------
    def check(self):
        rows = []
        for item in self.items():
            try:
                now = self.current(item)
                error = None
            except Exception as exc:  # one broken item must not hide the others
                now, error = None, type(exc).__name__
            rows.append({"key": item_key(item), "kind": item["kind"], "label": item.get("label") or item_key(item),
                         "expected": item.get("value"), "current": now,
                         "ok": error is None and now is not None and _same(item.get("value"), now),
                         "missing": now is None, "error": error})
        return rows

    def drifted(self):
        return [row for row in self.check() if not row["ok"] and not row["missing"]]

    def apply(self, keys=None, check=None):
        """Re-apply drifted items. ``check(item)`` (optional) raises for items the caller may
        not write, e.g. add-ons outside the write policy; those are reported as failed."""
        wanted = set(keys or [])
        applied, failed, restart = [], [], False
        for item in self.items():
            key = item_key(item)
            if wanted and key not in wanted:
                continue
            try:
                validate_item(dict(item))   # baseline.json may predate a rule or be hand-edited
                if check is not None:
                    check(item)
                if _same(item.get("value"), self.current(item)):
                    continue
                restart = self._write(item) or restart
                applied.append(key)
            except Exception as exc:
                failed.append({"key": key, "error": str(exc)[:200]})
        return {"applied": applied, "failed": failed, "restart_required": restart}

    def capture(self, items, check=None):
        """Protect the given items at their current live values (replaces items with the same key).

        ``check(item)`` (optional) raises for items the caller may not write."""
        # Held across read-modify-write so concurrent captures and removals keep each other's items.
        with path_lock(self.path):
            stored = {item_key(item): item for item in self.items()}
            added = []
            for raw in items:
                item = validate_item(dict(raw))
                if check is not None:
                    check(item)
                value = raw.get("value") if "value" in raw else self.current(item)
                if value is None:
                    raise LookupError("%s has no current value to protect" % item_key(item))
                if "value" in raw:
                    check_value(value)
                if item["kind"] == "addon_xml":
                    check_xml_value(value)
                item["value"] = value
                stored[item_key(item)] = {k: item[k] for k in ("kind", "addon", "id", "tag", "value", "label") if k in item}
                added.append(item_key(item))
            self.save(list(stored.values()))
        return {"protected": added, "count": len(stored)}

    def remove(self, keys):
        with path_lock(self.path):
            kept = [item for item in self.items() if item_key(item) not in set(keys)]
            self.save(kept)
        return {"count": len(kept)}
