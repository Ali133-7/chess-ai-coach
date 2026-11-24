import json,math,unittest
from unittest.mock import patch
import chess
from studio import core,analysis_runtime,analysis_evidence as evidence,player_diagnostics as diagnostics,telemetry
from studio.teacher_v7 import evaluation
import test_analysis_runtime as common

class ReliabilityTests(unittest.TestCase):
 setUp=common.RuntimeTests.setUp
 tearDown=common.RuntimeTests.tearDown
 game=common.RuntimeTests.game
 scan=common.RuntimeTests.scan
 def fixture(self,pgn,white='player',black='opponent',suffix='fixture',finished=1):
  with core.connection() as db:
   db.execute('UPDATE users SET chess_username=? WHERE id=?',('player',self.uids[1]))
   gid=db.execute("INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at,stage) VALUES(?,?,?,?,?,?,?,?,?,'done')",(self.uids[1],suffix,'https://example.test/unit-fixture',pgn,finished,white,black,'1-0',core.now())).lastrowid
   _,positions=core.game_moves_from_pgn(pgn)
   for ply,uci,san,before,after in positions:
    db.execute('INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade,loss_cp,eval_cp_white,phase) VALUES(?,?,?,?,?,?,?,?,?,?)',(gid,ply,san,uci,before,after,'blunder' if ply==1 else 'good',300 if ply==1 else 0,0,'opening'))
  return gid
 def test_provenance_is_stable_when_cache_reused_and_legacy_stays_unknown(self):
  b=chess.Board();first,_=analysis_runtime.shared_scan(b,10,2,lambda:self.scan(b));second,source=analysis_runtime.shared_scan(b,10,2,lambda:self.fail('duplicate'))
  self.assertEqual(source,'shared');self.assertEqual(first['analysis_meta'],second['analysis_meta']);self.assertEqual(first['analysis_meta']['requested_seconds'],10)
  self.assertFalse(evidence.summary({'eval':1,'lines':[]})['known'])
 def test_additional_search_owner_csrf_budget_and_non_destructive_result(self):
  gid=self.game()
  with core.connection() as db:
   db.execute("UPDATE games SET stage='done' WHERE id=?",(gid,));db.execute('INSERT INTO position_scans VALUES(?,?,?,?)',(gid,0,chess.STARTING_FEN,json.dumps(self.scan(chess.Board()))))
  url=f'/api/games/{gid}/positions/1/reanalyze'
  self.assertEqual(self.clients[0].post(url,json={'seconds':30},headers=self.headers[0]).status_code,404)
  self.assertEqual(self.clients[1].post(url,json={'seconds':30}).status_code,403)
  self.assertEqual(self.clients[1].post(url,json={'seconds':999},headers=self.headers[1]).status_code,422)
  result=self.clients[1].post(url,json={'seconds':30},headers=self.headers[1]);self.assertEqual(result.status_code,202,result.text);eid=result.json()['id']
  scan=evidence.metadata(self.scan(chess.Board()),30,3)
  with patch.object(analysis_runtime,'shared_scan',return_value=(scan,'shared')):self.assertTrue(evidence.job())
  self.assertEqual(self.clients[0].get('/api/analysis/experiments/'+eid).status_code,404)
  answer=self.clients[1].get('/api/analysis/experiments/'+eid).json();self.assertEqual(answer['status'],'done');self.assertTrue(answer['search']['known']);self.assertFalse(answer['original']['known'])
  with core.connection() as db:self.assertNotIn('analysis_meta',db.execute('SELECT scan_json FROM position_scans WHERE game_id=?',(gid,)).fetchone()[0])
 def test_hanging_piece_uses_legal_capture_and_no_defender(self):
  pgn='[SetUp "1"]\n[FEN "4k3/8/8/8/3r4/8/3Q4/4K3 w - - 0 1"]\n[Result "0-1"]\n\n1. Qd3 Rxd3 0-1'
  gid=self.fixture(pgn);self.assertTrue(diagnostics.update_game(gid,self.uids[1]));self.assertFalse(diagnostics.update_game(gid,self.uids[1]))
  report=diagnostics.profile(self.uids[1]);skill=next(s for s in report['skills'] if s['skill']=='hangingPiece')
  self.assertEqual(skill['errors'],1);self.assertEqual(skill['analysed_moves'],1);self.assertIn('d4d3',skill['examples'][0]['evidence']['legal_captures']);self.assertIsNone(skill['trend'])
 def test_fork_recognition_uses_actual_reply_and_black_initial_fen(self):
  pgn='[SetUp "1"]\n[FEN "k7/8/4q2r/8/8/3N4/8/K7 b - - 0 1"]\n[Result "1-0"]\n\n1... Rh5 2. Nf4 1-0'
  gid=self.fixture(pgn,white='opponent',black='player');diagnostics.update_game(gid,self.uids[1]);report=diagnostics.profile(self.uids[1]);skill=next(s for s in report['skills'] if s['skill']=='fork')
  self.assertEqual(skill['errors'],1);self.assertEqual(set(skill['examples'][0]['evidence']['fork_targets']),{'e6','h5'});self.assertEqual(report['own_game_moves'],1)
 def test_diagnostics_only_own_games_and_insufficient_data_not_a_claim(self):
  gid=self.game();self.assertEqual(self.clients[0].get(f'/api/games/{gid}/positions/1/evidence').status_code,404)
  report=self.clients[1].get('/api/training/diagnostics').json();self.assertEqual(report['games_processed'],0);self.assertTrue(all(x['error_percent'] is None for x in report['skills']))
  self.assertEqual(self.clients[1].post('/api/training/diagnostics/refresh',json={'limit':100},headers=self.headers[1]).status_code,422)
 def test_trend_uses_chronological_halves_and_real_denominators(self):
  pgn='[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 1-0'
  for i in range(10):diagnostics.update_game(self.fixture(pgn,suffix='trend-'+str(i),finished=i+1),self.uids[1])
  skill=next(x for x in diagnostics.profile(self.uids[1])['skills'] if x['skill']=='opening')
  self.assertEqual(skill['analysed_moves'],60);self.assertEqual(skill['trend']['earlier_moves'],30);self.assertEqual(skill['trend']['recent_moves'],30);self.assertEqual(skill['trend']['change_percentage_points'],0)
 def test_durable_histogram_and_privacy_admin_boundary(self):
  telemetry.flush()
  for duration in [1]*18+[100,900]:telemetry.record('http','/api/games/{gid}','200',duration)
  telemetry.flush();report=telemetry.history();row=next(x for x in report['rows'] if x['route']=='/api/games/{gid}' and x['status']=='200')
  self.assertEqual(row['n'],20);self.assertEqual(row['p95_upper_bound_ms'],100);self.assertEqual(row['mean_ms'],50.9)
  self.assertEqual(self.clients[1].get('/api/operations/metrics').status_code,403);self.assertEqual(self.clients[0].get('/api/operations/metrics').status_code,200)
  response=self.clients[0].get('/health?email=PRIVATE');self.assertRegex(response.headers['X-Request-ID'],r'^[0-9a-f]{32}$');self.assertNotIn('PRIVATE',json.dumps(telemetry.history()))
 def test_alert_thresholds_have_minimum_sample_and_no_fake_cost(self):
  for _ in range(20):telemetry.record('http','/synthetic-alert','500',25)
  report=telemetry.alerts();self.assertIn('http_error_rate',{x['code'] for x in report['alerts']})
  with patch.object(telemetry,'connect',side_effect=OSError('unavailable fixture')):
   telemetry.start();telemetry.stop()  # Optional monitoring must not stop the app.
 def test_bilingual_teacher_corpus_legal_intent_and_contradiction_detection(self):
  validation=evaluation.validate();self.assertEqual(validation['cases'],64);self.assertEqual(validation['issues'],[])
  case=next(c for c in evaluation.cases() if c['id']=='central-development-en-1')
  answer={'title_ar':'A move','explanation_ar':'This move gives check.','benefits_ar':[],'risks_ar':[],'scenario_notes':[],'learning_question_ar':''}
  self.assertFalse(evaluation.assess(case,answer)['fact_check_passed'])
  answer['explanation_ar']='The pawn occupies the center. This develops the position without forcing a win.'
  report=evaluation.compare([{'case_id':case['id'],'answer':answer,'provider':'groq','model':'fixture','input_tokens':10,'output_tokens':20}])
  self.assertTrue(report['results'][0]['fact_check_passed']);self.assertIsNone(report['summary'][0]['estimated_cost_usd'])
 def test_eval_prices_are_explicit_dated_estimates(self):
  case=evaluation.cases()[0];answer={'title_ar':'فكرة','explanation_ar':'السيطرة على المركز','benefits_ar':[],'risks_ar':[],'scenario_notes':[],'learning_question_ar':''}
  responses=[{'case_id':case['id'],'answer':answer,'provider':'groq','model':'fixture','input_tokens':1000,'output_tokens':1000}]
  prices={'groq':{'fixture':{'currency':'USD','input_per_million':1,'output_per_million':2,'as_of':'test-fixture-only'}}}
  self.assertEqual(evaluation.compare(responses,prices)['summary'][0]['estimated_cost_usd'],.003)

if __name__=='__main__':unittest.main()
