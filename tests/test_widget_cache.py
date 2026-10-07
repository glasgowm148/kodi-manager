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


# Setters InfoTagVideo has on Kodi 20+; Kodi 19's tag has none of them.
KODI20_SETTERS = ("setTitle", "setYear", "setMpaa", "setPlot", "setTagLine", "setOriginalTitle", "setIMDBNumber",
                  "setPremiered", "setFirstAired", "setTrailer", "setLastPlayed", "setDateAdded", "setPlaycount",
                  "setTvShowTitle", "setDuration", "setGenres", "setDirectors", "setWriters", "setStudios",
                  "setCountries", "setTags", "setSeason", "setEpisode", "setMediaType", "setRating",
                  "setUniqueIDs", "setResumePoint", "setCast")


class FakeTag:
    """Kodi 20+ InfoTagVideo: only the real setters exist."""

    def __init__(self):
        self.calls = {}
        for name in KODI20_SETTERS:
            setattr(self, name, (lambda n: lambda *args: self.calls.__setitem__(n, args))(name))


class Kodi19Tag:
    """Kodi 19 InfoTagVideo: getters only."""

    def getTitle(self):
        return ""


class FakeListItem:
    tag_class = FakeTag

    def __init__(self, label="", path="", offscreen=False):
        self.label, self.path, self.tag, self.art, self.props, self.context = label, path, self.tag_class(), {}, {}, []
        self.info, self.unique_ids, self.cast = {}, None, None

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


class Kodi19ListItem(FakeListItem):
    tag_class = Kodi19Tag

    def setInfo(self, kind, info):
        assert kind == "video"
        self.info.update(info)

    def setUniqueIDs(self, ids, default=""):
        self.unique_ids = (ids, default)

    def setCast(self, cast):
        self.cast = cast


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


def test_render_on_kodi19_falls_back_to_setinfo(tmp_path):
    files = wc.fetch(FakeRPC(listing("Up")), MOVIES)
    files[0].update(resume={"position": 30, "total": 120}, season=1, episode=2, showtitle="Show",
                    cast=[{"name": "A", "role": "B"}])
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=Kodi19ListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"})
    li = plugin.items[0][1]
    assert li.info["title"] == "Up" and li.info["season"] == 1 and li.info["episode"] == 2
    assert li.info["tvshowtitle"] == "Show" and li.info["mediatype"] == "movie"
    assert li.info["rating"] == 7.5
    assert li.unique_ids[1] == "tmdb"
    assert li.props["ResumeTime"] == "30" and li.props["TotalTime"] == "120"
    assert li.cast[0]["name"] == "A"


def test_render_on_kodi20_never_calls_setinfo():
    files = wc.fetch(FakeRPC(listing("Up")), MOVIES)
    plugin = FakePlugin()
    wc.render(SimpleNamespace(Actor=lambda *a: a), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"})
    li = plugin.items[0][1]
    assert not hasattr(li, "setInfo") and li.tag.calls["setMediaType"] == ("movie",)


def test_serve_miss_fetches_then_hit_skips_source(tmp_path):
    rpc = FakeRPC(listing("Up"))
    xbmc, gui, plugin, vfs = kodi_modules(tmp_path, rpc)
    argv = ["plugin://service.kodi.addonadmin/", "1", "?" + wc.cache_url(MOVIES).split("?", 1)[1]]
    wc.serve(argv, xbmc, gui, plugin, vfs)
    # Two pages read (list rows default to 2); one film plus the View more item.
    assert len(rpc.calls) == 2 and len(plugin.items) == 2
    plugin2 = FakePlugin()
    wc.serve(argv, xbmc, gui, plugin2, vfs)
    assert len(rpc.calls) == 2 and len(plugin2.items) == 2 and plugin2.ended is True


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
    assert len(rpc.calls) == 2 and bumps == [str(10 ** 6)]  # two pages
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


TMDB = "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_trending&tmdb_type=movie&widget=true"


def tmdb_item():
    return {"label": "Up", "file": "plugin://plugin.video.tmdb.bingie.helper/?info=play&tmdb_type=movie&tmdb_id=14160",
            "filetype": "file", "type": "movie", "uniqueid": {"tmdb": "14160", "imdb": "tt1049413"}}


def test_tmdb_helper_rows_are_cacheable_and_personal_ones_refresh_fast():
    assert wc.validate_source(TMDB) == TMDB
    assert wc.ttl_for(TMDB) == wc.TTL_DEFAULT
    assert wc.ttl_for("plugin://plugin.video.tmdb.bingie.helper/?info=trakt_ondeck_unwatched&tmdb_type=movie&widget=true") == wc.TTL_PROGRESS
    src = TMDB + "&reload=$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]&reload=$INFO[Window(Home).Property(x)]"
    assert wc.source_from_cache_url(wc.cache_url(src)) == TMDB


def test_tmdb_helper_properties_and_playability_are_restored():
    props, playable = wc.helper_item(tmdb_item(), TMDB)
    assert playable is True
    assert props["tmdb_id"] == "14160" and props["imdb_id"] == "tt1049413"
    assert props["item.info"] == "play" and props["item.type"] == "movie" and props["widget"] == "true"
    assert wc.helper_item(tmdb_item(), MOVIES) == ({}, False)
    folder = dict(tmdb_item(), file="plugin://plugin.video.tmdb.bingie.helper/?info=details&tmdb_type=tv&tmdb_id=1")
    assert wc.helper_item(folder, TMDB)[1] is False


def test_render_marks_only_tmdb_play_leaves_playable():
    plugin = FakePlugin()
    pov = {"label": "Coco", "file": "plugin://plugin.video.pov/?mode=playback.media&tmdb_id=2", "filetype": "file", "type": "movie"}
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": TMDB, "files": [tmdb_item()], "content": "movies"})
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": [pov], "content": "movies"})
    tmdb_li, pov_li = plugin.items[0][1], plugin.items[1][1]
    assert tmdb_li.props["IsPlayable"] == "true" and tmdb_li.props["tmdb_id"] == "14160"
    assert "IsPlayable" not in pov_li.props and "tmdb_id" not in pov_li.props


def test_external_reload_property_queues_personal_rows(tmp_path):
    cache = wc.WidgetCache(str(tmp_path))
    clock = Clock(1000)
    cache.save(CONTINUE, [], now=clock.t)
    cache.save(MOVIES, [], now=clock.t)
    token = ["a"]
    rpc = FakeRPC(listing("Up"))
    r = wc.Refresher(cache, rpc, lambda: False, lambda v: None, clock=clock, external_reload=lambda: token[0])
    r.next_sweep = 10 ** 9
    assert r.tick() == 0  # first value only primes
    token[0] = "b"
    assert r.tick() == 1 and rpc.calls[0][1]["directory"] == CONTINUE



class PagedRPC:
    """Serves page N of a source with a Next page item until the last page."""

    def __init__(self, pages, fail_on=None):
        self.pages, self.fail_on, self.calls = pages, fail_on, []

    def __call__(self, method, params=None):
        directory = params["directory"]
        self.calls.append(directory)
        page = int(parse_qs(urlsplit(directory).query).get("new_page", ["1"])[0])
        if page == self.fail_on:
            return {"error": {"code": -1}}
        files = [{"label": "Film %d-%d" % (page, i), "file": "plugin://plugin.video.pov/?mode=playback.media&tmdb_id=%d%d" % (page, i),
                  "filetype": "file", "type": "movie", "playcount": i % 2} for i in range(3)]
        if page < self.pages:
            files.append({"label": "[B]Next Page >>[/B]", "filetype": "directory",
                          "file": MOVIES + "&new_page=%d&exit_list_params=x" % (page + 1)})
        return {"result": {"files": files}}


def test_fetch_follows_next_page_up_to_the_requested_pages():
    rpc = PagedRPC(pages=5)
    files = wc.fetch(rpc, MOVIES, pages=3)
    assert [f["label"] for f in files][::3] == ["Film 1-0", "Film 2-0", "Film 3-0"] and len(files) == 9
    assert len(rpc.calls) == 3 and "new_page=3" in rpc.calls[-1]
    assert len(wc.fetch(PagedRPC(pages=1), MOVIES, pages=3)) == 3  # stops on the last page
    assert len(wc.fetch(PagedRPC(pages=5, fail_on=2), MOVIES, pages=3)) == 3  # keeps page 1


def test_fetch_ignores_next_page_items_to_other_routes():
    class Odd(PagedRPC):
        def __call__(self, method, params=None):
            reply = super().__call__(method, params)
            reply["result"]["files"][-1]["file"] = "plugin://plugin.video.pov/?mode=build_tvshow_list&action=x&new_page=2"
            return reply
    rpc = Odd(pages=3)
    assert len(wc.fetch(rpc, MOVIES, pages=3)) == 3 and len(rpc.calls) == 1


def test_list_rows_get_view_more_and_default_pages():
    assert wc.default_pages(MOVIES) == 2 and wc.default_pages(CONTINUE) == 1 and wc.default_pages(SEASONS) == 1
    assert wc.view_more_url(MOVIES) == MOVIES
    assert wc.view_more_url(CONTINUE) is None and wc.view_more_url(SEASONS) is None
    assert wc.view_more_url(TMDB) == "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_trending&tmdb_type=movie"
    assert wc.view_more_url("plugin://plugin.video.tmdb.bingie.helper/?info=trakt_ondeck_unwatched&tmdb_type=movie&widget=true") is None
    url = wc.cache_url(MOVIES, pages=9, hide_watched=True)
    q = parse_qs(urlsplit(url).query)
    assert wc.row_options(q) == (wc.MAX_PAGES, True)
    assert wc.row_options(parse_qs(urlsplit(wc.cache_url(MOVIES)).query)) == (2, False)


def test_render_hides_watched_on_request_and_appends_view_more():
    files = wc.fetch(PagedRPC(pages=1), MOVIES)
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"}, hide_watched=True, view_more=MOVIES)
    labels = [li.label for _, li, _ in plugin.items]
    assert labels == ["Film 1-0", "Film 1-2", "View more"]
    url, li, folder = plugin.items[-1]
    assert url == MOVIES and folder is True and li.props["specialsort"] == "bottom"
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"})
    assert [li.label for _, li, _ in plugin.items] == ["Film 1-0", "Film 1-1", "Film 1-2"]


def test_serve_with_more_pages_than_cached_queues_a_deeper_refresh(tmp_path):
    rpc = PagedRPC(pages=5)
    xbmc, gui, plugin, vfs = kodi_modules(tmp_path, rpc)
    cache = wc.WidgetCache(str(tmp_path))
    cache.save(MOVIES, wc.fetch(rpc, MOVIES, 2), pages=2)
    rpc.calls.clear()
    wc.serve(["x", "1", "?" + wc.cache_url(MOVIES, pages=4).split("?", 1)[1]], xbmc, gui, plugin, vfs)
    assert rpc.calls == [] and plugin.ended is True
    assert cache.take_queue() == [MOVIES] and cache.pages_for(MOVIES) == 4
    r = wc.Refresher(cache, rpc, lambda: False, lambda v: None, clock=Clock(10 ** 6))
    r.next_sweep = 10 ** 9
    cache.request(MOVIES, pages=4)
    assert r.tick() == 1 and len(rpc.calls) == 4 and cache.load(MOVIES)["pages"] == 4


def test_view_more_stays_inside_the_skin_widget_limit():
    files = wc.fetch(PagedRPC(pages=3), MOVIES, pages=3)
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": MOVIES, "files": files, "content": "movies"}, view_more=MOVIES, limit=5)
    assert [li.label for _, li, _ in plugin.items] == ["Film 1-0", "Film 1-1", "Film 1-2", "Film 2-0", "View more"]
    assert wc.skin_widget_limit(SimpleNamespace(getInfoLabel=lambda label: "21")) == 21
    assert wc.skin_widget_limit(SimpleNamespace(getInfoLabel=lambda label: "")) == 0
