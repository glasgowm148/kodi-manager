"""Synthetic HTTP/storage only: operation metadata must never alter write semantics."""
import concurrent.futures
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from kodi_manager import ManagerClient, ManagerError, api_status, server
from kodi_manager.operation_records import History, MAX_RECORDS, RETENTION, clean, record

CORRELATION = "a" * 32
BACKUP = "b" * 32
UNDO = "c" * 32


def test_history_is_private_bounded_and_serializes_independent_writers(tmp_path):
    directory = tmp_path / "private"
    stores = [History(directory), History(directory)]
    def write(i):
        row = record("addon_settings_patch", CORRELATION, time.monotonic(), result={"backup_id": BACKUP, "undo_backup_id": UNDO})
        row.update(arguments={"password": "secret"}, target="personal title")
        return stores[i % 2].append(row)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(write, range(300)))
    rows = History(directory).selected(500)
    assert len(rows) == 50 and len({r["operation_id"] for r in rows}) == 50
    assert all(r["backup_refs"] == [BACKUP] and r["recovery_refs"] == [UNDO] for r in rows)
    assert "secret" not in json.dumps(rows) and "personal title" not in json.dumps(rows)
    with sqlite3.connect(str(directory / "history.sqlite3")) as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == MAX_RECORDS
    assert (directory / "history.sqlite3").stat().st_size <= 1048576
    if os.name != "nt":
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (directory / "history.sqlite3").stat().st_mode & 0o777 == 0o600


def test_history_ages_out_and_refuses_corrupt_or_oversized_storage(tmp_path):
    store = History(tmp_path)
    old = record("status", CORRELATION, time.monotonic())
    old["recorded_at"] -= RETENTION + 1
    assert store.append(old)
    assert store.selected() == []
    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"not sqlite")
    assert store.selected() == [] and not store.available
    assert not store.append(record("status", CORRELATION, time.monotonic()))
    path.write_bytes(b"x" * 1048577)
    assert store.selected() == []


def test_history_serializes_separate_processes(tmp_path):
    source = "from kodi_manager.operation_records import History, record; import sys,time; h=History(sys.argv[1]); assert all(h.append(record('status', 'a'*32, time.monotonic())) for _ in range(40))"
    processes = [subprocess.Popen([sys.executable, "-c", source, str(tmp_path)]) for _ in range(3)]
    assert all(process.wait(timeout=15) == 0 for process in processes)
    with sqlite3.connect(str(tmp_path / "history.sqlite3")) as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 120


def test_schema_projection_excludes_values_and_unrecognized_references():
    row = record("status", "Authorization: secret", time.monotonic(), result={"backup_id": "personal-title", "undo_backups": {"profile secret": UNDO}})
    assert row["correlation_id"] != "Authorization: secret"
    assert row["backup_refs"] == [] and row["recovery_refs"] == [UNDO]
    assert "profile secret" not in str(row)
    row["token"] = "secret"
    assert "token" not in clean(row)
    row["schema_version"] = 99
    assert clean(row) is None


@pytest.fixture
def operations_service(tmp_path, monkeypatch):
    players, writes = [], []
    state = SimpleNamespace(
        kodi=SimpleNamespace(jsonrpc=lambda *args: {"result": players}),
        config={"host": "127.0.0.1", "auth_token": "synthetic-token", "write_enabled": True},
        operations=History(tmp_path / "operations"), logs=[], log=lambda *args: None,
        retired=False, web_root="", delay=0, retire_after_write=False, fail_after_write=None,
    )
    monkeypatch.setattr(api_status, "translate", lambda path: str(tmp_path / "metrics.json"))
    class Handler(server.make_handler(state)):
        def api_stack_backup(self):
            self._require_idle("Stop playback before taking a checkpoint", 409)
            writes.append("backup")
            if state.delay:
                time.sleep(state.delay)
            if state.retire_after_write:
                state.retired = True
            if state.fail_after_write == "oserror":
                raise PermissionError(13, "Permission denied")
            if state.fail_after_write == "unencodable":
                return {"backup_id": BACKUP, "when": object()}
            return {"backup_id": BACKUP, "token": "synthetic-token", "title": "personal title"}
        def api_stack_restore(self):
            self._require_idle("Stop playback before restoring", 409)
            writes.append("restore")
            return {"backup_id": BACKUP, "undo_backup_id": UNDO}
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    def request(path, method="GET", token="synthetic-token"):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=3)
        # These actions take no body fields. A separate body send can race an early
        # refusal and abort the response connection on Windows (WinError 10053).
        conn.request(method, path,
                     headers={"Authorization": "Bearer " + token, "X-Correlation-ID": CORRELATION})
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result
    yield SimpleNamespace(state=state, request=request, players=players, writes=writes,
                          url="http://%s:%s" % httpd.server_address)
    httpd.shutdown()
    httpd.server_close()
    thread.join(2)


def test_allow_refuse_auth_correlation_and_recovery(operations_service):
    service = operations_service
    status, body = service.request("/api/stack/backup", "POST")
    assert status == 200 and body["operation"]["outcome"] == "succeeded"
    assert body["operation"]["correlation_id"] == CORRELATION
    assert body["operation"]["backup_refs"] == [BACKUP]
    assert body["history_recorded"]
    status, body = service.request("/api/stack/restore", "POST")
    assert body["operation"]["recovery_refs"] == [UNDO]
    service.state.config["write_enabled"] = False
    status, body = service.request("/api/stack/backup", "POST")
    assert (status, body["operation"]["decision"], body["operation"]["reason_code"]) == (403, "refuse", "write_disabled")
    status, body = service.request("/api/stack/backup", "POST", token="wrong")
    assert status == 401 and body["operation"]["reason_code"] == "unauthorized"
    assert service.writes == ["backup", "restore"]
    status, bundle = service.request("/api/diagnostics/support")
    text = json.dumps(bundle["data"])
    assert status == 200 and "synthetic-token" not in text and "personal title" not in text
    assert bundle["data"]["schema_version"] == 1
    assert {f["reason_code"] for f in bundle["data"]["failures"]} == {"unauthorized", "write_disabled"}


def test_os_error_after_a_write_starts_is_unknown_not_refused(operations_service):
    service = operations_service
    service.state.fail_after_write = "oserror"
    status, body = service.request("/api/stack/backup", "POST")
    # An OS permission error is a server failure, not a Write Mode refusal.
    assert status == 500 and body["code"] == "server_error"
    assert body["operation"]["outcome"] == "unknown" and service.writes == ["backup"]


def test_unencodable_result_still_gets_an_error_envelope(operations_service):
    service = operations_service
    service.state.fail_after_write = "unencodable"
    status, body = service.request("/api/stack/backup", "POST")
    assert status == 500 and body["code"] == "server_error" and body["operation"]["outcome"] == "unknown"


def test_history_works_where_chmod_is_refused(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "chmod", refuse)
    store = History(tmp_path / "shared")
    assert store.append(record("status", CORRELATION, time.monotonic()))
    assert store.available and len(store.selected()) == 1


def test_playback_guard_does_not_write(operations_service):
    operations_service.players.append({"playerid": 1})
    status, body = operations_service.request("/api/stack/restore", "POST")
    assert status == 409 and body["operation"]["outcome"] == "refused"
    assert body["operation"]["reason_code"] == "playback_active"
    assert operations_service.writes == []


def test_client_preserves_response_correlation_and_refusal(operations_service):
    service = operations_service
    client = ManagerClient(service.url, "synthetic-token", allow_writes=True)
    client.request("/api/stack/backup", "POST", {}, correlation_id=CORRELATION)
    assert client.last_operation["correlation_id"] == CORRELATION
    assert client.last_operation["backup_refs"] == [BACKUP]
    service.state.config["write_enabled"] = False
    with pytest.raises(ManagerError) as caught:
        client.request("/api/stack/backup", "POST", {}, correlation_id=CORRELATION)
    assert caught.value.code == "write_disabled" and caught.value.outcome == "refused"
    assert caught.value.correlation_id == CORRELATION
    assert service.writes == ["backup"]


def test_history_failure_does_not_turn_completed_write_into_error(operations_service, monkeypatch):
    monkeypatch.setattr(operations_service.state.operations, "append", lambda row: (_ for _ in ()).throw(OSError("disk full")))
    status, body = operations_service.request("/api/stack/backup", "POST")
    assert status == 200 and body["operation"]["outcome"] == "succeeded"
    assert body["history_recorded"] is False and operations_service.writes == ["backup"]


def test_profile_retirement_after_write_reports_unknown_with_backup(operations_service):
    operations_service.state.retire_after_write = True
    status, body = operations_service.request("/api/stack/backup", "POST")
    assert status == 409 and body["operation"]["outcome"] == "unknown"
    assert body["operation"]["reason_code"] == "server_retired"
    assert body["operation"]["backup_refs"] == [BACKUP]
    assert "Do not repeat" in body["next_step"]


def test_timeout_can_complete_write_and_client_never_repeats_it(operations_service):
    service = operations_service
    service.state.delay = .15
    client = ManagerClient(service.url, "synthetic-token", allow_writes=True, timeout=.03)
    with pytest.raises(ManagerError) as caught:
        client.request("/api/stack/backup", "POST", {})
    assert caught.value.code == "outcome_unknown" and caught.value.outcome == "unknown"
    assert caught.value.correlation_id == client.last_correlation_id
    time.sleep(.2)
    assert service.writes == ["backup"]
    assert service.state.operations.selected()[0]["outcome"] == "succeeded"
    assert client.last_operation is None


def test_write_mode_refusal_stays_write_disabled_and_refused(operations_service):
    service = operations_service
    service.state.config["write_enabled"] = False
    status, body = service.request("/api/stack/backup", "POST")
    assert (status, body["code"], body["operation"]["outcome"]) == (403, "write_disabled", "refused")
    assert service.writes == []


def test_non_private_client_with_malformed_path_is_forbidden_and_unrecorded(operations_service, monkeypatch):
    from kodi_manager import http_base
    service = operations_service
    service.state.config["host"] = "0.0.0.0"
    monkeypatch.setattr(http_base, "_private_client", lambda address: False)
    before = len(service.state.operations.selected(500))
    status, body = service.request("/api/./stack/backup", "POST")
    assert status == 403 and body["code"] == "forbidden" and "operation" not in body
    assert len(service.state.operations.selected(500)) == before


def test_trakt_unavailable_is_a_refusal(operations_service):
    service = operations_service
    service.state.index = SimpleNamespace(get=lambda aid: None)
    status, body = service.request("/api/trakt/sync", "POST")
    assert (status, body["code"], body["operation"]["outcome"]) == (404, "trakt_unavailable", "refused")
