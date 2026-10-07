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
