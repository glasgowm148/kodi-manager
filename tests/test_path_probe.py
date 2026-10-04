import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

import path_probe


class PathProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_probe_chooses_later_candidate_with_expected_ids(self):
        bad = os.path.join(self.tmp, "bad")
        good = os.path.join(self.tmp, "good")
        os.makedirs(bad)
        os.makedirs(os.path.join(good, "skin.bingie"))
        os.makedirs(os.path.join(good, "plugin.video.fenlight"))
        probe = path_probe.probe_dir("addon_data", [bad, good], ["plugin.video.fenlight"])
        self.assertEqual(probe["selected_path"], good)
        self.assertIn("plugin.video.fenlight", probe["selected_dirs"])

    def test_probe_does_not_silently_return_empty_when_later_works(self):
        missing = os.path.join(self.tmp, "missing")
        good = os.path.join(self.tmp, "good")
        os.makedirs(os.path.join(good, "script.module.cocoscrapers"))
        probe = path_probe.probe_dir("addon_data", [missing, good], ["script.module.cocoscrapers"])
        self.assertTrue(probe["selected_path"].endswith("good"))
        self.assertTrue(any(a["result"].get("ok") for a in probe["attempts"]))


if __name__ == "__main__":
    unittest.main()
