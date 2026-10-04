import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('fix_protection',Path(__file__).parents[1]/'src/kodi_manager/fix_protection.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
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
if __name__=='__main__':unittest.main()
