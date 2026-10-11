"""Family directory rendering: offscreen ListItems and legacy resume properties."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import widget_plugin  # noqa: E402

RESULT = {"source": "plugin://plugin.video.example/?mode=list", "max_rating": "12A", "family_only": False}


def render(item, native=True):
    tag = Mock()
    li = Mock() if native else Mock(spec=["setInfo", "setArt", "setProperty", "addContextMenuItems", "setProperties"])
    if native:
        li.getVideoInfoTag.return_value = tag
    gui = SimpleNamespace(ListItem=Mock(return_value=li))
    plugin = Mock()
    widget_plugin.render_directory(gui, plugin, 1, dict(RESULT, files=[item]))
    return gui.ListItem, li, tag


class RenderTests(unittest.TestCase):
    def test_list_items_are_created_offscreen(self):
        make, _, _ = render({"file": "plugin://plugin.video.example/?mode=play&id=1", "label": "Example"})
        self.assertIs(make.call_args.kwargs.get("offscreen"), True)

    def test_legacy_resume_properties_become_a_native_resume_point(self):
        item = {"file": "plugin://plugin.video.example/?mode=play&id=2", "label": "Episode",
                "properties": {"ResumeTime": "120", "TotalTime": "3600", "other": "kept"}}
        _, li, tag = render(item)
        tag.setResumePoint.assert_called_once_with(120.0, 3600.0)
        names = [call.args[0] for call in li.setProperty.call_args_list]
        self.assertNotIn("ResumeTime", names)
        self.assertNotIn("TotalTime", names)
        self.assertIn("other", names)

    def test_legacy_total_falls_back_to_duration(self):
        item = {"file": "plugin://plugin.video.example/?mode=play&id=3", "duration": 1800,
                "properties": {"resumetime": "60"}}
        _, _, tag = render(item)
        tag.setResumePoint.assert_called_once_with(60.0, 1800.0)

    def test_jsonrpc_resume_wins_and_bad_legacy_values_are_ignored(self):
        item = {"file": "plugin://plugin.video.example/?mode=play&id=4", "resume": {"position": 5, "total": 50},
                "properties": {"ResumeTime": "120"}}
        _, _, tag = render(item)
        tag.setResumePoint.assert_called_once_with(5, 50)
        self.assertEqual(widget_plugin._legacy_resume({"properties": {"ResumeTime": "soon"}}, {}), {})

    def test_kodi19_items_keep_the_resume_properties(self):
        item = {"file": "plugin://plugin.video.example/?mode=play&id=5", "properties": {"ResumeTime": "120", "TotalTime": "3600"}}
        _, li, _ = render(item, native=False)
        props = {call.args[0]: call.args[1] for call in li.setProperty.call_args_list}
        self.assertEqual(props["TotalTime"], "3600")
        self.assertIn(props["ResumeTime"], ("120", "120.0"))


if __name__ == "__main__":
    unittest.main()


class CancellationTests(unittest.TestCase):
    def tearDown(self):
        widget_plugin._active_invocation = None

    def test_a_cancelled_invocation_stops_rendering(self):
        invocation = Mock()
        invocation.cancelled.side_effect = [False, True]
        widget_plugin._active_invocation = invocation
        gui = SimpleNamespace(ListItem=Mock(return_value=Mock()))
        plugin = Mock()
        files = [{"file": "plugin://plugin.video.example/?mode=play&id=%d" % n} for n in range(3)]
        widget_plugin.render_directory(gui, plugin, 7, dict(RESULT, files=files))
        self.assertEqual(plugin.addDirectoryItem.call_count, 1)
        plugin.endOfDirectory.assert_called_once_with(7, succeeded=False, cacheToDisc=False)

    def test_run_answers_a_cancelled_call_without_work(self):
        from unittest.mock import patch
        import profile_transition
        invocation = Mock()
        invocation.cancelled.return_value = True
        invocation.__enter__ = Mock(return_value=invocation)
        invocation.__exit__ = Mock(return_value=False)
        plugin = Mock()
        with patch.object(profile_transition, "Invocation", Mock(return_value=invocation)), \
                patch.dict(sys.modules, {"xbmcplugin": plugin}), patch.object(widget_plugin, "main") as main:
            widget_plugin.run(["plugin://service.kodi.addonadmin/", "4", "?mode=cached"])
        main.assert_not_called()
        plugin.endOfDirectory.assert_called_once_with(4, succeeded=False, cacheToDisc=False)
        self.assertIsNone(widget_plugin._active_invocation)

    def test_run_calls_main_inside_the_invocation(self):
        from unittest.mock import patch
        import profile_transition
        seen = []
        argv = ["plugin://service.kodi.addonadmin/", "4", "?mode=rows"]
        with patch.object(widget_plugin, "main", side_effect=lambda a: seen.append((a, widget_plugin._active_invocation))):
            widget_plugin.run(argv)
        self.assertEqual(seen[0][0], argv)
        self.assertIsInstance(seen[0][1], profile_transition.Invocation)
        self.assertFalse(seen[0][1].cancelled())
