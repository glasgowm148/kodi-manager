"""rows.json and baseline.json are changed by read-modify-write: a file that cannot be read
must refuse the change rather than be replaced by a list built from nothing, and changes
from other Kodi interpreters (the context-menu script, the service) must not be lost."""
import builtins
import errno
import http.client
import json
import multiprocessing
import os
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import baseline, dashboard_data, fsutil, server, widget_rows
from kodi_manager.write_policy import RequestRefused

SOURCE = "plugin://plugin.video.themoviedb.helper/?info=trending_week&tmdb_type=movie&n=%d"


class Kodi:
    def __init__(self):
        self.values = {}

    def get_addon_setting(self, addon, sid):
        return self.values.get((addon, sid), "live")

    def set_addon_setting(self, addon, sid, value):
        self.values[(addon, sid)] = value

    def jsonrpc(self, method, params=None):
        return {"result": {"value": "live"}}


def _fail_first_read(monkeypatch, path):
    """The first open() of ``path`` for reading fails like a transient EMFILE."""
    real_open, left = builtins.open, [1]

    def fake(file, mode="r", *args, **kwargs):
        if left[0] and str(file) == str(path) and "r" in mode and "+" not in mode:
            left[0] -= 1
            raise OSError(errno.EMFILE, "Too many open files")
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", fake)


def _rows(tmp_path):
    store = widget_rows.RowStore(str(tmp_path))
    store.add("Row A", SOURCE % 1)
    store.add("Row B", SOURCE % 2)
    return store, (tmp_path / "rows.json").read_text()


def test_row_changes_refuse_an_unreadable_rows_file(tmp_path, monkeypatch):
    store, before = _rows(tmp_path)
    row_id = store.load()[0]["id"]
    for change in (lambda: store.add("Row C", SOURCE % 3), lambda: store.remove(row_id)):
        _fail_first_read(monkeypatch, tmp_path / "rows.json")
        with pytest.raises(RequestRefused) as caught:
            change()
        assert caught.value.status == 409 and caught.value.code == "stale_revision"
        monkeypatch.setattr(builtins, "open", open)
        assert (tmp_path / "rows.json").read_text() == before


def test_row_changes_refuse_a_damaged_rows_file_but_listing_stays_lenient(tmp_path):
    store, _ = _rows(tmp_path)
    (tmp_path / "rows.json").write_text("[{\"id\": ")
    with pytest.raises(RequestRefused):
        store.add("Row C", SOURCE % 3)
    assert (tmp_path / "rows.json").read_text() == "[{\"id\": "
    assert store.load() == [] and store.listing() == []


def test_a_missing_rows_file_starts_empty(tmp_path):
    store = widget_rows.RowStore(str(tmp_path / "new"))
    assert store.add("Row A", SOURCE % 1)["label"] == "Row A"
    assert [r["label"] for r in store.load()] == ["Row A"]


def _baseline(tmp_path):
    path = tmp_path / "baseline.json"
    store = baseline.Baseline(str(path), Kodi())
    store.capture([{"kind": "addon_setting", "addon": "plugin.video.pov", "id": "a", "value": "1"},
                   {"kind": "addon_setting", "addon": "plugin.video.pov", "id": "b", "value": "2"}])
    return store, path, path.read_text()


def test_baseline_changes_refuse_an_unreadable_file(tmp_path, monkeypatch):
    store, path, before = _baseline(tmp_path)
    for change in (lambda: store.capture([{"kind": "addon_setting", "addon": "plugin.video.pov", "id": "c"}]),
                   lambda: store.remove(["setting:plugin.video.pov:a"]),
                   lambda: store.apply()):
        _fail_first_read(monkeypatch, path)
        with pytest.raises(RequestRefused):
            change()
        monkeypatch.setattr(builtins, "open", open)
        assert path.read_text() == before


def test_baseline_changes_refuse_a_hand_edit_typo_but_checks_stay_lenient(tmp_path):
    store, path, before = _baseline(tmp_path)
    damaged = before.replace('"version": 1,', '"version": 1,,', 1)
    path.write_text(damaged)
    with pytest.raises(RequestRefused):
        store.capture([{"kind": "addon_setting", "addon": "plugin.video.pov", "id": "c"}])
    with pytest.raises(RequestRefused):
        store.remove(["setting:plugin.video.pov:a"])
    assert path.read_text() == damaged
    assert store.check() == [] and store.items() == []


def test_baseline_capture_into_a_missing_file_starts_empty(tmp_path):
    store = baseline.Baseline(str(tmp_path / "baseline.json"), Kodi())
    assert store.capture([{"kind": "addon_setting", "addon": "plugin.video.pov", "id": "a"}])["count"] == 1


def test_baseline_remove_route_refuses_a_damaged_file_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "baseline.json"
    path.write_text('{"version": 1,, "items": []}')
    monkeypatch.setattr(dashboard_data, "translate", lambda p: str(path))
    state = SimpleNamespace(kodi=Kodi(), logs=[], log=lambda msg: None,
                            index=SimpleNamespace(refresh=lambda **k: None, get={}.get, addons={}),
                            config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": True})
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("POST", "/api/baseline/remove", json.dumps({"keys": ["kodi:videoplayer.seekdelay"]}),
                     {"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
    assert response.status == 409 and body["code"] == "stale_revision"
    assert body["operation"]["outcome"] == "refused"
    assert path.read_text() == '{"version": 1,, "items": []}'


# --- interprocess lock --------------------------------------------------------------------

def test_interprocess_lock_excludes_another_open_file_description_in_this_process(tmp_path):
    """Kodi add-ons are sub-interpreters of one process: the lock must be flock (per open
    file description), which excludes a second descriptor even in the same process."""
    fcntl = pytest.importorskip("fcntl")
    path = str(tmp_path / "rows.json")
    with fsutil.interprocess_lock(path):
        with fsutil.interprocess_lock(path):   # re-entrant in one thread
            fd = os.open(path + ".lock", os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
    fd = os.open(path + ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released on exit
    finally:
        os.close(fd)


def test_interprocess_lock_is_a_no_op_without_fcntl(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def no_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_fcntl)
    with fsutil.interprocess_lock(str(tmp_path / "rows.json")):
        pass
    assert not (tmp_path / "rows.json.lock").exists()


def _add_rows(root, tag, offset, count, start):
    store = widget_rows.RowStore(root)   # a forked copy: its own path_lock, like another interpreter
    start.wait()
    for i in range(count):
        store.add("%s %d" % (tag, i), SOURCE % (offset + i))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_concurrent_row_adds_from_two_processes_keep_every_row(tmp_path):
    pytest.importorskip("fcntl")
    context = multiprocessing.get_context("fork")
    start = context.Event()
    workers = [context.Process(target=_add_rows, args=(str(tmp_path), tag, offset, 15, start))
               for tag, offset in (("ctx", 1000), ("dash", 2000))]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(60)
        assert worker.exitcode == 0
    labels = {row["label"] for row in widget_rows.RowStore(str(tmp_path)).load()}
    assert labels == {"%s %d" % (tag, i) for tag in ("ctx", "dash") for i in range(15)}
