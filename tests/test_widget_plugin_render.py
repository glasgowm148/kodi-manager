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
