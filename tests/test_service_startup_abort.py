"""A Monitor registered late must not lose the service's original abort signal."""
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
from service import wait_for_shutdown  # noqa: E402


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
