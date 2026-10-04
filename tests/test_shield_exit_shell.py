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
    def run_sequence(self, lines):
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
            subprocess.run(['/bin/sh',str(script),'999','123','%s'%log,'0',str(result)],check=True,timeout=5)
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
if __name__=='__main__':unittest.main()
