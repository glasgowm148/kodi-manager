"""The startup notification: a reachable address, once per Kodi session, never on a profile switch."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import service  # noqa: E402


class AddressTests(unittest.TestCase):
    def test_wildcard_bind_shows_the_lan_address_or_loopback(self):
        config = {"host": "0.0.0.0", "port": 8765}
        self.assertEqual(service.dashboard_address(config, lambda: "192.168.1.147"), "http://192.168.1.147:8765")
        self.assertEqual(service.dashboard_address(config, lambda: ""), "http://127.0.0.1:8765")
        self.assertEqual(service.dashboard_address(config, Mock(side_effect=OSError)), "http://127.0.0.1:8765")
        self.assertEqual(service.dashboard_address({"host": "::", "port": 1}, "fd00::5"), "http://[fd00::5]:1")

    def test_specific_bind_is_shown_as_is(self):
        self.assertEqual(service.dashboard_address({"host": "127.0.0.1", "port": 8765}, Mock(side_effect=AssertionError)),
                         "http://127.0.0.1:8765")
        self.assertEqual(service.dashboard_address({"host": "192.168.1.9", "port": 9000}), "http://192.168.1.9:9000")


class OncePerSessionTests(unittest.TestCase):
    ADULTS, KIDS = "/kodi/userdata/", "/kodi/userdata/profiles/Kids/"

    def test_first_start_announces(self):
        self.assertTrue(service.announce_due({}, "100:5", self.ADULTS, 1000))

    def test_same_kodi_process_never_announces_again(self):
        previous = {"process": "100:5", "profile": self.ADULTS, "stopped_at": 990}
        self.assertFalse(service.announce_due(previous, "100:5", self.KIDS, 1000))   # in-process profile switch
        self.assertFalse(service.announce_due(previous, "100:5", self.ADULTS, 5000))  # add-on update

    def test_restart_into_another_profile_moments_later_is_a_switch(self):
        previous = {"process": "100:5", "profile": self.ADULTS, "stopped_at": 1000}
        self.assertFalse(service.announce_due(previous, "200:9", self.KIDS, 1017))
        # The next real Kodi start (later, or in the same profile) announces again.
        self.assertTrue(service.announce_due(previous, "200:9", self.KIDS, 1000 + 3600))
        self.assertTrue(service.announce_due(previous, "200:9", self.ADULTS, 1017))
        # A crash leaves no stop time: a new session.
        self.assertTrue(service.announce_due({"process": "100:5", "profile": self.ADULTS}, "200:9", self.KIDS, 1017))

    def test_session_record_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "session.json")
            self.assertEqual(service.read_session(path), {})
            service.write_session(path, {"process": "1:2", "profile": "p"})
            self.assertEqual(service.read_session(path), {"process": "1:2", "profile": "p"})
            Path(path).write_text("[]")
            self.assertEqual(service.read_session(path), {})

    def test_process_identity_includes_the_start_time_when_known(self):
        with patch.object(service, "process_start", return_value="777"):
            self.assertTrue(service.process_identity().endswith(":777"))
        with patch.object(service, "process_start", side_effect=OSError):
            self.assertTrue(service.process_identity().isdigit())


if __name__ == "__main__":
    unittest.main()
