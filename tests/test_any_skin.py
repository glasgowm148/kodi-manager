"""Kodi Manager's widget cache on skins and add-ons other than Bingie and POV."""
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import server  # noqa: E402
import widget_autocache as wa  # noqa: E402
import widget_cache as wc  # noqa: E402
import widget_plugin  # noqa: E402
import widget_rows as wr  # noqa: E402
from test_widget_cache import FakeListItem, FakePlugin  # noqa: E402

OTHER = "plugin://plugin.video.example/?route=popular"
FEN = "plugin://plugin.video.fenlight/?mode=build_movie_list&action=tmdb_movies_popular"


class Paged:
    """An unknown add-on with its own paging and Next page art."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, method, params=None):
        self.calls.append(params["directory"])
        page = int(parse_qs(urlsplit(params["directory"]).query).get("page", ["1"])[0])
        files = [{"label": "Item %d-%d" % (page, i), "file": "plugin://plugin.video.example/?play=%d%d" % (page, i),
                  "filetype": "file", "type": "movie"} for i in range(2)]
        if page < self.pages:
            files.append({"label": "Next page", "filetype": "directory", "art": {"thumb": "image://special%3a%2f%2fnext.png/"},
                          "file": OTHER + "&page=%d" % (page + 1)})
        return {"result": {"files": files}}


def test_any_addon_with_more_pages_gets_view_more_and_its_own_next_art():
    files, more, art = wc.fetch_listing(Paged(3), OTHER, 1)
    assert len(files) == 2 and more is True and art == "special://next.png"
    assert wc.view_more_url(OTHER, more) == OTHER
    assert wc.view_more_url(OTHER, False) is None
    files, more, _ = wc.fetch_listing(Paged(1), OTHER, 2)
    assert more is False
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": OTHER, "files": files, "content": "movies"}, view_more=OTHER, view_more_art="special://next.png")
    assert plugin.items[-1][1].art["thumb"] == "special://next.png"


def test_fen_family_routes_are_known_lists():
    assert wc.is_list_row(FEN) and wc.default_pages(FEN) == 2 and wc.view_more_url(FEN) == FEN
    assert wc.default_pages(OTHER) == 1


def test_row_limit_setting_beats_skin_detection():
    bingie = SimpleNamespace(getInfoLabel=lambda label: "40")
    assert wc.skin_widget_limit(bingie) == 40
    assert wc.skin_widget_limit(bingie, 15) == 15
    assert wc.skin_widget_limit(SimpleNamespace(getInfoLabel=lambda label: ""), 0) == 0


def test_row_store_and_plugin_root_list_rows_for_any_skin(tmp_path, monkeypatch):
    store = wr.RowStore(str(tmp_path))
    row = store.add("[B]Popular[/B]", OTHER + "&reload=$INFO[Window(Home).Property(x)]", pages=2)
    assert row["label"] == "Popular" and row["source"] == OTHER
    assert store.add("Popular films", OTHER)["id"] == row["id"]  # same source updates
    with pytest.raises(ValueError):
        store.add("Play", "plugin://plugin.video.example/?mode=play_media")
    url = store.listing()[0]["widget_url"]
    assert wc.source_from_cache_url(url) == OTHER and "reload=" in url
    plugin = FakePlugin()
    for name in ("xbmc", "xbmcgui", "xbmcplugin"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(ListItem=FakeListItem) if name == "xbmcgui" else plugin)
    monkeypatch.setitem(sys.modules, "xbmcvfs", SimpleNamespace(translatePath=lambda p: str(tmp_path)))
    widget_plugin.main(["plugin://service.kodi.addonadmin/", "3", ""])
    assert [(li.label, folder) for _, li, folder in plugin.items] == [
        ("Open the dashboard on another device", False), ("Cached rows", True)]
    plugin.items.clear()
    widget_plugin.main(["plugin://service.kodi.addonadmin/", "3", "?mode=rows"])
    (path, li, folder), = plugin.items
    assert path == url and folder is True and li.label == "Popular films"
    store.remove(row["id"])
    with pytest.raises(ValueError):
        store.remove(row["id"])


def test_context_menu_adds_the_focused_folder(tmp_path):
    notes = []
    gui = SimpleNamespace(Dialog=lambda: SimpleNamespace(input=lambda heading, defaultt="": defaultt + " row",
                                                         notification=lambda *a: notes.append(a)))
    vfs = SimpleNamespace(translatePath=lambda p: str(tmp_path))
    item = SimpleNamespace(getPath=lambda: FEN, getLabel=lambda: "Popular")
    row = wr.add_from_context(SimpleNamespace(), gui, vfs, item)
    assert row["label"] == "Popular row" and wr.RowStore(str(tmp_path)).load()[0]["source"] == FEN
    bad = SimpleNamespace(getPath=lambda: "plugin://script.module.x/", getLabel=lambda: "x")
    assert wr.add_from_context(SimpleNamespace(), gui, vfs, bad) is None


def test_autocache_routes_widget_path_properties_of_other_skins(tmp_path):
    rows = [["mainmenu", "movies", "widgetPath", FEN],
            ["mainmenu", "movies", "widgetPath.2", OTHER],
            ["mainmenu", "tv", "widgetPath", "plugin://plugin.video.example/?route=live"],
            ["mainmenu", "tv", "widgetName", "Popular"],
            ["mainmenu", "music", "widgetPath", "videodb://movies/titles/"]]
    props = tmp_path / "skin.arctic.zephyr.properties"
    props.write_text(repr(rows))
    assert wa.autocache(str(tmp_path), now=0) == {"skin.arctic.zephyr.properties": 1}
    new = eval(props.read_text())  # noqa: S307 - test fixture written by the code under test
    assert wc.source_from_cache_url(new[0][3]) == FEN and new[1][3] == OTHER and new[4][3] == "videodb://movies/titles/"
    # Opting another add-on in routes its rows too.
    assert wa.autocache(str(tmp_path), now=1, extra_addons=["plugin.video.example", "script.not.video"]) == {
        "skin.arctic.zephyr.properties": 2}
    new = eval(props.read_text())  # noqa: S307
    assert wc.source_from_cache_url(new[1][3]) == OTHER
    assert len(list((tmp_path / "kodi-manager-backups").glob("autocache-*/skin.arctic.zephyr.properties"))) == 2


@pytest.fixture
def api(tmp_path):
    state = SimpleNamespace(kodi=SimpleNamespace(), index=SimpleNamespace(refresh=lambda: None),
                            config={"auth_token": "t", "host": "127.0.0.1", "write_enabled": True}, log=lambda *a: None)
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None):
        conn = http.client.HTTPConnection(*http_server.server_address)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Authorization": "Bearer t", "Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    with patch.object(server, "translate", return_value=str(tmp_path)):
        yield call
    http_server.shutdown()
    http_server.server_close()


def test_rows_and_url_api(api):
    status, body = api("GET", "/api/widget-cache/url?source=" + FEN.replace("&", "%26") + "&pages=3")
    assert status == 200 and "pages=3" in body["data"]["url"]
    assert api("GET", "/api/widget-cache/url?source=plugin://plugin.video.x/?mode=play")[0] == 400
    status, row = api("POST", "/api/widget-cache/rows", {"label": "Popular", "source": FEN, "hide_watched": True})
    assert status == 200 and row["data"]["hide_watched"] is True
    status, rows = api("GET", "/api/widget-cache/rows")
    assert [r["label"] for r in rows["data"]] == ["Popular"] and "hide_watched=true" in rows["data"][0]["widget_url"]
    assert api("POST", "/api/widget-cache/rows/remove", {"id": row["data"]["id"]})[0] == 200
    assert api("POST", "/api/widget-cache/rows/remove", {"id": "nope"})[0] == 400


def test_dashboard_message_shows_address_and_token_only_with_lan_access():
    on = {"port": "8765", "auth_token": "abc", "allow_lan": "true", "host": "0.0.0.0"}
    heading, text = wr.dashboard_message(on, "192.168.1.20")
    assert heading == "Open the dashboard" and "http://192.168.1.20:8765" in text and "abc" in text
    heading, text = wr.dashboard_message(dict(on, allow_lan="false"), "192.168.1.20")
    assert heading == "Turn on network access" and "abc" not in text
    assert wr.dashboard_message(on, "")[0] == "Turn on network access"


def test_local_ip_waits_for_kodi_then_falls_back():
    answers = iter(["Busy", "Busy", "192.168.1.30"])
    xbmc = SimpleNamespace(getInfoLabel=lambda label: next(answers), sleep=lambda ms: None)
    assert wr.local_ip(xbmc) == "192.168.1.30"
    busy = SimpleNamespace(getInfoLabel=lambda label: "Busy", sleep=lambda ms: None)
    assert wr.local_ip(busy, attempts=2) != "Busy"
