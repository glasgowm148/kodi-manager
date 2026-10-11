"""Exercise the actual shell state machine with safe proc/toybox/clock fixtures.

The fake toybox never signals anything: ``kill -KILL`` is replaced by touching a
marker file, ``/proc/self/stat`` by a file naming a fake parent, and
``/proc/uptime`` by a file whose clock each ``usleep`` advances by ``step``
seconds, so a minute of a stalled exit replays in a fraction of a second.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'src/kodi_manager/shield_exit_guard.sh'

FAKE_TOYBOX = r'''import json,os,sys,time
STATE=%r
cmd=sys.argv[1]
if cmd=='stat': print(os.path.getsize(sys.argv[-1]))
elif cmd=='dd':
 args=dict(x.split('=',1) for x in sys.argv[2:]);f=open(args['if'],'rb');f.seek(int(args['skip']));sys.stdout.buffer.write(f.read(int(args['count'])))
elif cmd=='usleep':
 time.sleep(.001)
 with open(STATE) as h: s=json.load(h)
 s['polls']+=1;s['clock']+=s['step']
 with open(s['uptime'],'w') as h: h.write('%%.2f 0.00\n'%%s['clock'])
 if s['polls']==s['reparent_after']:
  with open(s['proc'],'w') as h: h.write('1 (guard) S 1 0 0\n')
 more=s['append'].get(str(s['polls']))
 if more:
  with open(s['log'],'a') as h: h.write(''.join(x+'\n' for x in more))
 with open(STATE,'w') as h: json.dump(s,h)
'''


def kodi_lines(lines):
    return ['2026-10-03 T:10    info <general>: ' + x for x in lines]


@unittest.skipUnless(os.name == "posix", "Android shell simulation needs POSIX")
class ExitSequenceTests(unittest.TestCase):
    def run_sequence(self, lines, extra=(), trace=None, step=0.0, polls=2, append=None,
                     reparent_after=-1, clock=True, raw=False, timeout=20, raw_trace=None):
        """Run the watcher over ``lines``; return (signalled, result json or None).

        ``polls`` replaces the 1500-poll watch limit (None keeps it), ``append``
        maps a poll number to log lines written at that poll and
        ``reparent_after`` makes Kodi exit on its own after that many polls.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stat = root / 'proc'; stat.write_text('1 (guard) S 999 0 0\n')
            uptime = root / 'uptime'; uptime.write_text('5000.25 100.00\n')
            log = root / 'kodi.log'
            log.write_text(''.join(x + '\n' for x in (lines if raw else kodi_lines(lines))))
            result = root / 'result.json'; marker = root / 'signalled'
            state = root / 'state.json'
            state.write_text(json.dumps({
                'polls': 0, 'clock': 5000.25, 'step': step, 'uptime': str(uptime), 'proc': str(stat),
                'log': str(log), 'reparent_after': reparent_after,
                'append': {str(k): (v if raw else kodi_lines(v)) for k, v in (append or {}).items()}}))
            toybox = root / 'toybox'
            toybox.write_text('#!' + sys.executable + '\n' + FAKE_TOYBOX % str(state)); toybox.chmod(0o700)
            text = (SCRIPT.read_text().replace('/proc/self/stat', str(stat))
                    .replace('/proc/uptime', str(uptime) if clock else str(root / 'missing'))
                    .replace('/system/bin/toybox', str(toybox))
                    .replace('kill -KILL "$pid"', 'touch ' + str(marker)))
            if polls is not None:
                text = text.replace('"$i" -lt 1500', '"$i" -lt %d' % polls)
            script = root / 'guard.sh'; script.write_text(text)
            with open(root / 'trace', 'wb') as stderr:
                subprocess.run(['/bin/sh', str(script), '999', '123', '%s' % log, '0', str(result)] + list(extra),
                               check=True, timeout=timeout, stderr=stderr)
            if trace is not None:
                trace.extend(x.split(' ', 1)[1] for x in (root / 'trace').read_text().splitlines())
            if raw_trace is not None:
                raw_trace.extend((root / 'trace').read_text().splitlines())
            return marker.exists(), json.loads(result.read_text()) if result.exists() else None

    def test_saved_stopped_skin_cleanup_exits_before_driver_teardown(self):
        done, result = self.run_sequence(['Stopping the application...', 'Saving skin settings', 'Application stopped', 'Unloaded skin'])
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_services_skin_cleanup_completed')

    def test_profile_switch_or_incomplete_save_never_signals(self):
        for lines in [['Stopping services for profile change', 'Unloaded skin'],
                      ['Stopping the application...', 'Application stopped', 'Unloaded skin'],
                      ['Stopping the application...', 'Saving skin settings', 'Unloaded skin']]:
            self.assertEqual(self.run_sequence(lines), (False, None))

    def test_old_unload_marker_remains_a_fallback(self):
        done, result = self.run_sequence(['Stopping the application...', 'Saving skin settings', 'Application stopped', 'unload sections'])
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_window_cleanup_completed')

    # The 2026-10-11 hang: quit with a paused video; Kodi saved its settings, logged
    # "Stopping all" and then never reached "Application stopped".
    HANG = ['XBMCApp: Stopping the application...', 'Stopping the application...', 'Stopping player',
            'Storing total System Uptime', 'Saving settings', 'Saving skin settings', 'Stopping all',
            '>> Example <<: SyncMonitor Service Update - Success']

    def test_exit_stalled_after_stopping_all_is_ended(self):
        trace = []
        done, result = self.run_sequence(self.HANG, ['5'], trace)
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_stopping_all_stalled')
        self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all', 'stalled polls 0s'])

    def test_stall_after_application_stopped_is_ended_too(self):
        done, result = self.run_sequence(['Stopping the application...', 'Saving skin settings', 'Stopping all', 'Application stopped'], ['5'])
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_application_stopped_stalled')

    def test_stopping_all_without_saved_settings_never_signals(self):
        for lines in [['Stopping all'], ['Saving skin settings', 'Stopping all'], ['Stopping the application...', 'Stopping all'],
                      ['Stopping all', 'Stopping the application...', 'Saving skin settings'],
                      ['Stopping services for profile change', 'Saving skin settings', 'Stopping all']]:
            trace = []
            self.assertEqual(self.run_sequence(lines, ['3'], trace), (False, None), lines)
            self.assertEqual(trace[-1], 'gave_up')

    def test_normal_exit_still_ends_at_skin_unload_before_the_stall_limit(self):
        trace = []
        done, result = self.run_sequence(['Stopping the application...', 'Saving skin settings', 'Stopping all', 'Application stopped', 'Unloaded skin'], ['1000'], trace)
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_services_skin_cleanup_completed')
        self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all', 'stopped'])

    def test_invalid_stall_limits_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            for extra in (['5;x'], ['5', '6;x'], ['5', '0']):
                done = subprocess.run(['/bin/sh', str(SCRIPT), '999', '123', '/missing', '0', temp + '/r'] + extra, timeout=5)
                self.assertEqual(done.returncode, 1, extra)

    # kodi.log of the second 2026-10-11 hang (Kodi 22.0 RC1, 0.7.9), verbatim from
    # "Stopping the application" on. The watcher was launched on System.OnQuit,
    # whose "armed on quit" line Kodi writes after "Stopping all"; no abort reached
    # the Python services and nothing more was logged for minutes.
    HANG_2 = ['2026-10-11 17:45:57.462 T:10615    info <general>: XBMCApp: Stopping the application...',
              '2026-10-11 17:45:57.503 T:10616    info <general>: Stopping the application...',
              '2026-10-11 17:45:57.503 T:10616    info <general>: Stopping player',
              '2026-10-11 17:45:57.504 T:10616    info <general>: Storing total System Uptime',
              '2026-10-11 17:45:57.504 T:10616    info <general>: Saving settings',
              '2026-10-11 17:45:57.515 T:10616    info <general>: Saving skin settings',
              '2026-10-11 17:45:57.524 T:10616    info <general>: Stopping all']
    ARMED_ON_QUIT = ['2026-10-11 17:45:57.564 T:10661    info <general>: [Kodi Manager] Shield exit guard armed on quit']

    def test_hang_2_is_ended_60_s_after_stopping_all_on_the_clock(self):
        # Production limits (3000 polls, 60 s) with polls of one second each:
        # the stall must end on the clock, after more than 60 s, not after 3000 polls.
        trace = []
        done, result = self.run_sequence(self.HANG_2, (), trace, step=1.0, polls=None, raw=True,
                                         append={1: self.ARMED_ON_QUIT})
        self.assertTrue(done); self.assertEqual(result, {'result': 'saved_stopping_all_stalled', 'pid': 999, 'start_tick': '123'})
        self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all', 'stalled clock 61s'])

    def test_hang_2_is_not_ended_before_60_s(self):
        # The same hang, but Kodi finishes on its own 55 s after "Stopping all".
        trace = []
        done, result = self.run_sequence(self.HANG_2, (), trace, step=1.0, polls=None, raw=True,
                                         append={1: self.ARMED_ON_QUIT}, reparent_after=55)
        self.assertEqual((done, result), (False, None))
        self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all'])

    def test_hang_2_without_a_clock_still_ends_on_the_poll_limit(self):
        trace = []
        done, result = self.run_sequence(self.HANG_2, ['4'], trace, step=1.0, polls=None, raw=True, clock=False)
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_stopping_all_stalled')
        self.assertEqual(trace[0], 'armed clock=none'); self.assertEqual(trace[-1], 'stalled polls ?s')

    # The clean 16:39 exit the same day: "armed on quit" arrives after "Stopping all",
    # "Application stopped" follows and Kodi exits by itself about three seconds later.
    CLEAN = HANG_2 + ['2026-10-11 16:39:12.001 T:10616    info <general>: ES: Stopping event server',
                      '2026-10-11 16:39:12.040 T:10661    info <general>: [Kodi Manager] Shield exit guard armed on quit',
                      '2026-10-11 16:39:12.420 T:10670    info <general>: ES: UDP Event server stopped',
                      '2026-10-11 16:39:13.330 T:10655    info <general>: script.bingie.widgets --> Backgroundservice stopped',
                      '2026-10-11 16:39:14.520 T:10661    info <general>: [Kodi Manager] Shield exit guard armed=True',
                      '2026-10-11 16:39:15.430 T:10616    info <general>: Application stopped']

    def test_clean_exit_is_never_signalled_as_a_stall(self):
        trace = []
        done, result = self.run_sequence(self.CLEAN[:7], (), trace, step=0.5, polls=None, raw=True,
                                         append={1: self.CLEAN[7:9], 3: self.CLEAN[9:12], 6: self.CLEAN[12:]},
                                         reparent_after=8)
        self.assertEqual((done, result), (False, None))
        self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all', 'stopped'])

    def test_clean_exit_reaching_skin_unload_ends_there(self):
        done, result = self.run_sequence(self.CLEAN, (), step=0.5, polls=None, raw=True,
                                         append={2: ['2026-10-11 16:39:15.600 T:10616    info <general>: Unloaded skin']})
        self.assertTrue(done); self.assertEqual(result['result'], 'saved_services_skin_cleanup_completed')

    def test_quit_announced_but_kodi_keeps_running_exits_without_signalling(self):
        # OnQuit announced, then no "Stopping all" while Kodi runs on for five
        # minutes: the watcher stops after 120 s, long before 1500 polls.
        trace = []
        done, result = self.run_sequence(['[Kodi Manager] Shield exit guard armed on quit'], (), step=10.0, polls=None,
                                         append={3: ['VideoPlayer::OpenFile: /storage/video.mkv'], 30: ['Stopping all']},
                                         raw_trace=trace)
        self.assertEqual((done, result), (False, None))
        self.assertEqual(trace, ['0 armed clock=uptime', '12 gave_up'])

    def test_playback_after_the_quit_sequence_is_never_signalled(self):
        for later in (['VideoPlayer::OpenFile: /storage/video.mkv'], ['Creating InputStream']):
            trace = []
            done, result = self.run_sequence(['Stopping the application...', 'Saving skin settings', 'Stopping all'] + later,
                                             ['5'], trace, step=10.0, polls=None)
            self.assertEqual((done, result), (False, None), later)
            self.assertEqual(trace, ['armed clock=uptime', 'started', 'saved', 'stopping_all', 'playback', 'gave_up'])


if __name__ == '__main__':
    unittest.main()
