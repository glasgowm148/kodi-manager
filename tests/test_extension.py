"""The optional private extension module: absent in public builds, isolated when broken."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "kodi_manager"))
sys.path.insert(0, str(ROOT / "scripts"))
import extension  # noqa: E402


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        extension.reset()
        self.addCleanup(extension.reset)

    def test_public_build_has_no_module(self):
        # None in sys.modules makes the module absent even in a private build that ships one.
        with patch.dict(sys.modules, {"household": None}):
            self.assertIsNone(extension.module())
            self.assertIsNone(extension.error)
            self.assertEqual(extension.attr("WIDGET_PROGRESS_MODES", ()), ())

    def test_a_present_module_is_loaded_once(self):
        fake = types.ModuleType("household")
        fake.WIDGET_PROGRESS_MODES = ("x",)
        with patch.dict(sys.modules, {"household": fake}):
            self.assertIs(extension.module(), fake)
            self.assertEqual(extension.attr("WIDGET_PROGRESS_MODES"), ("x",))
            self.assertIsNone(extension.attr("missing"))
        self.assertIs(extension.module(), fake)  # cached for this interpreter

    def test_a_broken_module_is_ignored_and_reported(self):
        def broken(name, *args, **kwargs):
            if name == "household":
                raise ImportError("No module named 'dependency'", name="dependency")
            return original(name, *args, **kwargs)
        import importlib
        original = importlib.import_module
        with patch.dict(sys.modules), patch("importlib.import_module", side_effect=broken):
            sys.modules.pop("household", None)
            self.assertIsNone(extension.module())
        self.assertEqual(extension.error, "ImportError")
        extension.reset()
        with patch.dict(sys.modules), patch("importlib.import_module", side_effect=SyntaxError("bad")):
            self.assertIsNone(extension.module())
        self.assertEqual(extension.error, "SyntaxError")


class ReleaseCheckTests(unittest.TestCase):
    def test_public_archives_refuse_a_household_module(self):
        import check_release
        with self.assertRaises(ValueError):
            check_release.check_name("service.kodi.addonadmin/resources/lib/household.py")
        with self.assertRaises(ValueError):
            check_release.check_name("kodi_manager/household.py")
        check_release.check_name("service.kodi.addonadmin/resources/lib/extension.py")


if __name__ == "__main__":
    unittest.main()
