"""Opt-in routing of new skin widget rows through the widget cache."""
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import widget_autocache as wa  # noqa: E402
import widget_cache as wc  # noqa: E402

POV = "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_blockbusters"
TMDB = "plugin://plugin.video.tmdb.bingie.helper/?info=trakt_trending&tmdb_type=movie&widget=true"


def data(*actions):
    rows = "".join("<shortcut><label>Row %d</label><action>%s</action></shortcut>" % (i, a.replace("&", "&amp;"))
                   for i, a in enumerate(actions))
    return "<shortcuts>%s</shortcuts>" % rows


def actions(path):
    return [a.text for a in ET.parse(path).getroot().iter("action")]


def test_new_widget_rows_are_routed_and_originals_backed_up(tmp_path):
    reload = "&reload=$INFO[Window(Home).Property(TMDbBingieHelper.Widgets.Reload)]"
    already = 'ActivateWindow(Videos,"%s",return)' % wc.cache_url(POV)
    hub = tmp_path / "skin.bingie-moviehub.DATA.xml"
    hub.write_text(data('ActivateWindow(Videos,%s,return)' % POV,
                        'ActivateWindow(Videos,"%s",return)' % (TMDB + reload),
                        already,
                        "ActivateWindow(Videos,plugin://plugin.video.tmdb.bingie.helper/?info=genres&tmdb_type=movie,return)",
                        "ActivateWindow(Videos,plugin://plugin.video.iplayerwww/?mode=101,return)",
                        "ActivateWindow(Videos,plugin://plugin.video.pov/?mode=playback.media&tmdb_id=1,return)"))
    menu = tmp_path / "skin.bingie-mainmenu.DATA.xml"
    menu.write_text(data("ActivateWindow(Videos,%s,return)" % POV))
    original = hub.read_text()
    assert wa.autocache(str(tmp_path), now=0) == {"skin.bingie-moviehub.DATA.xml": 2}
    new = actions(hub)
    assert wc.source_from_cache_url(new[0].split('"')[1]) == POV
    assert wc.source_from_cache_url(new[1].split('"')[1]) == TMDB
    assert new[2:] == actions(hub)[2:] and new[2] == already
    assert "info=genres" in new[3] and "iplayerwww" in new[4] and "playback.media" in new[5]
    assert actions(menu) == ["ActivateWindow(Videos,%s,return)" % POV]  # menus untouched
    backups = list((tmp_path / "kodi-manager-backups").glob("autocache-*/skin.bingie-moviehub.DATA.xml"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert wa.autocache(str(tmp_path), now=1) == {}  # idempotent


def test_home_widget_group_is_included_and_bad_files_skipped(tmp_path):
    (tmp_path / "skin.bingie-10000-1.DATA.xml").write_text(data("ActivateWindow(Videos,%s,return)" % POV))
    (tmp_path / "skin.bingie-newhub.DATA.xml").write_text("<shortcuts><broken")
    assert wa.autocache(str(tmp_path)) == {"skin.bingie-10000-1.DATA.xml": 1}
    assert wa.autocache(str(tmp_path / "missing")) == {}


def test_helper_rows_follow_only_resolve_strm(monkeypatch):
    setting = {"value": "false"}
    monkeypatch.setitem(sys.modules, "xbmcaddon", SimpleNamespace(
        Addon=lambda aid: SimpleNamespace(getSetting=lambda key: setting["value"])))
    assert wc.helper_resolves(TMDB) is True
    setting["value"] = "true"
    assert wc.helper_resolves(TMDB) is False
    assert wc.helper_resolves(POV) is True
    from test_widget_cache import FakeListItem, FakePlugin, tmdb_item
    plugin = FakePlugin()
    wc.render(SimpleNamespace(), SimpleNamespace(ListItem=FakeListItem), plugin, 1,
              {"source": TMDB, "files": [tmdb_item()], "content": "movies"}, helper_playable=False)
    assert "IsPlayable" not in plugin.items[0][1].props
