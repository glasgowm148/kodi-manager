"""A Monitor registered late must not lose the service's original abort signal."""
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
from service import retire_runtime, wait_for_shutdown  # noqa: E402


def test_shutdown_during_startup_exits_even_when_late_monitor_missed_abort():
    startup = Mock()
    startup.abortRequested.return_value = True
    late = Mock()
    late.abortRequested.return_value = False
    wait_for_shutdown(late, startup)
    late.waitForAbort.assert_not_called()


def test_original_monitor_can_abort_while_waiting_on_new_monitor():
    startup = Mock()
    startup.abortRequested.return_value = False
    late = Mock()
    late.abortRequested.return_value = False
    late.waitForAbort.side_effect = lambda seconds: setattr(startup.abortRequested, 'return_value', True)
    wait_for_shutdown(late, startup)
    late.waitForAbort.assert_called_once_with(1)


def test_callback_monitor_still_handles_normal_shutdown():
    late = Mock()
    late.abortRequested.return_value = True
    wait_for_shutdown(late)
    late.waitForAbort.assert_not_called()


def test_retire_blocks_new_work_before_extension_cleanup():
    from threading import Event
    from types import SimpleNamespace
    events = [Event(), Event(), Event()]
    retired = []

    class Server:
        def stop(self):
            # A final listener callback must see every producer already stopped.
            assert all(event.is_set() for event in events)
            retired.append(True)

    retire_runtime(Server(), SimpleNamespace(stop=events[1]),
                   SimpleNamespace(stop=events[2]), events[0])
    assert retired == [True] and all(event.is_set() for event in events)


def test_retire_handles_disabled_workers_and_server():
    retire_runtime()


def test_widget_shutdown_during_tick_skips_native_health_checks():
    from threading import Event
    from types import SimpleNamespace
    from service_workers import widget_refresh_tick
    stop = Event()
    refresher = SimpleNamespace(stop=stop, tick=lambda predicate: stop.set(), _quiet=Mock())
    health = Mock()
    widget_refresh_tick(refresher, health)
    health.tick.assert_not_called()
    refresher._quiet.assert_not_called()
