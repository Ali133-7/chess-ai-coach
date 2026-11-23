import json,os,time,unittest
from unittest.mock import patch
from pathlib import Path
import chess
from studio import core,adaptive_training as adaptive
from studio.knowledge import store,drills
from studio.teacher_v7 import grounding
from studio.teacher_v7.schema import TutorAnswer
from studio.teacher_v7.providers import ProviderError
import test_control_center as common

class AdaptiveTests(unittest.TestCase):
 def setUp(self):
  common.ControlTests.setUp(self)
  self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.temp.name)/'knowledge.sqlite3')});self.env.start();self.addCleanup(self.env.stop);store.setup()
  b=chess.Board();b.push_uci('e2e4')
  with store.connection() as db:
   for i in range(3):db.execute('INSERT INTO kc_puzzles VALUES(?,?,?,?,?,?,?,?,?)',('fixture-'+str(i),chess.STARTING_FEN,b.fen(),json.dumps(['e2e4','e7e5','g1f3','b8c6']),1000,'opening','','','synthetic-unit-fixture'))
 tearDown=common.ControlTests.tearDown
 def solve(self,pid='fixture-0'):
  s=drills.start(pid,self.uids[1]);s=drills.move(s['id'],self.uids[1],'e7e5',s['version']);return drills.move(s['id'],self.uids[1],'b8c6',s['version'])
 def test_completion_is_once_and_new_recommendations_never_repeat(self):
  s=self.solve();plan=adaptive.recommendation(self.uids[1]);self.assertNotIn('fixture-0',[x['id'] for x in plan['new']]);self.assertEqual(plan['weaknesses'][0]['attempts'],1);self.assertAlmostEqual(plan['weaknesses'][0]['mastery'],3/5)
  with core.connection() as db:
   row=dict(db.execute('SELECT * FROM knowledge_puzzle_sessions WHERE id=?',(s['id'],)).fetchone());adaptive.record(db,self.uids[1],drills.puzzle('fixture-0'),row,'solved')
  self.assertEqual(adaptive.evidence(self.uids[1])[0]['attempts'],1)
 def test_reveal_is_not_independent_success_and_review_is_opt_in(self):
  s=drills.start('fixture-0',self.uids[1]);drills.move(s['id'],self.uids[1],'',s['version'],True)
  self.assertAlmostEqual(adaptive.evidence(self.uids[1])[0]['mastery'],2/5)
  with core.connection() as db:db.execute('UPDATE adaptive_reviews SET due_at=0 WHERE user_id=?',(self.uids[1],))
  plan=adaptive.recommendation(self.uids[1]);self.assertEqual(plan['due_reviews'][0]['puzzle_id'],'fixture-0');self.assertNotIn('fixture-0',[x['id'] for x in plan['new']])
 def test_early_replay_neither_inflates_mastery_nor_advances_interval(self):
  self.solve();self.solve()
  self.assertEqual(adaptive.evidence(self.uids[1])[0]['attempts'],1)
  with core.connection() as db:self.assertEqual(db.execute('SELECT streak FROM adaptive_reviews').fetchone()[0],0)
 def test_due_success_advances_interval_and_accounts_stay_isolated(self):
  self.solve()
  with core.connection() as db:db.execute('UPDATE adaptive_reviews SET due_at=0')
  self.solve();self.assertEqual(adaptive.recommendation(self.uids[0])['weaknesses'],[])
  with core.connection() as db:
   row=db.execute('SELECT * FROM adaptive_reviews').fetchone();self.assertEqual(row['streak'],1);self.assertGreater(row['due_at'],time.time()+2*86400)
 def test_schema_migration_preserves_completed_sessions(self):
  self.solve();core.setup();core.setup();self.assertEqual(adaptive.evidence(self.uids[1])[0]['attempts'],1)
 def test_local_knowledge_and_fact_audit_are_explicit(self):
  context=grounding.enrich({'fen':chess.STARTING_FEN,'actual_move':{'uci':'e2e4'}},'Explain a rook and the board files')
  self.assertTrue(context['knowledge']['documents']);self.assertFalse(context['verified_move_facts']['checkmate'])
  def answer(text):return TutorAnswer(title_ar='test',explanation_ar=text,benefits_ar=[],risks_ar=[],scenario_notes=[],learning_question_ar='')
  with self.assertRaises(ProviderError):grounding.audit(answer('This move delivers checkmate'),context)
  result=grounding.audit(answer('Develop pieces and compare legal alternatives.'),context);self.assertFalse(result['grounding']['prose_formally_verified']);self.assertTrue(result['sources'])
 def test_general_question_has_no_inherited_board_facts(self):
  c=grounding.enrich({'scenarios':[]},'How does a rook move?');self.assertNotIn('verified_move_facts',c);self.assertNotIn('fen',c)

if __name__=='__main__':unittest.main()
