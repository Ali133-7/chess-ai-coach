import io,json,os,sqlite3,tarfile,tempfile,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from cryptography.exceptions import InvalidTag
from scripts import encrypted_backup as backup

class BackupTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.key=self.root/'key';self.key.write_bytes(os.urandom(32));self.key.chmod(0o600)
  self.db=self.root/'source.sqlite3'
  with closing(sqlite3.connect(self.db)) as db:db.execute('CREATE TABLE user_data(value TEXT)');db.execute("INSERT INTO user_data VALUES('PRIVATE-USER-RECORD')");db.commit()
 def test_authenticated_roundtrip_private_files_and_source_untouched(self):
  private=self.root/'private';private.mkdir();(private/'provider').write_text('PRIVATE-API-KEY')
  out=self.root/'backup.enc';backup.create({'studio':self.db},[private],out,self.key)
  self.assertNotIn(b'PRIVATE',out.read_bytes());self.assertTrue(backup.restore(out,self.key)['verified'])
  target=self.root/'restored';backup.restore(out,self.key,target)
  with closing(sqlite3.connect(target/'databases/studio.sqlite3')) as db:self.assertEqual(db.execute('SELECT value FROM user_data').fetchone()[0],'PRIVATE-USER-RECORD')
  self.assertEqual((target/'private/0/private/provider').read_text(),'PRIVATE-API-KEY')
  with self.assertRaises(FileExistsError):backup.restore(out,self.key,self.root)
 def test_tampering_and_wrong_key_fail_before_extraction(self):
  out=self.root/'backup.enc';backup.create({'studio':self.db},[],out,self.key);raw=bytearray(out.read_bytes());raw[35]^=1;out.write_bytes(raw)
  dest=self.root/'must-not-exist'
  with self.assertRaises(InvalidTag):backup.restore(out,self.key,dest)
  self.assertFalse(dest.exists())
 def test_archive_path_traversal_is_rejected_even_with_valid_encryption(self):
  tar=self.root/'bad.tar.gz'
  with tarfile.open(tar,'w:gz') as f:
   info=tarfile.TarInfo('../escape');info.size=1;f.addfile(info,io.BytesIO(b'x'))
  out=self.root/'bad.enc';backup.encrypt(tar,out,backup.private_key(self.key))
  with self.assertRaises(ValueError):backup.restore(out,self.key)
  self.assertFalse((self.root.parent/'escape').exists())
 def test_own_key_never_included_and_existing_backups_never_overwritten(self):
  with self.assertRaises(ValueError):backup.create({'studio':self.db},[self.key],self.root/'bad.enc',self.key)
  out=self.root/'backup.enc';backup.create({'studio':self.db},[],out,self.key)
  with self.assertRaises(FileExistsError):backup.create({'studio':self.db},[],out,self.key)
 def test_offsite_arguments_are_not_shell_injection_and_final_checksum_checked(self):
  file=self.root/'safe.enc';file.write_bytes(b'encrypted fixture')
  with self.assertRaises(ValueError):backup.offsite(file,'user@host:/backup;echo bad')
  with patch.object(backup.subprocess,'run') as run,patch.object(backup.subprocess,'check_output',return_value=backup.digest(file)+'  remote\n'):
   result=backup.offsite(file,'backup@example.test:/backups')
  self.assertTrue(result['checksum_verified']);self.assertTrue(all('StrictHostKeyChecking=yes' in c.args[0] for c in run.call_args_list))
if __name__=='__main__':unittest.main()
