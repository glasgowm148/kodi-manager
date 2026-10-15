"""Skin settings held in Kodi's memory, and Kodi's own settings file (guisettings.xml).

Kodi keeps the active skin's settings (``Skin.String``/``Skin.HasSetting``) in memory and
writes them to ``addon_data/<skin>/settings.xml`` whenever one changes and again when the
skin unloads. A restore that only replaces that file is therefore undone: the next change
or the next exit writes the old values back. ``apply_live`` sets them in memory instead,
through the same builtins the skin's own settings window uses (``Skin.SetBool``,
``Skin.SetString``, ``Skin.Reset``), and reads them back.

``Settings.SetSettingValue`` (JSON-RPC) likewise changes a Kodi setting only in memory;
Kodi writes guisettings.xml on a clean exit, so a crash or force-stop loses it.
``save_core_settings`` makes Kodi write it now.

Kodi 22 source: SkinBuiltins.cpp (each Skin.* builtin ends with CSettings::Save()),
Skin.cpp (CSkinInfo::SetString/SetBool/Reset trigger the settings.xml save; Reset of an
unknown name changes nothing), SettingsOperations.cpp (Settings.GetSkinSettings),
Util.cpp (CUtil::SplitParams, how builtin parameters are split and unquoted).
"""
import xml.etree.ElementTree as ET

# A name no skin uses: Skin.Reset finds nothing to reset, and still runs CSettings::Save().
SAVE_SENTINEL = "kodi_manager.save_settings"


def parse_skin_settings(text):
    """{setting id: (type, value)} from a skin's settings.xml; type is "bool" or "string".

    Mirrors CSkinInfo::SettingsFromXML: a <settings> root, <setting id= (or the old name=)
    type="bool|string">; other types are ignored. Raises ValueError for a file Kodi would
    not load, so a damaged backup is never applied.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("The skin's settings.xml is not valid XML (%s)" % exc) from None
    if root.tag != "settings":
        raise ValueError("The skin's settings.xml has no <settings> root")
    out = {}
    for elem in root.findall("setting"):
        sid = elem.get("id") or elem.get("name") or ""
        kind = elem.get("type")
        if not sid or kind not in ("bool", "string"):
            continue
        text_value = elem.text or ""
        out[sid] = ("bool", text_value.lower() == "true") if kind == "bool" else ("string", text_value)
    return out


def quote_param(value):
    """One builtin parameter, quoted so CUtil::SplitParams gives back exactly ``value``.

    Inside quotes commas and brackets are literal; ``\\"`` is a quote and ``\\\\`` a backslash.
    """
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def builtin_for(sid, kind, value):
    """The builtin that sets one skin setting to ``value`` (an empty string or false resets)."""
    if kind == "bool":
        return "Skin.SetBool(%s,%s)" % (quote_param(sid), "true" if value else "false")
    if value == "":
        return "Skin.Reset(%s)" % quote_param(sid)
    return "Skin.SetString(%s,%s)" % (quote_param(sid), quote_param(value))


def _live(kodi):
    """(skin id, {lower-case id: (id, type, value)}) from Settings.GetSkinSettings (Kodi 20+)."""
    response = kodi.jsonrpc("Settings.GetSkinSettings")
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("settings"), list):
        return None, None
    live = {}
    for entry in result["settings"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        kind = "bool" if entry.get("type") == "boolean" else "string" if entry.get("type") == "string" else None
        if kind:
            value = bool(entry.get("value")) if kind == "bool" else str(entry.get("value") or "")
            live[entry["id"].lower()] = (entry["id"], kind, value)
    return str(result.get("skin") or ""), live


def _default(kind):
    return False if kind == "bool" else ""


def apply_live(kodi, skin_id, wanted):
    """Make the running skin's settings equal ``wanted`` ({id: (type, value)}).

    Settings the skin has that ``wanted`` lacks are reset (that is what their absence from
    settings.xml means). Settings Kodi already has are set through JSON-RPC and saved with one
    builtin at the end; new ones through the builtins. Returns {"status": "applied"|"partial"|"not_active"|"unsupported",
    "changed": n, "failed": [ids]} after reading every value back.
    """
    active, live = _live(kodi)
    if live is None:
        return {"status": "unsupported", "changed": 0, "failed": [],
                "detail": "Kodi did not list its skin settings (Settings.GetSkinSettings needs Kodi 20 or later)"}
    if active != skin_id:
        return {"status": "not_active", "changed": 0, "failed": []}
    # Kodi matches skin setting names without regard to case (StringUtils::EqualsNoCase).
    target = {sid.lower(): (sid, kind, value) for sid, (kind, value) in wanted.items()}
    for key, (sid, kind, _value) in live.items():
        if key not in target:
            target[key] = (sid, kind, _default(kind))
    changed, last_set = 0, None
    for key, (sid, kind, value) in sorted(target.items()):
        now = live.get(key)
        if now is not None and now[1] == kind and now[2] == value:
            continue
        if now is None and value == _default(kind):
            continue   # absent and default: nothing in memory to change
        changed += 1
        # A setting Kodi already has: JSON-RPC changes it in memory only. Each Skin.* builtin
        # also writes guisettings.xml on the GUI thread, which hundreds of them would freeze.
        if now is not None and now[1] == kind:
            reply = kodi.jsonrpc("Settings.SetSkinSettingValue", {"setting": now[0], "value": value})
            if isinstance(reply, dict) and "error" not in reply:
                last_set = (now[0], kind, value)
                continue
        kodi.execute_builtin(builtin_for(sid, kind, value))
        last_set = None
    if last_set is not None:
        # JSON-RPC does not save: one builtin (same value) makes Kodi write settings.xml now.
        kodi.execute_builtin(builtin_for(*last_set))
    failed = []
    if changed:
        _active, after = _live(kodi)
        after = after or {}
        unlisted = {}
        for key, (sid, kind, value) in sorted(target.items()):
            now = after.get(key)
            if now is None:
                # Settings the skin registered while running (Skin.String in its XML) are not in
                # Settings.GetSkinSettings; ask the skin's info labels instead.
                unlisted[key] = (sid, kind, value)
            elif now[1] != kind or now[2] != value:
                failed.append(sid)
        failed += _check_unlisted(kodi, unlisted)
    return {"status": "partial" if failed else "applied", "changed": changed, "failed": sorted(failed)}


def _check_unlisted(kodi, settings):
    """Names in ``settings`` ({key: (id, type, value)}) whose value the skin does not report."""
    strings = {"Skin.String(%s)" % sid: (sid, value) for sid, kind, value in settings.values() if kind == "string"}
    bools = {"Skin.HasSetting(%s)" % sid: (sid, value) for sid, kind, value in settings.values() if kind == "bool"}
    failed = []
    for method, key, labels in (("XBMC.GetInfoLabels", "labels", strings), ("XBMC.GetInfoBooleans", "booleans", bools)):
        if not labels:
            continue
        reply = kodi.jsonrpc(method, {key: sorted(labels)})
        result = reply.get("result") if isinstance(reply, dict) else None
        for label, (sid, value) in labels.items():
            got = result.get(label) if isinstance(result, dict) else None
            if got is None or (bool(got) if isinstance(value, bool) else str(got)) != value:
                failed.append(sid)
    return failed


def save_core_settings(kodi):
    """Make Kodi write its settings (guisettings.xml) now. True when it was asked to."""
    return kodi.execute_builtin("Skin.Reset(%s)" % quote_param(SAVE_SENTINEL))
