"""Protected settings must not become a way around the write policy."""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import dashboard_data, server

OTHER = "plugin.video.notallowed"


class Kodi:
    def __init__(self):
        self.writes, self.values = [], {}

    def jsonrpc(self, method, params=None):
        if method == "Settings.SetSettingValue":
            self.writes.append((params["setting"], params["value"]))
            return {"result": True}
        if method == "Settings.GetSettingValue":
            return {"result": {"value": "live"}}
        return {"result": []}

    def get_addon_setting(self, addon, sid):
        return self.values.get((addon, sid), "live")

    def set_addon_setting(self, addon, sid, value):
        self.writes.append((addon, sid, value))
        self.values[(addon, sid)] = value

    def get_addon_details(self, addon):
        return {}


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = tmp_path / "baseline.json"
    monkeypatch.setattr(dashboard_data, "translate", lambda path: str(store))
    kodi = Kodi()
    addons = {"plugin.video.pov": {"addon_id": "plugin.video.pov", "is_stack_addon": True}}
    state = SimpleNamespace(kodi=kodi, logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda **k: None, get=addons.get, addons=addons),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True,
                                    "allowed_addons_csv": ""})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def call(path, body):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("POST", path, json.dumps(body), {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data.get("data", data)
    yield call, kodi, store
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.mark.parametrize("item, status", [
    ({"kind": "addon_setting", "addon": OTHER, "id": "x", "value": "attacker"}, 403),
    ({"kind": "addon_xml", "addon": OTHER, "tag": "platform", "value": "all"}, 403),
    ({"kind": "kodi_setting", "id": "network.usehttpproxy", "value": True}, 400),
    ({"kind": "kodi_setting", "id": "network.httpproxyserver", "value": "192.168.1.66"}, 400),
    ({"kind": "kodi_setting", "id": "addons.unknownsources", "value": True}, 400),
    ({"kind": "kodi_setting", "id": "lookandfeel.skin", "value": "skin.other"}, 400),
    ({"kind": "kodi_setting", "id": "videoplayer.adjustrefreshrate", "value": 0}, 400),
    ({"kind": "addon_xml", "addon": "service.kodi.addonadmin", "tag": "platform", "value": "all"}, 400),
    ({"kind": "addon_xml", "addon": "skin.bingie", "tag": "res", "value": "x"}, 400),
    ({"kind": "addon_setting", "addon": "plugin.video.pov", "id": "x", "label": "L" * 81}, 400),
    ({"kind": "addon_setting", "addon": "plugin.video.pov", "id": "x", "label": "Fine\nRe-apply me"}, 400),
])
def test_capture_refuses_what_the_write_policy_refuses(api, item, status):
    call, kodi, store = api
    code, body = call("/api/baseline/capture", {"items": [item]})
    assert code == status, body
    assert not store.exists()


def test_capture_accepts_stack_add_ons_and_playback_settings(api):
    call, kodi, store = api
    code, body = call("/api/baseline/capture", {"items": [
        {"kind": "addon_setting", "addon": "plugin.video.pov", "id": "reuse", "label": "POV invoker"},
        {"kind": "kodi_setting", "id": "general.addonupdates", "value": 2},
        {"kind": "kodi_setting", "id": "videoplayer.usedisplayasclock"},
        {"kind": "kodi_setting", "id": "subtitles.languages"}]})
    assert code == 200 and body["count"] == 4


def test_apply_skips_items_stored_before_these_rules(api):
    call, kodi, store = api
    store.write_text(json.dumps({"version": 1, "items": [
        {"kind": "addon_setting", "addon": OTHER, "id": "x", "value": "attacker"},
        {"kind": "kodi_setting", "id": "network.usehttpproxy", "value": True},
        {"kind": "addon_setting", "addon": "plugin.video.pov", "id": "y", "value": "wanted"}]}))
    code, body = call("/api/baseline/apply", {})
    assert code == 200
    assert body["applied"] == ["setting:plugin.video.pov:y"]
    assert sorted(f["key"] for f in body["failed"]) == ["kodi:network.usehttpproxy", "setting:%s:x" % OTHER]
    assert kodi.writes == [("plugin.video.pov", "y", "wanted")]
