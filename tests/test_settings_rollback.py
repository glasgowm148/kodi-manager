"""A settings batch that fails part way must not stay half-applied."""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import backup, pipeline, server


class FlakyKodi:
    """Kodi settings in memory; the ``fail_on``-th write raises."""

    def __init__(self, values, fail_on=None):
        self.values, self.fail_on, self.writes = dict(values), fail_on, 0

    def set_addon_setting(self, aid, sid, value):
        self.writes += 1
        if self.writes == self.fail_on:
            raise RuntimeError("Kodi refused the setting")
        self.values[(aid, sid)] = value

    def jsonrpc(self, method, params=None):
        return {"result": []}

    def get_kodi_version(self):
        return "21.0"


@pytest.fixture
def pov(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    data = tmp_path / "pov"
    data.mkdir()
    settings = data / "settings.xml"
    settings.write_text('<settings version="2"><setting id="a">old a</setting><setting id="b">old b</setting></settings>')
    return {"addon_id": "plugin.video.pov", "name": "POV", "addon_data_path": str(data),
            "user_settings_path": str(settings), "settings_schema_path": "", "path": "", "is_stack_addon": True}


def _raw(sid, value):
    return {"component": "plugin.video.pov", "setting_id": sid, "value": value, "source": "raw"}


def test_pipeline_batch_failure_puts_earlier_settings_back(pov):
    kodi = FlakyKodi({}, fail_on=2)
    index = SimpleNamespace(get={"plugin.video.pov": pov}.get)
    with pytest.raises(RuntimeError, match="refused"):
        pipeline.apply_account_settings(kodi, index, [_raw("a", "new a"), _raw("b", "new b")], True)
    assert kodi.values == {("plugin.video.pov", "a"): "old a"}


def test_settings_db_failure_puts_kodi_settings_back(monkeypatch):
    kodi = FlakyKodi({})
    monkeypatch.setattr(pipeline.fenlight_db, "write_changes",
                        lambda addon, pairs: (_ for _ in ()).throw(OSError("database is locked")))
    with pytest.raises(OSError, match="locked"):
        pipeline.write_settings(kodi, [("x", "a", "new", "old")], [({"addon_id": "plugin.video.fenlight"}, [("s", "1")])])
    assert kodi.values == {("x", "a"): "old"}


def test_failed_rollback_is_reported_with_the_settings_left_changed():
    class Broken(FlakyKodi):
        def set_addon_setting(self, aid, sid, value):
            self.writes += 1
            if self.writes >= 2:
                raise RuntimeError("Kodi refused the setting")
            self.values[(aid, sid)] = value
    kodi = Broken({})
    with pytest.raises(RuntimeError, match="x a could not be put back"):
        pipeline.write_settings(kodi, [("x", "a", "new", "old"), ("x", "b", "new", "old")])


def test_dashboard_settings_patch_rolls_back_a_half_applied_batch(pov):
    kodi = FlakyKodi({}, fail_on=2)
    state = SimpleNamespace(kodi=kodi, logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda: None, get={"plugin.video.pov": pov}.get,
                                                  addons={"plugin.video.pov": pov}),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"changes": [{"id": "a", "value": "new a", "source": "raw"},
                                       {"id": "b", "value": "new b", "source": "raw"}]})
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("PATCH", "/api/addons/plugin.video.pov/settings", body,
                     {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
    assert response.status == 500
    assert kodi.values == {("plugin.video.pov", "a"): "old a"}


def test_raw_setting_without_a_value_is_refused(pov):
    kodi = FlakyKodi({})
    state = SimpleNamespace(kodi=kodi, logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda: None, get={"plugin.video.pov": pov}.get,
                                                  addons={"plugin.video.pov": pov}),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        results = []
        for change in ({"id": "a", "value": None, "source": "raw"}, {"id": "a", "source": "raw"}):
            conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
            conn.request("PATCH", "/api/addons/plugin.video.pov/settings", json.dumps({"changes": [change]}),
                         {"Authorization": "Bearer tok", "Content-Type": "application/json"})
            response = conn.getresponse()
            results.append((response.status, json.loads(response.read())["code"]))
            conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
    assert results == [(400, "bad_request")] * 2
    assert kodi.values == {}
