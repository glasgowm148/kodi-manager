"""Synthetic logs only: persistence, rotation, retention and masked storage."""
from pathlib import Path
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import log_history  # noqa: E402
from log_history import LogHistory, RETENTION  # noqa: E402


def line(at, level="warning", message="sample"):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)) + ".000 T:123 " + level + " <general>: " + message + "\n"


@pytest.fixture
def history(tmp_path):
    clock = [1_800_000_000.0]
    logs = tmp_path / "logs"
    logs.mkdir()
    return LogHistory(tmp_path / "data" / "history.db", logs, lambda: clock[0]), logs, clock


def test_busy_log_keeps_problems_after_thousands_of_info_lines_and_restart(history):
    h, logs, clock = history
    (logs / "kodi.log").write_text(line(clock[0] - 30, "error", "Playback failed") + line(clock[0] - 20) + line(clock[0], "info", "Fine") * 5000)
    h.collect()
    assert h.snapshot()["counts"] == {"errors": 1, "warnings": 1, "notices": 0, "warning_lines": 1}
    restarted = LogHistory(h.path, logs, h.clock)
    restarted.collect()
    assert restarted.snapshot()["total"] == 2
    assert restarted.snapshot()["tracking_started_at"] == clock[0]


def test_signed_cdn_credentials_are_masked_on_disk_and_in_older_retained_entries(history):
    h, logs, clock = history
    raw = line(clock[0], "error", "CCurlFile::Stat <https://cdn.example.invalid/manifest.mpd?__gda__=fixture-signature&mimetype=dash>")
    (logs / "kodi.log").write_text(raw)
    h.collect()
    with sqlite3.connect(h.path) as db:
        assert 'fixture-signature' not in db.execute('SELECT line FROM events').fetchone()[0]
        # Simulate a retained entry written before these signed-token rules existed.
        db.execute('UPDATE events SET line=?', (raw,))
    before = h.snapshot()
    assert 'fixture-signature' not in before['entries'][0]['line']
    assert '?__gda__=***&mimetype=dash>' in before['entries'][0]['line']
    assert before['counts']['errors'] == 1 and before['tracking_started_at'] == clock[0]
    h.collect()
    assert h.snapshot()['entries'][0]['id'] == before['entries'][0]['id']


def test_rotation_preserves_warnings_without_double_counting_old_log(history):
    h, logs, clock = history
    current = logs / "kodi.log"
    current.write_text(line(clock[0] - 100, message="Old warning"))
    h.collect()
    current.rename(logs / "kodi.old.log")
    current.write_text(line(clock[0], "error", "New failure"))
    h = LogHistory(h.path, logs, h.clock)
    h.collect()
    assert h.snapshot()["counts"]["warnings"] == 1
    assert h.snapshot()["counts"]["errors"] == 1
    # A second rotation discards Kodi's old file, not the persisted warning.
    (logs / "kodi.old.log").unlink()
    current.rename(logs / "kodi.old.log")
    current.write_text(line(clock[0], "info"))
    h.collect()
    assert h.snapshot()["total"] == 2


def test_truncate_and_regrow_same_file_header_is_a_new_generation(history):
    h, logs, clock = history
    path = logs / "kodi.log"
    header = line(clock[0], "info", "Common header")
    path.write_text(header + line(clock[0], message="first"))
    h.collect()
    path.write_text(header + line(clock[0], message="second with a longer message"))
    h.collect()
    assert h.snapshot()["total"] == 2
    assert "second with a longer message" in h.snapshot()["entries"][0]["line"]


def test_retention_uses_log_time_not_import_time_and_expires_saved_events(history):
    h, logs, clock = history
    (logs / "kodi.old.log").write_text(line(clock[0] - RETENTION - 1, "error", "Expired") + line(clock[0] - RETENTION + 1, message="Recent"))
    (logs / "kodi.log").write_text(line(clock[0], "info"))
    h.collect()
    assert h.snapshot()["total"] == 1
    clock[0] += 2
    assert h.snapshot()["total"] == 0
    h.collect()
    with sqlite3.connect(h.path) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_partial_write_and_identical_occurrences_are_not_lost(history):
    h, logs, clock = history
    path = logs / "kodi.log"
    warning = line(clock[0], message="identical")
    path.write_text(warning + warning + warning[:-1])
    h.collect()
    assert h.snapshot()["total"] == 2
    with path.open("a") as handle:
        handle.write("\n")
    h.collect()
    h.collect()
    assert h.snapshot()["total"] == 3


def test_import_is_bounded_and_notices_keep_context_across_batches(history, monkeypatch):
    h, logs, clock = history
    skin = {"active": True, "addon_id": "skin.bingie", "version": "2.0.2.3"}
    (logs / "kodi.log").write_text(line(clock[0], message='JSONRPC: Could not parse type "Setting.Details.SettingList"') +
                                 line(clock[0], "info", "JSONRPC: Resolving incomplete types/methods referencing Setting.Details.Setting") +
                                 line(clock[0], message="Trying to add unsupported control type 7") +
                                 line(clock[0], message="Skipped 30 duplicate messages.."))
    monkeypatch.setattr(log_history, "READ_BYTES", 1)
    h.collect(skin)
    assert h.snapshot()["catching_up"]
    for _ in range(4):
        h.collect(skin)
    result = h.snapshot()
    assert result["counts"] == {"errors": 0, "warnings": 0, "notices": 3, "warning_lines": 3}
    assert not result["catching_up"]


def test_storage_masks_secrets_in_entries_and_cursor_anchors(history):
    h, logs, clock = history
    (logs / "kodi.log").write_text(line(clock[0], "error", "Authorization: Bearer abcdefghijklmnop failed") +
                                 line(clock[0], message="api_key=sk-test-12345 token=abc123secret"))
    h.collect()
    for secret in ("abcdefghijklmnop", "sk-test-12345", "abc123secret"):
        assert secret not in str(h.snapshot())
        assert secret.encode() not in Path(h.path).read_bytes()
    assert "••••••••" in str(h.snapshot())


def test_pagination_is_stable_when_new_entries_arrive(history):
    h, logs, clock = history
    path = logs / "kodi.log"
    path.write_text("".join(line(clock[0] - n, message=str(n)) for n in range(5, 0, -1)))
    h.collect()
    first = h.snapshot(limit=2)
    with path.open("a") as handle:
        handle.write(line(clock[0], "error", "new"))
    h.collect()
    second = h.snapshot(limit=2, before=first["next_before"])
    third = h.snapshot(limit=2, before=second["next_before"])
    assert len({e["id"] for page in (first, second, third) for e in page["entries"]}) == 5
    assert not third["has_more"]
    assert h.snapshot(level="error")["total"] == 1


def test_missing_or_stale_collector_does_not_claim_clean_logs(history):
    h, logs, clock = history
    assert not h.snapshot()["available"]
    h.collect()
    assert not h.snapshot()["available"]
    (logs / "kodi.log").write_text(line(clock[0], "info"))
    h.collect()
    assert h.snapshot()["available"]
    clock[0] += 31
    assert not h.snapshot()["available"]


@pytest.mark.parametrize("kwargs", [{"level": "debug"}, {"limit": "no"}, {"limit": 501}, {"limit": 0}, {"before": -1}, {"before": 2 ** 63}])
def test_bad_filters_are_rejected(history, kwargs):
    with pytest.raises(ValueError):
        history[0].snapshot(**kwargs)


def test_disk_failure_is_reported_as_unavailable_by_kodi_api(monkeypatch):
    from kodi_api import KodiAPI
    from types import SimpleNamespace
    kodi = KodiAPI()

    def failing(*args):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(kodi, "_log_history", SimpleNamespace(snapshot=failing))
    assert not kodi.get_log_history()["available"]


def test_background_collector_stops_and_never_calls_kodi_from_its_thread(monkeypatch):
    import service_workers
    import threading
    from types import SimpleNamespace
    monkeypatch.setattr(service_workers, "xbmc", object())
    entered, release = threading.Event(), threading.Event()
    caller = threading.get_ident()
    calls = []

    def active_skin():
        assert threading.get_ident() == caller
        return {"addon_id": "skin.test", "version": "1"}

    def collect(skin, stopping):
        calls.append(skin)
        entered.set()
        release.wait(3)
        assert stopping()

    stop = service_workers.start_log_collector(SimpleNamespace(
        log_history=lambda: SimpleNamespace(collect=collect), get_active_skin=active_skin))
    try:
        assert entered.wait(3)
        assert calls == [{"active": True, "addon_id": "skin.test", "version": "1"}]
    finally:
        stop.set()
        release.set()


@pytest.mark.parametrize('url,secrets', [
    ('http://stream.example.invalid/live/play/fixture-stream-token/42', ['fixture-stream-token']),
    ('https://stream.example.invalid/live/fixture-user/fixture-pass/42.ts', ['fixture-user', 'fixture-pass']),
    ('https://stream.example.invalid/movie/fixture-user/fixture-pass/42.mkv', ['fixture-user', 'fixture-pass']),
    ('https://stream.example.invalid/series/fixture-user/fixture-pass/42.mkv', ['fixture-user', 'fixture-pass']),
    ('http://fixture-user:fixture-pass@stream.example.invalid/file', ['fixture-user', 'fixture-pass']),
])
def test_stream_path_credentials_are_masked_in_storage_and_legacy_responses(history, url, secrets):
    h, logs, clock = history
    raw = line(clock[0], 'error', 'Process - <' + url + '> source read failed with -1!')
    (logs / 'kodi.log').write_text(raw)
    h.collect()
    with sqlite3.connect(h.path) as db:
        stored = db.execute('SELECT line FROM events').fetchone()[0]
        assert all(secret not in stored for secret in secrets)
        db.execute('UPDATE events SET line=?', (raw,))
    snapshot = h.snapshot()
    assert all(secret not in str(snapshot) for secret in secrets)
    assert snapshot['counts']['errors'] == snapshot['total'] == 1
    assert 'stream.example.invalid' in snapshot['entries'][0]['line']
