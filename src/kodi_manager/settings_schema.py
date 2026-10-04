import os
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

try:
    from .language_resolver import LanguageResolver
    from .validation import is_secret_like, mask_value, setting_editable
    from .kodi_api import exists as path_exists, read_text
except ImportError:
    from language_resolver import LanguageResolver
    from validation import is_secret_like, mask_value, setting_editable
    try:
        from kodi_api import exists as path_exists, read_text
    except ImportError:
        path_exists = os.path.exists
        def read_text(path):
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()


def setting_description(setting_id="", label=""):
    sid = (setting_id or "").lower()
    if sid.endswith(".priority"):
        return "Order used when choosing this provider. Lower number usually means higher priority."
    if sid.endswith(".enabled"):
        return "Turn this integration on or off."
    if sid.endswith(".token"):
        return "Access token used by the add-on."
    if sid.endswith(".refresh"):
        return "Refresh token used to renew access."
    if sid.endswith(".secret"):
        return "Client secret used for authorization."
    if "tmdb" in sid:
        return "TMDb metadata/account setting."
    if "trakt" in sid:
        return "Trakt account or playback-history integration setting."
    if "debrid" in sid or sid.startswith(("rd.", "ad.", "pm.", "tb.", "ed.", "oc.")):
        return "Debrid/account integration setting."
    if "scraper" in sid or "provider" in sid:
        return "Provider/scraper behavior setting."
    if "autoplay" in sid:
        return "Automatic playback behavior."
    return "Kodi add-on setting. Change only if you know this behavior."


def _attrs(elem):
    return dict(elem.attrib)


def _same_value(value, default, stype):
    if stype.lower() in ("bool", "boolean"):
        return str(value).strip().lower() == str(default).strip().lower()
    if stype.lower() in ("int", "integer", "number", "float", "slider"):
        try:
            return Decimal(str(value)) == Decimal(str(default))
        except InvalidOperation:
            pass
    return str(value) == str(default)


def parse_user_settings(path):
    values = {}
    if not path or not path_exists(path):
        return values
    try:
        root = ET.fromstring(read_text(path))
    except ET.ParseError:
        return values
    for elem in root.iter("setting"):
        sid = elem.get("id")
        if not sid:
            continue
        values[sid] = elem.get("value") if elem.get("value") is not None else (elem.text or "")
    return values


def _parse_options(elem, resolver=None):
    raw = elem.get("values") or elem.get("lvalues") or elem.get("entries")
    if raw:
        indexed = elem.get("type") == "enum" and str(elem.get("default", "")).isdigit()
        return [{"value": str(i) if indexed else part, "label": resolver.resolve(part) if resolver and elem.get("lvalues") else part} for i, part in enumerate(raw.split("|"))]
    opts = []
    for child in list(elem) + elem.findall("./constraints/options/option"):
        if child.tag in ("option", "value"):
            val = child.get("value") or child.text or ""
            label = child.get("label") or val
            opts.append({"value": val, "label": resolver.resolve(label) if resolver else label})
    return opts


def parse_schema(schema_path, addon_path=None, user_settings_path=None, allow_secret_replacement=False):
    resolver = LanguageResolver(addon_path)
    user_values = parse_user_settings(user_settings_path)
    groups = []
    unsupported = []
    warnings = []
    if not schema_path or not path_exists(schema_path):
        return {"groups": [], "unsupported": [], "warnings": ["Settings schema not found"]}
    try:
        root = ET.fromstring(read_text(schema_path))
    except ET.ParseError as exc:
        return {"groups": [], "unsupported": [], "warnings": ["Settings schema parse failed: %s" % exc]}

    def make_setting(elem):
        sid = elem.get("id") or ""
        label = resolver.resolve(elem.get("label") or sid)
        stype = elem.get("type") or elem.get("format") or "unknown"
        default = elem.get("default") if elem.get("default") is not None else elem.findtext("default")
        default_known = default is not None
        default = default if default_known else ""
        value = user_values.get(sid, default)
        masked = False if allow_secret_replacement else (is_secret_like(sid, label) or elem.get("option") == "hidden" or elem.get("visible") == "false")
        options = _parse_options(elem, resolver)
        editable = setting_editable({"id": sid, "label": label, "type": stype, "options": options}, allow_secret_replacement)
        if masked:
            editable = bool(allow_secret_replacement) and editable
        return {
            "id": sid,
            "label": label,
            "description": setting_description(sid, label),
            "type": stype,
            "value": mask_value(value) if masked else value,
            "default": mask_value(default) if masked else default,
            "default_known": default_known,
            "value_source": "saved" if sid in user_values else ("default" if default_known else "unknown"),
            "is_default": _same_value(value, default, stype) if default_known else None,
            "secret": stype.lower() == "password" or (stype.lower() in ("text", "string") and (is_secret_like(sid, label) or elem.get("option") == "hidden")),
            "options": options,
            "editable": editable,
            "masked": masked,
            "warning": "Secret-like value" if is_secret_like(sid, label) and not masked else ("Secret-like value masked" if masked else ""),
            "raw": _attrs(elem),
        }

    categories = list(root.findall(".//category"))
    if categories:
        for idx, cat in enumerate(categories):
            settings = [make_setting(e) for e in cat.findall(".//setting") if e.get("id")]
            groups.append({"id": cat.get("id") or "category_%d" % idx, "label": resolver.resolve(cat.get("label") or "Category"), "settings": settings})
    else:
        settings = [make_setting(e) for e in root.findall(".//setting") if e.get("id")]
        groups.append({"id": "settings", "label": "Settings", "settings": settings})
    for group in groups:
        for setting in group["settings"]:
            if setting["type"].lower() in ("unknown", "action", "folder", "file"):
                unsupported.append(setting["id"])
    return {"groups": groups, "unsupported": unsupported, "warnings": warnings}


def flatten_settings(parsed):
    out = {}
    for group in parsed.get("groups", []):
        for setting in group.get("settings", []):
            out[setting["id"]] = setting
    return out
