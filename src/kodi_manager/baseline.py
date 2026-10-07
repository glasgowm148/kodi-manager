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
import os
import re

try:
    from .fsutil import atomic_write_json, atomic_write_text, path_lock
except ImportError:
    from fsutil import atomic_write_json, atomic_write_text, path_lock

KINDS = ("addon_setting", "kodi_setting", "addon_xml")
_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


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
    if item["kind"] == "addon_setting" and item["addon"] == "service.kodi.addonadmin":
        raise ValueError("Kodi Manager's own settings cannot be protected here")
    if item["kind"] == "kodi_setting" and item["id"].split(".")[0] in ("services", "masterlock", "system"):
        raise ValueError("Security and system settings cannot be protected here")
    return item


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
        with path_lock(path):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            new, count = re.subn(r"(<%s>)\s*[^<]*?\s*(</%s>)" % (tag, tag),
                                 lambda m: m.group(1) + str(item["value"]) + m.group(2), text, count=1)
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

    def apply(self, keys=None):
        wanted = set(keys or [])
        applied, failed, restart = [], [], False
        for item in self.items():
            key = item_key(item)
            if wanted and key not in wanted:
                continue
            try:
                if _same(item.get("value"), self.current(item)):
                    continue
                restart = self._write(item) or restart
                applied.append(key)
            except Exception as exc:
                failed.append({"key": key, "error": str(exc)[:200]})
        return {"applied": applied, "failed": failed, "restart_required": restart}

    def capture(self, items):
        """Protect the given items at their current live values (replaces items with the same key)."""
        stored = {item_key(item): item for item in self.items()}
        added = []
        for raw in items:
            item = validate_item(dict(raw))
            value = raw.get("value") if "value" in raw else self.current(item)
            if value is None:
                raise LookupError("%s has no current value to protect" % item_key(item))
            item["value"] = value
            stored[item_key(item)] = {k: item[k] for k in ("kind", "addon", "id", "tag", "value", "label") if k in item}
            added.append(item_key(item))
        self.save(list(stored.values()))
        return {"protected": added, "count": len(stored)}

    def remove(self, keys):
        kept = [item for item in self.items() if item_key(item) not in set(keys)]
        self.save(kept)
        return {"count": len(kept)}
