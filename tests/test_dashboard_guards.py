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
import api_addons  # noqa: E402
import dashboard_data  # noqa: E402

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
    with patch.object(api_addons, "create_stack_backup") as backup, patch.object(api_addons, "stack_backup_addons", return_value=[]):
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
    with patch.object(api_addons, "create_stack_backup", side_effect=copying), \
            patch.object(api_addons, "stack_backup_addons", return_value=[]):
        status, body = dashboard.call("POST", "/api/stack/backup", {})
    assert status == 409 and body["code"] == "playback_active"
    assert "discarded" in body["error"]["message"]


def test_idle_checkpoint_still_runs(dashboard):
    with patch.object(api_addons, "create_stack_backup", return_value={"backup_id": "b1"}) as backup, \
            patch.object(api_addons, "stack_backup_addons", return_value=[]):
        status, body = dashboard.call("POST", "/api/stack/backup", {})
    assert status == 200 and body["data"]["backup_id"] == "b1"
    assert callable(backup.call_args.kwargs["should_stop"])


def test_protected_settings_are_not_reapplied_during_playback(dashboard):
    dashboard.players.update(PLAYING)
    with patch.object(api_addons, "make_baseline") as baseline:
        status, body = dashboard.call("POST", "/api/baseline/apply", {})
    assert status == 409 and body["code"] == "playback_active"
    baseline.assert_not_called()
    dashboard.players.clear()
    dashboard.players["result"] = []
    with patch.object(api_addons, "make_baseline") as baseline:
        baseline.return_value.apply.return_value = {"applied": [], "failed": [], "restart_required": False}
        assert dashboard.call("POST", "/api/baseline/apply", {})[0] == 200
        assert dashboard.call("POST", "/api/baseline/apply", {"keys": "x"})[0] == 400


def assert_masked(lines):
    text = "\n".join(lines)
    for secret in ("abc123secret", "abcdefghijklmnop", "sk-test-12345"):
        assert secret not in text
    assert "token=***" in text


def test_kodi_log_lines_are_masked(dashboard):
    status, body = dashboard.call("GET", "/api/kodi/logs")
    assert status == 200
    assert len(body["data"]["lines"]) == 3
    assert_masked(body["data"]["lines"])


def test_health_log_lines_are_masked():
    kodi = SimpleNamespace(get_kodi_version=lambda: "21.0", get_log_history=lambda **kw: {"available": True, "catching_up": False,
        "counts": {"errors": 1, "warnings": 1, "notices": 0, "warning_lines": 1},
        "entries": [{"level": "error", "line": SECRET_LINES[1]}, {"level": "warning", "line": SECRET_LINES[2]}]})
    index = SimpleNamespace(refresh=Mock(), list=lambda: [])
    with patch.object(dashboard_data, "detect_stack", return_value={}), patch.object(dashboard_data, "debug_paths", return_value={}), \
            patch.object(dashboard_data, "memory_status", return_value={}), patch.object(dashboard_data, "internet_check", return_value=None), \
            patch.object(dashboard_data, "maintenance_checks", return_value=[]):
        summary = server.health_summary(kodi, index, {})
    assert summary["stats"]["kodi_log_errors"] == 1 and summary["stats"]["kodi_log_warnings"] == 1
    assert_masked(summary["recent_errors"] + summary["recent_warnings"] + ["token=***"])
    assert "Bearer" in summary["recent_errors"][0]
    assert "past 24 hours" in next(c for c in summary["checks"] if c["id"] == "logs")["detail"]


@pytest.mark.parametrize("host", [
    None, "localhost", "localhost:8765", "LOCALHOST.", "tv.localhost:8765", "127.0.0.1:8765", "[::1]:8765",
    "192.168.1.50:8765", "10.0.0.5", "172.16.3.4:80", "169.254.10.2:8765", "[fe80::1]:8765", "[fd00::5]",
    "shield.local:8765", "Living-Room-TV.local", "8.8.4.4:8765"])
def test_allowed_hosts(host):
    from netconfig import host_allowed
    assert host_allowed(host, "8.8.4.4")


@pytest.mark.parametrize("host", [
    "attacker.example", "attacker.example:8765", "rebind.attacker.example.", "shield", "shield:8765",
    "local", "x.local.evil.example", "8.8.8.8:8765", "[2001:4860::8888]:8765", "192.168.1.50:http",
    "192.168.1.50:8765:1", "[::1", "under_score.local", "bad host"])
def test_refused_hosts(host):
    from netconfig import host_allowed
    assert not host_allowed(host, "0.0.0.0")


def test_bound_public_address_only_when_bound_to_it():
    from netconfig import host_allowed
    assert host_allowed("8.8.4.4:8765", "8.8.4.4")
    assert not host_allowed("8.8.4.4:8765", "0.0.0.0")
    assert not host_allowed("8.8.8.8:8765", "8.8.4.4")


def test_server_refuses_foreign_host_names_for_pages_and_api(dashboard):
    for target in ("/", "/api/status", "/api/bootstrap/status"):
        status, body = dashboard.call("GET", target, host="rebind.attacker.example:8765")
        assert status == 403 and body["code"] == "host_not_allowed", target
    assert dashboard.call("GET", "/api/kodi/logs", host="192.168.1.50:8765")[0] == 200
    assert dashboard.call("GET", "/api/kodi/logs", host="shield.local:8765")[0] == 200
    assert dashboard.call("GET", "/api/kodi/logs", host=False)[0] == 200


def test_history_route_validates_pages_and_returns_masked_entries(dashboard, tmp_path):
    from log_history import LogHistory
    import time
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "kodi.log").write_text("\n".join(SECRET_LINES) + "\n")
    history = LogHistory(tmp_path / "history.db", logs, time.time)
    history.collect()
    dashboard.state.kodi.get_log_history = history.snapshot
    status, body = dashboard.call("GET", "/api/kodi/logs/history?level=warning&limit=1")
    assert status == 200
    assert body["data"]["total"] == 1
    assert "sk-test-12345" not in str(body)
    for query in ("level=debug", "limit=501", "before=-1", "limit=no"):
        status, body = dashboard.call("GET", "/api/kodi/logs/history?" + query)
        assert status == 400 and body["code"] == "bad_request"
