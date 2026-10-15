"""Kodi's setSetting silently keeps the old value when it rejects one: offer only values
Kodi accepts, and read every write back so a rejected value is never reported as saved.

Kodi facts (xbmc AddonSettings.cpp / settings/lib/Setting.cpp): a v1 ``select`` with
``lvalues`` is an integer setting whose option values are the indexes 0..n-1; a v1
``number`` is an integer; a v1 ``slider`` with option int/percent is an integer within its
range; a v2 string refuses "" unless ``<allowempty>true</allowempty>``.
"""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import backup, baseline, pipeline, server
from kodi_manager.settings_schema import flatten_settings, parse_schema
from kodi_manager.validation import SettingValueError, coerce_setting
from kodi_manager.write_policy import RequestRefused

V1_SCHEMA = """<settings>
  <category label="General">
    <setting id="quality" type="select" label="Quality" lvalues="32001|32002|32003" default="1"/>
    <setting id="mode" type="select" label="Mode" values="fast|slow" default="fast"/>
    <setting id="both" type="select" label="Both" values="a|b" lvalues="32001|32002" default="Medium"/>
    <setting id="timeout" type="number" label="Timeout" default="10"/>
    <setting id="volume" type="slider" option="int" range="0,1,10" label="Vol" default="5"/>
    <setting id="share" type="slider" option="percent" range="10,90" label="Share" default="50"/>
    <setting id="ratio" type="slider" range="0.5,0.5,2.5" label="Ratio" default="1.0"/>
    <setting id="note" type="text" label="Note" default=""/>
  </category>
</settings>"""
STRINGS = 'msgid ""\nmsgstr ""\n\nmsgctxt "#32001"\nmsgid "Low"\nmsgstr ""\n\n' \
          'msgctxt "#32002"\nmsgid "Medium"\nmsgstr ""\n\nmsgctxt "#32003"\nmsgid "High"\nmsgstr ""\n'
V2_SCHEMA = """<settings version="1"><section id="plugin.video.x"><category id="general" label="General">
<group id="1">
<setting id="name" type="string" label="Name"><level>0</level><default>a</default>
<control type="edit" format="string"/></setting>
<setting id="optional" type="string" label="Optional"><level>0</level><default/>
<constraints><allowempty>true</allowempty></constraints><control type="edit" format="string"/></setting>
<setting id="ratio" type="number" label="Ratio"><level>0</level><default>1.5</default></setting>
<setting id="limit" type="integer" label="Limit"><level>0</level><default>5</default>
<constraints><minimum>1</minimum><step>1</step><maximum>9</maximum></constraints></setting>
</group></category></section></settings>"""


def _v1(tmp_path, stored='<settings version="2"><setting id="quality">2</setting></settings>'):
    folder = tmp_path / "addon"
    (folder / "resources" / "language" / "resource.language.en_gb").mkdir(parents=True)
    (folder / "resources" / "settings.xml").write_text(V1_SCHEMA)
    (folder / "resources" / "language" / "resource.language.en_gb" / "strings.po").write_text(STRINGS)
    user = tmp_path / "data" / "settings.xml"
    user.parent.mkdir()
    user.write_text(stored)
    return folder, user, flatten_settings(parse_schema(str(folder / "resources" / "settings.xml"), str(folder),
                                                       str(user), True))


def _v2(tmp_path):
    schema = tmp_path / "settings.xml"
    schema.write_text(V2_SCHEMA)
    return flatten_settings(parse_schema(str(schema), str(tmp_path), "", True))


def test_v1_select_with_lvalues_offers_the_index_kodi_stores(tmp_path):
    settings = _v1(tmp_path)[2]
    quality = settings["quality"]
    assert quality["options"] == [{"value": "0", "label": "Low"}, {"value": "1", "label": "Medium"},
                                  {"value": "2", "label": "High"}]
    assert quality["value"] == "2" and quality["default"] == "1" and quality["is_default"] is False
    assert coerce_setting("quality", quality, "0") == "0"
    with pytest.raises(SettingValueError):
        coerce_setting("quality", quality, "32003")   # the label's string id: Kodi ignores it
    # lvalues win over values for a select, as in Kodi; a non-integer default reads as index 0.
    assert [o["value"] for o in settings["both"]["options"]] == ["0", "1"]
    assert settings["both"]["default"] == "0"
    # A select with plain values stays a string setting whose values are the texts.
    assert [o["value"] for o in settings["mode"]["options"]] == ["fast", "slow"]
    assert coerce_setting("mode", settings["mode"], "slow") == "slow"


def test_v1_number_and_int_sliders_take_whole_numbers_in_range(tmp_path):
    settings = _v1(tmp_path)[2]
    assert coerce_setting("timeout", settings["timeout"], "20") == "20"
    assert coerce_setting("timeout", settings["timeout"], "3.0") == "3"
    with pytest.raises(SettingValueError, match="whole"):
        coerce_setting("timeout", settings["timeout"], "2.5")
    assert coerce_setting("volume", settings["volume"], "10") == "10"
    for bad in ("7.5", "11", "-1"):
        with pytest.raises(SettingValueError):
            coerce_setting("volume", settings["volume"], bad)
    assert coerce_setting("share", settings["share"], "90") == "90"
    with pytest.raises(SettingValueError, match="10 to 90"):
        coerce_setting("share", settings["share"], "5")
    # A float slider keeps fractions but not values outside its range.
    assert coerce_setting("ratio", settings["ratio"], "0.75") == "0.75"
    with pytest.raises(SettingValueError):
        coerce_setting("ratio", settings["ratio"], "3")
    # A v1 text setting may be emptied (Kodi allows it).
    assert coerce_setting("note", settings["note"], "") == ""


def test_v2_string_without_allowempty_refuses_an_empty_value(tmp_path):
    settings = _v2(tmp_path)
    with pytest.raises(SettingValueError, match="required"):
        coerce_setting("name", settings["name"], "")
    assert coerce_setting("name", settings["name"], "b") == "b"
    assert coerce_setting("optional", settings["optional"], "") == ""
    # A v2 number keeps fractions; a v2 integer obeys its minimum and maximum.
    assert coerce_setting("ratio", settings["ratio"], "2.5") == "2.5"
    assert coerce_setting("limit", settings["limit"], "9") == "9"
    with pytest.raises(SettingValueError):
        coerce_setting("limit", settings["limit"], "10")


class KodiLike:
    """Add-on settings like Kodi: a rejected value is ignored without an error."""

    def __init__(self, values, reject=()):
        self.values, self.reject, self.writes = dict(values), set(reject), []

    def set_addon_setting(self, aid, sid, value):
        self.writes.append((sid, value))
        if (sid, value) not in self.reject:
            self.values[(aid, sid)] = value

    def get_addon_setting(self, aid, sid):
        return self.values.get((aid, sid), "")

    def jsonrpc(self, method, params=None):
        return {"result": []}

    def get_kodi_version(self):
        return "21.0"


def test_a_rejected_first_write_is_a_refusal_with_nothing_changed():
    kodi = KodiLike({("x", "a"): "old a", ("x", "b"): "old b"}, reject={("a", "bad")})
    with pytest.raises(RequestRefused) as caught:
        pipeline.write_settings(kodi, [("x", "a", "bad", "old a"), ("x", "b", "new b", "old b")])
    assert caught.value.setting_id == "a"
    assert kodi.values == {("x", "a"): "old a", ("x", "b"): "old b"}
    assert kodi.writes == [("a", "bad")]   # b is never written


def test_a_rejected_later_write_puts_the_batch_back_and_is_not_a_refusal():
    kodi = KodiLike({("x", "a"): "old a", ("x", "b"): "old b"}, reject={("b", "bad")})
    with pytest.raises(pipeline.SettingRejected) as caught:
        pipeline.write_settings(kodi, [("x", "a", "new a", "old a"), ("x", "b", "bad", "old b")])
    assert not isinstance(caught.value, RequestRefused)
    assert caught.value.setting_id == "b" and "put back" in str(caught.value)
    assert kodi.values == {("x", "a"): "old a", ("x", "b"): "old b"}


def test_a_rollback_kodi_rejects_is_reported_as_stuck():
    kodi = KodiLike({("x", "a"): "old a"}, reject={("b", "bad"), ("a", "")})
    with pytest.raises(RuntimeError, match="x a could not be put back"):
        pipeline.write_settings(kodi, [("x", "a", "new a", ""), ("x", "b", "bad", "old b")])


def test_read_back_accepts_kodis_own_number_and_boolean_text():
    for written, stored in (("1.0", "1"), ("2.50", "2.5"), ("1234567.5", "1.23457e+06"), ("true", "true"),
                            ("x", "x")):
        assert pipeline.stored_matches(written, stored)
    for written, stored in (("2", "1"), ("a", "b"), ("x", None), ("true", "false"), ("1", "")):
        assert not pipeline.stored_matches(written, stored)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "backup_root", lambda: str(tmp_path / "backups"))
    folder, user, _ = _v1(tmp_path, '<settings version="2"><setting id="quality">2</setting>'
                                    '<setting id="timeout">10</setting></settings>')
    addon = {"addon_id": "plugin.video.x", "name": "X", "path": str(folder), "addon_data_path": str(user.parent),
             "settings_schema_path": str(folder / "resources" / "settings.xml"), "user_settings_path": str(user),
             "is_stack_addon": True}
    kodi = KodiLike({("plugin.video.x", "quality"): "2", ("plugin.video.x", "timeout"): "10"})
    state = SimpleNamespace(kodi=kodi, logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda: None, get={"plugin.video.x": addon}.get,
                                                  addons={"plugin.video.x": addon}),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def patch(changes):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("PATCH", "/api/addons/plugin.video.x/settings", json.dumps({"changes": changes}),
                     {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    yield SimpleNamespace(patch=patch, kodi=kodi)
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_settings_patch_saves_a_select_index_and_refuses_what_kodi_rejected(service):
    status, body = service.patch([{"id": "quality", "value": "0"}])
    assert status == 200 and body["data"]["changed_count"] == 1
    assert service.kodi.values[("plugin.video.x", "quality")] == "0"
    # A value Kodi silently ignores is a refusal: nothing was changed.
    service.kodi.reject.add(("timeout", "30"))
    status, body = service.patch([{"id": "timeout", "value": "30"}])
    assert status == 400 and body["operation"]["outcome"] == "refused"
    assert body["error"]["details"] == {"setting_id": "timeout"}
    assert service.kodi.values[("plugin.video.x", "timeout")] == "10"


def test_settings_patch_reports_a_later_rejection_after_putting_the_batch_back(service):
    service.kodi.reject.add(("timeout", "30"))
    status, body = service.patch([{"id": "quality", "value": "1"}, {"id": "timeout", "value": "30"}])
    assert status == 400 and body["operation"]["outcome"] == "unknown"
    assert body["error"]["details"] == {"setting_id": "timeout"}
    assert service.kodi.values[("plugin.video.x", "quality")] == "2"


def test_baseline_apply_reports_a_value_kodi_rejected_as_failed(tmp_path):
    store = tmp_path / "baseline.json"
    store.write_text(json.dumps({"version": 1, "items": [
        {"kind": "addon_setting", "addon": "plugin.video.x", "id": "a", "value": "wanted"}]}))
    kodi = KodiLike({("plugin.video.x", "a"): "drifted"}, reject={("a", "wanted")})
    result = baseline.Baseline(str(store), kodi).apply()
    assert result["applied"] == []
    assert [f["key"] for f in result["failed"]] == ["setting:plugin.video.x:a"]
    assert "rejected" in result["failed"][0]["error"]
