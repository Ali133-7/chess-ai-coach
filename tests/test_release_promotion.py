import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from scripts import promote_release as release
from deploy.ssh_entry import parse
from deploy.root_release import validate

class ReleaseTests(unittest.TestCase):
 def test_digest_and_commit_must_match_allowlisted_repository(self):
  image='ghcr.io/ali133-7/chess-ai-coach@sha256:'+'a'*64
  release.validate_image(image,'b'*40,'ghcr.io/ali133-7/chess-ai-coach')
  for bad in ('ghcr.io/ali133-7/chess-ai-coach:latest',image+'; echo unsafe',image.replace('ali133-7','other')):
   with self.assertRaises(ValueError):release.validate_image(bad,'b'*40,'ghcr.io/ali133-7/chess-ai-coach')
 def test_forced_ssh_entry_rejects_shell_and_arbitrary_commands(self):
  image='ghcr.io/ali133-7/chess-ai-coach@sha256:'+'a'*64
  self.assertEqual(parse('stage '+image+' '+'b'*40)[0],'stage')
  self.assertEqual(validate({'mode':'stage','image':image,'commit':'b'*40})['mode'],'stage')
  with self.assertRaises(ValueError):validate({'mode':'stage','image':image,'commit':'b'*40,'config':'/tmp/evil'})
  for command in ('bash','promote '+image+' '+'b'*40+'; id','promote "$(id)" '+'b'*40):
   with self.assertRaises(ValueError):parse(command)
 def test_compose_update_preserves_resources_environment_and_legacy_services(self):
  source=Path('compose.yaml').read_text();image='ghcr.io/ali133-7/chess-ai-coach@sha256:'+'a'*64
  result=release.render_compose(source.replace('\n','\r\n'),['studio','studio-worker','studio-sync'],image)
  self.assertEqual(result.count(image),3);self.assertIn('mem_limit: 1024m',result);self.assertIn('STUDIO_COOKIE_SECURE',Path('.env.example').read_text());self.assertIn('  coach:\n',result)
  self.assertEqual(result[result.index('  coach:'):],source[source.index('  coach:'):])
  with self.assertRaises(ValueError):release.render_compose(source,['arbitrary-shell'],image)
 def test_mfa_unsafe_downgrade_is_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db.sqlite3'
   with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE account_security(totp_ref TEXT)');db.commit()
   with patch.object(release,'run',return_value=json.dumps([{'Config':{'Labels':{}}}])):
    self.assertTrue(release.safe_rollback('old',path));self.assertFalse(release.safe_rollback('old',path,require_mfa=True))
    with closing(sqlite3.connect(path)) as db:db.execute("INSERT INTO account_security VALUES('private-ref')");db.commit()
    self.assertFalse(release.safe_rollback('old',path))
   with patch.object(release,'run',return_value=json.dumps([{'Config':{'Labels':{'org.chessstudio.account-security':'1'}}}])):self.assertTrue(release.safe_rollback('compatible',path))
 def test_candidate_uses_network_isolation_and_cloned_databases(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);databases={}
   for label in ('studio','knowledge'):
    path=root/(label+'.sqlite3')
    with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE existing(value TEXT)');db.commit()
    databases[label]=path
   with patch.object(release,'run',return_value='{"stage":"passed"}') as run:
    self.assertEqual(release.stage('candidate',databases,root)['stage'],'passed')
   args=run.call_args.args;self.assertIn('none',args);self.assertNotIn('--env-file',args);self.assertTrue((root/'candidate-data/studio.sqlite3').exists())
if __name__=='__main__':unittest.main()
