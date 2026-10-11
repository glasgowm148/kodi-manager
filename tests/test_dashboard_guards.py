"""Dashboard guards: playback refusals, masked log lines and the Host allowlist."""
import http.client
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import server  # noqa: E402

PLAYING = {"result": [{"playerid": 1, "type": "video"}]}
SECRET_LINES = ["info <general>: GET https://cdn.invalid/a?token=abc123secret&x=1",
                "error <general>: Authorization: Bearer abcdefghijklmnop failed",
                "warning <general>: api_key=sk-test-12345 rejected"]


@pytest.fixture
def dashboard():
    players = {"result": []}
    state = SimpleNamespace(
        kodi=SimpleNamespace(jsonrpc=lambda method, params=None: players, get_kodi_version=lambda: "21.0",
                             get_log_lines=lambda n=300: list(SECRET_LINES)),
        index=SimpleNamespace(refresh=Mock(), get=lambda aid: None, addons={}, list=lambda: []),
        config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True, "allowed_addons_csv": ""},
        log=lambda message: None, logs=[], web_root="")
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(method, target, body=None, host=None, token="tok"):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        headers = {"Content-Type": "application/json"}
        if host is not False:
            headers["Host"] = host or "%s:%s" % httpd.server_address
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else b""
        headers["Content-Length"] = str(len(data))
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, (json.loads(raw) if raw and raw[:1] == b"{" else raw)

    yield SimpleNamespace(call=call, state=state, players=players)
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_manual_checkpoint_is_refused_during_playback(dashboard):
    dashboard.players.update(PLAYING)
    with patch.object(server, "create_stack_backup") as backup, patch.object(server, "stack_backup_addons", return_value=[]):
        status, body = dashboard.call("POST", "/api/stack/backup", {})
    assert status == 409 and body["code"] == "playback_active"
    backup.assert_not_called()


def test_manual_checkpoint_stops_when_playback_starts(dashboard):
    def copying(addons, version, should_stop=None):
        assert should_stop is not None and not should_stop()
        dashboard.players.update(PLAYING)
        with patch.object(server.time, "monotonic", return_value=10 ** 9):
            if should_stop():
                raise server.BackupAborted("stopped")
        return {"backup_id": "never"}
    with patch.object(server, "create_stack_backup", side_effect=copying), \
            patch.object(server, "stack_backup_addons", return_value=[]):
        status, body = dashboard.call("POST", "/api/stack/backup", {})
    assert status == 409 and body["code"] == "playback_active"
    assert "discarded" in body["error"]["message"]


def test_idle_checkpoint_still_runs(dashboard):
    with patch.object(server, "create_stack_backup", return_value={"backup_id": "b1"}) as backup, \
            patch.object(server, "stack_backup_addons", return_value=[]):
        status, body = dashboard.call("POST", "/api/stack/backup", {})
    assert status == 200 and body["data"]["backup_id"] == "b1"
    assert callable(backup.call_args.kwargs["should_stop"])


def test_protected_settings_are_not_reapplied_during_playback(dashboard):
    dashboard.players.update(PLAYING)
    with patch.object(server, "make_baseline") as baseline:
        status, body = dashboard.call("POST", "/api/baseline/apply", {})
    assert status == 409 and body["code"] == "playback_active"
    baseline.assert_not_called()
    dashboard.players.clear()
    dashboard.players["result"] = []
    with patch.object(server, "make_baseline") as baseline:
        baseline.return_value.apply.return_value = {"applied": [], "failed": [], "restart_required": False}
        assert dashboard.call("POST", "/api/baseline/apply", {})[0] == 200
        assert dashboard.call("POST", "/api/baseline/apply", {"keys": "x"})[0] == 400
