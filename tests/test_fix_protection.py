import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
# Imported as part of the package so its relative imports (write_policy) resolve when this
# file runs on its own, not only after another test put src/kodi_manager on sys.path.
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from kodi_manager import fix_protection as m  # noqa: E402
class FixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.addons=self.root/'addons';self.addon=self.addons/'plugin.test';self.addon.mkdir(parents=True)
  (self.addon/'addon.xml').write_text('<addon version="1.0"/>');self.live=self.addon/'code.py';self.live.write_text('original')
  bundle=self.root/'bundle';payload=bundle/'files/plugin.test';payload.mkdir(parents=True);(payload/'code.py').write_text('patched')
  file={'path':'plugin.test/code.py','sha256':m.digest(payload/'code.py'),'restore_from':[m.digest(self.live)]}
  (bundle/'manifest.json').write_text(json.dumps({'groups':[{'id':'test','label':'Fix','addon_id':'plugin.test','version':'1.0','files':[file]}]}))
  self.p=m.FixProtection(self.addons,self.root/'backups',bundle)
 def test_restore_verifies_and_backs_up(self):
  self.assertTrue(self.p.status()['repairable']);result=self.p.repair();self.assertEqual(self.live.read_text(),'patched');self.assertEqual((Path(result['backup'])/'plugin.test/code.py').read_text(),'original');self.assertTrue(self.p.status()['healthy'])
 def test_new_version_or_unknown_edits_never_overwritten(self):
  for version,text in [('2.0','original'),('1.0','unknown edits')]:
   (self.addon/'addon.xml').write_text('<addon version="%s"/>'%version);self.live.write_text(text);self.assertFalse(self.p.status()['repairable'])
   with self.assertRaises(ValueError):self.p.repair()
   self.assertEqual(self.live.read_text(),text)
 def test_corrupt_copy_and_traversal_fail(self):
  (self.p.bundle/'files/plugin.test/code.py').write_text('corrupted')
  with self.assertRaises(ValueError):self.p.repair()
  self.assertEqual(self.live.read_text(),'original')
  with self.assertRaises(ValueError):m.safe_path(self.addons,'../escape')
 def test_shared_file_is_repaired_once(self):
  import copy
  self.p.manifest['groups'].append(copy.deepcopy(self.p.manifest['groups'][0]))
  self.p.manifest['groups'][1]['id']='other-feature'
  result=self.p.repair()
  self.assertEqual(result['restored_files'],1)
  self.assertEqual(self.live.read_text(),'patched')
  self.assertEqual((Path(result['backup'])/'plugin.test/code.py').read_text(),'original')
  self.assertTrue(self.p.status()['healthy'])
 def test_partial_restore_rolls_back(self):
  second=dict(self.p.manifest['groups'][0]['files'][0],path='plugin.test/other.py');self.p.manifest['groups'][0]['files'].append(second)
  (self.addon/'other.py').write_text('original');(self.p.bundle/'files/plugin.test/other.py').write_text('patched')
  replace=m.os.replace;calls=[]
  def fail_second(*args):
   calls.append(args)
   if len(calls)==2:raise OSError('test disk failure')
   return replace(*args)
  with patch.object(m.os,'replace',side_effect=fail_second):
   with self.assertRaises(OSError):self.p.repair()
  self.assertEqual(self.live.read_text(),'original');self.assertEqual((self.addon/'other.py').read_text(),'original')
 def _three_files(self):
  for name in ('two.py','three.py'):
   self.p.manifest['groups'][0]['files'].append(dict(self.p.manifest['groups'][0]['files'][0],path='plugin.test/'+name))
   (self.addon/name).write_text('original');(self.p.bundle/'files/plugin.test'/name).write_text('patched')
  return [self.live,self.addon/'two.py',self.addon/'three.py']
 def test_failed_rollback_keeps_files_whole_tries_every_file_and_names_the_backup(self):
  files=self._three_files();replace=m.os.replace;copy=m.shutil.copyfile;applied=[]
  def replace_fails_third(src,dst):
   if str(src).endswith('.km-restore') and not str(dst).endswith('code.py') and len(applied)<3:
    applied.append(dst)
    if len(applied)==3:raise OSError(28,'No space left on device')
   return replace(src,dst)
  def copy_fails_for_two(src,dst):
   if 'backups' in str(src) and str(src).endswith('two.py'):
    open(dst,'wb').close();raise OSError(28,'No space left on device')
   return copy(src,dst)
  applied.append('code.py')
  with patch.object(m.os,'replace',side_effect=replace_fails_third),patch.object(m.shutil,'copyfile',side_effect=copy_fails_for_two):
   with self.assertRaises(RuntimeError) as caught:self.p.repair()
  message=str(caught.exception);backups=list((self.root/'backups').iterdir())
  self.assertIn('plugin.test/two.py could not be rolled back; restore from %s'%backups[0],message)
  self.assertEqual([f.read_text() for f in files],['original','patched','original'])
  self.assertEqual((backups[0]/'plugin.test/two.py').read_text(),'original')
  self.assertTrue((backups[0]/'manifest.json').is_file())
  self.assertEqual([p.name for p in self.addon.iterdir() if 'km-restore' in p.name],[])
 def test_failed_repair_that_changed_nothing_leaves_no_backup_folder(self):
  def fail(src,dst):
   raise OSError(28,'No space left on device')
  with patch.object(m.shutil,'copyfile',side_effect=fail):
   with self.assertRaises(OSError):self.p.repair()
  self.assertEqual(list((self.root/'backups').iterdir()),[])
  self.test_partial_restore_rolls_back()  # rolled back completely: nothing changed either
  self.assertEqual(list((self.root/'backups').iterdir()),[])
  self.assertEqual([p.name for p in self.addon.iterdir() if 'km-restore' in p.name],[])
 def test_new_addon_version_needs_review_even_when_the_fixed_files_are_in_place(self):
  self.p.repair();self.assertTrue(self.p.status()['healthy'])
  (self.addon/'addon.xml').write_text('<addon version="1.1"/>')
  status=self.p.status();group=status['groups'][0]
  self.assertEqual((group['status'],group['changed'],group['repairable'],status['healthy']),('version_changed',[],False,False))
if __name__=='__main__':unittest.main()
