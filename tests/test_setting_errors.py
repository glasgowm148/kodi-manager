"""A refused value in a settings batch names the setting to fix."""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import backup, server
from kodi_manager.validation import SettingValueError, coerce_setting

SCHEMA = """<settings version="1"><section id="plugin.video.pov"><category id="general" label="General">
<group id="1"><setting id="limit" type="integer" label="Limit"><level>0</level><default>5</default>
<control type="edit" format="integer"/></setting>
<setting id="name" type="string" label="Name"><level>0</level><default>a</default>
<control type="edit" format="string"/></setting></group></category></section></settings>"""


def test_coerce_setting_names_the_setting_but_never_the_value():
    with pytest.raises(SettingValueError) as caught:
        coerce_setting("limit", {"type": "integer"}, "1.5")
    assert caught.value.setting_id == "limit"
    assert str(caught.value) == "limit: Expected a whole number"


def test_settings_patch_reports_which_setting_was_refused(tmp_path, monkeypatch):
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
    try:
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("PATCH", "/api/addons/plugin.video.pov/settings",
                     json.dumps({"changes": [{"id": "name", "value": "b"}, {"id": "limit", "value": "1.5"}]}),
                     {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
    assert response.status == 400
    assert body["error"]["message"] == "limit: Expected a whole number"
    assert body["error"]["details"] == {"setting_id": "limit"}
    assert writes == []


def test_fen_light_database_errors_name_the_setting(tmp_path, monkeypatch):
    from kodi_manager import fenlight_db
    db = tmp_path / "settings.db"
    db.write_bytes(b"")
    monkeypatch.setattr(fenlight_db, "db_path", lambda addon: str(db))
    monkeypatch.setattr(fenlight_db, "read_rows", lambda addon: [("results.limit", "integer", "5", "5")])
    with pytest.raises(SettingValueError) as caught:
        fenlight_db.validate_changes({}, [("results.limit", "nan")])
    assert caught.value.setting_id == "results.limit" and str(caught.value).startswith("results.limit: ")
