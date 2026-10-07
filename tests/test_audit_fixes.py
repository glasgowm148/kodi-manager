"""Regression tests for the 2026-10-07 backend audit fixes."""
import json
import os
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from kodi_manager import fsutil
from kodi_manager.widget_plugin import _set_video_info
from kodi_manager.widget_rows import RowStore

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


# --- Kodi 19 InfoTag compatibility ------------------------------------------

class Kodi19Tag:
    def getTitle(self):
        return ""


class Kodi19Item:
    def __init__(self):
        self.info, self.props, self.ids = {}, {}, None

    def getVideoInfoTag(self):
        return Kodi19Tag()

    def setInfo(self, kind, info):
        self.info.update(info)

    def setProperty(self, key, value):
        self.props[key] = value

    def setUniqueIDs(self, ids, default=""):
        self.ids = (ids, default)


def test_family_directory_metadata_falls_back_to_setinfo_on_kodi19():
    li = Kodi19Item()
    _set_video_info(li, {"title": "Ep", "season": 1, "episode": 2, "mediatype": "episode", "genre": "Kids"},
                    {"position": 10, "total": 100}, {"tmdb": "5"})
    assert li.info == {"title": "Ep", "season": 1, "episode": 2, "mediatype": "episode", "genre": "Kids"}
    assert li.props == {"ResumeTime": "10", "TotalTime": "100"}
    assert li.ids == ({"tmdb": "5"}, "tmdb")


# --- Python 3.8 compatibility ------------------------------------------------

def test_source_avoids_python39_only_string_methods():
    offenders = []
    for path in SRC.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(removeprefix|removesuffix)\(", line):
                offenders.append("%s:%d" % (path.relative_to(ROOT), number))
    assert offenders == []


# --- Atomic writes -------------------------------------------------------------

def test_atomic_writes_from_many_threads_never_collide(tmp_path):
    target = tmp_path / "data.json"
    errors = []

    def write(n):
        try:
            for _ in range(20):
                fsutil.atomic_write_json(str(target), {"n": n}, fsync=False)
        except Exception as exc:  # pragma: no cover - the failure being guarded against
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert json.loads(target.read_text())["n"] in range(8)
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_row_store_concurrent_adds_keep_every_row(tmp_path):
    store = RowStore(str(tmp_path))
    sources = ["plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular&n=%d" % n
               for n in range(12)]
    threads = [threading.Thread(target=store.add, args=("Row %d" % n, src)) for n, src in enumerate(sources)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(row["source"] for row in store.load()) == sorted(sources)


# --- Backup restore must never wipe live data ------------------------------------

import pytest  # noqa: E402

from kodi_manager import backup  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    stamps = iter("20260101-1200%02d" % i for i in range(60))
    monkeypatch.setattr(backup.time, "strftime", lambda *_: next(stamps))
    yield root, live, {"addon_id": "plugin.video.pov", "addon_data_path": str(live)}
    backup.set_retention(20)


def test_restoring_the_oldest_backup_at_retention_limit_keeps_it_and_live_data(store):
    root, live, info = store
    backup.set_retention(2)
    (live / "settings.xml").write_text("original")
    oldest = backup.create_backup(info)
    (live / "settings.xml").write_text("second")
    backup.create_backup(info)
    (live / "settings.xml").write_text("current")
    result = backup.restore_backup(info, oldest["backup_id"])
    assert (live / "settings.xml").read_text() == "original"
    # The restored snapshot and the undo snapshot both survive pruning.
    kept = set(os.listdir(root / info["addon_id"]))
    assert {oldest["backup_id"], result["undo_backup_id"]} <= kept
    backup.restore_backup(info, result["undo_backup_id"])
    assert (live / "settings.xml").read_text() == "current"


def test_restore_refuses_a_missing_or_empty_snapshot(store):
    root, live, info = store
    (live / "settings.xml").write_text("current")
    snap = backup.create_backup(info)
    data = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    (data / "settings.xml").unlink()
    with pytest.raises(ValueError):
        backup.restore_backup(info, snap["backup_id"])
    assert (live / "settings.xml").read_text() == "current"
    with pytest.raises(ValueError):
        backup._replace_tree(str(root / "missing"), str(live))
    assert (live / "settings.xml").read_text() == "current"


def test_backup_and_restore_do_not_follow_symlinks(store, tmp_path):
    root, live, info = store
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside")
    (live / "settings.xml").write_text("current")
    os.symlink(str(outside), str(live / "linked_dir"))
    os.symlink(str(outside / "secret.txt"), str(live / "linked_file"))
    snap = backup.create_backup(info)
    copied = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    assert sorted(p.name for p in copied.iterdir()) == ["settings.xml"]
    # A link planted in the snapshot is not followed on restore either.
    os.symlink(str(outside / "secret.txt"), str(copied / "planted"))
    backup.restore_backup(info, snap["backup_id"])
    assert not (live / "planted").exists()
    assert (outside / "secret.txt").read_text() == "outside"


def test_stack_restore_checks_every_component_before_replacing_any(store):
    root, live, info = store
    (live / "settings.xml").write_text("current")
    stack = backup.create_stack_backup([info])
    assert stack["file_counts"] == {info["addon_id"]: 1}
    (root / "_stack" / stack["backup_id"] / info["addon_id"] / "settings.xml").unlink()
    index = SimpleNamespace(get=lambda aid: info if aid == info["addon_id"] else None)
    with pytest.raises(ValueError):
        backup.restore_stack_backup(index, stack["backup_id"])
    assert (live / "settings.xml").read_text() == "current"


# --- HTTP server: routing, auth, CORS, headers --------------------------------------

import http.client  # noqa: E402
import socket  # noqa: E402
from unittest.mock import Mock, patch  # noqa: E402

from kodi_manager import server  # noqa: E402
from kodi_manager.client import READ_POSTS  # noqa: E402


@pytest.fixture
def api_server():
    logs = []
    players = {"result": []}
    addons = {
        "plugin.video.pov": {"addon_id": "plugin.video.pov", "name": "POV", "is_stack_addon": True},
        "plugin.video.other": {"addon_id": "plugin.video.other", "name": "Other", "is_stack_addon": False},
        "service.kodi.addonadmin": {"addon_id": "service.kodi.addonadmin", "name": "Kodi Manager", "is_stack_addon": False},
    }
    state = SimpleNamespace(
        kodi=SimpleNamespace(jsonrpc=lambda method, params=None: players, get_kodi_version=lambda: "21.0"),
        index=SimpleNamespace(refresh=Mock(), get=addons.get, addons=addons),
        config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True, "allowed_addons_csv": ""},
        log=logs.append, logs=[])
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(method, target, body=None, token="tok", headers=None):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        sent = {"Host": "%s:%s" % httpd.server_address, "Content-Type": "application/json"}
        if token:
            sent["Authorization"] = "Bearer " + token
        sent.update(headers or {})
        data = json.dumps(body).encode() if body is not None else b""
        sent["Content-Length"] = str(len(data))
        for key, value in sent.items():
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, (json.loads(raw) if raw else None), dict(response.getheaders())

    yield SimpleNamespace(call=call, state=state, logs=logs, players=players, httpd=httpd)
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_writes_outside_api_prefix_are_not_routed_and_need_no_token(api_server):
    with patch.object(server, "restore_backup") as restore:
        for target in ("/x/addons/plugin.video.pov/restore", "/api2/addons/plugin.video.pov/restore",
                       "/x/api/addons/plugin.video.pov/restore"):
            assert api_server.call("POST", target, {"backup_id": "b"}, token=None)[0] == 404
        restore.assert_not_called()


def test_absolute_form_and_unnormalised_targets_are_rejected(api_server):
    with patch.object(server, "restore_backup") as restore:
        for target in ("http://evil/api/addons/plugin.video.pov/restore",
                       "/api/addons/../addons/plugin.video.pov/restore", "/api//status", "/api/%2e%2e/status"):
            status, body, _ = api_server.call("POST", target, {"backup_id": "b"}, token=None)
            assert status == 400, target
        # Python 3.12+ collapses a leading "//" before the handler sees it; either way nothing runs.
        assert api_server.call("POST", "//evil/api/addons/plugin.video.pov/restore", {}, token=None)[0] in (400, 404)
        restore.assert_not_called()


def test_api_still_requires_token(api_server):
    status, body, _ = api_server.call("POST", "/api/addons/plugin.video.pov/restore", {"backup_id": "b"}, token=None)
    assert status == 401 and body["code"] == "unauthorized" and body["error"]["code"] == "unauthorized"


def test_no_wildcard_cors_and_security_headers(api_server):
    status, _, headers = api_server.call("OPTIONS", "/api/status", token=None)
    assert status == 204 and "Access-Control-Allow-Origin" not in headers
    status, _, headers = api_server.call("GET", "/api/logs")
    assert status == 200 and "Access-Control-Allow-Origin" not in headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" not in headers


def test_cross_origin_writes_are_refused(api_server):
    host = "%s:%s" % api_server.httpd.server_address
    with patch.object(server, "create_stack_backup", return_value={"backup_id": "x"}), \
            patch.object(server, "detect_stack", return_value={k: {} for k in ("tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers", "trakt", "skin")}):
        status, body, _ = api_server.call("POST", "/api/stack/backup", {}, headers={"Origin": "http://evil.example"})
        assert status == 403 and body["error"]["code"] == "origin_mismatch"
        assert api_server.call("POST", "/api/stack/backup", {}, headers={"Origin": "null"})[0] == 403
        assert api_server.call("POST", "/api/stack/backup", {}, headers={"Origin": "http://" + host})[0] == 200
        assert api_server.call("POST", "/api/stack/backup", {})[0] == 200


def test_private_client_check_applies_to_any_non_loopback_bind(api_server):
    api_server.state.config["host"] = "192.168.1.10"
    with patch.object(server, "_private_client", return_value=False):
        assert api_server.call("GET", "/api/logs")[0] == 403
    api_server.state.config["host"] = "127.0.0.1"
    with patch.object(server, "_private_client", return_value=False):
        assert api_server.call("GET", "/api/logs")[0] == 200
    assert not server.is_loopback("0.0.0.0") and server.is_loopback("localhost")


def test_non_object_json_body_is_a_400(api_server):
    status, body, _ = api_server.call("POST", "/api/stack/restore", ["not", "an", "object"])
    assert status == 400 and body["code"] == "bad_request"


def test_route_table_write_flags_match_read_posts():
    for method, pattern, _name, needs_write, _code in server.ROUTES:
        if method == "GET":
            assert not needs_write, pattern
        elif "(?P<" not in pattern:
            assert needs_write == (pattern not in READ_POSTS), pattern


def test_request_line_token_is_masked_in_logs(api_server):
    api_server.call("GET", "/index.html?token=supersecret&x=1", token=None)
    api_server.call("GET", "/api/logs?access_token=othersecret")
    joined = " ".join(api_server.logs)
    assert "supersecret" not in joined and "othersecret" not in joined and "token=***" in joined


def test_restores_require_idle_unless_forced(api_server):
    api_server.players["result"] = [{"playerid": 1}]
    with patch.object(server, "restore_backup", return_value={"restored": True}) as restore, \
            patch.object(server, "restore_stack_backup", return_value={"restored": []}) as stack:
        status, body, _ = api_server.call("POST", "/api/addons/plugin.video.pov/restore", {"backup_id": "b"})
        assert status == 400 and "Stop playback" in body["error"]["message"]
        assert api_server.call("POST", "/api/stack/restore", {"backup_id": "b"})[0] == 400
        restore.assert_not_called()
        stack.assert_not_called()
        assert api_server.call("POST", "/api/addons/plugin.video.pov/restore", {"backup_id": "b", "force": True})[0] == 200
        assert api_server.call("POST", "/api/stack/restore", {"backup_id": "b", "force": True})[0] == 200
    api_server.players["result"] = []
    with patch.object(server, "restore_backup", return_value={"restored": True}):
        assert api_server.call("POST", "/api/addons/plugin.video.pov/restore", {"backup_id": "b"})[0] == 200


def test_settings_report_editable_and_read_only_reason(api_server):
    adapter = SimpleNamespace(name="Generic", get_warnings=lambda addon: [])
    with patch.object(server, "settings_for_addon", return_value={"groups": []}), \
            patch.object(server, "adapter_for", return_value=adapter):
        get = lambda aid: api_server.call("GET", "/api/addons/%s/settings" % aid)[1]["data"]  # noqa: E731
        assert get("plugin.video.pov")["editable"] is True and get("plugin.video.pov")["read_only_reason"] is None
        other = get("plugin.video.other")
        assert other["editable"] is False and "Add plugin.video.other to 'Allowed add-ons'" in other["read_only_reason"]
        assert get("service.kodi.addonadmin")["read_only_reason"] == "Kodi Manager's own settings are edited in Kodi"
        api_server.state.config["allowed_addons_csv"] = "plugin.video.other"
        assert get("plugin.video.other")["editable"] is True
        api_server.state.config["write_enabled"] = False
        assert get("plugin.video.pov")["read_only_reason"] == "Enable writes in Kodi Manager settings"
        status, body, _ = api_server.call("GET", "/api/addons/plugin.video.pov/backups")
        assert status == 200 and "backups" in body["data"]


def test_settings_patch_never_writes_kodi_manager_itself(api_server):
    with patch.object(server, "create_backup") as snapshot:
        status, body, _ = api_server.call("PATCH", "/api/addons/service.kodi.addonadmin/settings",
                                          {"changes": [{"id": "auth_token", "value": "x", "source": "raw"}]})
        assert status == 403 and body["code"] == "self_read_only"
        status, body, _ = api_server.call("PATCH", "/api/addons/plugin.video.other/settings", {"changes": []})
        assert status == 403 and body["code"] == "addon_not_allowed"
        snapshot.assert_not_called()


def test_unknown_addon_is_404(api_server):
    status, body, _ = api_server.call("GET", "/api/addons/plugin.video.missing")
    assert status == 404 and body["code"] == "not_found"


def test_bounded_server_uses_daemon_threads_and_caps_handlers():
    entered, release = threading.Event(), threading.Event()

    class Slow(server.BaseHTTPRequestHandler):
        def do_GET(self):
            entered.set()
            release.wait(5)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    class One(server.BoundedThreadingHTTPServer):
        max_handlers = 1
        slot_wait = 0.2

    assert server.BoundedThreadingHTTPServer.daemon_threads is True
    assert server.BoundedThreadingHTTPServer.max_handlers == 16
    httpd = One(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    first = socket.create_connection(httpd.server_address, timeout=5)
    try:
        first.sendall(b"GET / HTTP/1.0\r\n\r\n")
        assert entered.wait(2)
        second = socket.create_connection(httpd.server_address, timeout=5)
        second.sendall(b"GET / HTTP/1.0\r\n\r\n")
        try:
            closed = second.recv(100) == b""  # Closed: every handler slot is busy.
        except ConnectionResetError:
            closed = True
        assert closed
        second.close()
    finally:
        release.set()
        first.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join()


# --- Pipeline/account writes: same gate as the settings editor ----------------------

import sqlite3  # noqa: E402

from kodi_manager import fenlight_db, pipeline  # noqa: E402
from kodi_manager.write_policy import WriteRefused  # noqa: E402


def _addon(tmp_path, aid, stack=True, values=None):
    data = tmp_path / ("addon data #%s" % aid)
    data.mkdir()
    settings = data / "settings.xml"
    settings.write_text('<settings version="2">%s</settings>' % "".join(
        '<setting id="%s">%s</setting>' % item for item in (values or {"tb.token": "old"}).items()))
    return {"addon_id": aid, "addon_data_path": str(data), "user_settings_path": str(settings),
            "settings_schema_path": "", "path": "", "is_stack_addon": stack}


@pytest.fixture
def writer(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    addons = {aid: _addon(tmp_path, aid, stack) for aid, stack in (
        ("plugin.video.pov", True), ("plugin.video.other", False), ("service.kodi.addonadmin", False),
        ("plugin.video.fenlight", True))}
    kodi = SimpleNamespace(set_addon_setting=Mock())
    index = SimpleNamespace(get=addons.get)
    return SimpleNamespace(kodi=kodi, index=index, addons=addons, root=root, tmp=tmp_path)


def _raw(aid, sid="tb.token", value="new"):
    return {"component": aid, "setting_id": sid, "value": value, "source": "raw"}


def test_account_raw_writes_never_reach_kodi_manager_itself(writer):
    for sid in ("tb.token", "auth_token", "host", "allow_lan", "write_enabled"):
        with pytest.raises(WriteRefused):
            pipeline.apply_account_settings(writer.kodi, writer.index, [_raw("service.kodi.addonadmin", sid)], True)
    writer.kodi.set_addon_setting.assert_not_called()


def test_account_writes_use_the_allowed_addons_gate(writer):
    with pytest.raises(PermissionError):
        pipeline.apply_account_settings(writer.kodi, writer.index, [_raw("plugin.video.other")], True)
    with pytest.raises(PermissionError):
        pipeline.apply_pipeline_settings(writer.kodi, writer.index, [_raw("plugin.video.other")], True)
    writer.kodi.set_addon_setting.assert_not_called()
    result = pipeline.apply_account_settings(writer.kodi, writer.index, [_raw("plugin.video.other")], True,
                                             config={"allowed_addons_csv": "plugin.video.other"})
    assert result["changed_count"] == 1
    writer.kodi.set_addon_setting.assert_called_once_with("plugin.video.other", "tb.token", "new")


def test_whole_batch_is_validated_before_any_write(writer):
    with pytest.raises(ValueError):
        pipeline.apply_account_settings(writer.kodi, writer.index,
                                        [_raw("plugin.video.pov"), _raw("plugin.video.pov", "not.there")], True)
    with pytest.raises(WriteRefused):
        pipeline.apply_account_settings(writer.kodi, writer.index,
                                        [_raw("plugin.video.pov"), _raw("service.kodi.addonadmin")], True)
    writer.kodi.set_addon_setting.assert_not_called()
    assert not (writer.root / "pipeline").exists() or not os.listdir(writer.root / "pipeline")


def test_account_write_backs_up_only_touched_files(writer):
    result = pipeline.apply_account_settings(writer.kodi, writer.index, [_raw("plugin.video.pov")], True)
    snapshot = writer.root / "pipeline" / result["backup_id"]
    files = sorted(str(p.relative_to(snapshot)) for p in snapshot.rglob("*") if p.is_file())
    assert files == ["manifest.json", "plugin.video.pov/settings.xml"]


def _fen_db(writer):
    path = Path(writer.addons["plugin.video.fenlight"]["addon_data_path"]) / "databases" / "settings.db"
    path.parent.mkdir()
    con = sqlite3.connect(str(path))
    con.execute("create table settings (setting_id text, setting_type text, setting_default text, setting_value text)")
    con.executemany("insert into settings values (?, ?, ?, ?)", [
        ("tb.token", "string", "", "old"), ("tb.enabled", "boolean", "false", "false"), ("results.limit", "integer", "5", "5")])
    con.commit()
    con.close()
    return path


def _db(sid, value):
    return {"component": "plugin.video.fenlight", "setting_id": sid, "value": value, "source": "settings.db"}


def test_settings_db_write_needs_existing_file_and_never_creates_one(writer):
    path = Path(writer.addons["plugin.video.fenlight"]["addon_data_path"]) / "databases" / "settings.db"
    with pytest.raises(ValueError, match="not found"):
        pipeline.apply_account_settings(writer.kodi, writer.index, [_db("tb.token", "x")], True)
    assert not path.exists()
    with pytest.raises(ValueError):
        fenlight_db.write_changes(writer.addons["plugin.video.fenlight"], [("tb.token", "x")])
    assert not path.exists()


def test_settings_db_values_are_type_checked_and_written_through_uri_with_special_characters(writer):
    path = _fen_db(writer)
    assert "#" in str(path) and " " in str(path)
    for sid, value in (("tb.enabled", "maybe"), ("results.limit", "ten"), ("results.limit", True), ("tb.token", ["x"])):
        with pytest.raises(ValueError):
            pipeline.apply_account_settings(writer.kodi, writer.index, [_db(sid, value)], True)
    with pytest.raises(ValueError, match="Unknown"):
        pipeline.apply_account_settings(writer.kodi, writer.index, [_db("nope", "1")], True)
    result = pipeline.apply_account_settings(writer.kodi, writer.index,
                                             [_db("tb.token", "new"), _db("tb.enabled", True), _db("results.limit", "7")], True)
    assert result["changed_count"] == 3
    rows = dict((sid, value) for sid, _t, _d, value in fenlight_db.read_rows(writer.addons["plugin.video.fenlight"]))
    assert rows == {"tb.token": "new", "tb.enabled": "true", "results.limit": "7"}
    snapshot = writer.root / "pipeline" / result["backup_id"]
    assert (snapshot / "plugin.video.fenlight" / "databases" / "settings.db").is_file()


def test_fenlight_reader_falls_back_to_a_copy_when_the_database_cannot_be_opened(writer, monkeypatch):
    _fen_db(writer)
    real = sqlite3.connect
    calls = []

    def flaky(database, *args, **kwargs):
        calls.append(database)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(database, *args, **kwargs)

    monkeypatch.setattr(fenlight_db.sqlite3, "connect", flaky)
    rows = fenlight_db.read_rows(writer.addons["plugin.video.fenlight"])
    assert len(rows) == 3 and len(calls) == 2 and calls[0].startswith("file:")


def test_redact_masks_secrets_inside_strings():
    from kodi_manager.validation import redact
    out = redact({"msg": '"GET /?token=abc123&x=1 HTTP/1.1" 200', "nested": ["Authorization: Bearer s3cr3t.v"],
                  "note": "auth_token=xyz password: hunter2", "plain": "Server started at http://0.0.0.0:8765"})
    joined = json.dumps(out)
    for secret in ("abc123", "s3cr3t", "xyz", "hunter2"):
        assert secret not in joined
    assert out["plain"] == "Server started at http://0.0.0.0:8765" and "x=1" in out["msg"]


# --- One validator for read-only directory routes ------------------------------------

from kodi_manager import route_guard, widget_cache, widget_catalog, widget_plugin  # noqa: E402

ACTION_ROUTES = [
    "plugin://plugin.video.pov/?mode=toggle_language_invoker",
    "plugin://plugin.video.pov/?mode=refresh_widgets",
    "plugin://plugin.video.fenlight/?mode=kodi_refresh",
    "plugin://plugin.video.example/?route=play",
    "plugin://plugin.video.example/?route=play&name=Popular",
    "plugin://plugin.video.pov/?mode=playNextEpisode",
    "plugin://plugin.video.pov/?mode=navigator.settings",
    "plugin://plugin.video.pov/?mode=clear_cache",
    "plugin://plugin.video.pov/?mode=trakt_sign_in",
    "plugin://plugin.video.pov/?mode=trakt_logout",
    "plugin://plugin.video.pov/?mode=uninstall_module",
    "plugin://plugin.video.pov/?mode=maintenance",
    "plugin://plugin.video.pov/?mode=rescan_library",
    "plugin://plugin.video.pov/?mode=reset_settings",
    "plugin://plugin.video.pov/?mode=build_movie_list&action=delete_list",
    "plugin://plugin.video.tmdb.bingie.helper/?info=play&tmdb_type=movie&tmdb_id=1",
    "plugin://plugin.video.tmdb.bingie.helper/?info=authenticate_trakt",
    "plugin://plugin.video.pov/play/123",
    "plugin://plugin.video.pov/%70lay/123",
    "plugin://plugin.video.pov/tools/",
    "plugin://plugin.video.pov/?isFolder=false",
]
LISTING_ROUTES = [
    "plugin://plugin.video.pov/",
    "plugin://plugin.video.pov/?mode=navigator.main",
    "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular",
    "plugin://plugin.video.pov/?mode=build_movie_list&action=trakt_watchlist&reload=$INFO[Window(Home).Property(km_widgets)]",
    "plugin://plugin.video.pov/?mode=build_tvshow_list&action=trakt_tv_popular",
    "plugin://plugin.video.pov/?name=In+Progress&iconImage=in_progress_tvshow.png&mode=build_tvshow_list&action=in_progress_tvshows",
    "plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=1399",
    "plugin://plugin.video.pov/?mode=build_episode_list&tmdb_id=1399&season=1",
    "plugin://plugin.video.pov/?mode=build_continue_episode",
    "plugin://plugin.video.pov/?mode=build_trakt_list&slug=little-favourites&list_type=my_lists",
    # Free-text values that merely start with an action word are not routes.
    "plugin://plugin.video.pov/?mode=build_trakt_list&slug=x&list_id=1&user=markus-kids-1&list_type=my_lists",
    "plugin://plugin.video.example/?mode=list&genre=playful&studio=Playground+Ltd",
    "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_media_discover&name=Hidden+gems",
    "plugin://plugin.video.pov/?mode=trakt_lists&action=popular",
    "plugin://plugin.video.fenlight/?mode=build_movie_list&action=tmdb_movies_latest_releases",
    "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_trending&tmdb_type=movie&widget=true",
    "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_ondeck_unwatched&tmdb_type=movie&widget=true",
    "plugin://plugin.video.tmdb.bingie.helper/?info=details&tmdb_type=tv&tmdb_id=1",
    "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_userlist&list_slug=play-time&user_slug=me",
    "plugin://plugin.video.themoviedb.helper/?info=trending_week&tmdb_type=movie&reload=$INFO[Window(Home).Property(TMDbHelper.Widgets.Reload)]",
]


class _Installed:
    def get(self, aid):
        return {"addon_id": aid, "installed": True, "enabled": True}


@pytest.mark.parametrize("source", ACTION_ROUTES)
def test_action_routes_are_refused_by_every_validator(source):
    with pytest.raises(ValueError):
        route_guard.check_directory(source)
    with pytest.raises(ValueError):
        widget_cache.validate_source(source)
    with pytest.raises(ValueError):
        widget_plugin.validate_source(_Installed(), source)
    with pytest.raises(ValueError):
        widget_catalog.listing_path(source, _Installed())


@pytest.mark.parametrize("source", LISTING_ROUTES)
def test_listing_routes_of_the_stack_stay_accepted(source):
    assert route_guard.check_directory(source) == source
    assert widget_plugin.validate_source(_Installed(), source) == source
    assert widget_catalog.listing_path(source, _Installed()) == source


def test_browse_never_calls_kodi_for_an_action_route():
    kodi = SimpleNamespace(jsonrpc=Mock())
    for source in ACTION_ROUTES[:4]:
        with pytest.raises(ValueError):
            widget_catalog.browse_directory(kodi, _Installed(), source)
    kodi.jsonrpc.assert_not_called()


# --- Add-on index refresh and kodi.log tail ------------------------------------------------

from kodi_manager import addon_index, kodi_api  # noqa: E402


def test_addon_index_refresh_is_rate_limited_and_swapped_atomically(monkeypatch):
    monkeypatch.setattr(addon_index, "probe_all", lambda seed: {})
    monkeypatch.setattr(addon_index, "safe_listdir", lambda root: {"dirs": []})
    monkeypatch.setattr(addon_index, "enrich_addon", lambda addon, kodi=None, index=None: dict(addon))
    calls = []
    clock = [100.0]

    def list_addons():
        calls.append(1)
        return [{"addon_id": "plugin.video.pov"}, {"addon_id": "plugin.video.fen"}]

    kodi = SimpleNamespace(list_addons=list_addons, get_addon_details=lambda aid: {})
    index = addon_index.AddonIndex(kodi, clock=lambda: clock[0])
    assert len(calls) == 1 and set(index.addons) == {"plugin.video.pov", "plugin.video.fen"}
    index.refresh()
    assert len(calls) == 1  # within 5 s: no rescan
    index.refresh(force=True)
    assert len(calls) == 2
    clock[0] += 6
    before = index.addons
    index.refresh()
    assert len(calls) == 3 and index.addons is not before and before  # a new dict replaced the old one

    seen_sizes = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            seen_sizes.append(len(index.addons))

    thread = threading.Thread(target=reader)
    thread.start()
    for _ in range(50):
        index.refresh(force=True)
    stop.set()
    thread.join()
    assert seen_sizes and min(seen_sizes) == 2  # never observed a half-built index


def test_kodi_log_reads_only_the_tail(tmp_path, monkeypatch):
    log = tmp_path / "kodi.log"
    lines = ["line %06d %s" % (i, "x" * 80) for i in range(20000)]  # about 1.8 MB
    log.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(kodi_api, "xbmcvfs", None)
    text = kodi_api.read_tail(str(log), 64 * 1024)
    assert len(text.encode()) <= 64 * 1024 and text.splitlines()[0].startswith("line ")
    assert text.splitlines()[-1] == lines[-1]
    monkeypatch.setattr(kodi_api, "translate", lambda p: str(log) if p.endswith("kodi.log") else p)
    assert kodi_api.KodiAPI().get_log_lines(3) == lines[-3:]


# --- Autocache keeps comments, takes the layout lock and prunes its backups ----------------

from kodi_manager import skin_layout, widget_autocache  # noqa: E402

POV_ROW = "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_blockbusters"


def _hub(tmp_path):
    hub = tmp_path / "skin.bingie-moviehub.DATA.xml"
    hub.write_text("<shortcuts><!-- keep me --><shortcut><label>Row</label><action>ActivateWindow(Videos,%s,return)"
                   "</action></shortcut></shortcuts>" % POV_ROW.replace("&", "&amp;"))
    return hub


def test_autocache_keeps_xml_comments_and_holds_the_layout_lock(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    held = []
    real = widget_autocache._autocache

    def spy(*args):
        acquired = skin_layout._LOCK.acquire(blocking=False)  # re-entrant: succeeds only for the holder
        held.append(acquired and skin_layout._LOCK._is_owned())
        skin_layout._LOCK.release()
        return real(*args)

    monkeypatch.setattr(widget_autocache, "_autocache", spy)
    assert widget_autocache.autocache(str(tmp_path), now=0) == {hub.name: 1}
    assert "<!-- keep me -->" in hub.read_text() and "mode=cached" in hub.read_text()
    assert held == [True]


def test_autocache_and_layout_backups_are_pruned_to_retention(tmp_path):
    backups = tmp_path / "kodi-manager-backups"
    for i in range(5):
        for prefix in ("autocache-2026010%d-000000" % i, "skin-layout-%d" % i, "claude-2026-%d" % i):
            (backups / prefix).mkdir(parents=True)
            os.utime(str(backups / prefix), (i, i))
    backup.set_retention(2)
    try:
        _hub(tmp_path)
        widget_autocache.autocache(str(tmp_path), now=10 ** 9)
        names = sorted(os.listdir(str(backups)))
        newest = "autocache-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(10 ** 9))
        assert {n for n in names if n.startswith("autocache-")} == {"autocache-20260104-000000", newest}
        assert len([n for n in names if n.startswith("claude-")]) == 5  # other folders are never touched
        assert backup.prune_folder(str(backups), "skin-layout-") == ["skin-layout-2", "skin-layout-1", "skin-layout-0"]
    finally:
        backup.set_retention(20)


# --- Service resilience ---------------------------------------------------------------------

from kodi_manager import service, widget_rows  # noqa: E402


class _Addon:
    def __init__(self, **settings):
        self.settings = dict({"auth_token": "t"}, **settings)

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.settings[key] = value


def _config(tmp_path, **settings):
    with patch.object(service, "translate", return_value=str(tmp_path)):
        return service.load_config(_Addon(**settings))


def test_int_settings_fall_back_to_defaults(tmp_path):
    config = _config(tmp_path, port="80x", backup_retention="lots")
    assert config["port"] == 8765 and config["backup_retention"] == 20
    assert _config(tmp_path, port="70000")["port"] == 8765
    assert _config(tmp_path, port="9000", backup_retention="5")["port"] == 9000


def test_lan_access_with_default_host_binds_all_interfaces(tmp_path):
    assert _config(tmp_path, allow_lan="true", host="127.0.0.1")["host"] == "0.0.0.0"
    assert _config(tmp_path, allow_lan="true")["host"] == "0.0.0.0"
    assert _config(tmp_path, allow_lan="true", host="192.168.1.20")["host"] == "192.168.1.20"
    assert _config(tmp_path, allow_lan="false", host="0.0.0.0")["host"] == "127.0.0.1"
    assert _config(tmp_path, allow_lan="false", host="192.168.1.20")["host"] == "127.0.0.1"
    heading, _text = widget_rows.dashboard_message({"allow_lan": "true", "host": "127.0.0.1", "port": "8765", "auth_token": "x"}, "192.168.1.9")
    assert heading == "Open the dashboard"


def test_server_bind_failure_is_logged_and_notified():
    kodi = SimpleNamespace(log=Mock(), notify=Mock())

    class Busy:
        def __init__(self, *args):
            raise OSError(48, "Address already in use")

    assert service.start_server(kodi, {"host": "0.0.0.0", "port": 8765}, "", Busy) is None
    assert "could not start" in kodi.log.call_args[0][0]
    kodi.notify.assert_called_once()


def test_settings_change_swaps_config_or_restarts_on_network_change():
    kodi = SimpleNamespace(log=Mock(), notify=Mock())
    started = []

    class FakeServer:
        def __init__(self, kodi, config, web_root):
            self.config, self.stopped = config, False
            started.append(self)

        def start(self):
            pass

        def stop(self):
            self.stopped = True

        def update_config(self, config):
            self.config = config

    old = {"host": "0.0.0.0", "port": 8765, "allow_lan": True, "write_enabled": False}
    current = service.start_server(kodi, old, "", FakeServer)
    swapped = service.apply_settings_change(kodi, current, old, dict(old, write_enabled=True), "", FakeServer)
    assert swapped is current and current.config["write_enabled"] is True and len(started) == 1
    moved = service.apply_settings_change(kodi, current, old, dict(old, port=9000), "", FakeServer)
    assert moved is not current and current.stopped and moved.config["port"] == 9000 and len(started) == 2
