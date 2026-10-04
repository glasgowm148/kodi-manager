from pathlib import Path
from types import SimpleNamespace

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
