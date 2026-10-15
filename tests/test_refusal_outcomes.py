"""Validation refusals raised inside write routes, before any write, are reported as refused."""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import api_widgets, backup, server, skin_layout
from kodi_manager.fix_protection import FixProtection

SCHEMA = """<settings version="1"><section id="plugin.video.pov"><category id="general" label="General">
<group id="1"><setting id="limit" type="integer" label="Limit"><level>0</level><default>5</default>
<control type="edit" format="integer"/></setting>
<setting id="name" type="string" label="Name"><level>0</level><default>a</default>
<control type="edit" format="string"/></setting></group></category></section></settings>"""


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "backup_root", lambda: str(tmp_path / "backups"))
    folder = tmp_path / "addon"
    (folder / "resources").mkdir(parents=True)
    (folder / "resources" / "settings.xml").write_text(SCHEMA)
    user = tmp_path / "data" / "settings.xml"
    user.parent.mkdir()
    user.write_text('<settings version="2"><setting id="limit">5</setting><setting id="name">a</setting></settings>')
    pov = {"addon_id": "plugin.video.pov", "name": "POV", "path": str(folder), "addon_data_path": str(user.parent),
           "settings_schema_path": str(folder / "resources" / "settings.xml"), "user_settings_path": str(user),
           "is_stack_addon": True}
    writes = []
    kodi = SimpleNamespace(set_addon_setting=lambda *a: writes.append(a), jsonrpc=lambda m, p=None: {"result": []},
                           get_kodi_version=lambda: "21.0")
    state = SimpleNamespace(kodi=kodi, logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda: None, get={"plugin.video.pov": pov}.get,
                                                  addons={"plugin.video.pov": pov}),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def request(method, path, body):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request(method, path, body if isinstance(body, str) else json.dumps(body),
                     {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    yield SimpleNamespace(request=request, writes=writes, backups=tmp_path / "backups")
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def _outcome(body):
    return body["code"], body["operation"]["outcome"]


@pytest.mark.parametrize("change, message", [
    ({"id": "missing", "value": "1"}, "Unknown setting: missing"),
    ({"id": "missing", "value": "1", "source": "raw"}, "Unknown raw setting: missing"),
    ({"id": "limit", "value": "1.5"}, "limit: Expected a whole number"),
])
def test_settings_batch_refusals_are_refused(service, change, message):
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings",
                                   {"changes": [{"id": "name", "value": "b"}, change]})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert body["error"]["message"] == message
    assert service.writes == [] and not service.backups.exists()


def test_setting_not_editable_is_refused(service, monkeypatch):
    from kodi_manager import api_addons
    monkeypatch.setattr(api_addons, "flatten_settings", lambda parsed: {"name": {"editable": False}})
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings",
                                   {"changes": [{"id": "name", "value": "b"}]})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert body["error"]["message"] == "Setting not editable: name"
    assert service.writes == []


def _preview(can_apply, revision="r1"):
    def preview(kodi, index, body):
        return {"can_apply": can_apply, "reasons": [] if can_apply else ["Unsupported skin version"],
                "revision": revision, "rows": [], "exports": []}, "", {}
    return preview


def test_layout_apply_refusals_are_refused(service, monkeypatch):
    monkeypatch.setattr(skin_layout, "_preview", _preview(False))
    status, body = service.request("POST", "/api/widgets/layout/apply", {"expected_revision": "r1"})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert body["error"]["message"] == "Unsupported skin version"
    monkeypatch.setattr(skin_layout, "_preview", _preview(True, revision="r2"))
    status, body = service.request("POST", "/api/widgets/layout/apply", {"expected_revision": "r1"})
    assert status == 409 and _outcome(body) == ("stale_revision", "refused")


def test_layout_rebuild_refusal_is_refused(service, monkeypatch):
    monkeypatch.setattr(skin_layout, "_context", lambda kodi, index: ({"can_apply": False, "reasons": ["Unsupported"]}, "", {}))
    status, body = service.request("POST", "/api/widgets/layout/rebuild", {})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")


def test_fix_repair_with_nothing_to_restore_is_refused(service, monkeypatch):
    protection = FixProtection.__new__(FixProtection)
    protection.status = lambda: {"groups": [{"id": "pov", "repairable": False}]}
    monkeypatch.setattr(api_widgets, "protection_for_kodi", lambda: protection)
    status, body = service.request("POST", "/api/fixes/repair", {})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert body["error"]["message"] == "No changed files can be restored safely"


def test_other_value_errors_after_a_write_starts_stay_unknown(service, monkeypatch):
    def apply_layout(*args):
        raise ValueError("Shortcut configuration changed during staging; preview again")
    monkeypatch.setattr(api_widgets, "apply_layout", apply_layout)
    status, body = service.request("POST", "/api/widgets/layout/apply", {"expected_revision": "r1"})
    assert status == 400 and _outcome(body) == ("bad_request", "unknown")


@pytest.mark.parametrize("raw", ['{"start": Infinity}', '{"path": "x", "limit": NaN}', '{"x": -Infinity}'])
def test_nan_and_infinity_bodies_are_bad_requests(service, raw):
    status, body = service.request("POST", "/api/widgets/browse", raw)
    assert status == 400 and body["code"] == "bad_request"
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings",
                                   raw.replace('{', '{"changes": [{"id": "limit", "value": 1}], ', 1))
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert service.writes == []


# --- Wrong-typed bodies and bodies JSON cannot hold are refusals, not 500s or unknowns ----

@pytest.mark.parametrize("raw", ['{"start": 1e999}', '{"x": -1e400}', '[' * 100000 + ']' * 100000])
def test_out_of_range_numbers_and_deep_nesting_are_bad_requests(service, raw):
    status, body = service.request("POST", "/api/widgets/browse", raw)
    assert status == 400 and body["code"] == "bad_request"
    if raw.startswith("{"):
        patch = raw.replace('{', '{"changes": [{"id": "limit", "value": 1}], ', 1)
    else:
        patch = '{"changes": ' + '[' * 100000 + ']' * 100000 + '}'
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings", patch)
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert service.writes == []


@pytest.mark.parametrize("sid", [["limit"], {"id": "limit"}, None, 5])
def test_settings_change_ids_that_are_not_text_are_refused(service, sid):
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings",
                                   {"changes": [{"id": sid, "value": "1"}]})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert service.writes == [] and not service.backups.exists()
    status, body = service.request("PATCH", "/api/addons/plugin.video.pov/settings",
                                   {"changes": [{"id": sid, "value": "1", "source": "raw"}]})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")


def test_missing_addon_on_a_write_route_is_refused(service):
    status, body = service.request("PATCH", "/api/addons/plugin.video.missing/settings",
                                   {"changes": [{"id": "limit", "value": "1"}]})
    assert status == 404 and _outcome(body) == ("not_found", "refused")
    assert body["error"]["message"] == "Add-on not found"


def test_other_lookup_errors_after_a_write_starts_stay_unknown(service, monkeypatch):
    def apply_layout(*args):
        raise KeyError("rows")
    monkeypatch.setattr(api_widgets, "apply_layout", apply_layout)
    status, body = service.request("POST", "/api/widgets/layout/apply", {"expected_revision": "r1"})
    assert status == 404 and _outcome(body) == ("not_found", "unknown")


@pytest.mark.parametrize("row", [
    {"label": "Row", "source": 5},
    {"label": "Row", "source": ["plugin://plugin.video.pov/?mode=build_movie_list"]},
    {"label": ["Row"], "source": "plugin://plugin.video.pov/?mode=build_movie_list"},
    {"label": "Row", "source": "plugin://plugin.video.pov/?mode=play_media"},
    {"label": "", "source": "plugin://plugin.video.pov/?mode=build_movie_list"},
])
def test_widget_row_add_input_errors_are_refused(service, monkeypatch, tmp_path, row):
    monkeypatch.setattr(api_widgets, "translate", lambda path: str(tmp_path / "widget_cache"))
    status, body = service.request("POST", "/api/widget-cache/rows", row)
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    assert not (tmp_path / "widget_cache" / "rows.json").exists()


def test_widget_row_add_still_saves_a_listing(service, monkeypatch, tmp_path):
    monkeypatch.setattr(api_widgets, "translate", lambda path: str(tmp_path / "widget_cache"))
    status, body = service.request("POST", "/api/widget-cache/rows",
                                   {"label": "Movies", "source": "plugin://plugin.video.pov/?mode=build_movie_list"})
    assert status == 200 and body["data"]["label"] == "Movies"


@pytest.mark.parametrize("keys", [[["setting:a:b"]], [{"k": 1}], [1], [None]])
def test_baseline_remove_keys_that_are_not_text_are_refused(service, monkeypatch, tmp_path, keys):
    from kodi_manager import api_addons
    from kodi_manager.baseline import Baseline
    path = tmp_path / "baseline.json"
    path.write_text("[]")
    monkeypatch.setattr(api_addons, "make_baseline", lambda kodi: Baseline(str(path), kodi))
    status, body = service.request("POST", "/api/baseline/remove", {"keys": keys})
    assert status == 400 and _outcome(body) == ("bad_request", "refused")
    status, body = service.request("POST", "/api/baseline/remove", {"keys": ["setting:a:b"]})
    assert status == 200 and body["data"] == {"count": 0}
