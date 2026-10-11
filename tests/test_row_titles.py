"""Friendly row titles, memory pressure on Android, Kodi restarts and stale-row counts (0.7.9)."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from kodi_manager.memstat import memory_status
from kodi_manager.metrics import MetricsHistory, Sampler, build_sample, process_started_at, widget_row_counts
from kodi_manager.row_titles import (group_name, label_resolver, resolve_label, route_title, row_titles,
                                     skin_rows, skin_strings)
from kodi_manager.widget_cache import cache_url

NOW = 1_800_000_000
HISTORY = "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_history&tmdb_type=movie&widget=true"
RECS = "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_recommendations&tmdb_type=tv&widget=true"
POV = "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular&name=Popular%20films"
STRINGS = {32043: "Recently watched", 32044: "Because you watched"}


def kodi_string(number):
    return STRINGS.get(number, "")


def test_string_ids_resolve_through_kodi_addons_and_po_files():
    assert resolve_label("32043", kodi_string) == "Recently watched"
    assert resolve_label("$LOCALIZE[32043]", kodi_string) == "Recently watched"
    assert resolve_label("$ADDON[skin.bingie 32050]", kodi_string, lambda addon, n: "From %s" % addon) == "From skin.bingie"
    assert resolve_label("32099", lambda n: "", po_strings={"32099": "Top picks"}) == "Top picks"
    assert resolve_label("32099", lambda n: "") == "", "an unresolvable id is dropped, never shown"
    assert resolve_label("$INFO[Window(Home).Property(x)]", kodi_string) == ""
    assert resolve_label("[COLOR red]New[/COLOR]   films", kodi_string) == "New films"
    assert resolve_label("32043", lambda n: 1 / 0, po_strings={"32043": "From po"}) == "From po", "Kodi errors fall back"


def test_paths_become_readable_titles():
    assert route_title(HISTORY) == {"title": "Trakt history (movies)", "addon": "TMDb Helper"}
    assert route_title(RECS)["title"] == "Trakt recommendations (shows)"
    assert route_title(POV) == {"title": "Popular films", "addon": "POV"}
    assert route_title("plugin://plugin.video.example/?mode=build_tvshow_list&name=32043")["title"] == "TV show"
    assert route_title("plugin://plugin.video.fen/?mode=trakt.list.trending")["title"].startswith("Trakt")
    assert route_title(HISTORY, {"plugin.video.tmdb.bingie.helper": "[B]TMDb Bingie Helper[/B]"})["addon"] == "TMDb Bingie Helper"
    assert group_name("10000-1") == "Home"
    assert group_name("movieshub") == "Movies hub"
    assert group_name("tvshowshub") == "TV shows hub"


def write_shortcuts(root):
    root.mkdir()
    (root / "skin.bingie-10000-1.DATA.xml").write_text(
        '<shortcuts><shortcut><label>32043</label><action>ActivateWindow(Videos,"%s",return)</action></shortcut>'
        '<shortcut><label>$LOCALIZE[99999]</label><action>ActivateWindow(Videos,"%s",return)</action></shortcut></shortcuts>'
        % (cache_url(HISTORY).replace("&", "&amp;"), RECS.replace("&", "&amp;")))
    (root / "skin.bingie-movieshub.DATA.xml").write_text(
        '<shortcuts><shortcut><label>Watched films</label><action>ActivateWindow(10025,"%s",return)</action></shortcut></shortcuts>'
        % HISTORY.replace("&", "&amp;"))
    (root / "skin.other.properties").write_text(repr([
        ["mainmenu", "tvshows", "widgetPath.2", POV], ["mainmenu", "tvshows", "widgetName.2", "Films everyone is watching"],
        ["mainmenu", "tvshows", "widgetPath", "not a plugin"]]))
    (root / "skin.bingie-mainmenu.DATA.xml").write_text('<shortcuts><shortcut><label>Ignored</label><action>ActivateWindow(Videos,"%s",return)</action></shortcut></shortcuts>' % POV.replace("&", "&amp;"))
    (root / "broken.DATA.xml").write_text("<shortcuts>")


def test_skin_labels_win_and_say_where_the_row_is(tmp_path):
    root = tmp_path / "script.skinshortcuts"
    write_shortcuts(root)
    resolve = lambda label: resolve_label(label, kodi_string)  # noqa: E731
    rows = skin_rows(str(root), resolve)
    assert rows[HISTORY] == {"label": "Recently watched", "where": ["Home", "Movies hub"]}
    assert rows[RECS] == {"label": "", "where": ["Home"]}
    assert rows[POV] == {"label": "Films everyone is watching", "where": ["TV shows"]}
    titles = row_titles([HISTORY, RECS, POV, "plugin://plugin.video.x/?info=new"], str(root), resolve)
    assert titles[HISTORY] == {"title": "Recently watched", "addon": "TMDb Helper", "where": ["Home", "Movies hub"], "from": "skin"}
    assert titles[RECS]["title"] == "Trakt recommendations (shows)" and titles[RECS]["from"] == "path"
    assert titles[POV]["title"] == "Films everyone is watching"
    assert titles["plugin://plugin.video.x/?info=new"]["where"] == []
    assert row_titles([HISTORY], str(tmp_path / "missing"))[HISTORY]["from"] == "path"


def test_skin_strings_fall_back_to_the_english_po_file(tmp_path):
    folder = tmp_path / "skin.bingie" / "language" / "resource.language.en_gb"
    folder.mkdir(parents=True)
    (folder / "strings.po").write_text('msgctxt "#32043"\nmsgid "Recently watched"\nmsgstr ""\n')
    assert skin_strings(str(tmp_path / "skin.bingie")) == {"32043": "Recently watched"}
    resolve = label_resolver(SimpleNamespace(get_localized_string=lambda n: ""), str(tmp_path / "skin.bingie"))
    assert resolve("32043") == "Recently watched"
    assert skin_strings(str(tmp_path / "nothing")) == {}


def test_memory_is_tight_only_when_swap_is_full_and_little_is_free(tmp_path):
    def status(available_kb, swap_free_kb):
        m, s = tmp_path / "meminfo", tmp_path / "status"
        m.write_text("MemTotal: 2969600 kB\nMemAvailable: %d kB\nSwapTotal: 1048576 kB\nSwapFree: %d kB\n" % (available_kb, swap_free_kb))
        s.write_text("VmRSS:\t600000 kB\n")
        return memory_status(str(m), str(s))
    roomy = status(1200 * 1024, 40000)            # swap 96% used, 1.2 GB free: normal on Android
    assert roomy["status"] == "ok" and roomy["pressure"] == "ok"
    assert "normal on Android" in roomy["detail"]
    tight = status(600 * 1024, 40000)             # swap 96% used, 20% free
    assert tight["status"] == "warning" and tight["pressure"] == "tight"
    assert "Android may close Kodi when it is in the background" in tight["detail"]
    assert "Low memory" not in tight["detail"]
    assert status(600 * 1024, 900000)["status"] == "ok", "free RAM alone is fine while swap has room"
    assert status(200 * 1024, 40000)["pressure"] == "low"


def test_tight_memory_is_explained_on_the_dashboard_not_announced_on_the_tv():
    from kodi_manager.netwatch import Watchdog
    notes = []
    for pressure in ("tight", "low"):
        dog = Watchdog(lambda title, msg: notes.append(title), lambda: True, memory=lambda p=pressure: {"status": "warning", "pressure": p},
                       probe=lambda host: 0.1, clock=lambda: NOW)
        dog.next_check = 0
        dog.tick()
    assert notes == ["Kodi is low on memory"]


def test_kodi_starts_are_recorded_and_listed(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "stat").write_text("123 (kodi (main)) S " + " ".join(["0"] * 18) + " 50000 0 0\n")
    (proc / "stat").write_text("cpu 1 2 3\nbtime 1799990000\n")
    hertz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    assert process_started_at(str(proc)) == int(1799990000 + 50000 / hertz)
    assert process_started_at(str(tmp_path / "none")) is None
    h = MetricsHistory(str(tmp_path / "h.json"))
    first, second = NOW - 3 * 86400, NOW - 3600
    for i, started in enumerate([first, first, second]):
        t = NOW - 4000 + i * 1000 if i else NOW - 10 * 86400 // 3
        h.record(build_sample(t, started=started), now=t)
    data = h.series(7, now=NOW)
    assert data["kodi_starts"] == [first, second]
    assert data["series"]["kodi_started_at"][-1] == second
    assert h.series(1, now=NOW)["kodi_starts"] == [second]
    sampler = Sampler(MetricsHistory(str(tmp_path / "s.json")), lambda: {}, lambda: None, lambda: None,
                      clock=lambda: NOW, first_after=0, started=lambda: NOW - 50)
    assert sampler.tick(True) and sampler.history.load()[-1]["kp"] == NOW - 50


def test_stale_and_empty_rows_are_counted_from_the_listing_edges(tmp_path):
    from kodi_manager.widget_cache import WidgetCache
    cache = WidgetCache(str(tmp_path))
    cache.save(POV, [{"label": "A", "file": "x"}], now=NOW - 10)
    cache.save(HISTORY, [{"label": "B", "file": "y"}], now=NOW - 30 * 86400)
    cache.save(RECS, [], now=NOW - 10)
    counts = widget_row_counts(str(tmp_path), ttl=lambda source: 3600, now=NOW)
    assert counts == {"cached": 3, "failing": 0, "persistent": 0, "stale": 1, "empty": 1}
    assert widget_row_counts(str(tmp_path)) == {"cached": 3, "failing": 0, "persistent": 0}


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import server  # noqa: E402


def test_cached_row_listing_carries_friendly_titles(tmp_path, monkeypatch):
    shortcuts = tmp_path / "script.skinshortcuts"
    write_shortcuts(shortcuts)
    kodi = SimpleNamespace(get_localized_string=kodi_string, get_active_skin=lambda: {"path": str(tmp_path / "skin")})
    index = SimpleNamespace(addons={"plugin.video.pov": {"name": "POV"}})
    monkeypatch.setattr(server, "translate", lambda p: str(shortcuts) if p == server.SHORTCUTS_DATA else p)
    entries = server.with_row_titles(kodi, index, [{"source": HISTORY, "items": 3}, {"source": RECS, "items": 0}])
    assert entries[0]["title"] == "Recently watched" and entries[0]["where"] == ["Home", "Movies hub"]
    assert entries[0]["items"] == 3 and entries[0]["title_from"] == "skin"
    assert entries[1]["title"] == "Trakt recommendations (shows)" and entries[1]["addon_name"] == "TMDb Helper"
    assert json.dumps(entries)
