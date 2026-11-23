import os,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import chess
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import store,recognition,perspectives,traps,study
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play

from knowledge_fixture import public_knowledge_fixture
GOLD=public_knowledge_fixture()
class ColorTrapTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'studio.sqlite3'
  self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'knowledge.sqlite3')});self.env.start()
  import shutil
  if GOLD.exists():shutil.copyfile(GOLD,store.db_path())
  core.setup();setup_teacher();setup_play();store.setup()
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def test_common_opening_colors_and_response_names(self):
  for name in ('Sicilian Defense','French Defense','Caro-Kann Defense',"Petrov's Defense"):
   self.assertEqual(perspectives.orientation(name)['primary_side'],'black')
  for name in ('Italian Game','Ruy Lopez','London System',"Queen's Gambit"):
   self.assertEqual(perspectives.orientation(name)['primary_side'],'white')
  self.assertEqual(perspectives.orientation("Queen's Gambit Declined")['primary_side'],'both')
  self.assertEqual(perspectives.orientation('Marienbad System')['primary_side'],'both')
 def test_all_catalogue_entries_have_a_perspective(self):
  with store.connection() as db:rows=db.execute('SELECT id,name,family FROM kc_openings WHERE revision=?',(store.current_revision(db),)).fetchall()
  self.assertGreater(len(rows),3800)
  values=perspectives.decorate([dict(r) for r in rows]);self.assertEqual(len(values),len(rows))
  for r in values:self.assertIn(r['orientation']['primary_side'],('white','black','both'))
  self.assertEqual(sum(bool(r['trap_id']) for r in values),14)
 def test_every_catalogue_trap_has_a_complete_lesson(self):
  with store.connection() as db:rows=db.execute("SELECT id FROM kc_openings WHERE revision=? AND lower(name) LIKE '%trap%'",(store.current_revision(db),)).fetchall()
  self.assertEqual(len(rows),14)
  for row in rows:
   original=recognition.opening(row['id']);tid=traps.for_opening(row['id']);self.assertIsNotNone(tid)
   r=study.lesson(row['id'],lambda:self.fail('trap must not invoke engine quota'))
   self.assertEqual(r['kind'],'trap');self.assertEqual([s['uci'] for s in r['path'][:len(original['uci'])]],original['uci'])
 def test_all_trap_and_avoidance_paths_are_legal_and_color_correct(self):
  for p in traps.catalogue()['items']:
   for variant in ('trap','safe'):
    r=traps.lesson(p['id'],variant);b=chess.Board()
    for i,s in enumerate(r['path'],1):
     self.assertEqual(s['mover'],'white' if b.turn else 'black');self.assertEqual(s['move_number'],b.fullmove_number)
     m=chess.Move.from_uci(s['uci']);self.assertIn(m,b.legal_moves);self.assertEqual(s['san'],b.san(m));b.push(m);self.assertEqual(s['fen'],b.fen());self.assertEqual(set(s['legal_moves']),{m.uci() for m in b.legal_moves});self.assertTrue(s['note']['ar']['why']);self.assertTrue(s['note']['en']['watch'])
    if variant=='safe':self.assertEqual(r['path'][p['mistake_ply']-1]['trap_event'],'avoid')
   main=traps.lesson(p['id']);self.assertEqual(main['path'][p['setup_ply']-1]['mover'],p['side']);self.assertNotEqual(main['path'][p['mistake_ply']-1]['mover'],p['side']);self.assertEqual(main['path'][p['punish_ply']-1]['mover'],p['side'])
 def test_avoiding_reply_changes_only_at_the_decision(self):
  for p in traps.catalogue()['items']:
   self.assertEqual(p['moves'][:p['mistake_ply']-1],p['safe_moves'][:p['mistake_ply']-1]);self.assertNotEqual(p['moves'][p['mistake_ply']-1],p['safe_moves'][p['mistake_ply']-1])
 def test_proven_mates_and_conditional_material_examples(self):
  mates=0
  for p in traps.catalogue()['items']:
   r=traps.lesson(p['id']);b=chess.Board(r['path'][-1]['fen'])
   if p['classification']=='mate-example':self.assertTrue(b.is_checkmate());self.assertEqual(b.outcome().winner,p['side']=='white');self.assertEqual(r['path'][-1]['trap_event'],'checkmate');self.assertIn('no legal move',r['path'][-1]['note']['en']['why']);mates+=1
   elif p['classification']=='material-example':self.assertGreater(r['end']['material_white']*(1 if p['side']=='white' else -1),0)
  self.assertEqual(mates,6)
 def test_siberian_prevention_and_nonforced_traps(self):
  p=traps.lesson('8fa5437871af78783d8b16be');self.assertEqual(p['trap']['timing']['mistake_ply'],'9. h3');self.assertEqual(p['trap']['safe_san'],'Rd1');self.assertTrue(p['end']['checkmate'])
  w=traps.lesson('bcd91c83474880a27432e10d');self.assertEqual(w['trap']['classification'],'counterplay');self.assertFalse(w['end']['checkmate'])
  m=traps.lesson('41802bf766869f80ca46a0dc','safe');self.assertEqual(m['trap']['safe_san'],'Kf1');self.assertFalse(m['end']['checkmate'])
 def test_engine_evidence_pvs_replay_from_the_right_positions(self):
  for p in traps.catalogue()['items']:
   roots={};b=chess.Board()
   for i,u in enumerate(p['moves']):
    if i==p['mistake_ply']-1:roots['before_mistake']=b.copy()
    b.push_uci(u)
    if i+1==p['mistake_ply']:roots['after_mistake']=b.copy()
   roots['end']=b.copy();safe=roots['before_mistake'].copy();safe.push_san(p['safe_san']);roots['after_safe_reply']=safe
   for key,b in roots.items():
    for u in p['evidence'][key]['pv']:m=chess.Move.from_uci(u);self.assertIn(m,b.legal_moves);b.push(m)
 def test_auth_filters_and_unknown_lessons(self):
  c=TestClient(app);self.assertEqual(c.get('/api/knowledge/traps').status_code,401)
  c.post('/api/auth/register',json={'email':'traps@example.net','password':'trap-tests-password-123'})
  r=c.get('/api/knowledge/traps?side=black&limit=24');self.assertEqual(r.status_code,200,r.text);self.assertTrue(all(p['side']=='black' for p in r.json()['items']));self.assertEqual(r.json()['all_count'],19)
  self.assertEqual(c.get('/api/knowledge/traps?side=green').status_code,422);self.assertEqual(c.get('/api/knowledge/traps?limit=1000').status_code,422);self.assertEqual(c.get('/api/knowledge/traps/missing').status_code,404);self.assertEqual(c.get('/api/knowledge/traps/legal-mate?variant=wrong').status_code,422)
  r=c.get('/api/knowledge/traps/legal-mate?variant=safe');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.headers['Cache-Control'],'no-store')
 def test_results_are_not_shared_mutable_state(self):
  a=traps.lesson('legal-mate');a['path'].clear();self.assertGreater(len(traps.lesson('legal-mate')['path']),0)
