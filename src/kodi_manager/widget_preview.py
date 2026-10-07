"""Read previews for saved skin rows; never execute their actions.

row_preview accepts saved section/row IDs, not client-provided sources. The
response retains source.label/path/action verbatim and supplies resolved_label,
resolved_path, resolution, status, reason, items, limits and sample separately.
Dynamic expressions are evaluated only by Kodi's getInfoLabel. Native directory
and narrowly observed Bingie widget routes use read-only JSON-RPC listings.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlparse

try:
    import xbmc
except ImportError:
    xbmc = None

try:
    from .skin_layout import inspect_layout, _validate_destination
    from .widget_catalog import browse_directory, listing_path, clean_label, PROPERTIES, _media_item, _RPC_SLOTS
    from .widget_plugin import collect_family_directory
except ImportError:
    from skin_layout import inspect_layout, _validate_destination
    from widget_catalog import browse_directory, listing_path, clean_label, PROPERTIES, _media_item, _RPC_SLOTS
    from widget_plugin import collect_family_directory

_DYNAMIC = re.compile(r"\$(?:VAR|INFO)\[", re.I)
_FAVOURITES = re.compile(r"ActivateWindow\(\s*(?:FavouritesBrowser|10134)\s*\)", re.I)
_WINDOW = re.compile(r"ActivateWindow\(\s*(?:Videos|VideoLibrary|10025)\s*,\s*(.*?)\s*(?:,\s*return)?\s*\)", re.I)


def _display_label(value):
    return re.sub(r"\[/?(?:CAPITALIZE|UPPERCASE|LOWERCASE)\]", "", clean_label(value), flags=re.I)


def _resolve(value):
    if not isinstance(value, str):
        return "", False
    dynamic = bool(_DYNAMIC.search(value))
    if not dynamic:
        return value, False
    if xbmc is None:
        return "", True
    for _ in range(3):
        try:
            resolved = xbmc.getInfoLabel(value)
        except Exception:
            return "", True
        if not isinstance(resolved, str) or not resolved:
            return "", True
        if not _DYNAMIC.search(resolved):
            return resolved, True
        if resolved == value:
            # Reload is an optional cache-busting parameter in observed skin
            # widget URLs. Keep the actual route; drop only unresolved reload.
            candidate = _directory(resolved)
            if isinstance(candidate, str) and "?" in candidate:
                base, query = candidate.split("?", 1)
                parts = query.split("&")
                kept = [part for part in parts if not (unquote(part.split("=", 1)[0]).casefold() == "reload" and _DYNAMIC.search(unquote(part)))]
                stripped = base + ("?" + "&".join(kept) if kept else "")
                if not _DYNAMIC.search(stripped) and len(kept) != len(parts):
                    return stripped, True
            return "", True
        value = resolved
    return "", True


def _directory(value):
    """Extract a video directory or the exact favourites window, never run it."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if _FAVOURITES.fullmatch(value):
        return None
    match = _WINDOW.fullmatch(value)
    if match:
        value = match.group(1).strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif any(c in value for c in ',()"\';'):
            return ""
        return value
    return value


def _validate_path(path, index):
    if not isinstance(path, str) or not path or len(path) > 12000 or any(ord(c) < 32 for c in path):
        raise ValueError("This row does not resolve to a directory.")
    try:
        parsed = urlparse(path)
    except ValueError:
        raise ValueError("The resolved directory is malformed.") from None
    if parsed.username or parsed.password or parsed.fragment or "\\" in path or _DYNAMIC.search(path):
        raise ValueError("The resolved directory is not supported for a preview.")
    decoded = parsed.path
    for _ in range(3):
        decoded = unquote(decoded)
    if any(ord(c) < 32 for c in decoded) or "\\" in decoded or any(part in (".", "..") for part in decoded.split("/")):
        raise ValueError("Directory traversal is not supported.")
    if parsed.scheme == "plugin" and parsed.netloc.startswith("plugin.video."):
        listing_path(path, index)
        return "video_plugin"
    if parsed.scheme == "plugin" and parsed.netloc == "service.kodi.addonadmin":
        try:
            _validate_destination(index, path)
        except (OSError, ValueError, ET.ParseError) as error:
            raise ValueError("This saved family route is invalid or its Kodi Manager extension is unavailable.") from error
        return "family"
    if parsed.scheme == "plugin" and parsed.netloc == "script.bingie.widgets":
        addon = index.get(parsed.netloc)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not addon or addon.get("installed") is not True or addon.get("enabled") is not True:
            raise ValueError("Bingie Widgets is not confirmed installed and enabled.")
        if (parsed.path not in ("", "/") or set(query) - {"action", "mediatype", "reload"}
                or query.get("action") not in (["recent"], ["popular"])
                or query.get("mediatype") not in (["media"], ["movies"], ["tvshows"], ["episodes"])
                or any(len(values) != 1 for values in query.values())):
            raise ValueError("Only the saved Bingie recent/popular video lists support previews.")
        return "bingie_widget"
    if parsed.query and parsed.scheme in ("special", "addons"):
        raise ValueError("This native directory query is not supported.")
    if parsed.scheme == "special" and parsed.netloc == "videoplaylists":
        return "native"
    if parsed.scheme == "addons" and parsed.netloc == "sources" and parsed.path in ("/video", "/video/"):
        return "native"
    if parsed.scheme == "videodb" and parsed.netloc in ("", "movies", "tvshows", "musicvideos"):
        return "native"
    if parsed.scheme == "library" and parsed.netloc == "video":
        return "native"
    raise ValueError("This saved source needs its native Kodi screen; it is not a supported video directory.")


def _items(files):
    items = []
    for raw in files:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["path"] = raw.get("file", "")
        item["label"] = _display_label(raw.get("label") or raw.get("title"))
        item["title"] = _display_label(raw.get("title") or raw.get("label"))
        item["classification"] = "media" if _media_item(raw) else "menu" if raw.get("filetype") == "directory" else "unknown"
        item["traversable"] = False
        item["browseable"] = False
        items.append(item)
    return items


def _listing(kodi, path, limit):
    with _RPC_SLOTS:
        response = kodi.jsonrpc("Files.GetDirectory", {"directory": path, "media": "files", "properties": PROPERTIES,
                                                      "limits": {"start": 0, "end": limit}})
    if not isinstance(response, dict) or response.get("error"):
        raise ValueError("Kodi could not read this saved directory. It may need its native screen.")
    result = response.get("result", {})
    if not isinstance(result, dict) or not isinstance(result.get("files"), list):
        raise ValueError("Kodi did not return a directory preview.")
    return _items(result["files"][:limit]), result.get("limits") or {"start": 0, "end": min(limit, len(result["files"])), "total": len(result["files"])}


def _favourites(kodi, index, limit):
    with _RPC_SLOTS:
        response = kodi.jsonrpc("Favourites.GetFavourites", {"properties": ["window", "windowparameter", "thumbnail", "path"]})
    result = response.get("result", {}) if isinstance(response, dict) and not response.get("error") else {}
    if not isinstance(result, dict):
        result = {}
    favourites = result.get("favourites")
    if not isinstance(favourites, list):
        raise ValueError("Kodi could not read favourites.")
    files, skipped = [], 0
    for favourite in favourites:
        if not isinstance(favourite, dict) or favourite.get("type") != "window" or str(favourite.get("window", "")).casefold() not in ("videos", "videolibrary", "10025"):
            skipped += 1
            continue
        path = _directory(favourite.get("windowparameter") or "")
        try:
            _validate_path(path, index)
        except ValueError:
            skipped += 1
            continue
        files.append({"label": favourite.get("title", ""), "file": path, "filetype": "directory", "thumbnail": favourite.get("thumbnail", "")})
    return _items(files[:limit]), {"start": 0, "end": min(limit, len(files)), "total": len(files)}, skipped


def row_preview(kodi, index, body):
    if not isinstance(body, dict) or set(body) - {"section_id", "row_id", "limit"}:
        raise ValueError("Preview a saved row by its section_id and row_id only.")
    section_id, row_id = body.get("section_id"), body.get("row_id")
    if not isinstance(section_id, str) or not isinstance(row_id, str) or not section_id or not row_id:
        raise ValueError("A saved section_id and row_id are required.")
    limit = body.get("limit", 48)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 48:
        raise ValueError("Preview limit must be an integer between 1 and 48.")
    layout = inspect_layout(kodi, index)
    section = next((section for section in layout.get("sections", []) if section.get("id") == section_id), None)
    row = next((row for row in (section or {}).get("rows", []) if row.get("id") == row_id), None)
    if row is None:
        raise ValueError("This saved widget row was not found. Refresh the TV layout.")
    source = {key: row.get(key, "") for key in ("label", "path", "action")}
    label_expression = row.get("raw_label") if isinstance(row.get("raw_label"), str) and _DYNAMIC.search(row["raw_label"]) else source["label"]
    label, _ = _resolve(label_expression)
    result = {"section_id": section_id, "row_id": row_id, "source": source, "resolved_label": _display_label(label) or source["label"],
              "resolved_path": "", "resolution": "saved_source", "status": "unresolved", "reason": "", "items": [],
              "limits": {"start": 0, "end": 0, "total": 0}, "sample": {"truncated": False, "returned": 0, "message": ""}}
    value, dynamic = _resolve(source["path"] or source["action"])
    result["resolution"] = "Kodi getInfoLabel" if dynamic else "saved_source"
    if not value:
        result["reason"] = "Kodi could not resolve this skin variable in the current skin context." if dynamic else "This row has no directory source."
        return result
    path = _directory(value)
    try:
        if path is None:
            items, limits, skipped = _favourites(kodi, index, limit)
            result["resolved_path"] = "favourites://"
            result["skipped"] = skipped
            if skipped:
                result["reason"] = "%s favourites need their native Kodi screen and are omitted from this directory preview." % skipped
        else:
            kind = _validate_path(path, index)
            result["resolved_path"] = path
            if kind == "video_plugin":
                directory = browse_directory(kodi, index, path, limit=limit)
                result.update({key: value for key, value in directory.items() if key not in ("path", "items", "limits")})
                items, limits = directory["items"], directory["limits"]
            elif kind == "family":
                query = parse_qs(urlparse(path).query, keep_blank_values=True)
                with _RPC_SLOTS:
                    family = collect_family_directory(kodi, index, query["source"][0], query["max_rating"][0], query["family_only"][0] == "true")
                items = _items(family["files"][:limit])
                limits = {"start": 0, "end": len(items), "total": family["included_count"]}
                result.update({key: family[key] for key in ("included_count", "input_count", "excluded_counts", "max_rating", "family_only", "pagination")})
                result["sample"]["truncated"] = family["pagination"]["truncated"]
            else:
                items, limits = _listing(kodi, path, limit)
    except ValueError as exc:
        result["status"] = "unavailable" if result["resolved_path"] else "unsupported"
        result["reason"] = "Kodi could not read this saved source. Open its native Kodi screen to check its availability." if result["resolved_path"] else str(exc)
        return result
    result.update({"status": "ok", "items": items, "limits": limits})
    truncated = bool(result["sample"].get("truncated")) or limits.get("total", len(items)) > len(items)
    result["sample"] = {"truncated": truncated, "returned": len(items), "message": "Truncated saved-row preview; more items are available in Kodi." if truncated else "Preview of this saved TV row."}
    if result.get("pagination", {}).get("truncated"):
        result["sample"]["message"] = "Family collection stopped at its pagination safety bound; counts cover the collected pages."
    if not items and not result["reason"]:
        result["reason"] = "This saved directory returned no items in the current Kodi context."
    return result
