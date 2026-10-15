import os
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

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
    provider = ""
    if sid.startswith("rd."):
        provider = "Real-Debrid"
    elif sid.startswith("ad."):
        provider = "AllDebrid"
    elif sid.startswith("pm."):
        provider = "Premiumize"
    elif sid.startswith("tb."):
        provider = "TorBox"
    elif sid.startswith("ed."):
        provider = "EasyDebrid"
    elif sid.startswith("oc."):
        provider = "OffCloud"
    if provider:
        if sid.endswith(".enabled"):
            return "Turn %s account integration on or off." % provider
        if sid.endswith(".priority"):
            return "Order used when choosing %s results. Lower number usually means higher priority." % provider
        if sid.endswith(".token"):
            return "%s access token used by the add-on." % provider
        if sid.endswith(".refresh"):
            return "%s refresh token used to renew access." % provider
        if sid.endswith(".secret"):
            return "%s client secret used for authorization." % provider
        if sid.endswith(".client_id"):
            return "%s client ID used for authorization." % provider
        if sid.endswith(".account_id"):
            return "%s account name or account ID currently linked." % provider
        if sid.endswith(".alt_api"):
            return "Alternative %s API key/token." % provider
    generic = ((".priority", "Order used when choosing this provider. Lower number usually means higher priority."),
               (".enabled", "Turn this integration on or off."),
               (".token", "Access token used by the add-on."),
               (".refresh", "Refresh token used to renew access."),
               (".secret", "Client secret used for authorization."))
    for suffix, desc in generic:
        if sid.endswith(suffix):
            return desc
    rules = [
        ("tmdb", "TMDb API/account credential used for metadata and lists."),
        ("trakt", "Trakt account credential or authorization setting."),
        ("easynews_user", "EasyNews username."),
        ("easynews_password", "EasyNews password."),
        ("omdb", "OMDb API key used for ratings/metadata."),
        ("fanart", "Fanart.tv API key used for artwork."),
        ("tvdb", "TVDb token used for TV metadata."),
        ("mdblist", "MDBList API key used for list metadata."),
        ("prowlarr", "Prowlarr token used by scraper integration."),
        ("furk", "Furk account/API credential."),
        ("debrid", "Debrid/account integration setting."),
        ("default_addon_fanart", "Artwork shown when Fen Light has no specific background."),
        ("autoplay", "Controls automatic playback behavior."),
        ("external", "Connects this add-on to an external helper/module."),
        ("scraper", "Controls scraper/provider integration."),
        ("provider", "Controls provider behavior or appearance."),
        ("timeout", "How long to wait before giving up."),
        ("thread", "Concurrency/performance setting."),
        ("quality", "Playback/source quality preference."),
        ("cache", "Cache behavior."),
        ("resume", "Resume playback behavior."),
    ]
    for key, desc in rules:
        if key in sid:
            return desc
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


def _old_select_lvalues(elem, v2=False):
    """A v1 ``select`` with ``lvalues``: Kodi makes it an integer setting whose option values
    are the indexes 0..n-1 (AddonSettings.cpp InitializeFromOldSettingSelect), and it uses
    ``lvalues`` even when ``values`` is also given."""
    return not v2 and elem.get("type") == "select" and bool(elem.get("lvalues"))


def _parse_options(elem, resolver=None, v2=False):
    select_lvalues = _old_select_lvalues(elem, v2)
    raw = elem.get("lvalues") if select_lvalues else (elem.get("values") or elem.get("lvalues") or elem.get("entries"))
    if raw:
        labels = raw.split("|")
        localized = bool(resolver and (select_lvalues or not elem.get("values") and elem.get("lvalues")))
        values = labels
        if select_lvalues:
            # Kodi stores the chosen index, never the label's string id.
            values = [str(i) for i in range(len(labels))]
        elif elem.get("type") == "enum":
            # Kodi stores a v1 enum as the chosen index, or as the matching
            # ``entries`` value when given; ``labelenum`` stores the label.
            entries = (elem.get("entries") or "").split("|")
            values = entries if elem.get("entries") and len(entries) == len(labels) else [str(i) for i in range(len(labels))]
        return [{"value": value, "label": resolver.resolve(part) if localized and resolver else part} for value, part in zip(values, labels)]
    opts = []
    for child in list(elem) + elem.findall("./constraints/options/option"):
        if child.tag in ("option", "value"):
            val = child.get("value") or child.text or ""
            label = child.get("label") or val
            opts.append({"value": val, "label": resolver.resolve(label) if resolver else label})
    return opts


def _enum_default(elem, default, options):
    """A v1 ``enum`` default as the stored value its options use.

    Kodi stores a v1 enum as an index (or the matching ``entries`` value), but some add-ons give
    the label as the default (``default="poster"``). Kodi reads a non-integer default as index 0,
    so a label default becomes its option's value and anything else unmatched becomes the first
    option's.
    """
    if elem.get("type") != "enum" or not options or default in [o["value"] for o in options]:
        return default
    raw = elem.get("values") or elem.get("lvalues") or elem.get("entries")
    if not raw:
        return default
    raw_labels = raw.split("|")
    for idx, option in enumerate(options):
        if default == option["label"] or (idx < len(raw_labels) and default == raw_labels[idx]):
            return option["value"]
    return options[0]["value"]


def _whole_text(text):
    """``text`` as Kodi's CSettingInt reads it (strtol, nothing after the digits), else None."""
    text = (text or "").strip()
    return str(int(text)) if re.fullmatch(r"[-+]?[0-9]+", text) else None


def _number(text):
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _constraints(elem, stype, v2):
    """What Kodi checks before it stores a value (CSetting*::CheckValidity), beyond the type.

    ``whole``: Kodi keeps the setting as an integer (v1 ``number``, v1 ``slider`` with
    option int/percent, v1 ``select`` with ``lvalues``); ``minimum``/``maximum``: the range
    Kodi enforces when they differ; ``allow_empty`` False: Kodi refuses "" (a v2 string
    without ``<allowempty>true</allowempty>``).
    """
    out = {}
    kind = stype.lower()
    if not v2:
        if kind == "number" or _old_select_lvalues(elem):
            out["whole"] = True
        elif kind == "slider":
            option = (elem.get("option") or "").strip().lower()
            parts = (elem.get("range") or "").split(",")
            low, high = 0.0, 100.0
            if len(parts) > 1:
                low = _number(parts[0]) or 0.0
                high = _number(parts[2] if len(parts) > 2 else parts[1]) or 0.0
            if option in ("int", "percent"):
                out["whole"] = True
                low, high = float(int(low)), float(int(high))
            if option in ("", "float", "int", "percent") and low != high:
                out["minimum"], out["maximum"] = low, high
        return out
    constraints = elem.find("constraints")
    if kind in ("integer", "number") and constraints is not None:
        low, high = _number(constraints.findtext("minimum")), _number(constraints.findtext("maximum"))
        if low is not None and high is not None and low != high:
            out["minimum"], out["maximum"] = low, high
    if kind == "string":
        allow = constraints.findtext("allowempty") if constraints is not None else None
        out["allow_empty"] = (allow or "").strip().lower() in ("true", "1")
    return out


def parse_schema(schema_path, addon_path=None, user_settings_path=None, allow_secret_replacement=False) -> Dict[str, Any]:
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

    # A <settings version="1"> file is Kodi's current format; one without a version is the old one.
    v2 = (root.get("version") or "").strip() not in ("", "0")

    def make_setting(elem):
        sid = elem.get("id") or ""
        label = resolver.resolve(elem.get("label") or sid)
        stype = elem.get("type") or elem.get("format") or "unknown"
        default = elem.get("default") if elem.get("default") is not None else elem.findtext("default")
        default_known = default is not None
        default = default if default_known else ""
        options = _parse_options(elem, resolver, v2)
        constraints = _constraints(elem, stype, v2)
        if default_known:
            default = _enum_default(elem, default, options)
            if _old_select_lvalues(elem, v2):
                # Kodi reads a non-integer default as index 0.
                default = _whole_text(default) or "0"
        value = user_values.get(sid, default)
        masked = False if allow_secret_replacement else (is_secret_like(sid, label) or elem.get("option") == "hidden" or elem.get("visible") == "false")
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
            **constraints,
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
