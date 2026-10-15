import json
import os
from pathlib import Path
from types import SimpleNamespace
import shutil

import pytest

from kodi_manager import backup
from kodi_manager.pipeline import pipeline_backup


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    monkeypatch.setattr(backup.time, "strftime", lambda *_: "20260101-120000")
    info = {"addon_id": "plugin.video.pov", "addon_data_path": str(live)}
    return root, live / "settings.xml", info


def test_same_second_snapshots_and_restore_keep_original_and_undo(storage):
    root, settings, info = storage
    settings.write_bytes(b"original")
    first = backup.create_backup(info)
    settings.write_bytes(b"second")
    second = backup.create_backup(info)
    assert first["backup_id"] != second["backup_id"]
    settings.write_bytes(b"before restore")
    result = backup.restore_backup(info, first["backup_id"])
    assert settings.read_bytes() == b"original"
    assert result["undo_backup_id"] not in (first["backup_id"], second["backup_id"])
    snapshots = root / info["addon_id"]
    assert (snapshots / first["backup_id"] / "addon_data/settings.xml").read_bytes() == b"original"
    assert (snapshots / second["backup_id"] / "addon_data/settings.xml").read_bytes() == b"second"
    backup.restore_backup(info, result["undo_backup_id"])
    assert settings.read_bytes() == b"before restore"


@pytest.mark.parametrize("operation", ["backup", "files", "stack", "pipeline", "restore", "stack_restore"])
def test_profile_switch_keeps_pruning_and_rollback_in_original_root(storage, tmp_path, monkeypatch, operation):
    import json
    root, settings, info = storage
    other = tmp_path / "other-profile-backups"
    preserved = []
    scope = {"files": "selected", "stack": "_stack", "pipeline": "pipeline"}.get(operation, info["addon_id"])
    index = SimpleNamespace(get=lambda aid: info if aid == info["addon_id"] else None)
    for name in ("20250101-120000-a", "20250102-120000-b"):
        folder = other / scope / name
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"backup_id": name}))
        preserved.append(folder)
    settings.write_bytes(b"snapshot")
    snapshot = backup.create_stack_backup([info]) if operation == "stack_restore" else backup.create_backup(info)
    settings.write_bytes(b"current")
    current = {"root": str(root), "switched": False}
    monkeypatch.setattr(backup, "backup_root", lambda: current["root"])
    monkeypatch.setattr(backup, "_retention", 1)
    original = backup._copy_file

    def switching(src, dst):
        original(src, dst)
        if not current["switched"] and (operation not in ("restore", "stack_restore") or dst == str(settings)):
            current.update(root=str(other), switched=True)
            if operation in ("restore", "stack_restore"):
                raise OSError("synthetic profile-switch failure")

    monkeypatch.setattr(backup, "_copy_file", switching)
    if operation in ("restore", "stack_restore"):
        with pytest.raises(OSError, match="profile-switch failure"):
            if operation == "restore":
                backup.restore_backup(info, snapshot["backup_id"])
            else:
                backup.restore_stack_backup(index, snapshot["backup_id"])
    else:
        {"backup": lambda: backup.create_backup(info),
         "files": lambda: backup.create_file_backup("selected", {"settings.xml": str(settings)}),
         "stack": lambda: backup.create_stack_backup([info]),
         "pipeline": lambda: pipeline_backup(index)}[operation]()
    assert current["switched"] and settings.read_bytes() == b"current"
    assert all(folder.exists() for folder in preserved)
    assert Path(backup._backup_path(scope)).parent == other  # A later request uses its own profile.


def test_stack_and_pipeline_snapshots_are_distinct_and_recoverable(storage):
    root, settings, info = storage
    index = SimpleNamespace(get=lambda aid: info if aid == info["addon_id"] else None)
    settings.write_bytes(b"original")
    stack = backup.create_stack_backup([info])
    pipeline = pipeline_backup(index)
    settings.write_bytes(b"changed")
    newer_stack = backup.create_stack_backup([info])
    newer_pipeline = pipeline_backup(index)
    assert stack["backup_id"] != newer_stack["backup_id"]
    assert pipeline["backup_id"] != newer_pipeline["backup_id"]
    assert (root / "pipeline" / pipeline["backup_id"] / info["addon_id"] / "settings.xml").read_bytes() == b"original"
    result = backup.restore_stack_backup(index, stack["backup_id"])
    assert settings.read_bytes() == b"original"
    backup.restore_backup(info, result["undo_backups"][info["addon_id"]])
    assert settings.read_bytes() == b"changed"


def test_existing_snapshot_directory_cannot_be_reused(storage, monkeypatch):
    root, settings, info = storage
    monkeypatch.setattr(backup.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    settings.write_bytes(b"original")
    first = backup.create_backup(info)
    settings.write_bytes(b"changed")
    with pytest.raises(FileExistsError):
        backup.create_backup(info)
    original = Path(root, info["addon_id"], first["backup_id"], "addon_data/settings.xml")
    assert original.read_bytes() == b"original"


@pytest.mark.parametrize("kind", ["addon", "stack", "files", "pipeline"])
def test_failed_backup_preserves_last_complete_snapshot(storage, monkeypatch, kind):
    root, settings, info = storage
    monkeypatch.setattr(backup, "_retention", 1)
    index = SimpleNamespace(get=lambda aid: info if aid == info["addon_id"] else None)
    create = {
        "addon": lambda: backup.create_backup(info),
        "stack": lambda: backup.create_stack_backup([info]),
        "files": lambda: backup.create_file_backup("selected", {"settings.xml": str(settings)}),
        "pipeline": lambda: pipeline_backup(index),
    }[kind]
    settings.write_bytes(b"original")
    first = create()
    scope = {"addon": info["addon_id"], "stack": "_stack", "files": "selected", "pipeline": "pipeline"}[kind]
    snapshot = root / scope / first["backup_id"]
    original_copy = next(snapshot.rglob("settings.xml"))
    real_copy = backup.shutil.copy2
    monkeypatch.setattr(backup.shutil, "copy2", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        create()
    assert original_copy.read_bytes() == b"original"
    monkeypatch.setattr(backup.shutil, "copy2", real_copy)
    # Incomplete attempts must not consume the retention allowance.
    monkeypatch.setattr(backup, "_retention", 2)
    create()
    assert original_copy.read_bytes() == b"original"
    assert len(backup.list_backups(scope)) == 2


@pytest.mark.parametrize("kind", ["addon", "stack", "files", "pipeline"])
def test_failed_backup_leaves_no_partial_snapshot_folder(storage, monkeypatch, kind):
    root, settings, info = storage
    index = SimpleNamespace(get=lambda aid: info if aid == info["addon_id"] else None)
    create = {
        "addon": lambda: backup.create_backup(info),
        "stack": lambda: backup.create_stack_backup([info]),
        "files": lambda: backup.create_file_backup("selected", {"settings.xml": str(settings)}),
        "pipeline": lambda: pipeline_backup(index),
    }[kind]
    scope = {"addon": info["addon_id"], "stack": "_stack", "files": "selected", "pipeline": "pipeline"}[kind]
    settings.write_bytes(b"original")
    first = create()
    monkeypatch.setattr(backup.shutil, "copy2", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        create()
    # The unfinished folder has no manifest: it would never be listed, restored or pruned.
    assert sorted(p.name for p in (root / scope).iterdir()) == [first["backup_id"]]


def _fail_on(monkeypatch, live, name):
    """Make copying ``name`` into the live folder fail once (disk full part way through a restore)."""
    real = backup._copy_file
    state = {"failed": False}

    def copy(src, dst):
        if not state["failed"] and Path(dst).parent == live and Path(dst).name == name:
            state["failed"] = True
            raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(backup, "_copy_file", copy)



def _fail_on_second_live_copy(monkeypatch, live):
    """Fail the second file copied into the live folder, whatever its name (os.walk order varies),
    and record the live files as they were at that moment."""
    real = backup._copy_file
    state = {"copies": 0, "at_failure": None}

    def copy(src, dst):
        if Path(dst).parent == live:
            state["copies"] += 1
            if state["copies"] == 2:
                state["at_failure"] = {p.name: p.read_bytes() for p in live.iterdir() if not p.name.startswith(".")}
                raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(backup, "_copy_file", copy)
    return state

def test_restore_failing_part_way_puts_the_live_folder_back(storage, monkeypatch):
    root, settings, info = storage
    live = settings.parent
    (live / "a.xml").write_bytes(b"old a")
    (live / "b.xml").write_bytes(b"old b")
    snap = backup.create_backup(info)
    (live / "a.xml").write_bytes(b"new a")
    (live / "b.xml").write_bytes(b"new b")
    (live / "c.xml").write_bytes(b"new c")
    seen = _fail_on_second_live_copy(monkeypatch, live)
    with pytest.raises(OSError, match="disk full"):
        backup.restore_backup(info, snap["backup_id"])
    # The first file really was replaced before the failure, so the rollback had work to do.
    assert seen["at_failure"] != {"a.xml": b"new a", "b.xml": b"new b", "c.xml": b"new c"}
    assert {p.name: p.read_bytes() for p in live.iterdir()} == {
        "a.xml": b"new a", "b.xml": b"new b", "c.xml": b"new c"}


def test_stack_restore_rolls_back_when_a_later_undo_snapshot_fails(tmp_path, storage, monkeypatch):
    root, settings, info = storage
    other_live = tmp_path / "other"
    other_live.mkdir()
    other = {"addon_id": "plugin.video.fenlight", "addon_data_path": str(other_live)}
    settings.write_bytes(b"pov old")
    (other_live / "settings.xml").write_bytes(b"fen old")
    snap = backup.create_stack_backup([info, other])
    settings.write_bytes(b"pov new")
    (other_live / "settings.xml").write_bytes(b"fen new")
    index = SimpleNamespace(get={info["addon_id"]: info, other["addon_id"]: other}.get)
    real = backup.create_backup

    def undo_snapshot(addon, *args, **kwargs):
        if addon["addon_id"] == info["addon_id"]:  # POV restores second; its undo cannot be taken
            raise OSError("disk full")
        return real(addon, *args, **kwargs)
    monkeypatch.setattr(backup, "create_backup", undo_snapshot)
    with pytest.raises(OSError, match="disk full"):
        backup.restore_stack_backup(index, snap["backup_id"])
    assert (other_live / "settings.xml").read_bytes() == b"fen new"
    assert settings.read_bytes() == b"pov new"


def test_stack_restore_failing_part_way_rolls_back_earlier_components(tmp_path, storage, monkeypatch):
    root, settings, info = storage
    other_live = tmp_path / "other"
    other_live.mkdir()
    other = {"addon_id": "plugin.video.fenlight", "addon_data_path": str(other_live)}
    settings.write_bytes(b"pov old")
    (other_live / "settings.xml").write_bytes(b"fen old")
    snap = backup.create_stack_backup([info, other])
    settings.write_bytes(b"pov new")
    (other_live / "settings.xml").write_bytes(b"fen new")
    index = SimpleNamespace(get={info["addon_id"]: info, other["addon_id"]: other}.get)
    # Components restore in name order: Fen Light first, then POV fails.
    _fail_on(monkeypatch, settings.parent, "settings.xml")
    with pytest.raises(OSError, match="disk full"):
        backup.restore_stack_backup(index, snap["backup_id"])
    assert (other_live / "settings.xml").read_bytes() == b"fen new"
    assert settings.read_bytes() == b"pov new"


def test_stack_backup_stops_on_request_and_discards_the_partial_snapshot(storage):
    root, settings, info = storage
    settings.write_bytes(b"original")
    with pytest.raises(backup.BackupAborted):
        backup.create_stack_backup([info], should_stop=lambda: True)
    assert not list((root / "_stack").iterdir())
    assert backup.create_stack_backup([info], should_stop=lambda: False)["file_counts"] == {info["addon_id"]: 1}


@pytest.mark.parametrize("stack", [False, True])
def test_restoring_kodi_managers_own_folder_keeps_its_live_access_settings(storage, tmp_path, stack):
    root, _settings, _info = storage
    live = tmp_path / "self"
    live.mkdir()
    me = {"addon_id": backup.SELF_ID, "addon_data_path": str(live)}
    (live / "settings.xml").write_bytes(b'<setting id="auth_token">leaked</setting><setting id="allow_lan">true</setting>')
    (live / "baseline.json").write_bytes(b"old")
    snap = backup.create_stack_backup([me]) if stack else backup.create_backup(me)
    (live / "settings.xml").write_bytes(b'<setting id="auth_token">replaced</setting><setting id="allow_lan">false</setting>')
    (live / "baseline.json").write_bytes(b"new")
    if stack:
        backup.restore_stack_backup(SimpleNamespace(get={backup.SELF_ID: me}.get), snap["backup_id"])
    else:
        backup.restore_backup(me, snap["backup_id"])
    assert (live / "baseline.json").read_bytes() == b"old"
    assert b"replaced" in (live / "settings.xml").read_bytes()


def test_stack_missing_component_cannot_partially_restore_others(storage, tmp_path):
    root, settings, info = storage
    other_live = tmp_path / "other"
    other_live.mkdir()
    other = {"addon_id": "plugin.video.fenlight", "addon_data_path": str(other_live)}
    other_settings = other_live / "settings.xml"
    settings.write_text("original POV")
    other_settings.write_text("original Fen")
    snapshot = backup.create_stack_backup([info, other])
    settings.write_text("current POV")
    other_settings.write_text("current Fen")
    shutil.rmtree(root / "_stack" / snapshot["backup_id"] / info["addon_id"])
    index = SimpleNamespace(get={info["addon_id"]: info, other["addon_id"]: other}.get)
    with pytest.raises(ValueError, match="incomplete"):
        backup.restore_stack_backup(index, snapshot["backup_id"])
    assert settings.read_text() == "current POV"
    assert other_settings.read_text() == "current Fen"
    assert backup.list_backups(other["addon_id"]) == []


@pytest.mark.parametrize("stack", [False, True])
@pytest.mark.parametrize("metadata", ["{", "[]"])
def test_corrupt_restore_manifest_is_not_treated_as_legacy(storage, stack, metadata):
    root, settings, info = storage
    settings.write_text("original")
    snapshot = backup.create_stack_backup([info]) if stack else backup.create_backup(info)
    scope = "_stack" if stack else info["addon_id"]
    (root / scope / snapshot["backup_id"] / "manifest.json").write_text(metadata)
    settings.write_text("current")
    with pytest.raises(ValueError, match="metadata"):
        if stack:
            backup.restore_stack_backup(SimpleNamespace(get={info["addon_id"]: info}.get), snapshot["backup_id"])
        else:
            backup.restore_backup(info, snapshot["backup_id"])
    assert settings.read_text() == "current"


def test_stack_does_not_restore_folders_absent_from_manifest(storage, tmp_path):
    root, settings, info = storage
    settings.write_text("original")
    snapshot = backup.create_stack_backup([info])
    extra_live = tmp_path / "extra"
    extra_live.mkdir()
    extra = {"addon_id": "plugin.video.extra", "addon_data_path": str(extra_live)}
    (extra_live / "settings.xml").write_text("current extra")
    unexpected = root / "_stack" / snapshot["backup_id"] / extra["addon_id"]
    unexpected.mkdir()
    (unexpected / "settings.xml").write_text("unexpected old extra")
    settings.write_text("current")
    index = SimpleNamespace(get={info["addon_id"]: info, extra["addon_id"]: extra}.get)
    result = backup.restore_stack_backup(index, snapshot["backup_id"])
    assert result["restored"] == [info["addon_id"]]
    assert (extra_live / "settings.xml").read_text() == "current extra"


def _self_folder(tmp_path):
    live = tmp_path / "self"
    for rel, data in {"settings.xml": "live settings", "baseline.json": "old baseline",
                      "widget_cache/rows.json": "old rows", "widget_cache/entries/a.json": "old cache",
                      "fix_backups/fix1/settings.xml": "old fix", "operations/history.sqlite3": "old history",
                      "log-history.db": "old log", "metrics_history.json": "old metrics",
                      "installer_seed.json": "old seed", "installer_result.json": "old token"}.items():
        (live / rel).parent.mkdir(parents=True, exist_ok=True)
        (live / rel).write_text(data)
    return live, {"addon_id": backup.SELF_ID, "addon_data_path": str(live)}


@pytest.mark.parametrize("kind", ["addon", "stack"])
def test_restoring_own_snapshot_keeps_internal_stores(storage, tmp_path, kind):
    live, me = _self_folder(tmp_path)
    snap = backup.create_backup(me) if kind == "addon" else backup.create_stack_backup([me])
    folder = Path(storage[0], backup.SELF_ID if kind == "addon" else "_stack", snap["backup_id"],
                  "addon_data" if kind == "addon" else backup.SELF_ID)
    # Only user configuration is in Kodi Manager's own snapshot.
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
        "baseline.json", "settings.xml", "widget_cache/rows.json"]
    newer = {"fix_backups/fix2/settings.xml": "new fix", "operations/history.sqlite3": "new history",
             "log-history.db": "new log", "log-history.db-journal": "new journal",
             "widget_cache/entries/b.json": "new cache", "metrics_history.json": "new metrics",
             "installer_seed.applied": "digest", "installer_result.json": "new token",
             "baseline.json": "new baseline", "widget_cache/rows.json": "new rows", "extra.json": "new"}
    for rel, data in newer.items():
        (live / rel).parent.mkdir(parents=True, exist_ok=True)
        (live / rel).write_text(data)
    if kind == "addon":
        backup.restore_backup(me, snap["backup_id"])
    else:
        backup.restore_stack_backup(SimpleNamespace(get={backup.SELF_ID: me}.get), snap["backup_id"])
    for rel in ("fix_backups/fix1/settings.xml", "fix_backups/fix2/settings.xml", "operations/history.sqlite3",
                "log-history.db", "log-history.db-journal", "widget_cache/entries/a.json",
                "widget_cache/entries/b.json", "metrics_history.json", "installer_seed.applied",
                "installer_result.json"):
        assert (live / rel).exists(), rel
    assert (live / "operations/history.sqlite3").read_text() == "new history"
    assert (live / "installer_result.json").read_text() == "new token"
    # User configuration comes back from the snapshot; files it lacks are removed.
    assert (live / "baseline.json").read_text() == "old baseline"
    assert (live / "widget_cache/rows.json").read_text() == "old rows"
    assert not (live / "extra.json").exists()


def test_restoring_an_older_own_snapshot_that_holds_internal_stores_still_works(storage, tmp_path):
    live, me = _self_folder(tmp_path)
    snap = backup.create_backup(me)
    folder = Path(storage[0], backup.SELF_ID, snap["backup_id"], "addon_data")
    # Snapshots taken before internal stores were left out still hold them.
    (folder / "operations").mkdir()
    (folder / "operations/history.sqlite3").write_text("ancient history")
    manifest = json.loads((Path(folder).parent / "manifest.json").read_text())
    manifest["files_copied"] += 1
    (Path(folder).parent / "manifest.json").write_text(json.dumps(manifest))
    (live / "operations/history.sqlite3").write_text("new history")
    backup.restore_backup(me, snap["backup_id"])
    assert (live / "operations/history.sqlite3").read_text() == "new history"
    assert (live / "baseline.json").read_text() == "old baseline"


def test_backup_skips_transient_and_vanished_files(storage, monkeypatch):
    root, settings, info = storage
    live = settings.parent
    settings.write_text("settings")
    for name in ("cache.db-journal", "cache.db-shm", ".settings.xml.ab1_x9zq.tmp",
                 ".settings.xml.ab1_x9zq.km-tmp", "job.%s.tmp" % ("0" * 32), "gone.json"):
        (live / name).write_text("x")
    real_copy = backup._copy_file

    def racing_copy(src, dst, *args, **kwargs):
        if src.endswith("gone.json"):
            os.remove(src)  # Deleted by its add-on after the folder was listed.
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup, "_copy_file", racing_copy)
    snap = backup.create_backup(info)
    folder = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    # A hot rollback journal is needed to recover a half-written cache.db: kept.
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db-journal", "settings.xml"]
    assert snap["files_copied"] == 2
    (live / "cache.db-wal").write_text("committed pages")  # may hold data not yet in cache.db: kept
    snap = backup.create_backup(info)
    folder = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db-journal", "cache.db-wal", "settings.xml"]
    assert snap["files_copied"] == 3
    stack = backup.create_stack_backup([info])
    assert stack["file_counts"] == {info["addon_id"]: 3}
    settings.write_text("changed")
    backup.restore_backup(info, snap["backup_id"])
    assert settings.read_text() == "settings"


def _torn_sqlite_db(live):
    import sqlite3
    db = str(live / "cache.db")
    conn = sqlite3.connect(db)
    conn.execute("pragma journal_mode=delete")
    conn.execute("create table t(id integer primary key, v text)")
    conn.executemany("insert into t(v) values (?)", [("a" * 500,) for _ in range(2000)])
    conn.commit()
    conn.close()
    # A writer mid-transaction whose cache spilled: cache.db already holds
    # uncommitted pages and cache.db-journal is hot.
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute("pragma cache_size=1")
    writer.execute("begin")
    writer.execute("update t set v=?", ("b" * 500,))
    writer.execute("delete from t where id>1000")
    return writer


def test_snapshot_of_a_database_mid_write_keeps_its_hot_journal(storage):
    import sqlite3
    root, settings, info = storage
    writer = _torn_sqlite_db(settings.parent)
    try:
        assert (settings.parent / "cache.db-journal").exists()
        snap = backup.create_backup(info)
    finally:
        writer.execute("rollback")
        writer.close()
    folder = root / info["addon_id"] / snap["backup_id"] / "addon_data"
    assert sorted(p.name for p in folder.iterdir()) == ["cache.db", "cache.db-journal"]
    conn = sqlite3.connect(str(folder / "cache.db"))
    try:
        assert conn.execute("pragma integrity_check").fetchall() == [("ok",)]
        assert conn.execute("select count(*), sum(v like 'b%') from t").fetchone() == (2000, 0)
    finally:
        conn.close()


@pytest.mark.parametrize("side", ["cache.db-wal", "cache.db-journal"])
def test_snapshot_is_aborted_when_a_sqlite_side_file_vanishes(storage, monkeypatch, side):
    root, settings, info = storage
    live = settings.parent
    settings.write_text("settings")
    (live / "cache.db").write_text("db")
    (live / side).write_text("pages")
    real_copy = backup._copy_file

    def racing_copy(src, dst, *args, **kwargs):
        if src.endswith(side):
            os.remove(src)  # SQLite checkpointed or rolled back after cache.db was copied.
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup, "_copy_file", racing_copy)
    with pytest.raises(backup.BackupAborted) as caught:
        backup.create_backup(info)
    assert caught.value.deferred
    assert list((root / info["addon_id"]).iterdir()) == []  # the partial snapshot is discarded


def test_restore_still_fails_when_a_snapshot_file_vanishes(storage, monkeypatch):
    root, settings, info = storage
    settings.write_text("settings")
    snap = backup.create_backup(info)
    real_copy = backup._copy_file

    snapshot_file = str(root / info["addon_id"] / snap["backup_id"] / "addon_data" / "settings.xml")

    def racing_copy(src, dst, *args, **kwargs):
        if src == snapshot_file:
            os.remove(src)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup, "_copy_file", racing_copy)
    settings.write_text("live")
    with pytest.raises(FileNotFoundError):
        backup.restore_backup(info, snap["backup_id"])
    assert settings.read_text() == "live"
