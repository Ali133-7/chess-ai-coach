import copy,json,unittest
from unittest.mock import MagicMock,patch
from contextlib import contextmanager
import chess,chess.engine
from fastapi import HTTPException
from studio import training_teacher as teacher, training_routes as routes,play_groq as play,core
from studio.teacher_v7.schema import TutorAnswer,LineNote
import test_play_groq as common

class CoachingTests(unittest.TestCase):
 setUp=common.PlayTests.setUp
 tearDown=common.PlayTests.tearDown
 post=common.PlayTests.post
 new=common.PlayTests.new
 def sample(self,ply=1):
  b=chess.Board();return {'ply':ply,'san':'e4','uci':'e2e4','grade':'best','grade_ar':'الأفضل','summary_ar':'تجربة',
    'benefits_ar':['فائدة مؤكدة'],'risks_ar':['خطر محسوب'],'scenarios':[{'id':'line-0','moves':['e2e4'],'fens':[b.fen()],'arrow':{'from':'e2','to':'e4','color':'green'}}],
    '_verified_context':{'scenarios':[{'id':'line-0'}]}}
 def moved(self):
  g=self.new();response=self.post(f"/api/play/games/{g['id']}/move",{'version':0,'uci':'e2e4'});self.assertEqual(response.status_code,200);return g['id']
 def test_coach_is_owned_cached_and_accepts_only_saved_plies(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach'
  with patch.object(routes,'analyze_move',return_value=self.sample()) as engine:
   r=self.post(url,{'ply':1});self.assertEqual(r.status_code,200,r.text);self.assertNotIn('_verified_context',r.json())
   r=self.post(url,{'ply':1});self.assertTrue(r.json()['cached']);self.assertEqual(engine.call_count,1)
   self.assertEqual(self.post(url,{'ply':1},1).status_code,404)
   self.assertEqual(self.post(url,{'ply':2}).status_code,404)
   self.assertEqual(self.post(url,{'ply':1,'fen':chess.STARTING_FEN}).status_code,422)
   self.assertEqual(self.clients[0].post(url,json={'ply':1}).status_code,403)
 def test_failed_deep_explanation_keeps_engine_teaching_and_releases_lock(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach'
  with patch.object(routes,'analyze_move',return_value=self.sample()),patch.object(routes,'generate',side_effect=routes.ProviderError('no service')):
   r=self.post(url,{'ply':1,'elaborate':True});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['benefits_ar'],['فائدة مؤكدة']);self.assertTrue(r.json()['explanation_error'])
  with core.connection() as db:
   row=db.execute('SELECT * FROM training_move_coaching WHERE game_id=?',(gid,)).fetchone();self.assertEqual(row['lock_until'],0);self.assertTrue(row['analysis_json'])
 def test_engine_failure_releases_coach_lease_and_can_retry(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach'
  with patch.object(routes,'analyze_move',side_effect=HTTPException(503,'engine busy')):
   self.assertEqual(self.post(url,{'ply':1}).status_code,503)
  with core.connection() as db:
   row=db.execute('SELECT * FROM training_move_coaching WHERE game_id=?',(gid,)).fetchone();self.assertEqual(row['lock_until'],0)
  with patch.object(routes,'analyze_move',return_value=self.sample()):self.assertEqual(self.post(url,{'ply':1}).status_code,200)
 def test_coach_concurrent_lease_avoids_duplicate_analysis(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach'
  with core.connection() as db:db.execute('INSERT INTO training_move_coaching(game_id,ply,lock_token,lock_until) VALUES(?,?,?,?)',(gid,1,'other',routes.time.time()+60))
  with patch.object(routes,'analyze_move') as engine:
   self.assertEqual(self.post(url,{'ply':1}).status_code,409);engine.assert_not_called()
 def test_migrations_are_idempotent_and_preserve_current_game(self):
  gid=self.moved();play.setup_play();play.setup_play()
  game=self.clients[0].get('/api/play/current').json()['game'];self.assertEqual(game['id'],gid);self.assertEqual(game['moves'][0]['uci'],'e2e4');self.assertEqual(game['level'],'strong')
 def test_deep_explanation_uses_only_groq_and_caches_default(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach'
  answer=TutorAnswer(title_ar='فكرة',explanation_ar='شرح',benefits_ar=['فائدة'],risks_ar=['خطر'],scenario_notes=[LineNote(scenario_id='line-0',explanation_ar='خط',focus_ar='فكرة')],learning_question_ar='لماذا؟')
  with patch.object(routes,'analyze_move',return_value=self.sample()),patch.object(routes,'generate',return_value=(answer,1,2,'groq','test-model')) as llm:
   r=self.post(url,{'ply':1,'elaborate':True});self.assertEqual(r.status_code,200,r.text)
   cfg=llm.call_args.args[0];self.assertEqual(cfg['primary'],'groq');self.assertEqual(cfg['fallback'],[])
   prompt=llm.call_args.args[1];self.assertIn('تدريب مستقلة',prompt)
   r2=self.post(url,{'ply':1,'elaborate':True});self.assertTrue(r2.json()['cached']);self.assertEqual(llm.call_count,1)
   self.assertEqual(r.json()['explanation']['board_actions'][0]['from'],'e2')
 def test_coach_limit_is_separate_and_saved_explanations_remain(self):
  gid=self.moved();url=f'/api/play/games/{gid}/coach';day=routes.datetime.now(routes.timezone.utc).date().isoformat()
  with core.connection() as db:db.execute('INSERT INTO training_coach_usage(user_id,day,analyses) VALUES(?,?,?)',(self.uids[0],day,routes.MAX_ANALYSES))
  with patch.object(routes,'analyze_move') as engine:
   self.assertEqual(self.post(url,{'ply':1}).status_code,429);engine.assert_not_called()

class EngineTeachingTests(unittest.TestCase):
 def prepare(self,before,uci,best,score_before,score_after):
  engine=MagicMock();pv=[chess.Move.from_uci(best)]
  engine.analyse.side_effect=[[{'pv':pv,'score':chess.engine.PovScore(chess.engine.Cp(score_before),chess.WHITE),'depth':16}],{'score':chess.engine.PovScore(chess.engine.Cp(score_after),chess.WHITE),'depth':15}]
  @contextmanager
  def session(skill=20):yield engine
  return patch.object(teacher,'engine_session',side_effect=session)
 def test_white_and_black_losses_use_movers_perspective(self):
  before=chess.Board()
  with self.prepare(before,'f2f3','e2e4',30,-90):
   a=teacher.analyze_move(before,chess.Move.from_uci('f2f3'),'white',1)
  self.assertEqual(a['loss_cp'],120);self.assertEqual(a['grade'],'mistake');self.assertIn('-0.90',a['evaluation_ar'])
  before.push_uci('e2e4')
  with self.prepare(before,'f7f6','c7c5',20,250):
   a=teacher.analyze_move(before,chess.Move.from_uci('f7f6'),'black',2)
  self.assertEqual(a['loss_cp'],230);self.assertIn('-2.50',a['evaluation_ar']);self.assertTrue(a['mover_is_you'])
  for sc in a['scenarios']:
   board=before.copy()
   for uci in sc['moves']:self.assertIn(chess.Move.from_uci(uci),board.legal_moves);board.push_uci(uci)
 def test_best_move_is_not_penalized_for_search_noise(self):
  before=chess.Board()
  with self.prepare(before,'e2e4','e2e4',40,0):a=teacher.analyze_move(before,chess.Move.from_uci('e2e4'),'white',1)
  self.assertEqual(a['grade'],'best');self.assertEqual(a['loss_cp'],0)
 def test_checkmate_is_displayed_as_mate_not_huge_pawn_score(self):
  b=chess.Board()
  for uci in ['f2f3','e7e5','g2g4']:b.push_uci(uci)
  engine=MagicMock();engine.analyse.return_value=[{'pv':[chess.Move.from_uci('d8h4')],'score':chess.engine.PovScore(chess.engine.Mate(-1),chess.WHITE),'depth':10}]
  @contextmanager
  def session(skill=20):yield engine
  with patch.object(teacher,'engine_session',side_effect=session):a=teacher.analyze_move(b,chess.Move.from_uci('d8h4'),'white',4)
  self.assertIsNone(a['eval_after']['cp_white']);self.assertEqual(a['eval_after']['mate_winner'],'black');self.assertIn('كش مات للخصم',a['evaluation_ar']);self.assertIsNone(a['loss_cp'])
 def test_opponent_level_is_applied_and_coaching_uses_full_skill(self):
  seen=[];engine=MagicMock();engine.play.return_value.move=chess.Move.from_uci('e2e4')
  @contextmanager
  def session(skill=20):seen.append(skill);yield engine
  with patch.object(teacher,'engine_session',side_effect=session):
   self.assertEqual(teacher.choose_stockfish_move(chess.Board(),'calm'),'e2e4');teacher.choose_stockfish_move(chess.Board(),'strong')
  self.assertEqual(seen,[3,20])

if __name__=='__main__':unittest.main()
