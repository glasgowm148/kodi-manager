"""Search history (suggestions while typing) and putting a search into the running skin."""
import json
from types import SimpleNamespace

import pytest

from kodi_manager import widget_plugin
from kodi_manager.search_history import MAX_ENTRIES, SearchHistory, clean, open_search
from test_skin_settings_live import split_exec


@pytest.fixture
def history(tmp_path):
    clock = iter(range(1000, 2000))
    return SearchHistory(str(tmp_path / "search_history.json"), clock=lambda: next(clock))


def test_clean_keeps_one_short_line():
    assert clean("  The   Traitors\n") == "The Traitors"
    assert clean("a") == "" and clean(None) == "" and clean("\x00\x01") == ""
    assert len(clean("x" * 500)) == 100


def test_add_moves_a_repeat_to_the_top_and_caps_the_list(history):
    for text in ("traitors", "bluey", "TRAITORS ", "x"):
        history.add(text)
    assert [e["query"] for e in history.entries()] == ["TRAITORS", "bluey"]
    for i in range(MAX_ENTRIES + 5):
        history.add("show %d" % i)
    entries = history.entries()
    assert len(entries) == MAX_ENTRIES and entries[0]["query"] == "show %d" % (MAX_ENTRIES + 4)


def test_suggest_prefers_starts_then_later_words_newest_first(history):
    for text in ("The Traitors", "traitors", "trainspotting", "bluey", "Celebrity Traitors"):
        history.add(text)
    assert history.suggest("trai") == ["trainspotting", "traitors", "Celebrity Traitors", "The Traitors"]
    assert history.suggest("TRAITORS") == ["Celebrity Traitors", "The Traitors"]   # the exact search is left out
    assert history.suggest("t", limit=2) == ["trainspotting", "traitors"]
    assert history.suggest("") == ["Celebrity Traitors", "bluey", "trainspotting", "traitors", "The Traitors"]
    assert history.suggest("zz") == []


def test_damaged_file_reads_as_empty_and_is_replaced(history):
    with open(history.path, "w") as handle:
        handle.write("{not json")
    assert history.entries() == [] and history.suggest("") == []
    history.add("bluey")
    assert json.load(open(history.path))["entries"][0]["query"] == "bluey"


def test_remove_and_clear(history):
    history.add("bluey")
    history.add("traitors")
    assert history.remove("BLUEY") == 1 and [e["query"] for e in history.entries()] == ["traitors"]
    history.clear()
    assert history.entries() == []


@pytest.mark.parametrize("options,expected", [
    ('?mode=search_history&limit=5&query="trai"', "trai"),                 # $ESCINFO in a content path
    ("?mode=search_history_add&query=fast & furious", "fast & furious"),    # RunPlugin already unquoted it
    ('?mode=search_history&query="say \\"hi\\" \\\\ bye"', 'say "hi" \\ bye'),
    ("?query=the%20traitors", "the traitors"),
    ("?mode=search_history&query=", ""),
    ("?mode=search_history", ""),
])
def test_raw_query(options, expected):
    assert widget_plugin.raw_query(options) == expected


class FakePlugin:
    def __init__(self):
        self.items, self.ended = [], None

    def ListItem(self, label="", offscreen=False):
        props = {}
        return SimpleNamespace(label=label, props=props, setProperty=props.__setitem__)

    def addDirectoryItem(self, handle, url, li, isFolder=False):
        self.items.append((url, li.label, dict(li.props), isFolder))

    def endOfDirectory(self, handle, succeeded=True, cacheToDisc=True):
        self.ended = (succeeded, cacheToDisc)


def test_plugin_lists_suggestions_with_a_search_path(history):
    history.add("The Traitors")
    history.add("traitors")
    fake = FakePlugin()
    target = "plugin://plugin.video.tmdb.bingie.helper?info=search&query="
    from urllib.parse import quote
    argv = ["plugin://service.kodi.addonadmin/", "7",
            "?mode=search_history&limit=5&target=%s&query=\"tra\"" % quote(target, safe="")]
    assert widget_plugin.search_history_mode("search_history", argv, fake, fake, history)
    assert fake.items == [
        (target + "traitors", "traitors", {"search_history": "true", "path": target + "traitors"}, True),
        (target + "The+Traitors", "The Traitors", {"search_history": "true", "path": target + "The+Traitors"}, True)]
    assert fake.ended == (True, False)
    # Recording goes through RunPlugin (handle -1): nothing is listed.
    added = FakePlugin()
    assert widget_plugin.search_history_mode("search_history_add", ["u", "-1", "?mode=search_history_add&query=bluey"],
                                             added, added, history)
    assert history.entries()[0]["query"] == "bluey" and added.ended is None
    assert widget_plugin.search_history_mode("family", argv, fake, fake, history) is False


class FakeKodi:
    def __init__(self, skin="skin.bingie", search_window_open=False, helpers=()):
        self.skin, self.open, self.helpers = skin, search_window_open, set(helpers)
        self.builtins = []

    def get_active_skin(self):
        return {"addon_id": self.skin}

    def get_addon_details(self, aid):
        return {"addon_id": aid, "enabled": True} if aid in self.helpers else {}

    def jsonrpc(self, method, params=None):
        assert method == "XBMC.GetInfoBooleans"
        return {"result": {params["booleans"][0]: self.open}}

    def execute_builtin(self, command):
        self.builtins.append(split_exec(command))
        return True


def test_open_search_in_bingie_sets_the_term_and_opens_its_window(history):
    kodi = FakeKodi()
    assert open_search(kodi, ' the "office", US ', history) == {"opened": True, "query": 'the "office", US', "how": "bingie"}
    assert kodi.builtins == [("dialog.close", ["all", "true"]),
                             ("skin.setstring", ["CustomSearchTerm", 'the "office", US']),
                             ("setproperty", ["CustomSearch", "1", "home"]),
                             ("activatewindow", ["1109"])]
    assert history.entries()[0]["query"] == 'the "office", US'
    already = FakeKodi(search_window_open=True)
    open_search(already, "bluey", history)
    assert ("activatewindow", ["1109"]) not in already.builtins


def test_open_search_elsewhere_uses_tmdb_helper_or_refuses(history):
    kodi = FakeKodi(skin="skin.estuary", helpers={"plugin.video.themoviedb.helper"})
    result = open_search(kodi, "fast & furious", history)
    assert result["how"] == "plugin.video.themoviedb.helper"
    assert kodi.builtins == [("activatewindow", ["Videos",
                                                 "plugin://plugin.video.themoviedb.helper/?info=search&tmdb_type=both&query=fast+%26+furious",
                                                 "return"])]
    assert open_search(FakeKodi(skin="skin.estuary"), "bluey") == {"opened": False, "reason": "no_search_handler",
                                                                  "skin": "skin.estuary"}
    assert open_search(FakeKodi(), " ")["reason"] == "empty_query"


def test_api_handlers(tmp_path, monkeypatch):
    from kodi_manager import api_status
    monkeypatch.setattr(api_status, "translate", lambda path: str(tmp_path / "search_history.json"))
    handler = api_status.StatusRoutes.__new__(api_status.StatusRoutes)
    handler.state = SimpleNamespace(kodi=FakeKodi())
    handler.body = lambda: {"query": "the traitors"}
    assert handler.api_search_voice() == {"opened": True, "query": "the traitors", "how": "bingie"}
    assert [e["query"] for e in handler.api_search_history()["entries"]] == ["the traitors"]
    handler.body = lambda: {"query": 5}
    with pytest.raises(ValueError):
        handler.api_search_voice()
    handler.body = lambda: {"query": "The Traitors"}
    assert handler.api_search_history_remove() == {"removed": 1}
    handler.body = lambda: {"all": True}
    assert handler.api_search_history_remove() == {"removed": "all"}
    handler.body = lambda: {}
    with pytest.raises(ValueError):
        handler.api_search_history_remove()
