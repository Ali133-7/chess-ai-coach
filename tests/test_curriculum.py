import sys,os,json,tempfile,unittest,sqlite3,copy
from pathlib import Path
from unittest.mock import patch
import chess
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import curriculum as c,store
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play

class CurriculumTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'main.sqlite3';self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'knowledge.sqlite3')});self.env.start();core.setup();setup_teacher();setup_play();store.setup();self.client=TestClient(app)
  self.client.post('/api/auth/register',json={'email':'path@example.net','password':'path-tests-12345'});me=self.client.get('/api/me').json();self.uid=me['id'];self.csrf={'X-CSRF-Token':me['csrf']}
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def run_action(self,s,kind,**kwargs):return c.action(s['id'],self.uid,s['version'],kind,**kwargs)
 def finish(self,lid,help=False):
  s=c.start(lid,self.uid,True);s=self.run_action(s,'theory');s=self.run_action(s,'demo')
  if help:s=self.run_action(s,'hint')
  while not s['steps']['practice']:
   s=self.run_action(s,'move',uci=c.lesson(lid)['example']['moves'][s['cursor']])
  with core.connection() as db:state=json.loads(db.execute('select state_json from learning_sessions where id=?',(s['id'],)).fetchone()[0])
  return self.run_action(s,'quiz',answer=state['options'].index(0))
 def test_all_48_lessons_have_full_bilingual_content_and_legal_timelines(self):
  self.assertEqual(len(c.data()['stages']),8);self.assertEqual(len(c.data()['lessons']),48);self.assertEqual(len({x['id'] for x in c.data()['lessons']}),48)
  for x in c.data()['lessons']:
   self.assertEqual(sum(z['stage']==x['stage'] for z in c.data()['lessons']),6)
   for lang in ['ar','en']:
    self.assertGreater(len(' '.join(x['theory'][lang])),180);self.assertTrue(x['objective'][lang]);self.assertTrue(x['quiz']['question'][lang]);self.assertEqual(len(x['quiz']['options']),3)
   d=c.detail(x['id'])
   for e in [d['demo']]+d['extra_examples']:
    b=chess.Board(e['fen']);self.assertTrue(b.is_valid())
    for step in e['path']:
     m=chess.Move.from_uci(step['uci']);self.assertIn(m,b.legal_moves);self.assertEqual(step['san'],b.san(m));self.assertEqual(step['move_number'],b.fullmove_number);self.assertEqual(step['mover'],'white' if b.turn else 'black');b.push(m);self.assertEqual(step['fen'],b.fen());self.assertTrue(b.is_valid());self.assertTrue(step['note']['ar']['why']);self.assertTrue(step['note']['en']['why'])
 def test_every_lesson_can_be_completed_with_correct_server_moves(self):
  for x in c.data()['lessons']:
   result=self.finish(x['id']);self.assertTrue(result['completed'],x['id']);self.assertTrue(result['independent']);self.assertTrue(all(result['steps'].values()))
  cat=c.catalog(self.uid);self.assertEqual(cat['completed'],48);self.assertEqual(cat['independent'],48);self.assertIsNone(cat['recommended']);self.assertEqual(cat['due_count'],0)
 def test_no_solution_or_correct_answer_in_initial_session(self):
  s=c.start('fork',self.uid);self.assertNotIn('moves',s);self.assertNotIn('answer',s);self.assertFalse(s['completed']);self.assertEqual(s['hint_uci'],None);self.assertEqual(len(s['quiz_options']),3)
 def test_legal_alternative_not_auto_accepted_and_illegal_rejected(self):
  s=c.start('board-rook',self.uid);result=self.run_action(s,'move',uci='a1a2');self.assertFalse(result['correct']);self.assertEqual(result['cursor'],0);self.assertEqual(result['mistakes'],1)
  with self.assertRaises(Exception) as ctx:self.run_action(result,'move',uci='a1b2')
  self.assertEqual(ctx.exception.status_code,422)
 def test_auto_reply_is_legal_and_stops_on_learner_turn(self):
  s=c.start('board-rook',self.uid);r=self.run_action(s,'move',uci='a1a4');self.assertEqual(r['cursor'],2);self.assertEqual(len(r['animation']),2);self.assertEqual(chess.Board(r['fen']).turn,chess.WHITE);self.assertFalse(r['steps']['practice'])
 def test_only_all_four_steps_complete_progress(self):
  s=c.start('mate-one',self.uid);s=self.run_action(s,'move',uci='e1e8');self.assertTrue(s['checkmate']);self.assertFalse(s['completed']);self.assertEqual(c.catalog(self.uid)['completed'],0)
 def test_revealing_is_not_passing_and_requires_restart(self):
  s=c.start('board-rook',self.uid);r=self.run_action(s,'reveal');self.assertTrue(r['assisted']);self.assertTrue(r['revealed']);self.assertFalse(r['completed']);self.assertFalse(r['steps']['practice']);self.assertGreater(len(r['animation']),0)
  with self.assertRaises(Exception) as ctx:self.run_action(r,'move',uci='a1a4')
  self.assertEqual(ctx.exception.status_code,409)
  r=c.start('board-rook',self.uid,True);self.assertFalse(r['assisted']);self.assertFalse(r['revealed'])
 def test_hint_marks_help_and_independent_is_not_invented(self):
  r=self.finish('board-rook',help=True);self.assertTrue(r['completed']);self.assertFalse(r['independent']);self.assertEqual(c.catalog(self.uid)['independent'],0)
 def test_resume_preserves_checked_steps_and_cursor(self):
  s=c.start('board-rook',self.uid);s=self.run_action(s,'theory');s=self.run_action(s,'move',uci='a1a4');res=c.start('board-rook',self.uid);self.assertEqual(res['id'],s['id']);self.assertEqual(res['cursor'],2);self.assertTrue(res['steps']['theory'])
 def test_concurrent_version_is_rejected(self):
  s=c.start('board-rook',self.uid);self.run_action(s,'theory')
  with self.assertRaises(Exception) as ctx:self.run_action(s,'demo')
  self.assertEqual(ctx.exception.status_code,409)
 def test_users_cannot_read_or_mutate_another_session(self):
  s=c.start('board-rook',self.uid)
  with self.assertRaises(Exception) as ctx:c.action(s['id'],self.uid+999,0,'theory')
  self.assertEqual(ctx.exception.status_code,404);self.assertEqual(c.catalog(self.uid+999)['completed'],0)
 def test_review_advances_only_if_due_and_resets_with_help(self):
  self.finish('board-rook');self.finish('board-rook');p=c.catalog(self.uid)['lessons'][0]['progress'];self.assertEqual(p['review_count'],0)
  with core.connection() as db:db.execute("update learning_progress set due_at='2000-01-01T00:00:00+00:00' where user_id=?",(self.uid,))
  self.assertEqual(c.catalog(self.uid)['recommended'],'board-rook');self.finish('board-rook');p=c.catalog(self.uid)['lessons'][0]['progress'];self.assertEqual(p['review_count'],1)
  with core.connection() as db:db.execute("update learning_progress set due_at='2000-01-01T00:00:00+00:00' where user_id=?",(self.uid,))
  self.finish('board-rook',help=True);self.assertEqual(c.catalog(self.uid)['lessons'][0]['progress']['review_count'],0)
 def test_actual_stalemate_and_castling_en_passant_underpromotion_rules(self):
  self.assertTrue(c.detail('stalemate')['demo']['path'][-1]['stalemate']);self.assertFalse(c.detail('stalemate')['demo']['path'][-1]['checkmate'])
  cast=c.detail('special-rules');self.assertEqual(cast['demo']['path'][0]['uci'],'e1g1');self.assertEqual(cast['extra_examples'][0]['path'][0]['uci'],'e5d6');self.assertIn('en passant',cast['extra_examples'][0]['path'][0]['note']['en']['why'])
 def test_migration_is_additive_idempotent_and_foreign_keyed(self):
  c.setup();c.setup()
  with core.connection() as db:
   self.assertEqual(db.execute('select count(*) from users').fetchone()[0],1);self.assertEqual(len(db.execute('pragma foreign_key_list(learning_progress)').fetchall()),1)
 def test_expired_or_changed_revision_session_rejected(self):
  s=c.start('board-rook',self.uid)
  with core.connection() as db:db.execute("update learning_sessions set updated_at='2000-01-01T00:00:00+00:00' where id=?",(s['id'],))
  with self.assertRaises(Exception) as ctx:self.run_action(s,'theory')
  self.assertEqual(ctx.exception.status_code,409)
 def test_http_auth_csrf_validation_cache_and_local_only(self):
  anon=TestClient(app);self.assertEqual(anon.get('/api/learning').status_code,401)
  res=self.client.get('/api/learning');self.assertEqual(res.status_code,200);self.assertEqual(res.headers['cache-control'],'no-store');self.assertEqual(res.json()['total'],48)
  self.assertEqual(self.client.get('/api/learning/lessons/missing').status_code,404)
  r=self.client.post('/api/learning/lessons/board-rook/start',json={});self.assertEqual(r.status_code,403)
  r=self.client.post('/api/learning/lessons/board-rook/start',json={},headers=self.csrf);self.assertEqual(r.status_code,200,r.text);s=r.json()
  r=self.client.post('/api/learning/sessions/'+s['id']+'/action',json={'version':0,'kind':'unknown'},headers=self.csrf);self.assertEqual(r.status_code,422)
  self.assertEqual(self.client.get('/api/learning/lessons/board-rook').status_code,200)
 def test_detail_is_a_copy_and_does_not_damage_cache(self):
  a=c.detail('fork');a['demo']['path'].clear();self.assertGreater(len(c.detail('fork')['demo']['path']),0)
 def test_local_data_provenance_and_black_opening_practice(self):
  import csv
  puzzles={r['PuzzleId']:r for r in csv.DictReader((store.DATA/'puzzles-sample.csv').read_text(encoding='utf8').splitlines())}
  openings={}
  for file in ['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv']:
   for r in csv.DictReader((store.DATA/file).read_text(encoding='utf8').splitlines(),delimiter='\t'):openings[r['name']]=r
  for x in c.data()['lessons']:
   e=x['example'];s=e['source']
   if s['kind']=='puzzle':
    r=puzzles[s['id']];b=chess.Board(r['FEN']);line=r['Moves'].split();b.push_uci(line[0]);self.assertEqual(e['fen'],b.fen());self.assertEqual(e['moves'],line[1:]);self.assertEqual(s['rating'],int(r['Rating']))
   if s['kind']=='opening':self.assertIn(s['label'],openings)
  for lid in ['sicilian','french']:
   s=c.start(lid,self.uid);self.assertEqual(s['side'],'black');self.assertEqual(chess.Board(s['fen']).turn,chess.BLACK)

if __name__=='__main__':unittest.main()
