"""profile_transition: a no-op without a coordinator; the shared protocol with one."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

LIB = Path(__file__).resolve().parents[1] / "src" / "kodi_manager"
sys.path.insert(0, str(LIB))
import extension  # noqa: E402


class FakeMonitor:
    def __init__(self):
        self.aborted = False
        self.waits = []

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, timeout=-1):
        self.waits.append(timeout)
        return self.aborted


class TransitionCase(unittest.TestCase):
    def load(self, coordinator=None, household=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        paths = {"special://masterprofile/": str(self.root / "master") + "/",
                 "special://profile/": str(self.root / "master") + "/"}

        def translate(path):
            for prefix, value in paths.items():
                if path.startswith(prefix):
                    return value + path[len(prefix):]
            raise AssertionError(path)
        modules = {"xbmc": types.SimpleNamespace(Monitor=FakeMonitor),
                   "xbmcvfs": types.SimpleNamespace(translatePath=translate)}
        if household:
            fake = types.ModuleType("household")
            if coordinator is not None:
                fake.TRANSITION_COORDINATOR = coordinator
            modules["household"] = fake
        saved = {name: sys.modules.get(name) for name in ("xbmc", "xbmcvfs", "household")}
        original_start = threading.Thread.start
        owner = threading.current_thread().__dict__.get("_kodi_profile_worker_owner")

        def restore():
            for name, value in saved.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
            threading.Thread.start = original_start
            if owner is None:
                threading.current_thread().__dict__.pop("_kodi_profile_worker_owner", None)
            else:
                threading.current_thread().__dict__["_kodi_profile_worker_owner"] = owner
            extension.reset()
        self.addCleanup(restore)
        for name in ("xbmc", "xbmcvfs", "household"):
            sys.modules.pop(name, None)
        sys.modules.update(modules)
        extension.reset()
        spec = importlib.util.spec_from_file_location("profile_transition_under_test", LIB / "profile_transition.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def files(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())


class NoCoordinatorTests(TransitionCase):
    def test_public_build_is_a_no_op(self):
        for household in (False, True):
            with self.subTest(household=household):
                original_start = threading.Thread.start
                pt = self.load(household=household)
                self.assertFalse(pt.ENABLED)
                self.assertIs(threading.Thread.start, original_start)
                monitor = pt.Monitor()
                self.assertFalse(monitor.abortRequested())
                monitor.aborted = True
                self.assertTrue(monitor.abortRequested())
                monitor.aborted = False
                self.assertFalse(monitor.waitForAbort(5))
                self.assertEqual(monitor.waits, [5])  # one native wait, no 0.2 s polling
                with pt.Invocation("service.kodi.addonadmin") as invocation:
                    self.assertFalse(invocation.cancelled())
                self.assertTrue(pt.drained("service.kodi.addonadmin"))
                self.assertEqual(self.files(), [])

    def test_invalid_coordinator_ids_disable_it(self):
        for value in ("../escape", "", "a/b", 5):
            with self.subTest(value=value):
                self.assertFalse(self.load(coordinator=value).ENABLED)

    def test_without_kodi_it_imports_and_stays_disabled(self):
        pt = self.load(coordinator="coordinator.example")
        with patch.dict(sys.modules, {"xbmc": None, "xbmcvfs": None}):
            spec = importlib.util.spec_from_file_location("pt_no_kodi", LIB / "profile_transition.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertTrue(pt.ENABLED)
        self.assertFalse(module.ENABLED)
        self.assertTrue(module.drained("x"))


class CoordinatorTests(TransitionCase):
    def state(self, pt, **values):
        os.makedirs(pt.ROOT, exist_ok=True)
        with open(pt.STATE, "w", encoding="utf-8") as handle:
            json.dump(dict({"pid": os.getpid()}, **values), handle)

    def test_paths_follow_the_coordinator(self):
        pt = self.load(coordinator="coordinator.example")
        self.assertTrue(pt.ENABLED)
        self.assertEqual(Path(pt.STATE), self.root / "master" / "addon_data" / "coordinator.example" / "transition.json")

    def test_switch_away_from_this_profile_or_a_new_generation_cancels(self):
        pt = self.load(coordinator="coordinator.example")
        self.state(pt, generation="g1", switching=False)
        monitor = pt.Monitor()
        self.assertFalse(monitor.abortRequested())
        self.state(pt, generation="g1", switching=True, outgoing=pt.PROFILE)
        self.assertTrue(monitor.abortRequested())
        self.assertTrue(monitor.waitForAbort(5))
        self.state(pt, generation="g2", switching=False)
        self.assertTrue(pt.Lease().cancelled() is False and monitor.abortRequested())
        # Another process's record is ignored.
        self.state(pt, generation="g1", switching=False)
        with open(pt.STATE, "w", encoding="utf-8") as handle:
            json.dump({"pid": -1, "generation": "other", "switching": True, "outgoing": pt.PROFILE}, handle)
        self.assertFalse(pt.Lease().cancelled())

    def test_invocation_registers_and_waits_for_its_workers(self):
        pt = self.load(coordinator="coordinator.example")
        self.state(pt, generation="g1")
        release = threading.Event()
        with pt.Invocation("service.kodi.addonadmin") as invocation:
            jobs = list((Path(pt.ROOT) / "jobs" / str(os.getpid())).glob("*.json"))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(json.loads(jobs[0].read_text()), {"profile": pt.PROFILE, "addon": "service.kodi.addonadmin"})
            worker = threading.Thread(target=release.wait, args=(2,), daemon=True)
            worker.start()
            self.assertEqual(pt._owned_workers("service.kodi.addonadmin"), [worker])
            threading.Timer(0.2, release.set).start()
        self.assertFalse(worker.is_alive())
        self.assertFalse(jobs[0].exists())
        self.assertFalse(invocation.cancelled())

    def test_drained_acknowledges_the_generation(self):
        pt = self.load(coordinator="coordinator.example")
        self.state(pt, generation="g7", switching=True, outgoing=pt.PROFILE)
        self.assertTrue(pt.drained("service.kodi.addonadmin"))
        self.assertTrue((Path(pt.ROOT) / "drained" / "g7" / "service.kodi.addonadmin.json").is_file())
        self.assertTrue((Path(pt.ROOT) / "drain-start-service.kodi.addonadmin.json").is_file())

    def test_drained_gives_up_after_its_timeout_and_reports_workers(self):
        pt = self.load(coordinator="coordinator.example")
        self.state(pt, generation="g8")
        release = threading.Event()
        worker = threading.Thread(target=release.wait, args=(3,), name="stuck-worker", daemon=True)
        worker.start()
        try:
            self.assertFalse(pt.drained("service.kodi.addonadmin", timeout=0.1))
        finally:
            release.set()
        report = json.loads((Path(pt.ROOT) / "drain-diagnostic.json").read_text())
        self.assertEqual(report, {"addon": "service.kodi.addonadmin", "workers": ["stuck-worker"]})

    def test_a_malformed_state_file_is_ignored(self):
        pt = self.load(coordinator="coordinator.example")
        os.makedirs(pt.ROOT, exist_ok=True)
        Path(pt.STATE).write_text("[1, 2]")
        self.assertEqual(pt.read_state(), {})


class ServiceStartupTests(unittest.TestCase):
    def test_service_returns_before_reading_settings_when_cancelled_at_startup(self):
        import service
        cancelled = Mock()
        cancelled.return_value.abortRequested.return_value = True
        with patch.object(service, "xbmc", Mock()), \
                patch.object(service.profile_transition, "Monitor", cancelled), \
                patch.object(service, "service_addon") as addon:
            service.main()
        addon.assert_not_called()


if __name__ == "__main__":
    unittest.main()
