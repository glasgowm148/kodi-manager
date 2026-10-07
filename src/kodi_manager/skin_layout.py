"""Version-pinned Bingie section inspection and staged widget edits.

Existing hub: {section_id, rows: [{id?, label, path, action?}], expected_revision}.
Repurpose disabled New & Popular: {section_id: 'hub:newhub', operation:
    'repurpose', label: 'Kids', rows: six family wrapper rows, expected_revision}.
Legacy new custom hub: {label, rows: [{label, path}], replace_customhub: bool,
                      expected_revision: inspect/preview revision}.
Only explicit dashboard apply should call apply_layout. No network installation.
"""
import ast
import copy
import hashlib
import json
import os
import re
import threading
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qs

try:
    from .kodi_api import translate
    from .fsutil import atomic_write_bytes
    from .backup import prune_folder
except ImportError:
    from kodi_api import translate
    from fsutil import atomic_write_bytes
    from backup import prune_folder

SKIN = "skin.bingie"
SHORTCUTS = "script.skinshortcuts"
GROUPS = "mainmenu|powermenu|searchmenu|tmdbsearchmenu|moviehub|tvshowhub|newhub|musichub|customhub|somethinghub|mylisthub"
REBUILD = "RunScript(script.skinshortcuts,type=buildxml&mainmenuID=900&levels=1&group=%s)" % GROUPS
# Reviewed skin v2.0.2 commit 9f1c6eba7a15f63fac05c6f0aa655f55e84dd775,
# and official Kodi omega script.skinshortcuts-2.0.3.zip. Unknown forks stay read-only.
SOURCE_HASHES = {
    SKIN: {
        "shortcuts/template.xml": "d54cf8e56aee0ec8062cf6315af51a306f379835451bf55543185f08317962a1",
        "shortcuts/overrides.xml": "3028e6579f4501a172b8a0c066f4b15cbbdee829b4cea4da270757b3a4805778",
        "1080i/Home.xml": "288dabc45fef98794f42767ca5245cbc0cdd51762b7d00519462656d329fb2aa",
        "1080i/IncludesHomeBingie.xml": "a1a6a01546bc43f7b3d5afccc533f77c034cd2e3f1753783c3f3e23344e6dbf7",
    },
    SHORTCUTS: {
        "resources/lib/skinshorcuts/datafunctions.py": "07b3675760e0c03d704a46c6a9bfbda0c1c05f1b306a30857ae77639a1fa3dcf",
        "resources/lib/skinshorcuts/xmlfunctions.py": "171f6e4e322616a544d154b66e6534d8c74e1fc0b47e445a9fc5bdf0e4e36b56",
        "resources/lib/skinshorcuts/property_utils.py": "4646b4394ee6c4a6a6fd829dbb872fc098f30c85d07206a6a94e7ea8d0587471",
    },
}
_LOCK = threading.RLock()


def _hash(data):
    return hashlib.sha256(data).hexdigest() if data is not None else "absent"


def _read(path, optional=False):
    if optional and not os.path.lexists(path):
        return None
    if os.path.islink(path):
        raise ValueError("Shortcut files must not be symlinks")
    with open(path, "rb") as handle:
        data = handle.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Shortcut file exceeds size limit")
    return data


def _xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsupported XML declarations")
    root = ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != "shortcuts":
        raise ValueError("Unknown shortcut XML format")
    return root


def _verify_sources(addons):
    for aid, files in SOURCE_HASHES.items():
        base = translate(addons[aid].get("path") or "")
        if not base:
            raise ValueError("Installed add-on sources are unavailable")
        meta = ET.fromstring(_read(os.path.join(base, "addon.xml")))
        expected = "2.0.2" if aid == SKIN else "2.0.3"
        if meta.get("id") != aid or meta.get("version") != expected:
            raise ValueError("Installed source version does not match the supported schema")
        for relative, digest in files.items():
            if _hash(_read(os.path.join(base, relative))) != digest:
                raise ValueError("Installed skin/shortcut source differs from the reviewed schema")


def _context(kodi, index):
    index.refresh()
    active = kodi.get_active_skin()
    addons = {aid: index.get(aid) or {} for aid in (SKIN, SHORTCUTS)}
    reasons = []
    if active.get("addon_id") != SKIN or active.get("version") != "2.0.2" or addons[SHORTCUTS].get("version") != "2.0.3":
        reasons.append("Direct editing supports only Bingie 2.0.2 with Skin Shortcuts 2.0.3")
    try:
        _verify_sources(addons)
    except (OSError, ValueError, ET.ParseError) as exc:
        reasons.append(str(exc))
    data_root = addons[SHORTCUTS].get("addon_data_path") or ""
    root = os.path.realpath(translate(data_root)) if data_root else ""
    names = ["skin.bingie-mainmenu.DATA.xml", "skin.bingie-customhub.DATA.xml", "skin.bingie.properties"]
    snapshots, parsed, files = {}, {}, {}
    if not root or not os.path.isdir(root):
        reasons.append("Kodi shortcut storage is unavailable; use the exported draft and manual guide")
    else:
        for name in names:
            try:
                raw = _read(os.path.join(root, name), optional=True)
                snapshots[name] = raw
                files[name] = _hash(raw)
                if raw is not None and name.endswith(".xml"):
                    parsed[name] = _xml(raw)
                elif raw is not None:
                    values = ast.literal_eval(raw.decode("utf-8"))
                    if not isinstance(values, list) or any(not isinstance(v, (list, tuple)) or len(v) != 4 or not all(isinstance(part, str) for part in v) for v in values):
                        raise ValueError("Unknown shortcut properties format")
            except (OSError, ValueError, SyntaxError, UnicodeError, ET.ParseError) as exc:
                reasons.append("Cannot read %s: %s" % (name, exc))
        if snapshots.get(names[0]) is None:
            try:
                # The active skin defaults are the authoritative starting menu.
                raw = _read(os.path.join(translate(addons[SKIN].get("path") or ""), "shortcuts", "mainmenu.DATA.xml"))
                parsed[names[0]] = _xml(raw)
                snapshots["default-mainmenu"] = raw
                files["default-mainmenu"] = _hash(raw)
            except (OSError, ValueError, ET.ParseError) as exc:
                reasons.append("Cannot read the current/default main menu: %s" % exc)
    revision = _hash(json.dumps({"files": files, "active": active.get("addon_id"), "versions": [active.get("version"), addons[SHORTCUTS].get("version")]}, sort_keys=True).encode())
    main = parsed.get(names[0])
    hub = parsed.get(names[1])
    entries = [{"label": s.findtext("label", ""), "action": s.findtext("action", "")} for s in main.findall("shortcut")] if main is not None else []
    rows = [{"label": s.findtext("label", ""), "action": s.findtext("action", "")} for s in hub.findall("shortcut")] if hub is not None else []
    occupants = [e["label"] for e in entries if re.fullmatch(r"ActivateWindow\(1113,\s*return\)", e["action"], re.I)]
    result = {"active_skin": active, "shortcuts_version": addons[SHORTCUTS].get("version"), "can_apply": not reasons,
              "reasons": reasons, "revision": revision, "menu": entries, "customhub": rows,
              "customhub_occupied": bool(rows or occupants), "customhub_menu_labels": occupants,
              "max_rows": 20, "hub_window": 1113,
              "manual_guide": "Skin settings > Configure shortcuts > Customize custom hub. Add a main-menu custom action ActivateWindow(1113,return), then configure the custom hub rows. Movies uses window 1111; choosing Movies again shares that hub."}
    _sections(kodi, index, result, root, snapshots)
    return result, root, snapshots


def _path_from_action(action):
    match = re.fullmatch(r'ActivateWindow\((?:Videos|VideoLibrary|10025),\s*(".*"|.*),\s*return\)', action or "", re.I)
    return match.group(1).strip().strip('"') if match else ""


def _label_ids(nodes):
    """Reviewed 2.0.3 label-ID algorithm, restricted to roundtrippable ASCII."""
    seen, result = set(), []
    nice = {'3': 'videos', '2': 'music', '342': 'movies', '20343': 'tvshows', '32022': 'livetv',
            '20389': 'musicvideos', '10002': 'pictures', '12600': 'weather', '10001': 'programs',
            '32032': 'dvd', '10004': 'settings', '32087': 'radio'}
    for node in nodes:
        label = node.findtext("label", "")
        localized = re.fullmatch(r'\$(?:LOCALIZE|SKIN)\[(\d+)(?:\|[^]]+)?\]', label)
        label = localized.group(1) if localized else label
        if not label.isascii() or "$" in label or re.search(r'&(?:\w+|#\d+);', label):
            raise ValueError("Localized or non-ASCII row identities need native Kodi editing")
        base = re.sub(r'[^a-z0-9-]+', '-', label.replace(' ', '').lower().replace("'", '')).strip('-')
        base = nice.get(base, base)
        action = node.findtext("action", "")
        if "plugin://" in action and "?" not in action:
            try:
                base = action[15:-1].split(',')[1].replace('"', '')[9:]
            except IndexError:
                pass
        value, count = base, 0
        while value in seen:
            value = "%s--%s" % (base, count)
            count += 1
        seen.add(value)
        result.append(value)
    return result


def _display_label(node, translations=None):
    value = node.findtext('label', '')
    if value.isdigit() or value.startswith(('$SKIN[', '$LOCALIZE[')):
        try:
            from .kodi_api import xbmc
        except ImportError:
            from kodi_api import xbmc
        number = re.search(r'\d+', value)
        if xbmc and number:
            return xbmc.getLocalizedString(int(number.group()))
        if number and translations and number.group() in translations:
            return translations[number.group()]
        return node.findtext('label2') or value
    return value


def _section_rows(nodes, group, properties, translations=None):
    counts, rows = {}, []
    try:
        identities = _label_ids(nodes)
    except ValueError:
        identities = [''] * len(nodes)
    for position, node in enumerate(nodes):
        digest = _hash(ET.tostring(node, encoding='utf-8'))[:16]
        count = counts.get(digest, 0)
        counts[digest] = count + 1
        action = node.findtext('action', '')
        rows.append({'id': '%s:%s:%d' % (group, digest, count), 'label': _display_label(node, translations),
                     'raw_label': node.findtext('label', ''), 'path': _path_from_action(action), 'action': action,
                     'label_id': identities[position], 'disabled': node.findtext('disabled') == 'True',
                     'properties': {p[2]: p[3] for p in properties if p[0] == group and p[1] == identities[position]}})
    return rows


def _sections(kodi, index, state, root, snapshots):
    """Discover windows from the installed include conditions, never route guesses."""
    addon = index.get(SKIN) or {}
    source = translate(addon.get('path') or '')
    translations = {}
    try:
        po = _read(os.path.join(source, 'language', 'resource.language.en_gb', 'strings.po')).decode('utf-8')
        translations = {number: json.loads(label) for number, label in re.findall(r'msgctxt "#(\d+)"\s*\nmsgid ("(?:\\.|[^"])*")', po)}
    except (OSError, ValueError, UnicodeError):
        pass
    mappings, mapping_reason, home_schema = {}, '', False
    try:
        includes = ET.fromstring(_read(os.path.join(source, '1080i', 'IncludesHomeBingie.xml')))
        template = ET.fromstring(_read(os.path.join(source, 'shortcuts', 'template.xml')))
        home_templates = template.findall("submenuOther[@include='Widgets'][@level='1']")
        home_schema = len(home_templates) == 1 and home_templates[0].find(".//property[@name='widgetPath'][@attribute='name|list']") is not None and home_templates[0].find(".//property[@name='widgetName'][@tag='label']") is not None and any(
            (include.text or '').strip() == 'skinshortcuts-template-Widgets' and re.fullmatch(r'Window.IsActive\(Home\)', include.get('condition', ''), re.I) for include in includes.iter('include'))
        groups = {item.get('name') for item in template.findall('submenu') if item.find(".//property[@name='widgetPath'][@attribute='name|list']") is not None}
        for include in includes.iter('include'):
            text = (include.text or '').strip()
            match = re.fullmatch(r'Window.IsActive\((\d+)\)', include.get('condition', ''))
            group = text[len('skinshortcuts-template-'):] if text.startswith('skinshortcuts-template-') else text
            if match and text.startswith('skinshortcuts-template-') and group in groups:
                mappings[group] = int(match.group(1))
    except (OSError, ValueError, ET.ParseError) as exc:
        mapping_reason = 'Installed hub mapping is unavailable: %s' % exc
    # Snapshot every user DATA file: another open Kodi shortcut editor cannot
    # silently invalidate the revision while this dashboard stages changes.
    if root and os.path.isdir(root):
        for name in os.listdir(root):
            if re.fullmatch(r'skin\.bingie-[A-Za-z0-9_.-]+\.DATA\.xml', name) and name not in snapshots:
                try:
                    snapshots[name] = _read(os.path.join(root, name))
                    _xml(snapshots[name])
                except (OSError, ValueError, ET.ParseError) as exc:
                    state['can_apply'] = False
                    state['reasons'].append('Cannot safely snapshot %s: %s' % (name, exc))
    try:
        properties = ast.literal_eval(snapshots.get('skin.bingie.properties', b'[]').decode()) if snapshots.get('skin.bingie.properties') else []
        if not isinstance(properties, list) or any(not isinstance(p, (list, tuple)) or len(p) != 4 or not all(isinstance(part, str) for part in p) for p in properties):
            properties = []
    except (ValueError, SyntaxError, UnicodeError):
        properties = []
    main_raw = snapshots.get('skin.bingie-mainmenu.DATA.xml') or snapshots.get('default-mainmenu')
    try:
        nodes = _xml(main_raw).findall('shortcut') if main_raw else []
    except (ValueError, ET.ParseError):
        nodes = []
    menu_rows = _section_rows(nodes, 'mainmenu', properties, translations)
    sections = [{'id': 'mainmenu', 'kind': 'menu', 'group': 'mainmenu', 'window': None, 'label': 'Main menu', 'action': '',
                 'rows': menu_rows, 'supported': False, 'editable': False,
                 'disabled': False, 'active': False, 'in_menu': False,
                 'reasons': ['Menu identities also link Home widget groups; configure menu actions in Kodi'],
                 'provenance': {'filename': 'skin.bingie-mainmenu.DATA.xml', 'source': 'user' if snapshots.get('skin.bingie-mainmenu.DATA.xml') else 'skin defaults'}}]
    for group, window in mappings.items():
        name = 'skin.bingie-%s.DATA.xml' % group
        snapshots.setdefault(name, None)
        raw = snapshots.get(name)
        origin = 'user'
        if raw is None:
            try:
                raw = _read(os.path.join(source, 'shortcuts', group + '.DATA.xml'), optional=True)
                if raw is not None:
                    snapshots['default:' + group] = raw
            except (OSError, ValueError):
                raw = None
            origin = 'skin defaults'
        try:
            hub_nodes = _xml(raw).findall('shortcut') if raw else []
        except (ValueError, ET.ParseError):
            hub_nodes = []
            raw = None
        rows = _section_rows(hub_nodes, group, properties, translations)
        menu = [row for row in menu_rows if re.fullmatch(r'ActivateWindow\(%d,\s*return\)' % window, row['action'], re.I)]
        reasons = list(state['reasons'])
        if raw is None:
            reasons.append('No saved/default widget rows are available')
        try:
            _label_ids(hub_nodes)
        except ValueError as exc:
            reasons.append(str(exc))
        active_menu = [row for row in menu if not row['disabled']]
        sections.append({'id': 'hub:' + group, 'kind': 'hub', 'group': group, 'window': window,
                         'label': (active_menu or menu)[0]['label'] if menu else group, 'action': 'ActivateWindow(%d,return)' % window,
                         'rows': rows, 'supported': True, 'editable': not reasons, 'reasons': reasons,
                         'shared_menu_labels': [row['label'] for row in menu], 'in_menu': bool(menu),
                         'disabled': bool(menu) and not active_menu, 'active': bool(active_menu),
                         'provenance': {'filename': name, 'source': origin, 'mapping': '1080i/IncludesHomeBingie.xml and shortcuts/template.xml'}})
    home_entries = [row for row in menu_rows if re.fullmatch(r'ActivateWindow\(home,\s*return\)', row['action'], re.I)]
    home = home_entries[0] if home_entries else None
    if home and home['label_id']:
        group = home['label_id'] + '.1'
        name = 'skin.bingie-%s-1.DATA.xml' % home['label_id']
        raw = snapshots.get(name)
        reasons = list(state['reasons'])
        if not home_schema:
            reasons.append('The installed Home level-1 widget template could not be verified')
        if len(home_entries) != 1:
            reasons.append('Multiple Home menu shortcuts prevent a unique widget-group mapping')
        if raw is None:
            reasons.append('Saved Home level-1 widget rows are unavailable')
        try:
            home_nodes = _xml(raw).findall('shortcut') if raw else []
            _label_ids(home_nodes)
        except (ValueError, ET.ParseError) as error:
            home_nodes = []
            reasons.append('Home widget identities are unsupported: %s' % error)
        sections.insert(1, {'id': 'home:' + group, 'kind': 'home', 'group': group, 'window': 'home', 'label': home['label'],
                           'action': home['action'], 'rows': _section_rows(home_nodes, group, properties, translations),
                           'disabled': home['disabled'], 'active': not home['disabled'], 'in_menu': True,
                           'supported': home_schema and len(home_entries) == 1 and raw is not None, 'editable': not reasons, 'reasons': reasons,
                           'provenance': {'filename': name, 'source': 'user', 'mapping': 'submenuOther Widgets level=1'}})
    mapped_windows = set(mappings.values())
    for row in menu_rows:
        target = re.fullmatch(r'ActivateWindow\((\d+),\s*return\)', row['action'], re.I)
        if target and int(target.group(1)) in mapped_windows or home and row['id'] == home['id']:
            continue
        if any(section['kind'] == 'destination' and section['action'].casefold() == row['action'].casefold() for section in sections):
            continue
        sections.append({'id': 'menu:' + row['id'], 'kind': 'destination', 'group': None, 'window': int(target.group(1)) if target else None,
                         'label': row['label'], 'action': row['action'], 'path': row['path'],
                         'rows': [dict(row)] if row['path'] else [], 'supported': False, 'editable': False,
                         'disabled': row['disabled'], 'active': not row['disabled'], 'in_menu': True,
                         'reasons': [mapping_reason or 'This menu action is not a supported independent widget hub'],
                         'provenance': {'filename': 'skin.bingie-mainmenu.DATA.xml', 'source': 'user'}})
    # Main-menu entries are shortcuts to destinations, not one new hub per label.
    # Several labels can share the same fixed window and its widget group.
    menu_entries = []
    for order, row in enumerate(menu_rows):
        window = re.fullmatch(r'ActivateWindow\((\d+),\s*return\)', row['action'], re.I)
        target = next((section for section in sections if section['id'] != 'mainmenu' and
                       (window and section['kind'] == 'hub' and section['window'] == int(window.group(1)) or
                        section['action'].casefold() == row['action'].casefold() or
                        section['id'] == 'menu:' + row['id'])), None)
        entry = dict(row, order=order, kind=target['kind'] if target else 'destination',
                     target_section_id=target['id'] if target else None)
        shared = target.get('shared_menu_labels') if target and target['kind'] == 'hub' else [
            other['label'] for other in menu_rows if other['action'].casefold() == row['action'].casefold()]
        entry.update(shared_target=entry['target_section_id'], shared=len(shared) > 1,
                     shared_menu_labels=shared)
        # These files belong to this menu identity. Keep their rows separate from
        # the fixed hub destination, rather than creating tabs from widget labels.
        for key, suffix, level in [('submenu_rows', '', ''), ('home_widget_rows', '-1', '.1')]:
            name = 'skin.bingie-%s%s.DATA.xml' % (row['label_id'], suffix)
            raw = snapshots.get(name) if row['label_id'] else None
            try:
                children = _xml(raw).findall('shortcut') if raw else []
            except (ValueError, ET.ParseError):
                children = []
            entry[key] = _section_rows(children, row['label_id'] + level, properties, translations)
            entry[key.replace('_rows', '_provenance')] = {'filename': name if row['label_id'] else None,
                                                        'source': 'user' if raw is not None else 'unavailable'}
        menu_entries.append(entry)
    for section in sections:
        linked = [entry for entry in menu_entries if entry['target_section_id'] == section['id']]
        if linked:
            enabled = [entry for entry in linked if not entry['disabled']]
            section.update(in_menu=True, active=bool(enabled), disabled=not enabled,
                           shared_menu_labels=[entry['label'] for entry in linked])
            if section['kind'] == 'destination':
                first = (enabled or linked)[0]
                section['label'] = first['label']
                section['rows'] = [dict(first)] if first['path'] else []
    state['menu_entries'] = menu_entries
    state['sections'] = sections
    state['inactive_sections'] = [section for section in sections if section['kind'] == 'hub' and not section['active']]
    state['hub_capabilities'] = {
        'custom_hub_count': int(mappings.get('customhub') == 1113),
        'custom_hub_window': mappings.get('customhub'),
        'custom_hub_occupied': state['customhub_occupied'],
        'limitation': ('This installed skin has one independent Custom hub. Additional menu shortcuts to the same window share its rows; menu submenus and Home widgets are separate per-menu lists.'
                       if mappings.get('customhub') == 1113 else 'The independent Custom hub mapping could not be verified; native configuration is required.'),
        'provenance': '1080i/IncludesHomeBingie.xml and shortcuts/template.xml',
    }
    for section in sections:
        section['can_rename'] = False
        if section['window'] == 'home':
            section['limitations'] = ['Home rows are displayed from the saved level-1 submenu.',
                                      'The Home menu identity and linked submenu remain unchanged; configure its menu action in Kodi.']
    state['new_section_available'] = state['can_apply'] and mappings.get('customhub') == 1113 and not state['customhub_occupied']
    state['new_section_reasons'] = ([] if state['new_section_available'] else
                                    ['The independent custom hub is already used by %s' % ', '.join(state['customhub_menu_labels'] or ['existing widget rows'])]
                                    if state['customhub_occupied'] else list(state['reasons']) or ['An unused independent custom hub could not be verified'])
    _revision(state, snapshots)


def _revision(state, snapshots):
    state['revision'] = _hash(json.dumps({'files': {name: _hash(raw) for name, raw in snapshots.items()},
                                        'skin': state['active_skin'], 'shortcuts': state['shortcuts_version']}, sort_keys=True).encode())


def inspect_layout(kodi, index):
    return _context(kodi, index)[0]


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value) or any(c in value for c in "$[]"):
        raise ValueError("Labels must be plain text of 1–100 characters")
    return value.strip()


def _rows(body):
    rows = body.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError("Choose 1–20 widget rows")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid widget row")
        path = row.get("path")
        if not isinstance(path, str) or len(path) > 4096 or any(ord(c) < 32 or c in ',"()$' for c in path):
            raise ValueError("Choose an exact plugin directory path from the browser")
        url = urlsplit(path)
        if url.scheme != "plugin" or not re.fullmatch(r"[a-zA-Z0-9_.-]+", url.netloc) or url.fragment or any(c.isspace() for c in path):
            raise ValueError("Only discovered plugin:// directories are supported")
        if not url.netloc.startswith("plugin.video.") and url.netloc != "service.kodi.addonadmin":
            raise ValueError("Only video directories or Kodi Manager family rows are supported")
        out.append({"label": _label(row.get("label")), "path": path})
    return out


def _validate_destination(index, path):
    try:
        from .widget_plugin import validate_source
        from .widget_filters import filter_items
    except ImportError:
        from widget_plugin import validate_source
        from widget_filters import filter_items
    parsed = urlsplit(path)
    if parsed.netloc != "service.kodi.addonadmin":
        return validate_source(index, path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    # Bingie appends reload to refresh a widget after a watchlist change.
    # It is a cache token, not another route or filter.
    if parsed.path not in ("", "/") or set(query) - {"reload"} != {"mode", "source", "max_rating", "family_only"} or any(len(v) != 1 for v in query.values()):
        raise ValueError("Unknown Kodi Manager family wrapper route")
    if query["mode"][0] != "family" or query["family_only"][0] not in ("true", "false"):
        raise ValueError("Invalid Kodi Manager family filter")
    validate_source(index, query["source"][0])
    filter_items([], query["max_rating"][0], query["family_only"][0] == "true")
    manager = index.get("service.kodi.addonadmin") or {}
    if manager.get("installed") is not True or manager.get("enabled") is not True or not manager.get("path"):
        raise ValueError("Kodi Manager family directory extension is unavailable")
    addon_xml = ET.fromstring(_read(os.path.join(translate(manager["path"]), "addon.xml")))
    if addon_xml.get("id") != "service.kodi.addonadmin" or not any(
            ext.get("point") == "xbmc.python.pluginsource" and ext.get("library") == "resources/lib/widget_plugin.py" and "video" in (ext.findtext("provides", "").split())
            for ext in addon_xml.findall("extension")):
        raise ValueError("Install the Kodi Manager build containing the family directory extension")
    return path


def _shortcut(label, action):
    node = ET.Element("shortcut")
    for tag, text in [("label", label), ("label2", ""), ("icon", ""), ("thumb", ""), ("action", action)]:
        ET.SubElement(node, tag).text = text
    return ET.tostring(node, encoding="unicode")


def _preview(kodi, index, body):
    if not isinstance(body, dict):
        raise ValueError("A layout object is required")
    if body.get('operation'):
        if body['operation'] != 'repurpose':
            raise ValueError('Unknown layout operation')
        return _preview_repurpose(kodi, index, body)
    if body.get('section_id'):
        return _preview_section(kodi, index, body)
    state, root, snapshots = _context(kodi, index)
    label, rows = _label(body.get("label", "Kids")), _rows(body)
    for row in rows:
        try:
            _validate_destination(index, row["path"])
        except (OSError, ValueError, ET.ParseError) as exc:
            state["can_apply"] = False
            state["reasons"].append("%s: %s" % (row["label"], exc))
    replace = body.get("replace_customhub", False)
    if not isinstance(replace, bool):
        raise ValueError("replace_customhub must be true or false")
    if state["customhub_occupied"] and not replace:
        state["can_apply"] = False
        state["reasons"].append("The custom hub is already used; review its rows and explicitly choose replacement")
    if replace and state["customhub_menu_labels"] and any(l.casefold() != label.casefold() for l in state["customhub_menu_labels"]):
        state["can_apply"] = False
        state["reasons"].append("Another menu uses the custom hub; rename or remove that shortcut in Kodi before replacing it")
    if any(e["label"].casefold() == label.casefold() and e["action"] != "ActivateWindow(1113,return)" for e in state["menu"]):
        state["can_apply"] = False
        state["reasons"].append("A menu with this label already points elsewhere; change its action in Kodi first")
    new_menu = _shortcut(label, "ActivateWindow(1113,return)")
    main_raw = snapshots.get("skin.bingie-mainmenu.DATA.xml") or snapshots.get("default-mainmenu")
    if main_raw and not any(e["label"].casefold() == label.casefold() for e in state["menu"]):
        text = main_raw.decode("utf-8")
        end = text.rfind("</shortcuts>")
        if end < 0:
            raise ValueError("Unsupported main menu closing tag")
        menu_xml = text[:end] + "\n" + new_menu + "\n" + text[end:]
    elif main_raw:
        menu_xml = main_raw.decode("utf-8")
    else:
        menu_xml = '<shortcuts>\n%s\n</shortcuts>' % new_menu
    hub_xml = '<?xml version="1.0" encoding="utf-8"?>\n<shortcuts>\n' + "\n".join(_shortcut(r["label"], "ActivateWindow(Videos,%s,return)" % r["path"]) for r in rows) + '\n</shortcuts>\n'
    exports = [{"filename": "skin.bingie-mainmenu.DATA.xml", "xml": menu_xml}, {"filename": "skin.bingie-customhub.DATA.xml", "xml": hub_xml}]
    state.update({"label": label, "rows": rows, "exports": exports, "replace_customhub": replace,
                  "export_complete": main_raw is not None, "rebuild_required": True, "rebuild_command": REBUILD,
                  "rebuild_instructions": "After applying, set the Home window property skinshortcuts-reloadmainmenu to True, then run the rebuild command; Skin Shortcuts reloads the skin after rebuilding. Reopening Kodi also checks changed shortcut hashes."})
    return state, root, snapshots


def _preview_repurpose(kodi, index, body):
    """Replace only the known disabled New & Popular slot after explicit review."""
    state, root, snapshots = _context(kodi, index)
    section = next((s for s in state['sections'] if s['id'] == 'hub:newhub'), None)
    if body.get('section_id') != 'hub:newhub' or not section or section['window'] != 1112 or not section['supported']:
        raise ValueError('Repurpose supports only the verified New & Popular hub 1112')
    if not state['can_apply']:
        raise ValueError('; '.join(state['reasons']))
    label, rows = _label(body.get('label')), _rows(body)
    if label != 'Kids' or len(rows) != 6:
        raise ValueError('This repurpose operation requires Kids with six family widget rows')
    for row in rows:
        _validate_destination(index, row['path'])
        url = urlsplit(row['path'])
        if url.netloc != 'service.kodi.addonadmin' or parse_qs(url.query).get('family_only') != ['true']:
            raise ValueError('Kids rows must use persistent Kodi Manager family filters')
    main = _xml(snapshots.get('skin.bingie-mainmenu.DATA.xml') or snapshots['default-mainmenu'])
    menu_nodes = main.findall('shortcut')
    targets = [n for n in menu_nodes if re.fullmatch(r'ActivateWindow\(1112,\s*return\)', n.findtext('action', ''), re.I)]
    if len(targets) != 1 or targets[0].findtext('disabled') != 'True':
        raise ValueError('Repurpose requires exactly one disabled New & Popular menu shortcut')
    target = targets[0]
    position = menu_nodes.index(target)
    old_ids = _label_ids(menu_nodes)
    old_id = old_ids[position]
    if not old_id or any(_display_label(n).casefold() == label.casefold() for n in menu_nodes if n is not target):
        raise ValueError('Kids menu identity already exists or cannot be verified')
    target.find('label').text = label
    for disabled in target.findall('disabled'):
        target.remove(disabled)
    new_ids = _label_ids(menu_nodes)
    new_id = new_ids[position]
    if new_id in old_ids[:position] + old_ids[position + 1:] or any(old != new for i, (old, new) in enumerate(zip(old_ids, new_ids)) if i != position):
        raise ValueError('Renaming would change another menu identity')
    name = section['provenance']['filename']
    hub = _xml(snapshots.get(name) or snapshots.get('default:newhub'))
    old_nodes = hub.findall('shortcut')
    defaults = [('DefNewHub%sName' % suffix, 'DefNewHub%sContent' % suffix) for suffix in ('', '1', '2', '3')]
    if [(n.findtext('label'), n.findtext('action')) for n in old_nodes] != [('$VAR[%s]' % label_var, '$VAR[%s]' % action_var) for label_var, action_var in defaults]:
        raise ValueError('New & Popular no longer contains its four known default rows')
    obsolete = {'var-' + label_var.lower() for label_var, _ in defaults}
    new_nodes = [ET.fromstring(_shortcut(r['label'], 'ActivateWindow(Videos,%s,return)' % r['path'])) for r in rows]
    _label_ids(new_nodes)  # Reject identities the reviewed writer cannot roundtrip.
    insertion = next((i for i, n in enumerate(hub) if n.tag == 'shortcut'), len(hub))
    for node in old_nodes:
        hub.remove(node)
    for offset, node in enumerate(new_nodes):
        hub.insert(insertion + offset, node)
    exports = [{'filename': 'skin.bingie-mainmenu.DATA.xml', 'xml': ET.tostring(main, encoding='unicode')},
               {'filename': name, 'xml': ET.tostring(hub, encoding='unicode')}]
    migrations = []
    for suffix in ('', '-1'):
        source_name = 'skin.bingie-%s%s.DATA.xml' % (old_id, suffix)
        dest_name = 'skin.bingie-%s%s.DATA.xml' % (new_id, suffix)
        snapshots.setdefault(source_name, None)
        dest_raw = _read(os.path.join(root, dest_name), optional=True)
        snapshots.setdefault(dest_name, dest_raw)
        if dest_raw is not None:
            raise ValueError('Kids linked submenu/widget file already exists; native review is required')
        raw = snapshots.get(source_name)
        if raw is not None:
            _xml(raw)
            exports += [{'filename': dest_name, 'xml': raw.decode('utf-8')}, {'filename': source_name, 'delete': True}]
            migrations.append({'from': source_name, 'to': dest_name})
    props = ast.literal_eval(snapshots['skin.bingie.properties'].decode()) if snapshots.get('skin.bingie.properties') else []
    if any(p[0] in (new_id, new_id + '.1') or p[0] == 'mainmenu' and p[1] == new_id for p in props):
        raise ValueError('Kids linked properties already exist; native review is required')
    migrated = []
    for prop in props:
        value = list(prop)
        if value[0] == 'newhub' and value[1] in obsolete:
            continue
        if value[0] == 'mainmenu' and value[1] == old_id:
            value[1] = new_id
        elif value[0] in (old_id, old_id + '.1'):
            value[0] = new_id + value[0][len(old_id):]
        migrated.append(value)
    if migrated != props:
        exports.append({'filename': 'skin.bingie.properties', 'xml': repr(migrated), 'format': 'python-literal'})
    _revision(state, snapshots)
    state.update(operation='repurpose', section_id=section['id'], label=label, rows=rows, exports=exports,
                 previous_label=section['label'], menu_identity_migrations=migrations, export_complete=True,
                 rebuild_required=True, rebuild_command=REBUILD,
                 rebuild_instructions='Rebuild Skin Shortcuts after applying to enable the renamed Kids menu.')
    return state, root, snapshots


def _preview_section(kodi, index, body):
    state, root, snapshots = _context(kodi, index)
    section = next((s for s in state['sections'] if s['id'] == body['section_id']), None)
    if section is None or not section['supported']:
        raise ValueError('Choose a supported existing widget hub')
    if body.get('label', section['label']) != section['label']:
        raise ValueError('Rename the main-menu section in Kodi; its identity also links Home widgets')
    if not section['editable']:
        state['can_apply'] = False
        state['reasons'] += section['reasons']
    requested = body.get('rows')
    if not isinstance(requested, list) or len(requested) > 20:
        raise ValueError('A hub supports at most 20 rows')
    group, name = section['group'], section['provenance']['filename']
    raw = snapshots.get(name) or snapshots.get('default:' + group)
    if raw is None:
        raise ValueError('Current widget rows are unavailable')
    tree = _xml(raw)
    old_nodes = tree.findall('shortcut')
    existing = {row['id']: (row, node) for row, node in zip(section['rows'], old_nodes)}
    seen, new_nodes, edits, original_ids = set(), [], [], []
    for request in requested:
        if not isinstance(request, dict):
            raise ValueError('Invalid widget row')
        rid = request.get('id')
        if rid:
            if rid not in existing or rid in seen:
                raise ValueError('Unknown or repeated widget row identity; refresh the layout')
            seen.add(rid)
            original, node = existing[rid]
            node = copy.deepcopy(node)
            if request.get('action', original['action']) != original['action']:
                raise ValueError('Arbitrary actions cannot be changed; choose a folder source')
            label = request.get('label', original['label'])
            if label not in (original['label'], original['raw_label']):
                node.find('label').text = _label(label)
            path = request.get('path', original['path'])
            changed = path != original['path']
            if changed:
                path = _rows({'rows': [{'label': _display_label(node), 'path': path}]})[0]['path']
                _validate_destination(index, path)
                node.find('action').text = 'ActivateWindow(Videos,%s,return)' % path
            original_ids.append(original['label_id'])
            edits.append({'id': rid, 'label': _display_label(node), 'path': path,
                          'action': node.findtext('action'), 'validate_source': changed})
        else:
            row = _rows({'rows': [request]})[0]
            if request.get('action'):
                raise ValueError('New rows must use a source chosen from the directory browser')
            _validate_destination(index, row['path'])
            node = ET.fromstring(_shortcut(row['label'], 'ActivateWindow(Videos,%s,return)' % row['path']))
            original_ids.append(None)
            edits.append(dict(row, validate_source=True))
        new_nodes.append(node)
    new_ids = _label_ids(new_nodes)
    remap = {old: new for old, new in zip(original_ids, new_ids) if old is not None}
    properties = ast.literal_eval(snapshots.get('skin.bingie.properties', b'[]').decode()) if snapshots.get('skin.bingie.properties') else []
    old_ids = {r['label_id'] for r in section['rows']}
    migrated = []
    for prop in properties:
        value = list(prop)
        if value[0] == group and value[1] in old_ids:
            if value[1] not in remap:
                continue
            value[1] = remap[value[1]]
        migrated.append(value)
    # Keep root attributes, unknown child nodes, row metadata and comments.
    positions = [i for i, child in enumerate(tree) if child.tag == 'shortcut']
    insertion = positions[0] if positions else len(tree)
    for node in old_nodes:
        tree.remove(node)
    for offset, node in enumerate(new_nodes):
        tree.insert(insertion + offset, node)
    exports = [{'filename': name, 'xml': ET.tostring(tree, encoding='unicode')}]
    if migrated != properties:
        exports.append({'filename': 'skin.bingie.properties', 'xml': repr(migrated), 'format': 'python-literal'})
    state.update({'section_id': section['id'], 'label': section['label'], 'rows': edits, 'exports': exports,
                  'export_complete': True, 'rebuild_required': True, 'rebuild_command': REBUILD,
                  'rebuild_instructions': 'Reopen Kodi to rebuild changed shortcuts, or set skinshortcuts-reloadmainmenu=True on Home and run the rebuild command.'})
    return state, root, snapshots


def preview_layout(kodi, index, body):
    return _preview(kodi, index, body)[0]


def _atomic(path, raw):
    atomic_write_bytes(path, raw)


def _check_snapshots(root, snapshots, staged=None):
    staged = staged or {}
    for name, original in snapshots.items():
        if name.startswith('default'):
            continue
        if _read(os.path.join(root, name), optional=True) != staged.get(name, original):
            raise ValueError('Shortcut configuration changed during staging; preview again')


def apply_layout(kodi, index, body, write_enabled):
    if not write_enabled:
        raise ValueError("Kodi Manager writes are disabled")
    with _LOCK:
        preview, root, snapshots = _preview(kodi, index, body)
        if not preview["can_apply"]:
            raise ValueError("; ".join(preview["reasons"]))
        if not body.get("expected_revision") or body["expected_revision"] != preview["revision"]:
            raise ValueError("Layout changed since preview; refresh and preview again")
        for row in preview["rows"]:
            if row.get('validate_source') is False:
                continue
            _validate_destination(index, row["path"])
            res = kodi.jsonrpc("Files.GetDirectory", {"directory": row["path"], "media": "video"})
            if res.get("error") or not isinstance(res.get("result", {}).get("files"), list):
                raise ValueError("Widget source could not be verified: %s" % row["label"])
        # Check every original, including unrelated properties, immediately before writing.
        _check_snapshots(root, snapshots)
        backup_id = "skin-layout-" + uuid.uuid4().hex
        backup_root = os.path.join(root, "kodi-manager-backups")
        if os.path.islink(backup_root):
            raise ValueError("Backup directory must not be a symlink")
        backup = os.path.join(backup_root, backup_id)
        os.makedirs(backup, exist_ok=False)
        for name, original in snapshots.items():
            if not name.startswith('default') and original is not None:
                _atomic(os.path.join(backup, name), original)
        _atomic(os.path.join(backup, "manifest.json"), json.dumps({"revision": preview["revision"], "files": {n: _hash(v) for n, v in snapshots.items()}}, sort_keys=True).encode())
        prune_folder(backup_root, "skin-layout-", keep=(backup_id,))
        _check_snapshots(root, snapshots)
        changed, staged = [], {}
        try:
            for export in preview["exports"]:
                name = export["filename"]
                _check_snapshots(root, snapshots, staged)
                raw = None if export.get('delete') else export["xml"].encode("utf-8")
                if raw is None:
                    os.unlink(os.path.join(root, name))
                else:
                    _atomic(os.path.join(root, name), raw)
                changed.append(name)
                staged[name] = raw
            _check_snapshots(root, snapshots, staged)
        except Exception:
            for name in reversed(changed):
                original = snapshots.get(name)
                if _read(os.path.join(root, name), optional=True) != staged[name]:
                    # A concurrent native editor owns the newer contents. Keep
                    # them and retain the backup for an explicit recovery.
                    continue
                if original is None:
                    if os.path.exists(os.path.join(root, name)):
                        os.unlink(os.path.join(root, name))
                else:
                    _atomic(os.path.join(root, name), original)
            raise
        return {"applied": True, "backup_id": backup_id, "changed_files": changed,
                "rebuild_required": True, "rebuild_command": REBUILD,
                "rebuild_instructions": preview["rebuild_instructions"]}


def request_rebuild(kodi, index):
    """Start the reviewed native rebuild after an explicit dashboard action.

    Returns only dispatch status; Skin Shortcuts asynchronously generates its
    includes and reloads the skin. This function does not confirm completion.
    """
    with _LOCK:
        state, _, _ = _context(kodi, index)
        if not state['can_apply']:
            raise ValueError('; '.join(state['reasons']))
        try:
            from .kodi_api import xbmc, xbmcgui
        except ImportError:
            from kodi_api import xbmc, xbmcgui
        if xbmc is None or xbmcgui is None:
            raise ValueError('Rebuild must run inside the Kodi Manager service on Kodi')
        xbmcgui.Window(10000).setProperty('skinshortcuts-reloadmainmenu', 'True')
        xbmc.executebuiltin(REBUILD)
        return {'started': True}
