"""Security-relevant request checks and outcome records that earlier tests left unpinned:
a refused request must change nothing (not only answer 403), bootstrap files must never
open protected routes, and route checks must refuse ambiguous or oversized sources."""
import http.client
import io
import json
import threading
import time
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from kodi_manager import baseline, dashboard_data, http_base, server
from kodi_manager.operation_records import clean, record
from kodi_manager.route_guard import action_word, blocked_reason, check_directory

CAPTURE = {"items": [{"kind": "kodi_setting", "id": "videoplayer.seekdelay", "value": 750}]}


class Kodi:
    def __init__(self):
        self.values = {}

    def jsonrpc(self, method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": []}
        if method == "Settings.GetSettingValue":
            return {"result": {"value": 500}}
        return {"result": True}

    def get_addon_setting(self, addon, sid):
        return self.values.get((addon, sid), "live")

    def set_addon_setting(self, addon, sid, value):
        self.values[(addon, sid)] = value

    def get_kodi_version(self):
        return "21.0"


class Operations:
    available = True

    def __init__(self):
        self.rows = []

    def append(self, row):
        self.rows.append(row)
        return True


def _state(tmp_path, **config):
    settings = {"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True, "allowed_addons_csv": "",
                "addon_data_dir": str(tmp_path)}
    settings.update(config)
    addons = {"plugin.video.pov": {"addon_id": "plugin.video.pov", "is_stack_addon": True}}
    return SimpleNamespace(kodi=Kodi(), logs=[], log=lambda msg: None, operations=Operations(),
                           index=SimpleNamespace(refresh=lambda **k: None, get=addons.get, addons=addons,
                                                 list=lambda: []),
                           config=settings, web_root=str(tmp_path))


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = tmp_path / "baseline.json"
    monkeypatch.setattr(dashboard_data, "translate", lambda path: str(store))
    state = _state(tmp_path)
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()

    def call(method, target, body=None, host=None, token="tok", origin=None):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        data = json.dumps(body).encode() if body is not None else b""
        headers = {"Host": host or "%s:%s" % httpd.server_address, "Content-Type": "application/json",
                   "Content-Length": str(len(data))}
        if token:
            headers["Authorization"] = "Bearer " + token
        if origin:
            headers["Origin"] = origin
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, (json.loads(raw) if raw[:1] == b"{" else raw)

    yield SimpleNamespace(call=call, state=state, store=store, tmp=tmp_path)
    httpd.shutdown()
    httpd.server_close()
    thread.join()


# --- refused requests change nothing ------------------------------------------------------

def test_foreign_host_name_changes_nothing_and_records_nothing(service):
    status, body = service.call("POST", "/api/baseline/capture", CAPTURE, host="rebind.attacker.example:8765")
    time.sleep(0.1)   # a handler that wrongly carried on would still be writing
    assert status == 403 and body["code"] == "host_not_allowed"
    assert not service.store.exists()
    assert service.state.operations.rows == []


def test_cross_origin_write_changes_nothing_and_records_only_the_refusal(service):
    origin = "http://evil.example"
    status, body = service.call("POST", "/api/baseline/capture", CAPTURE, origin=origin)
    time.sleep(0.1)
    assert status == 403 and body["code"] == "origin_mismatch"
    assert not service.store.exists()
    assert [(r["reason_code"], r["outcome"]) for r in service.state.operations.rows] == [("origin_mismatch",
                                                                                          "refused")]
    # The same request without a foreign Origin (the dashboard itself) writes.
    status, _ = service.call("POST", "/api/baseline/capture", CAPTURE)
    assert status == 200 and service.store.exists()


def _offline_handler(state, client, method="POST", target="/api/baseline/capture", body=None,
                     host="192.168.1.50:8765"):
    """A handler for one request from ``client`` without a socket (a public address cannot
    connect in a test). ``_private_client`` is the real one."""
    handler_class = server.make_handler(state)
    handler = handler_class.__new__(handler_class)
    data = json.dumps(body if body is not None else CAPTURE).encode()
    handler.client_address = client
    handler.command, handler.path, handler.request_version = method, target, "HTTP/1.1"
    handler.requestline = "%s %s HTTP/1.1" % (method, target)
    handler.headers = BytesParser().parsebytes(
        ("Host: %s\r\nAuthorization: Bearer tok\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
         % (host, len(data))).encode())
    handler.rfile, handler.wfile = io.BytesIO(data), io.BytesIO()
    handler.server = SimpleNamespace(body_deadline=5.0)
    handler.close_connection = True
    return handler


def _answer(handler):
    raw = handler.wfile.getvalue()
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(body)


def test_public_client_is_refused_before_anything_happens(tmp_path, monkeypatch):
    store = tmp_path / "baseline.json"
    monkeypatch.setattr(dashboard_data, "translate", lambda path: str(store))
    state = _state(tmp_path, host="0.0.0.0", allow_lan="true")
    handler = _offline_handler(state, ("8.8.8.8", 1))
    handler._dispatch("POST")
    status, body = _answer(handler)
    assert status == 403 and body["code"] == "forbidden"
    assert not store.exists() and state.operations.rows == []
    # A LAN client with the same request is served (the check looks at the address, not the port).
    handler = _offline_handler(state, ("192.168.1.20", 1))
    handler._dispatch("POST")
    assert _answer(handler)[0] == 200 and store.exists()


def test_private_client_check_uses_the_address(tmp_path):
    state = _state(tmp_path, host="0.0.0.0")
    for client, allowed in ((("8.8.8.8", 1), False), (("8.8.8.8", 54321), False), (("192.168.1.20", 1), True),
                            (("10.0.0.2", 80), True)):
        handler = _offline_handler(state, client)
        handler.err = lambda *args, **kwargs: None
        assert handler._client_allowed() is allowed, client


# --- bootstrap files never open protected routes ---------------------------------------------

def test_bootstrap_files_only_open_the_bootstrap_status_route(service):
    (service.tmp / "installer_seed.json").write_text("{}")
    (service.tmp / "installer_result.json").write_text("{}")
    assert service.call("GET", "/api/bootstrap/status", token=None)[0] == 200
    for method, target, body in (("GET", "/api/addons", None), ("GET", "/api/baseline", None),
                                 ("POST", "/api/baseline/capture", CAPTURE)):
        status, answer = service.call(method, target, body, token=None)
        assert status == 401 and answer["code"] == "unauthorized", target
        status, answer = service.call(method, target, body, token="wrong")
        assert status == 401, target
    assert not service.store.exists()


def test_bootstrap_status_needs_the_token_without_bootstrap_files(service):
    assert service.call("GET", "/api/bootstrap/status", token=None)[0] == 401


# --- outcome records -------------------------------------------------------------------------

def test_a_batch_with_failed_items_is_recorded_as_partial(service):
    service.store.write_text(json.dumps({"version": 1, "items": [
        {"kind": "addon_setting", "addon": "plugin.video.notallowed", "id": "x", "value": "1"},
        {"kind": "addon_setting", "addon": "plugin.video.pov", "id": "y", "value": "wanted"}]}))
    status, body = service.call("POST", "/api/baseline/apply", {})
    assert status == 200 and body["data"]["applied"] == ["setting:plugin.video.pov:y"]
    assert (body["operation"]["reason_code"], body["operation"]["outcome"]) == ("operation_failed", "partial")
    service.store.write_text(json.dumps({"version": 1, "items": []}))
    status, body = service.call("POST", "/api/baseline/apply", {})
    assert (body["operation"]["reason_code"], body["operation"]["outcome"]) == ("ok", "succeeded")


@pytest.mark.parametrize("change", ["profile", "retired"])
def test_a_context_change_after_a_completed_write_is_an_unknown_outcome(service, monkeypatch, change):
    done = threading.Event()
    real_capture = baseline.Baseline.capture

    def capture(self, items, check=None):
        result = real_capture(self, items, check)
        done.set()
        if change == "retired":
            service.state.retired = True
        return result
    monkeypatch.setattr(baseline.Baseline, "capture", capture)
    service.state.profile_path = "profile-a"
    monkeypatch.setattr(http_base, "profile_path",
                        lambda: "profile-b" if done.is_set() and change == "profile" else "profile-a")
    status, body = service.call("POST", "/api/baseline/capture", CAPTURE)
    assert status == 409
    assert body["code"] == ("profile_changed" if change == "profile" else "server_retired")
    assert body["operation"]["outcome"] == "unknown"   # the write did happen
    assert service.store.exists()


# --- operation record validation ---------------------------------------------------------------

def _row(**changes):
    row = record("baseline_capture", None, time.monotonic())
    row.update(changes)
    return row


def test_record_rows_with_a_bad_decision_or_numbers_are_dropped():
    assert clean(_row()) is not None
    assert clean(_row(duration_ms=10 ** 12, recorded_at=10 ** 12)) is not None   # the bound itself is kept
    for bad in ({"decision": "maybe"}, {"decision": ""}, {"decision": None},
                {"duration_ms": -1}, {"duration_ms": 10 ** 12 + 1}, {"recorded_at": 10 ** 12 + 1},
                {"duration_ms": 5.0}, {"recorded_at": True}, {"duration_ms": "5"}):
        assert clean(_row(**bad)) is None, bad


# --- route checks ------------------------------------------------------------------------------

def test_iplayer_routing_key_in_another_case_is_refused():
    for source in ("plugin://plugin.video.iplayerwww/?MODE=119", "plugin://plugin.video.iplayerwww/?Mode=201",
                   "plugin://plugin.video.iplayerwww/?mode=101&MODE=119"):
        assert blocked_reason(source).startswith(("ambiguous mode=", "repeated mode=")), source
        with pytest.raises(ValueError):
            check_directory(source)
    assert check_directory("plugin://plugin.video.iplayerwww/?mode=101")


def test_dialog_words_count_only_where_they_name_the_route():
    assert action_word("options_menu_choice", dialog=True) == "options"
    assert action_word("choiceDialog", dialog=True) == "choice"
    assert action_word("erase_bookmark", dialog=True) == "erase"
    assert action_word("more_like_this") == ""
    for source in ("plugin://plugin.video.example/?mode=options_menu", "plugin://plugin.video.example/?action=select",
                   "plugin://plugin.video.example/?mode=show_text", "plugin://plugin.video.pov/?mode=build_trakt_choice"):
        assert blocked_reason(source), source
        with pytest.raises(ValueError):
            check_directory(source)
    assert blocked_reason("plugin://plugin.video.example/?mode=list&name=options") == ""


def test_directory_sources_with_control_characters_or_too_long_are_invalid():
    good = "plugin://plugin.video.pov/?mode=build_movie_list&name="
    assert check_directory(good + "Films")
    for bad in (good + "a\nb", good + "a\x00b", good + "\x1f", good + "a" * 12000, None, "", 42):
        with pytest.raises(ValueError, match="Invalid source directory URL"):
            check_directory(bad)
    assert check_directory(good + "a" * (12000 - len(good)))   # the limit itself is allowed
