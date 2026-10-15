"""Consistent SQLite snapshots, abort reasons, restore serialisation and long file names."""
import os
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kodi_manager import backup, fsutil, maintenance
from kodi_manager.maintenance import Maintenance


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    info = {"addon_id": "plugin.video.pov", "addon_data_path": str(live)}
    return root, live, info


def _wal_db_with_uncheckpointed_rows(path, rows=500):
    """A WAL database whose newest commits are only in its -wal file; the writer stays open."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma wal_autocheckpoint=0")
    conn.execute("create table t(id integer primary key, v text)")
    conn.executemany("insert into t(v) values (?)", [("x" * 100,) for _ in range(rows)])
    return conn


def test_wal_database_snapshot_is_self_contained_and_restores(storage):
    root, live, info = storage
    (live / "settings.xml").write_text("<settings/>")
    writer = _wal_db_with_uncheckpointed_rows(live / "cache.db")
    try:
        assert (live / "cache.db-wal").stat().st_size > 0
        snap = backup.create_backup(info)
    finally:
        writer.close()
    folder = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    # Only the database itself: its -wal/-shm are folded into the copy.
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db", "settings.xml"]
    assert snap["files_copied"] == 2
    conn = sqlite3.connect(str(folder / "cache.db"))
    try:
        assert conn.execute("pragma integrity_check").fetchall() == [("ok",)]
        assert conn.execute("select count(*) from t").fetchone() == (500,)
    finally:
        conn.close()
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db", "settings.xml"]

    # A newer live state with its own -wal: restoring must not leave that -wal beside the old database.
    writer = sqlite3.connect(str(live / "cache.db"), isolation_level=None)
    writer.execute("pragma wal_autocheckpoint=0")
    writer.execute("delete from t")
    writer.execute("insert into t(v) values ('new')")
    wal = (live / "cache.db-wal").read_bytes()
    writer.close()  # the last connection checkpoints and deletes the -wal: put it back
    (live / "cache.db-wal").write_bytes(wal)
    stack = backup.create_stack_backup([info])
    assert stack["file_counts"] == {info["addon_id"]: 2}
    real_copytree = backup._copytree
    seen = []

    def copytree(src, dst, *args, **kwargs):
        seen.append(os.path.exists(os.path.join(dst, "cache.db-wal")))
        return real_copytree(src, dst, *args, **kwargs)
    with patch.object(backup, "_copytree", copytree):
        backup.restore_backup(info, snap["backup_id"])
    # [undo snapshot, restore]: the stale -wal was gone before the old database was copied in.
    assert seen[-1] is False
    assert not (live / "cache.db-wal").exists()
    conn = sqlite3.connect(str(live / "cache.db"))
    try:
        assert conn.execute("select count(*) from t").fetchone() == (500,)
    finally:
        conn.close()


def test_rollback_journal_database_is_copied_without_its_journal(storage):
    root, live, info = storage
    conn = sqlite3.connect(str(live / "cache.db"))
    conn.execute("create table t(v)")
    conn.execute("insert into t values (1)")
    conn.commit()
    conn.close()
    (live / "cache.db-journal").write_bytes(b"")  # an empty journal left between transactions
    snap = backup.create_backup(info)
    folder = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db"]
    assert snap["files_copied"] == 1
    backup.restore_backup(info, snap["backup_id"])


def test_older_snapshot_with_side_files_still_restores(storage):
    root, live, info = storage
    (live / "cache.db").write_bytes(backup.SQLITE_HEADER + b"\0" * 100)
    folder = root / info["addon_id"] / "20250101-000000-old" / "addon_data"
    folder.mkdir(parents=True)
    for name in ("cache.db", "cache.db-wal", "settings.xml"):
        (folder / name).write_bytes(b"old " + name.encode())
    (folder.parent / "manifest.json").write_text('{"backup_id": "20250101-000000-old", "files_copied": 3}')
    with patch.object(backup, "_copy_sqlite", return_value=False):  # the live file is not a real database
        backup.restore_backup(info, "20250101-000000-old")
    assert (live / "cache.db-wal").read_bytes() == b"old cache.db-wal"


def test_vanished_side_file_aborts_as_busy_even_if_it_reappeared(storage, monkeypatch):
    root, live, info = storage
    (live / "cache.db").write_text("not sqlite")
    (live / "cache.db-wal").write_text("pages")
    real_copy = backup._copy_file

    def racing_copy(src, dst, *args, **kwargs):
        if src.endswith("-wal"):
            raise FileNotFoundError(src)  # gone at open time, back again by the time we look
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup, "_copy_file", racing_copy)
    with pytest.raises(backup.BackupAborted) as caught:
        backup.create_backup(info)
    assert caught.value.reason == "busy_database"
    assert list((root / info["addon_id"]).iterdir()) == []


def test_should_stop_reason_is_carried_by_the_abort(storage):
    root, live, info = storage
    (live / "a.json").write_text("{}")
    with pytest.raises(backup.BackupAborted) as caught:
        backup.create_stack_backup([info], should_stop=lambda: "playback")
    assert caught.value.reason == "playback"
    with pytest.raises(backup.BackupAborted) as caught:
        backup.create_backup(info, should_stop=lambda: True)
    assert caught.value.reason == "stopped"


def test_locked_database_snapshot_is_stoppable_while_waiting(storage, monkeypatch):
    root, live, info = storage
    conn = sqlite3.connect(str(live / "cache.db"), isolation_level=None)
    conn.execute("create table t(v)")
    conn.execute("begin exclusive")
    try:
        calls = []

        def stop():
            calls.append(1)
            return "stopping" if len(calls) > 3 else False
        started = time.monotonic()
        with pytest.raises(backup.BackupAborted) as caught:
            backup.create_backup(info, should_stop=stop)
        assert caught.value.reason == "stopping"
        assert time.monotonic() - started < backup.SQLITE_BUSY_SECONDS
    finally:
        conn.execute("rollback")
        conn.close()


# --- long names ------------------------------------------------------------------

@pytest.mark.parametrize("name", ["s" * 235 + ".xml", "设" * 80 + ".json"])
def test_long_file_names_are_backed_up_and_written(storage, name):
    root, live, info = storage
    try:
        (live / name).write_text("data")
    except OSError:
        pytest.skip("file system refuses the name itself")
    snap = backup.create_backup(info)
    assert snap["files_copied"] == 1
    target = root / info["addon_id"] / snap["backup_id"] / "addon_data" / name
    assert target.read_text() == "data"
    fsutil.atomic_write_bytes(str(live / name), b"new")
    assert (live / name).read_bytes() == b"new"
    assert sorted(os.listdir(str(live))) == [name]
    assert backup._TRANSIENT.search(os.path.basename(backup._temp_sibling(str(live / name))))
    prefix = fsutil.temp_prefix(str(live / name))
    assert len((prefix + "abcdefgh.km-tmp").encode("utf-8")) < 255


# --- restores, pruning ---------------------------------------------------------------

def test_prune_and_delete_skip_snapshots_a_restore_is_using(storage, monkeypatch):
    root, live, info = storage
    (live / "a.json").write_text("{}")
    monkeypatch.setattr(backup, "_retention", 1)
    stack = [backup.create_stack_backup([info]) for _ in range(1)][0]
    folder = backup._backup_path("_stack", stack["backup_id"])
    key = backup._hold(folder)
    try:
        newer = backup.create_stack_backup([info])  # its prune would remove the older one
        assert (root / "_stack" / stack["backup_id"]).is_dir()
        assert backup.delete_stack_backup(stack["backup_id"]) is False
    finally:
        backup._release(key)
    assert backup.delete_stack_backup(stack["backup_id"]) is True
    assert (root / "_stack" / newer["backup_id"]).is_dir()


def test_restore_undo_snapshot_is_kept_while_the_restore_runs(storage, monkeypatch):
    root, live, info = storage
    (live / "a.json").write_text("one")
    first = backup.create_backup(info)
    monkeypatch.setattr(backup, "_retention", 1)
    real_restore = backup._restore_folder
    seen = {}

    def restore_while_others_back_up(aid, src, dest, skip, expected):
        # Another thread finishes a backup of the same add-on: its prune must keep the undo copy.
        worker = threading.Thread(target=lambda: seen.setdefault("other", backup.create_backup(info)))
        worker.start()
        worker.join()
        seen["undo_dirs"] = sorted(p.name for p in (root / info["addon_id"]).iterdir())
        return real_restore(aid, src, dest, skip, expected)

    monkeypatch.setattr(backup, "_restore_folder", restore_while_others_back_up)
    result = backup.restore_backup(info, first["backup_id"])
    assert result["undo_backup_id"] in seen["undo_dirs"]
    assert backup._IN_USE == {}


def test_restores_are_serialised(storage, monkeypatch):
    root, live, info = storage
    (live / "a.json").write_text("one")
    snap = backup.create_backup(info)
    real_restore = backup._restore_folder
    active, overlap = [0], []

    def slow(aid, src, dest, skip, expected):
        active[0] += 1
        overlap.append(active[0])
        time.sleep(0.05)
        try:
            return real_restore(aid, src, dest, skip, expected)
        finally:
            active[0] -= 1

    monkeypatch.setattr(backup, "_restore_folder", slow)
    threads = [threading.Thread(target=backup.restore_backup, args=(info, snap["backup_id"])) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap == [1, 1, 1]


def test_busy_undo_snapshot_leaves_every_stack_component_untouched(storage, tmp_path, monkeypatch):
    root, live, info = storage
    other_live = tmp_path / "other"
    other_live.mkdir()
    other = {"addon_id": "plugin.video.other", "addon_data_path": str(other_live)}
    (live / "a.json").write_text("old")
    (other_live / "b.json").write_text("old")
    stack = backup.create_stack_backup([info, other])
    (live / "a.json").write_text("new")
    (other_live / "b.json").write_text("new")
    real = backup.create_backup

    def busy_second(addon, *args, **kwargs):
        if addon["addon_id"] == "plugin.video.pov":
            raise backup.BackupAborted("busy", "busy_database")
        return real(addon, *args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", busy_second)
    index = {info["addon_id"]: info, other["addon_id"]: other}
    with pytest.raises(backup.BackupAborted):
        backup.restore_stack_backup(index, stack["backup_id"])
    assert (live / "a.json").read_text() == "new" and (other_live / "b.json").read_text() == "new"


# --- nightly ---------------------------------------------------------------------------

class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_nightly_busy_database_is_retried_the_same_night_and_shown():
    clock = Clock(time.mktime((2026, 10, 9, 3, 30, 0, 0, 0, -1)))
    outcomes = [backup.BackupAborted("busy", "busy_database"), {"backup_id": "x"}]
    logs = []

    def checkpoint():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    m = Maintenance(lambda *a: None, checkpoint=checkpoint, clock=clock, log=logs.append)
    m.tick(True)
    nightly = maintenance.snapshot()["nightly"]
    assert nightly["status"] == "retrying" and nightly["error"] == "busy_database"
    assert any("database" in line for line in logs)
    clock.t += Maintenance.RETRY_DEFERRED_AFTER
    m.tick(True)
    assert maintenance.snapshot()["nightly"]["status"] == "ok" and outcomes == []


def test_nightly_busy_database_gives_up_for_the_day_after_repeated_retries():
    clock = Clock(time.mktime((2026, 10, 10, 3, 30, 0, 0, 0, -1)))
    runs = []

    def checkpoint():
        runs.append(1)
        raise backup.BackupAborted("busy", "busy_database")
    m = Maintenance(lambda *a: None, checkpoint=checkpoint, clock=clock)
    for _ in range(Maintenance.BUSY_RETRIES + 3):
        m.tick(True)
        clock.t += Maintenance.RETRY_DEFERRED_AFTER
    assert len(runs) == Maintenance.BUSY_RETRIES + 1
    assert maintenance.snapshot()["nightly"]["status"] == "error"


# --- API --------------------------------------------------------------------------------

def _routes(retired=False, playing=False):
    from kodi_manager import api_addons
    calls = []

    def jsonrpc(method, params=None):
        calls.append(method)
        return {"result": [{"playerid": 1}] if playing else []}
    handler = api_addons.AddonRoutes.__new__(api_addons.AddonRoutes)
    handler.state = SimpleNamespace(retired=retired, kodi=SimpleNamespace(jsonrpc=jsonrpc))
    return handler, calls


def test_backup_should_stop_checks_retirement_before_asking_kodi():
    handler, calls = _routes(retired=True, playing=True)
    stop = handler._backup_should_stop(playback=True)
    assert stop() == "stopping" and calls == []
    handler, calls = _routes(playing=True)
    stop = handler._backup_should_stop(playback=True)
    assert stop() == "playback" and calls == ["Player.GetActivePlayers"]
    handler, calls = _routes(playing=True)
    assert handler._backup_should_stop()() is False and calls == []


def test_retired_service_stops_a_copy_in_progress(storage):
    root, live, info = storage
    for i in range(5):
        (live / ("f%d.json" % i)).write_text("{}")
    handler, calls = _routes()
    stop = handler._backup_should_stop(playback=True)
    copied = []
    real = backup._copy_file

    def copy(src, dst, should_stop=None):
        copied.append(src)
        if len(copied) == 2:
            handler.state.retired = True
        return real(src, dst, should_stop=should_stop)

    with patch.object(backup, "_copy_file", copy), pytest.raises(backup.BackupAborted) as caught:
        backup.create_stack_backup([info], should_stop=stop)
    assert caught.value.reason == "stopping" and len(copied) == 2
    error = handler._backup_aborted(caught.value, stop, "checkpoint")
    assert (error.status, error.code) == (409, "server_retired")
    assert list((root / "_stack").iterdir()) == []


@pytest.mark.parametrize("reason,code", [("busy_database", "stale_revision"), ("playback", "playback_active"),
                                         ("stopping", "server_retired"), ("low_storage", "stale_revision")])
def test_backup_abort_reasons_map_to_api_errors(reason, code):
    from kodi_manager import api_addons, operation_records
    error = api_addons.AddonRoutes._backup_aborted(backup.BackupAborted("x", reason), None, "backup")
    assert error.status == 409 and error.code == code and code in operation_records.REASONS
    if reason == "busy_database":
        assert code in operation_records.REFUSALS and "Try again" in str(error)
    if reason == "low_storage":
        assert code in operation_records.REFUSALS and "nothing changed" in str(error)


# --- Low storage --------------------------------------------------------------------------

def _low_storage():
    return backup.BackupAborted("Not enough free storage for a backup (150 MB free, 400 MB needed); free some "
                                "space or delete old backups", "low_storage", deferred=False)


def test_nightly_low_storage_prunes_older_nightly_checkpoints_first():
    backups = [{"backup_id": "202610%02d-030000-x" % d, "timestamp": "202610%02d" % d, "note": "nightly"} for d in range(1, 8)]
    backups.append({"backup_id": "manual", "timestamp": "20260101", "note": ""})
    outcomes = [_low_storage(), {"backup_id": "new"}]
    deleted = []

    def make():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        backups.append({"backup_id": "20261008-030000-new", "timestamp": "20261008", "note": "nightly"})
        return outcome

    def delete(backup_id):
        deleted.append(backup_id)
        backups[:] = [b for b in backups if b["backup_id"] != backup_id]
    assert maintenance.nightly_checkpoint(make, lambda: list(backups), delete)["backup_id"] == "new"
    assert deleted == ["20261001-030000-x"]  # down to 6 before, so 7 after tonight's
    assert len([b for b in backups if b["note"] == "nightly"]) == 7 and outcomes == []


def test_nightly_low_storage_with_nothing_to_prune_is_skipped_for_the_night():
    clock = Clock(time.mktime((2026, 10, 11, 3, 30, 0, 0, 0, -1)))
    runs, logs = [], []

    def checkpoint():
        runs.append(1)
        return maintenance.nightly_checkpoint(lambda: (_ for _ in ()).throw(_low_storage()), lambda: [],
                                              lambda backup_id: None)
    m = Maintenance(lambda *a: None, checkpoint=checkpoint, clock=clock, log=logs.append)
    m.tick(True)
    nightly = maintenance.snapshot()["nightly"]
    assert nightly["status"] == "error" and nightly["error"] == "low_storage"
    assert "Not enough free storage" in nightly["detail"]
    assert any("low storage" in line for line in logs)
    for _ in range(10):  # no retry storm: not again that night
        clock.t += Maintenance.RETRY_DEFERRED_AFTER
        m.tick(True)
    assert runs == [1]
    clock.t += 24 * 3600
    m.tick(True)
    assert runs == [1, 1]
    from kodi_manager import dashboard_data
    with patch.object(dashboard_data, "make_baseline", side_effect=RuntimeError("no baseline")):
        checks = dashboard_data.maintenance_checks(SimpleNamespace())
    check = next(c for c in checks if c["id"] == "nightly")
    assert check["status"] == "warning" and "low storage" in check["detail"] and "400 MB needed" in check["detail"]
