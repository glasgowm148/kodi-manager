"""Extension points: identical public behaviour without a module, hooks with a fake one."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import extension  # noqa: E402
import service  # noqa: E402
import widget_cache  # noqa: E402
import widget_plugin  # noqa: E402

ROW = "plugin://plugin.video.example/?mode=107&url=watching"
LEAF = {"file": "plugin://plugin.video.example/?mode=202&url=episode", "label": "Episode"}


class ExtensionCase(unittest.TestCase):
    def use(self, **attrs):
        """Install a fake household module (or none) for this test."""
        patcher = patch.dict(sys.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(extension.reset)
        sys.modules.pop("household", None)
        if attrs:
            fake = types.ModuleType("household")
            for name, value in attrs.items():
                setattr(fake, name, value)
            sys.modules["household"] = fake
        extension.reset()
        return sys.modules.get("household")


class WidgetCacheHookTests(ExtensionCase):
    def test_without_extension_rows_and_leaves_are_unchanged(self):
        self.use()
        self.assertFalse(widget_cache.is_progress(ROW))
        self.assertEqual(widget_cache.ttl_for(ROW), widget_cache.TTL_DEFAULT)
        self.assertEqual(widget_cache.helper_item(LEAF, ROW), ({}, False))

    def test_extra_progress_and_playable_modes(self):
        self.use(WIDGET_PROGRESS_MODES=("107", "141"),
                 WIDGET_PLAYABLE_MODES={"plugin.video.example": ("201", "202")})
        self.assertTrue(widget_cache.is_progress(ROW))
        self.assertEqual(widget_cache.ttl_for(ROW), widget_cache.TTL_PROGRESS)
        self.assertFalse(widget_cache.is_progress("plugin://plugin.video.example/?mode=108"))
        self.assertEqual(widget_cache.helper_item(LEAF, ROW), ({}, True))
        other = {"file": "plugin://plugin.video.example/?mode=203"}
        self.assertEqual(widget_cache.helper_item(other, ROW), ({}, False))
        # Other add-ons keep the public rules (TMDb Helper play leaves stay playable).
        helper = {"file": "plugin://plugin.video.themoviedb.helper/?info=play&tmdb_id=1", "uniqueid": {"tmdb": 1}}
        props, playable = widget_cache.helper_item(helper, "plugin://plugin.video.themoviedb.helper/?info=trending")
        self.assertTrue(playable)
        self.assertEqual(props["tmdb_id"], "1")

    def test_malformed_tables_are_ignored(self):
        self.use(WIDGET_PROGRESS_MODES="107", WIDGET_PLAYABLE_MODES=["plugin.video.example"])
        self.assertFalse(widget_cache.is_progress(ROW))
        self.assertEqual(widget_cache.helper_item(LEAF, ROW), ({}, False))


def kodi_modules():
    xbmc = types.SimpleNamespace(log=Mock(), LOGWARNING=2, executeJSONRPC=Mock(return_value="{}"))
    return {"xbmc": xbmc, "xbmcgui": Mock(), "xbmcplugin": Mock(), "xbmcaddon": Mock(), "xbmcvfs": Mock()}


class WidgetPluginHookTests(ExtensionCase):
    ARGV = ["plugin://service.kodi.addonadmin/", "9", "?mode=continue"]

    def test_unknown_mode_without_extension_fails_the_directory_as_before(self):
        self.use()
        modules = kodi_modules()
        with patch.dict(sys.modules, modules):
            widget_plugin.main(self.ARGV)
        modules["xbmcplugin"].endOfDirectory.assert_called_once_with(9, succeeded=False, cacheToDisc=False)

    def test_unknown_mode_is_offered_to_the_extension(self):
        handler = Mock(return_value=True)
        self.use(widget_mode=handler)
        modules = kodi_modules()
        with patch.dict(sys.modules, modules):
            widget_plugin.main(self.ARGV)
        handler.assert_called_once_with("continue", self.ARGV)
        modules["xbmcplugin"].endOfDirectory.assert_not_called()

    def test_declined_mode_falls_through_and_family_is_never_offered(self):
        handler = Mock(return_value=False)
        self.use(widget_mode=handler)
        modules = kodi_modules()
        with patch.dict(sys.modules, modules):
            widget_plugin.main(self.ARGV)
            widget_plugin.main(["plugin://service.kodi.addonadmin/", "9", "?mode=family&source="])
        handler.assert_called_once_with("continue", self.ARGV)
        self.assertEqual(modules["xbmcplugin"].endOfDirectory.call_count, 2)


class ServiceHookTests(ExtensionCase):
    def setUp(self):
        self.logs = []
        self.kodi = types.SimpleNamespace(log=self.logs.append)
        self.monitor = Mock()
        self.monitor.abortRequested.return_value = False

    def test_no_extension_does_nothing(self):
        self.use()
        with patch.object(service, "xbmc", Mock()):
            self.assertIsNone(service.start_extension(self.kodi, self.monitor))
        service.stop_extension(self.kodi, None)
        self.assertEqual(self.logs, [])

    def test_start_and_stop_are_called(self):
        start, stop = Mock(), Mock()
        private = self.use(start=start, stop=stop)
        with patch.object(service, "xbmc", Mock()):
            self.assertIs(service.start_extension(self.kodi, self.monitor), private)
        start.assert_called_once_with(self.monitor, self.kodi.log)
        service.stop_extension(self.kodi, private)
        stop.assert_called_once_with()

    def test_failures_are_logged_by_type_and_contained(self):
        private = self.use(start=Mock(side_effect=OSError("/secret/path")), stop=Mock(side_effect=ValueError("x")))
        with patch.object(service, "xbmc", Mock()):
            service.start_extension(self.kodi, self.monitor)
        service.stop_extension(self.kodi, private)
        self.assertEqual(self.logs, ["Private extension start failed: OSError", "Private extension stop failed: ValueError"])

    def test_not_started_outside_kodi_or_when_cancelled(self):
        start = Mock()
        self.use(start=start)
        self.assertIsNone(service.start_extension(self.kodi, self.monitor))  # no xbmc
        self.monitor.abortRequested.return_value = True
        with patch.object(service, "xbmc", Mock()):
            self.assertIsNone(service.start_extension(self.kodi, self.monitor))
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
