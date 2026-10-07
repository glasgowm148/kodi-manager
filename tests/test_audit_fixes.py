"""Regression tests for the 2026-10-07 backend audit fixes."""
import json
import os
import re
import threading
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
