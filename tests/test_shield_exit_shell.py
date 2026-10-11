import os
"""Exercise the actual shell state machine with safe proc/toybox fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).parents[1]/'src/kodi_manager/shield_exit_guard.sh'
@unittest.skipUnless(os.name == "posix", "Android shell simulation needs POSIX")
class ExitSequenceTests(unittest.TestCase):
    def run_sequence(self, lines, extra=(), trace=None):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);stat=root/'proc';stat.write_text('1 (guard) S 999 0 0\n')
            log=root/'kodi.log';log.write_text('\n'.join('2026-10-03 T:10    info <general>: '+x for x in lines)+'\n')
            result=root/'result.json';marker=root/'signalled'
            toybox=root/'toybox';toybox.write_text('#!'+sys.executable+'\n'+'''import os,sys,time
cmd=sys.argv[1]
if cmd=='stat': print(os.path.getsize(sys.argv[-1]))
elif cmd=='dd':
 args=dict(x.split('=',1) for x in sys.argv[2:]);f=open(args['if'],'rb');f.seek(int(args['skip']));sys.stdout.buffer.write(f.read(int(args['count'])))
elif cmd=='usleep': time.sleep(.001)
''');toybox.chmod(0o700)
            script=root/'guard.sh';script.write_text(SCRIPT.read_text().replace('/proc/self/stat',str(stat)).replace('/system/bin/toybox',str(toybox)).replace('kill -KILL "$pid"', 'touch '+str(marker)).replace('"$i" -lt 1500','"$i" -lt 2'))
            with open(root/'trace','wb') as stderr:
                subprocess.run(['/bin/sh',str(script),'999','123','%s'%log,'0',str(result)]+list(extra),check=True,timeout=10,stderr=stderr)
            if trace is not None:
                trace.extend(x.split(' ',1)[1] for x in (root/'trace').read_text().splitlines())
            return marker.exists(), json.loads(result.read_text()) if result.exists() else None
    def test_saved_stopped_skin_cleanup_exits_before_driver_teardown(self):
        done,result=self.run_sequence(['Stopping the application...','Saving skin settings','Application stopped','Unloaded skin'])
        self.assertTrue(done);self.assertEqual(result['result'],'saved_services_skin_cleanup_completed')
    def test_profile_switch_or_incomplete_save_never_signals(self):
        for lines in [['Stopping services for profile change','Unloaded skin'],['Stopping the application...','Application stopped','Unloaded skin'],['Stopping the application...','Saving skin settings','Unloaded skin']]:
            self.assertEqual(self.run_sequence(lines),(False,None))
    def test_old_unload_marker_remains_a_fallback(self):
        done,result=self.run_sequence(['Stopping the application...','Saving skin settings','Application stopped','unload sections'])
        self.assertTrue(done);self.assertEqual(result['result'],'saved_window_cleanup_completed')
    # The 2026-10-11 hang: quit with a paused video; Kodi saved its settings, logged
    # "Stopping all" and then never reached "Application stopped".
    HANG=['XBMCApp: Stopping the application...','Stopping the application...','Stopping player',
          'Storing total System Uptime','Saving settings','Saving skin settings','Stopping all',
          '>> Example <<: SyncMonitor Service Update - Success']
    def test_exit_stalled_after_stopping_all_is_ended(self):
        trace=[]
        done,result=self.run_sequence(self.HANG,['5'],trace)
        self.assertTrue(done);self.assertEqual(result['result'],'saved_stopping_all_stalled')
        self.assertEqual(trace,['armed','started','saved','stopping_all','stalled'])
    def test_stall_after_application_stopped_is_ended_too(self):
        done,result=self.run_sequence(['Stopping the application...','Saving skin settings','Stopping all','Application stopped'],['5'])
        self.assertTrue(done);self.assertEqual(result['result'],'saved_application_stopped_stalled')
    def test_stopping_all_without_saved_settings_never_signals(self):
        for lines in [['Stopping all'],['Saving skin settings','Stopping all'],['Stopping the application...','Stopping all'],
                      ['Stopping all','Stopping the application...','Saving skin settings'],
                      ['Stopping services for profile change','Saving skin settings','Stopping all']]:
            trace=[]
            self.assertEqual(self.run_sequence(lines,['3'],trace),(False,None),lines)
            self.assertEqual(trace[-1],'gave_up')
    def test_normal_exit_still_ends_at_skin_unload_before_the_stall_limit(self):
        trace=[]
        done,result=self.run_sequence(['Stopping the application...','Saving skin settings','Stopping all','Application stopped','Unloaded skin'],['1000'],trace)
        self.assertTrue(done);self.assertEqual(result['result'],'saved_services_skin_cleanup_completed')
        self.assertEqual(trace,['armed','started','saved','stopping_all','stopped'])
    def test_invalid_stall_limit_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            done=subprocess.run(['/bin/sh',str(SCRIPT),'999','123','/missing','0',temp+'/r','5;x'],timeout=5)
            self.assertEqual(done.returncode,1)
if __name__=='__main__':unittest.main()
