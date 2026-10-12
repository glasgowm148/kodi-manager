"""A retained widget worker must not retain Kodi's native classes."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import service_workers as workers  # noqa: E402


def test_widget_callbacks_release_native_objects_between_calls(monkeypatch, tmp_path):
    alive = weakref.WeakSet()
    properties = {}

    class Window:
        def __init__(self, window_id):
            alive.add(self)

        def setProperty(self, name, value):
            properties[name] = value

        def getProperty(self, name):
            return properties.get(name, "")

    class Player:
        def __init__(self):
            alive.add(self)

        def isPlayingVideo(self):
            return False

    gui = SimpleNamespace(Window=Window)
    kodi = SimpleNamespace(log=lambda message: None)
    monkeypatch.setitem(sys.modules, "xbmcgui", gui)
    monkeypatch.setattr(workers, "xbmc", SimpleNamespace(Player=Player))
    monkeypatch.setattr(workers, "translate", lambda path: str(tmp_path))
    monkeypatch.setattr(workers, "tv_busy", lambda: False)
    monkeypatch.setattr("threading.Thread", Mock())
    health_factory = Mock(wraps=workers.WidgetHealth)
    monkeypatch.setattr(workers, "WidgetHealth", health_factory)
    refresher = workers.start_widget_refresher(kodi)
    assert not alive  # Old bound callbacks retained both objects even before a tick.
    assert refresher._quiet()
    assert refresher.external_reload() == "||"
    refresher.bump("1")
    health_factory.call_args.args[1](workers.WIDGET_FAILURES_PROPERTY, "0")
    assert properties == {workers.RELOAD_PROPERTY: "1", workers.WIDGET_FAILURES_PROPERTY: "0"}
    assert not alive
    refresher.stop.set()
