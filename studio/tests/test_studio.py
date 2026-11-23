"""Run inside container: python -m unittest discover -s studio/tests -v"""
import importlib,os,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient

class StudioTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  os.environ['STUDIO_DB']=str(Path(cls.tmp.name)/'unit.sqlite3')
  import studio.core as core
  import studio.app as application
  importlib.reload(core)
  importlib.reload(application)
  cls.app=application.app
  core.setup()
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def setUp(self):
  from studio.core import connection
  with connection() as db:db.execute('DELETE FROM auth_attempts')
  self.a=TestClient(self.app);self.b=TestClient(self.app)
 def register(self,client,email):
  r=client.post('/api/auth/register',json={'email':email,'password':'this-is-a-good-very-long-password'})
  self.assertEqual(r.status_code,201,r.text)
  return r.json()['csrf']
 def test_register_login_and_csrf(self):
  token=self.register(self.a,'csrf-a@example.com')
  r=self.a.put('/api/settings',json={'chess_username':'cs_user'})
  self.assertEqual(r.status_code,403)
  r=self.a.put('/api/settings',json={'chess_username':'cs_user','target_rating':1500},headers={'X-CSRF-Token':token})
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.a.get('/api/me').json()['target_rating'],1500)
 def test_user_isolation(self):
  t=self.register(self.a,'alice@example.com');self.register(self.b,'bob@example.com')
  self.a.put('/api/settings',json={'chess_username':'alice-chess'},headers={'X-CSRF-Token':t})
  self.assertEqual(self.b.get('/api/me').json()['chess_username'],None)
  self.assertEqual(self.b.get('/api/games/1').status_code,404)
 def test_admin_is_not_granted_by_register(self):
  self.register(self.a,'nobody@example.com')
  self.assertEqual(self.a.get('/api/admin/overview').status_code,403)
 def test_course_locks_until_positions_analyzed(self):
  self.register(self.a,'no-games@example.com')
  course=self.a.get('/api/course')
  self.assertEqual(course.status_code,200)
  self.assertEqual(len(course.json()['lessons']),6)
  self.assertFalse(course.json()['lessons'][0]['unlocked'])
 def test_logout_revokes_session(self):
  token=self.register(self.a,'logout@example.com')
  self.assertEqual(self.a.post('/api/auth/logout',headers={'X-CSRF-Token':token}).status_code,200)
  self.assertEqual(self.a.get('/api/me').status_code,401)
 def test_rating_grade_and_game_scope(self):
  self.register(self.a,'grades@example.com')
  self.assertEqual(self.a.get('/api/grades').status_code,200)
  self.assertEqual(self.a.get('/api/games?grade=blunder').status_code,200)
  self.assertEqual(self.a.get('/api/games?grade=private').status_code,422)
 def test_grade_scope_counts_player_not_opponent(self):
  token=self.register(self.a,'filter-grade@example.com')
  self.a.put('/api/settings',json={'chess_username':'alicechess'},headers={'X-CSRF-Token':token})
  from studio.core import connection,now
  with connection() as db:
   uid=db.execute('SELECT id FROM users WHERE email=?',('filter-grade@example.com',)).fetchone()[0]
   cur=db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,stage,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
      (uid,'x1','https://www.chess.com/game/live/012','[Result "1-0"]',1000,'alicechess','Rival','1-0','done',now()))
   gid=cur.lastrowid
   for ply,grade in ((1,'blunder'),(2,'excellent')):
    db.execute('INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade) VALUES(?,?,?,?,?,?,?)',
       (gid,ply,'e4','e2e4','start','end',grade))
  mine=self.a.get('/api/grades?scope=mine').json()['counts']
  both=self.a.get('/api/grades?scope=both').json()['counts']
  self.assertEqual(mine['blunder'],1);self.assertEqual(mine['excellent'],0)
  self.assertEqual(both['blunder'],1);self.assertEqual(both['excellent'],1)
  self.assertEqual(self.a.get('/api/games?grade=blunder&scope=mine').json()['total'],1)
  self.assertEqual(self.a.get('/api/games?grade=excellent&scope=mine').json()['total'],0)

 def test_password_change_revokes_existing_session(self):
  token=self.register(self.a,'pass-change@example.com')
  r=self.a.post('/api/password',json={'current_password':'this-is-a-good-very-long-password',
      'new_password':'another-long-good-secure-password'},headers={'X-CSRF-Token':token})
  self.assertEqual(r.status_code,200)
  self.assertEqual(self.a.get('/api/me').status_code,401)
  r=self.a.post('/api/auth/login',json={'email':'pass-change@example.com',
      'password':'another-long-good-secure-password'})
  self.assertEqual(r.status_code,200)

 def test_admin_settings_require_role_and_csrf(self):
  token=self.register(self.a,'owner-admin@example.com')
  self.assertEqual(self.a.get('/api/admin/overview').status_code,403)
  from studio.core import connection
  with connection() as db:db.execute("UPDATE users SET role='admin' WHERE email=?",('owner-admin@example.com',))
  self.assertEqual(self.a.get('/api/admin/overview').status_code,200)
  payload={'deep_seconds':75,'multipv':3,'worker_paused':True,'archive_refresh_hours':6,'max_games_per_user':1000}
  self.assertEqual(self.a.put('/api/admin/settings',json=payload).status_code,403)
  self.assertEqual(self.a.put('/api/admin/settings',json=payload,headers={'X-CSRF-Token':token}).status_code,200)
  self.assertEqual(self.a.get('/api/admin/overview').json()['config']['deep_seconds'],'75')
  with connection() as db:
   db.execute("UPDATE app_config SET value='120' WHERE key='deep_seconds'")
   db.execute("UPDATE app_config SET value='false' WHERE key='worker_paused'")

 def test_account_deletion_is_scoped(self):
  token=self.register(self.a,'to-delete@example.com')
  self.register(self.b,'keep-this@example.com')
  self.assertEqual(self.a.delete('/api/account',headers={'X-CSRF-Token':token}).status_code,200)
  self.assertEqual(self.a.get('/api/me').status_code,401)
  self.assertEqual(self.b.get('/api/me').status_code,200)

 def test_user_can_change_speed_without_admin_privileges(self):
  token=self.register(self.a,'speed-user@example.com')
  r=self.a.get('/api/analysis/speed')
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['speed']['preset'],'fast')
  self.assertEqual(r.json()['speed']['seconds'],3)
  self.assertEqual(self.a.put('/api/analysis/speed',json={'preset':'turbo'}).status_code,403)
  r=self.a.put('/api/analysis/speed',json={'preset':'turbo'},headers={'X-CSRF-Token':token})
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['speed']['seconds'],1)
  self.assertEqual(r.json()['speed']['multipv'],1)
  self.assertEqual(self.a.get('/api/analysis/speed').json()['speed']['preset'],'turbo')
  self.assertEqual(self.a.put('/api/analysis/speed',json={'preset':'unsupported'},headers={'X-CSRF-Token':token}).status_code,422)

 def test_speed_is_private_and_obeys_server_caps(self):
  token_a=self.register(self.a,'speed-a@example.com')
  self.register(self.b,'speed-b@example.com')
  from studio.core import connection,config_set,user_analysis_speed
  with connection() as db:
   config_set(db,'deep_seconds','2');config_set(db,'multipv','1')
  try:
   r=self.a.put('/api/analysis/speed',json={'preset':'deep'},headers={'X-CSRF-Token':token_a})
   self.assertEqual(r.status_code,200,r.text)
   self.assertEqual(r.json()['speed']['seconds'],2)
   self.assertEqual(r.json()['speed']['multipv'],1)
   self.assertTrue(r.json()['speed']['limited_by_admin'])
   self.assertEqual(self.b.get('/api/analysis/speed').json()['speed']['preset'],'fast')
   with connection() as db:
    aid=db.execute("SELECT id FROM users WHERE email='speed-a@example.com'").fetchone()[0]
    self.assertEqual(user_analysis_speed(db,aid)['seconds'],2)
  finally:
   with connection() as db:
    config_set(db,'deep_seconds','120');config_set(db,'multipv','3')

 def test_no_live_game_assistance(self):
  # Only completed imported PGNs can be used as analysis/training roots.
  self.register(self.a,'postgame@example.com')
  self.assertEqual(self.a.get('/api/games/991234').status_code,404)
  self.assertEqual(self.a.get('/api/games/991234/practice').status_code,404)

if __name__=='__main__':unittest.main()
