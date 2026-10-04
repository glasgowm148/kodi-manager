import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/kodi_manager'))
import shield_exit


class ShieldExitTests(unittest.TestCase):
    def test_start_time_with_spaces_and_parentheses(self):
        stat = '123 (Kodi (worker)) ' + ' '.join(['S'] + ['0'] * 18 + ['12345', '0'])
        with patch('builtins.open', return_value=io.StringIO(stat)):
            self.assertEqual(shield_exit.process_start(123), '12345')

    def test_profile_stop_is_not_application_stop(self):
        self.assertFalse(shield_exit.shutdown_started('info <general>: Stopping services for profile change'))
        self.assertFalse(shield_exit.shutdown_started('debug <general>: Stopping the application...'))
        self.assertTrue(shield_exit.shutdown_started('2026-10-03 T:123    info <general>: Stopping the application...\n'))
        self.assertTrue(shield_exit.shutdown_started('2026-10-03 T:123    info <general>: XBMCApp: Stopping the application...\n'))

    def test_disabled_guard_never_spawns(self):
        with patch('shield_exit.subprocess.Popen') as spawn:
            guard = shield_exit.ShieldExitGuard(False, '/missing', '/script', '/result')
            guard.arm(); guard.on_abort()
            spawn.assert_not_called()

    def test_abort_does_not_reuse_earlier_log_records(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'kodi.log'
            log.write_bytes(b'info <general>: Stopping the application...\n')
            guard = shield_exit.ShieldExitGuard(True, str(log), '/script', '/result')
            with patch.object(guard, 'arm') as arm:
                guard.on_abort()
                arm.assert_not_called()

    def test_native_abort_launches_only_once_with_current_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'kodi.log'; log.write_bytes(b'startup\n')
            guard = shield_exit.ShieldExitGuard(True, str(log), '/script', '/result')
            with log.open('ab') as file: file.write(b'info <general>: Stopping the application...\n')
            with patch('shield_exit.process_start', return_value='9988'), patch('shield_exit.subprocess.Popen', return_value=Mock()) as spawn:
                guard.on_abort(); guard.arm()
                spawn.assert_called_once()
                args = spawn.call_args.args[0]
                self.assertEqual(args[2:4], [str(os.getpid()), '9988'])
                self.assertEqual(args[5], '8')
                self.assertTrue(spawn.call_args.kwargs['start_new_session'])

    def test_shutdown_marker_can_arrive_after_abort_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'kodi.log'; log.write_bytes(b'startup\n')
            guard = shield_exit.ShieldExitGuard(True, str(log), '/script', '/result')
            def publish(_):
                with log.open('ab') as file:
                    file.write(b'info <general>: Stopping the application...\n')
            with patch('shield_exit.time.sleep', side_effect=publish), patch.object(guard, 'arm') as arm:
                guard.on_abort()
                arm.assert_called_once()

    def test_arm_limits_old_history_without_reading_pre_service_records(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'kodi.log'; log.write_bytes(b'startup\n')
            guard = shield_exit.ShieldExitGuard(True, str(log), '/script', '/result')
            with log.open('ab') as file: file.write(b'session noise\n' * 20000)
            with patch('shield_exit.process_start', return_value='9988'), patch('shield_exit.subprocess.Popen', return_value=Mock()) as spawn:
                guard.arm()
                self.assertEqual(int(spawn.call_args.args[0][5]), log.stat().st_size - 65536)


if __name__ == '__main__':
    unittest.main()
