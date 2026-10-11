"""Widget row health for skins (KM.WidgetFailures) and the external reload token."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import service  # noqa: E402
from widget_cache import WidgetCache  # noqa: E402

ROW = "plugin://plugin.video.example/?mode=row"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class WidgetHealthTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = WidgetCache(temp.name)
        self.props, self.notices, self.clock = {}, [], Clock()
        self.health = service.WidgetHealth(self.cache, self.props.__setitem__, lambda: self.notices.append(1), self.clock)

    def fail(self, source, times):
        for _ in range(times):
            self.cache.record_failure(source, self.clock())

    def test_counts_only_active_rows_failing_three_times(self):
        self.cache.save(ROW, [{"file": "plugin://plugin.video.example/?mode=play", "label": "A"}])
        self.fail(ROW, 2)
        self.fail("plugin://plugin.video.example/?mode=inactive", 5)  # no cached entry: not on screen
        self.assertEqual(service.persistent_widget_failures(self.cache), 0)
        self.fail(ROW, 1)
        self.assertEqual(service.persistent_widget_failures(self.cache), 1)

    def test_one_notice_per_failure_episode_only_while_quiet(self):
        self.cache.save(ROW, [{"file": "plugin://plugin.video.example/?mode=play", "label": "A"}])
        self.fail(ROW, 3)
        self.health.tick(lambda: False)
        self.assertEqual((self.props, self.notices), ({}, []))
        self.health.tick(lambda: True)
        self.assertEqual((self.props["KM.WidgetFailures"], len(self.notices)), ("1", 1))
        self.clock.now += 30
        self.health.tick(lambda: self.fail_test("checked within a minute"))
        self.clock.now += 31
        self.health.tick(lambda: True)
        self.assertEqual(len(self.notices), 1)
        self.cache.record_success(ROW)
        self.clock.now += 61
        self.health.tick(lambda: True)
        self.assertEqual(self.props["KM.WidgetFailures"], "0")
        self.fail(ROW, 3)
        self.clock.now += 61
        self.health.tick(lambda: True)
        self.assertEqual(len(self.notices), 2)

    def fail_test(self, message):
        raise AssertionError(message)

    def test_external_reload_token_includes_pov(self):
        class Home:
            def getProperty(self, name):
                return {"POV.Widgets.Reload": "pov-1", "TMDbHelper.Widgets.Reload": "t-2"}.get(name, "")
        self.assertEqual(service.external_reload_token(Home()), "|t-2|pov-1")


if __name__ == "__main__":
    unittest.main()
