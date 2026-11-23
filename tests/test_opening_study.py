import os,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
import chess
from studio.knowledge import study,store,recognition
from studio import core
GOLD=Path(os.environ.get('CHESS_TEST_KNOWLEDGE_GOLD',str(Path(__file__).resolve().parent.parent/'knowledge-dev/knowledge.sqlite3')))
class StudyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'studio.sqlite3';core.setup();self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'knowledge.sqlite3')});self.env.start();shutil.copyfile(GOLD,store.db_path());store.setup()
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def test_all_source_lines_replay_and_have_bilingual_facts(self):
  with store.connection() as db:rows=db.execute('SELECT uci_json,plies FROM kc_openings WHERE revision=?',(store.current_revision(db),)).fetchall()
  self.assertGreater(len(rows),3800)
  for row in rows:
   steps=study.materialize(json.loads(row[0]),row[1]);self.assertEqual(len(steps),row[1])
   for step in steps:
    b=chess.Board(step['fen']);self.assertTrue(b.is_valid());self.assertEqual(set(step['legal_moves']),{m.uci() for m in b.legal_moves});self.assertTrue(step['note']['ar']['why']);self.assertTrue(step['note']['en']['watch'])
 def test_main_branch_expands_definition_and_preserves_prefix(self):
  o=next(x for x in recognition.search('Italian Game',100)['items'] if x['name']=='Italian Game')
  with patch.object(study,'engine_session') as mocked:
   mocked.return_value.__enter__.return_value.analyse.return_value={'pv':[]}
   r=study.lesson(o['id'],lambda:None)
  self.assertGreater(len(r['path']),10);self.assertEqual([x['uci'] for x in r['path'][:len(recognition.opening(o['id'])['uci'])]],recognition.opening(o['id'])['uci']);self.assertIn('Pianissimo',r['branch']);self.assertTrue(all(x['source']=='catalogue' for x in r['path'][:r['catalogue_plies']]))
 def test_engine_extension_is_labelled_cached_and_legal(self):
  o=recognition.search('London System',100)['items'][0];calls=[]
  class Engine:
   def analyse(self,board,limit):
    b=board.copy();pv=[]
    for _ in range(25):
     if b.is_game_over(claim_draw=True):break
     m=next(iter(b.legal_moves));pv.append(m);b.push(m)
    return {'pv':pv}
  @contextmanager
  def engine(*args):yield Engine()
  with patch.object(study,'engine_session',engine):r=study.lesson(o['id'],lambda:calls.append(1))
  self.assertEqual(len(calls),1);self.assertTrue(r['engine_added']);self.assertTrue(any(x['source']=='engine' for x in r['path']));study.materialize([x['uci'] for x in r['path']],r['catalogue_plies'])
  with patch.object(study,'engine_session',side_effect=AssertionError('not cached')):again=study.lesson(o['id'],lambda:self.fail('quota on cache hit'))
  self.assertEqual(r['path'],again['path'])
 def test_branch_selection_does_not_change_opening_identity(self):
  o=next(x for x in recognition.search('Italian Game',100)['items'] if x['name']=='Italian Game');
  with patch.object(study,'engine_session') as mocked:
   mocked.return_value.__enter__.return_value.analyse.return_value={'pv':[]}
   r=study.lesson(o['id'],lambda:None)
  other=next(x for x in r['branches'] if x['id']!=r['branch_id'] and x['plies']>=24);s=study.lesson(o['id'],lambda:None,other['id']);self.assertEqual(s['id'],o['id']);self.assertEqual(s['branch_id'],other['id'])
 def test_special_move_facts(self):
  b=chess.Board('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1');self.assertIn('Castles',study.explain(b,chess.Move.from_uci('e1g1'))['en']['why'])
  b=chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1');self.assertIn('en passant',study.explain(b,chess.Move.from_uci('e5d6'))['en']['why'])
 def test_invalid_legal_line_rejected(self):
  with self.assertRaises(ValueError):study.materialize(['e2e5'],1)

 def test_engine_busy_keeps_catalogue_available_without_caching_failure(self):
  from fastapi import HTTPException
  o=recognition.search('London System',100)['items'][0]
  with patch.object(study,'engine_session',side_effect=HTTPException(503,'busy')):r=study.lesson(o['id'],lambda:None)
  self.assertEqual(r['continuation_pending'],'engine_busy');self.assertTrue(r['path']);self.assertFalse(r['engine_added'])
  with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM kc_meta WHERE key LIKE ?',('study-v2:'+recognition.opening(o['id'])['revision']+':'+o['id']+':%',)).fetchone()[0],0)
 def test_study_endpoint_auth_csrf_and_legacy_definition(self):
  from fastapi.testclient import TestClient
  from studio.app import app
  from studio.teacher_v7.router import setup_teacher
  from studio.play_groq import setup_play
  setup_teacher();setup_play();c=TestClient(app)
  o=next(x for x in recognition.search('Italian Game',100)['items'] if x['name']=='Italian Game');url='/api/knowledge/openings/'+o['id']+'/study'
  self.assertEqual(c.post(url,json={}).status_code,401)
  self.assertEqual(c.post('/api/auth/register',json={'email':'study@example.net','password':'study-test-password-123'}).status_code,201)
  self.assertEqual(c.post(url,json={}).status_code,403)
  headers={'X-CSRF-Token':c.get('/api/me').json()['csrf']}
  with patch.object(study,'engine_session') as mocked:
   mocked.return_value.__enter__.return_value.analyse.return_value={'pv':[]}
   r=c.post(url,json={},headers=headers)
  self.assertEqual(r.status_code,200,r.text);self.assertGreater(len(r.json()['path']),5)
  original=c.get('/api/knowledge/openings/'+o['id']).json();self.assertEqual(len(original['path']),o['plies']);self.assertGreater(len(r.json()['path']),len(original['path']))
