"""Widget cache: stale-while-revalidate rows served without calling the source add-on."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import widget_cache as wc  # noqa: E402
import widget_plugin  # noqa: E402

MOVIES = "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_media_discover&name=Hidden+gems"
CONTINUE = "plugin://plugin.video.pov/?mode=build_continue_episode"
SEASONS = "plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=82728"


def listing(*titles, extra=None):
    files = [{"label": t, "title": t, "file": "plugin://plugin.video.pov/?mode=playback.media&tmdb_id=%d" % (i + 1),
              "filetype": "file", "type": "movie", "year": 2001, "rating": 7.5, "votes": "1,234",
              "art": {"poster": "image://https%3a%2f%2fimage.tmdb.org%2fp%2fw780%2fa.jpg/"},
              "uniqueid": {"tmdb": str(i + 1), "imdb": "tt%d" % i},
              "resume": {"position": 0, "total": 0}, "cast": [{"name": "A%d" % n, "role": "R", "order": n} for n in range(12)]}
             for i, t in enumerate(titles)]
    files.append({"label": "Next Page >>", "file": MOVIES + "&new_page=2", "filetype": "directory"})
    return {"result": {"files": files + (extra or [])}}


class FakeRPC:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, method, params=None):
        self.calls.append((method, params))
        return self.reply


@pytest.mark.parametrize("source", [MOVIES, CONTINUE, SEASONS,
                                    "plugin://plugin.video.pov/?mode=build_trakt_list&slug=little-favourites&list_type=my_lists"])
def test_directory_sources_are_accepted(source):
    assert wc.validate_source(source) == source


@pytest.mark.parametrize("source", ["plugin://plugin.video.pov/?mode=playback.media&tmdb_id=1",
                                    "plugin://plugin.video.pov/?mode=mark_as_watched_unwatched_movie",
                                    "plugin://plugin.video.pov/?mode=manager_watchlist",
                                    "plugin://script.module.x/?mode=build_list", "http://example.com/", ""])
def test_action_and_foreign_sources_are_rejected(source):
    with pytest.raises(ValueError):
        wc.validate_source(source)


def test_cache_url_round_trip_ignores_reload():
    url = wc.cache_url(MOVIES)
    assert url.endswith("&reload=$INFO[Window(Home).Property(km_widgets)]")
    assert wc.source_from_cache_url(url) == MOVIES
    assert parse_qs(urlsplit(url).query)["mode"] == ["cached"]


def test_ttls_follow_row_kind():
    assert wc.ttl_for(CONTINUE) == wc.TTL_PROGRESS
    assert wc.ttl_for("plugin://plugin.video.pov/?mode=build_movie_list&action=in_progress_movies") == wc.TTL_PROGRESS
    assert wc.ttl_for(SEASONS) == wc.TTL_STATIC
    assert wc.ttl_for(MOVIES) == wc.TTL_DEFAULT


def test_fetch_normalises_listing():
    rpc = FakeRPC(listing("Up", "Coco"))
    files = wc.fetch(rpc, MOVIES)
    assert [f["label"] for f in files] == ["Up", "Coco"]  # next-page control dropped
    assert files[0]["art"]["poster"] == "https://image.tmdb.org/p/w780/a.jpg"
    assert len(files[0]["cast"]) == wc.MAX_CAST
    assert "resume" not in files[0] or files[0]["resume"]
    method, params = rpc.calls[0]
    assert method == "Files.GetDirectory" and params["directory"] == MOVIES and "uniqueid" in params["properties"]


def test_fetch_raises_on_error_so_old_cache_survives():
    with pytest.raises(ValueError):
        wc.fetch(FakeRPC({"error": {"code": -32602}}), MOVIES)


def test_save_load_and_change_detection(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    files = wc.fetch(FakeRPC(listing("Up")), MOVIES)
    assert cache.save(MOVIES, files, now=100) is True
    assert cache.save(MOVIES, files, now=200) is False
    entry = cache.load(MOVIES)
    assert entry["fetched_at"] == 200 and entry["content"] == "movies"
    assert cache.save(MOVIES, wc.fetch(FakeRPC(listing("Up", "Coco")), MOVIES), now=300) is True
    assert cache.load(CONTINUE) is None


def test_corrupt_or_mismatched_entry_is_a_miss(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    os.makedirs(cache.entries)
    Path(cache.entry_path(MOVIES)).write_text("{bad")
    assert cache.load(MOVIES) is None
    Path(cache.entry_path(MOVIES)).write_text(json.dumps({"source": CONTINUE, "files": []}))
    assert cache.load(MOVIES) is None


def test_staleness_and_queue_priority(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(MOVIES, [], now=0)
    cache.save(CONTINUE, [], now=0)
    cache.save(SEASONS, [], now=wc.TTL_STATIC)
    assert cache.queue_stale(now=wc.TTL_DEFAULT + 1) == 2
    assert cache.take_queue() == [CONTINUE, MOVIES]
    assert cache.take_queue() == []
    cache.request(MOVIES)
    cache.request(MOVIES)
    assert cache.take_queue() == [MOVIES]


def test_prune_removes_unused_rows(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(MOVIES, [], now=0)
    os.utime(cache.entry_path(MOVIES), (0, 0))
    cache.save(CONTINUE, [], now=wc.PRUNE_AFTER)
    assert cache.prune(now=wc.PRUNE_AFTER + 10) == 1
    assert cache.load(MOVIES) is None and cache.load(CONTINUE) is not None


class FakeTag:
    def __init__(self):
        self.calls = {}

    def __getattr__(self, name):
        if not name.startswith("set"):
            raise AttributeError(name)
        return lambda *args: self.calls.__setitem__(name, args)


class FakeListItem:
    def __init__(self, label="", path="", offscreen=False):
        self.label, self.path, self.tag, self.art, self.props, self.context = label, path, FakeTag(), {}, {}, []

    def getVideoInfoTag(self):
        return self.tag

    def setArt(self, art):
        self.art = art

    def setProperties(self, props):
        self.props.update(props)

    def setProperty(self, key, value):
        self.props[key] = value

    def addContextMenuItems(self, items):
        self.context = items


class FakePlugin:
    def __init__(self):
        self.items, self.content, self.ended = [], None, None

    def setContent(self, handle, content):
        self.content = content

    def addDirectoryItems(self, handle, items, total):
        self.items.extend(items)

    def endOfDirectory(self, handle, succeeded=True, cacheToDisc=True):
        self.ended = succeeded


def kodi_modules(tmp_path, rpc):
    xbmc = SimpleNamespace(executeJSONRPC=lambda req: json.dumps(rpc(json.loads(req)["method"], json.loads(req)["params"])),
                           log=lambda *a: None, LOGWARNING=2, Actor=lambda *a: a)
    return xbmc, SimpleNamespace(ListItem=FakeListItem), FakePlugin(), SimpleNamespace(translatePath=lambda p: str(tmp_path))


def test_render_keeps_source_urls_and_metadata(tmp_path):
    files = wc.fetch(FakeRPC(listing("Up")), MOVIES)
    files[0]["resume"] = {"position": 30, "total": 120}
    plugin = FakePlugin()
    wc.render(SimpleNamespace(Actor=lambda *a: a), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"})
    url, li, folder = plugin.items[0]
    assert url == files[0]["file"] and folder is False and plugin.ended is True
    assert "IsPlayable" not in li.props  # POV plays through its own route
    assert li.props["watchedprogress"] == "25" and li.props["km_tmdb_id"] == "1"
    assert li.tag.calls["setUniqueIDs"][1] == "tmdb"
    assert li.tag.calls["setRating"][:2] == (7.5, 1234)
    assert li.tag.calls["setResumePoint"] == (30.0, 120.0)
    assert li.art["poster"].startswith("https://")


def test_serve_miss_fetches_then_hit_skips_source(tmp_path):
    rpc = FakeRPC(listing("Up"))
    xbmc, gui, plugin, vfs = kodi_modules(tmp_path, rpc)
    argv = ["plugin://service.kodi.addonadmin/", "1", "?" + wc.cache_url(MOVIES).split("?", 1)[1]]
    wc.serve(argv, xbmc, gui, plugin, vfs)
    assert len(rpc.calls) == 1 and len(plugin.items) == 1
    plugin2 = FakePlugin()
    wc.serve(argv, xbmc, gui, plugin2, vfs)
    assert len(rpc.calls) == 1 and len(plugin2.items) == 1 and plugin2.ended is True


def test_serve_stale_hit_queues_refresh(tmp_path):
    rpc = FakeRPC(listing("Up"))
    xbmc, gui, plugin, vfs = kodi_modules(tmp_path, rpc)
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(CONTINUE, [], now=0)
    wc.serve(["x", "1", "?mode=cached&source=" + CONTINUE.replace("?", "%3F").replace("=", "%3D")], xbmc, gui, plugin, vfs)
    assert rpc.calls == [] and plugin.ended is True
    assert cache.take_queue() == [CONTINUE]


def test_serve_failure_ends_directory_unsuccessfully(tmp_path):
    xbmc, gui, plugin, vfs = kodi_modules(tmp_path, FakeRPC({"error": {}}))
    wc.serve(["x", "1", "?mode=cached&source=plugin%3A%2F%2Fplugin.video.pov%2F%3Fmode%3Dplayback.media"], xbmc, gui, plugin, vfs)
    assert plugin.ended is False and plugin.items == []


def test_plugin_entry_routes_cached_mode_without_addon_index(tmp_path, monkeypatch):
    called = []
    monkeypatch.setitem(sys.modules, "xbmc", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcgui", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcplugin", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcvfs", SimpleNamespace())
    monkeypatch.setattr(wc, "serve", lambda *a: called.append(a[0]))
    widget_plugin.main(["x", "1", "?mode=cached&source=x"])
    assert called == [["x", "1", "?mode=cached&source=x"]]


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_refresher_refreshes_serially_and_bumps_on_change(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(MOVIES, [], now=0)
    rpc, bumps, clock = FakeRPC(listing("Up")), [], Clock(10 ** 6)
    r = wc.Refresher(cache, rpc, lambda: False, bumps.append, clock=clock)
    r.next_sweep = 0
    assert r.tick() == 1  # first sweep queues the stale row
    assert len(rpc.calls) == 1 and bumps == [str(10 ** 6)]
    clock.t += 1
    cache.request(MOVIES)
    assert r.tick() == 1 and len(bumps) == 1  # unchanged data: no skin reload


def test_refresher_waits_while_playing_and_after_playback_refreshes_progress(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    clock = Clock(1000)
    cache.save(CONTINUE, [], now=clock.t)
    cache.save(MOVIES, [], now=clock.t)
    playing = [True]
    rpc = FakeRPC(listing("Up"))
    r = wc.Refresher(cache, rpc, lambda: playing[0], lambda v: None, clock=clock)
    r.next_sweep = 10 ** 9
    r.playback_stopped()
    clock.t += 10
    assert r.tick() == 0 and rpc.calls == []
    playing[0] = False
    assert r.tick() == 1 and rpc.calls[0][1]["directory"] == CONTINUE
    clock.t += 200
    assert r.tick() == 2


def test_refresher_keeps_old_rows_when_source_fails(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(MOVIES, [{"label": "Up", "file": "plugin://plugin.video.pov/?x=1"}], now=0)
    r = wc.Refresher(cache, FakeRPC({"error": {}}), lambda: False, lambda v: None, clock=Clock(10 ** 6))
    r.next_sweep = 0
    r.tick()
    assert cache.load(MOVIES)["files"][0]["label"] == "Up"


def test_cache_url_drops_skin_reload_counters_and_watchlists_refresh_fast():
    src = "plugin://plugin.video.pov/?mode=build_movie_list&action=trakt_watchlist&reload=$INFO[Window(Home).Property(widgetreload)]"
    assert wc.source_from_cache_url(wc.cache_url(src)) == "plugin://plugin.video.pov/?mode=build_movie_list&action=trakt_watchlist"
    assert wc.ttl_for(src) == wc.TTL_PROGRESS
