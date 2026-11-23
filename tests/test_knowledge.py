import csv,io,json,os,shutil,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import chess,chess.engine,httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException
from studio import core
from studio.app import app
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play
from studio.knowledge import store,recognition,importer,external,analysis,drills,router
from studio.teacher_v7 import dialogue
from studio.teacher_v7.schema import TutorAnswer

GOLD=Path(os.getenv('CHESS_TEST_KNOWLEDGE_GOLD',str(Path(__file__).resolve().parent.parent/'knowledge-dev/knowledge.sqlite3')))
class KnowledgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'studio.sqlite3'
  self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'knowledge.sqlite3')});self.env.start()
  if GOLD.exists():shutil.copyfile(GOLD,store.db_path())
  core.setup();setup_teacher();setup_play();store.setup()
  if not GOLD.exists():importer.seed()
  self.clients=[TestClient(app),TestClient(app)];self.h=[];self.ids=[]
  for i,c in enumerate(self.clients):
   r=c.post('/api/auth/register',json={'email':f'knowledge{i}@example.net','password':'test-knowledge-password-123'});self.assertEqual(r.status_code,201,r.text)
   me=c.get('/api/me').json();self.h.append({'X-CSRF-Token':me['csrf']});self.ids.append(me['id'])
  with core.connection() as db:
   db.execute('UPDATE users SET chess_username=? WHERE id=?',('learner',self.ids[0]))
   self.gid=db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,stage,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(self.ids[0],'known-game','https://example.net/1','1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0',12345,'learner','other','1-0','done',core.now())).lastrowid
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def post(self,path,body,who=0):return self.clients[who].post(path,json=body,headers=self.h[who])

 def test_recommendation_uses_same_weakness_without_full_profile(self):
  from studio.knowledge import analysis
  report=analysis.report_game(self.gid,self.ids[0]);report['errors']=[{'tags':['hangingPiece']}];report['phases']={'opening':{'errors':2},'endgame':{'errors':8}}
  with core.connection() as db:db.execute('UPDATE knowledge_game_reports SET report_json=? WHERE game_id=?',(json.dumps(report),self.gid))
  with patch.object(analysis,'profile',side_effect=AssertionError('Do not build full profile for a puzzle')):
   result=self.clients[0].get('/api/knowledge/recommendations');self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['recommended_theme'],'hangingPiece')
   other=self.clients[1].get('/api/knowledge/recommendations');self.assertEqual(other.status_code,200);self.assertEqual(other.json()['recommended_theme'],'')
  report['errors']=[]
  with core.connection() as db:db.execute('UPDATE knowledge_game_reports SET report_json=? WHERE game_id=?',(json.dumps(report),self.gid))
  self.assertEqual(analysis.recommendation_basis(self.ids[0])['theme'],'endgame')
 def test_indexed_personal_position_stats_keep_results_and_owner_scope(self):
  board=chess.Board();board.push_uci('e2e4')
  with core.connection() as db:db.execute('INSERT INTO moves(game_id,ply,uci,san,fen_before,fen_after,grade) VALUES(?,?,?,?,?,?,?)',(self.gid,1,'e2e4','e4',chess.STARTING_FEN,board.fen(),'good'))
  key=recognition.position_key(chess.Board());mine=analysis.local_position_stats(key,self.ids[0]);other=analysis.local_position_stats(key,self.ids[1])
  self.assertEqual(mine['sample_size'],1);self.assertEqual(mine['white_wins'],1);self.assertEqual(mine['most_popular_uci'],'e2e4');self.assertEqual(other['sample_size'],0)

 def test_real_catalogue_and_source_integrity(self):
  s=self.clients[0].get('/api/knowledge/status').json();self.assertEqual(s['counts']['openings'],3865);self.assertEqual(s['counts']['kc_puzzles'],5000)
  before=s['counts']['opening_steps'];r=importer.import_file('a.tsv',7);self.assertEqual(r['status'],'complete');self.assertEqual(router.status()['counts']['opening_steps'],before)
  for f in ['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv']:
   self.assertTrue(any(j['filename']==f and j['rejected']==0 for j in s['imports']))
 def test_resumable_import_does_not_duplicate_records(self):
  with store.connection() as db:db.execute("DELETE FROM kc_imports WHERE filename='a.tsv'")
  a=importer.import_file('a.tsv',7);b=importer.import_file('a.tsv',7)
  self.assertEqual((a['cursor'],b['cursor']),(7,14));self.assertEqual(importer.import_file('a.tsv',2000)['status'],'complete');self.assertEqual(router.status()['counts']['openings'],3865)
 def test_transposition_and_explicit_match_formula(self):
  _,moves,boards,_=recognition.parse_pgn('1. d4 d5 2. c4 *');key=recognition.position_key(boards[-1])
  with store.connection() as db:oid=db.execute('SELECT id FROM kc_openings WHERE revision=? AND terminal_key=? ORDER BY plies LIMIT 1',(store.current_revision(db),key)).fetchone()[0]
  _,moves,boards,_=recognition.parse_pgn('1. c4 d5 2. d4 *');r=recognition.classify(boards,moves,'white',only_ids=[oid]);c=r['candidates'][0]
  self.assertIsNone(r['deviation']);self.assertTrue(c['transposition']);self.assertEqual(c['match_percent'],100);self.assertEqual((c['matched_player_moves'],c['compared_player_moves']),(2,2))
  self.assertIn('توافق مسار',r['formula'])
  fen=recognition.recognize_fen(boards[-1].fen());self.assertIsNone(fen['match_percent']);self.assertTrue(fen['exact_openings'])
 def test_castling_and_legal_ep_are_in_the_position_key(self):
  a=chess.Board('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1');b=chess.Board(a.fen());b.castling_rights=0;self.assertNotEqual(recognition.position_key(a),recognition.position_key(b))
  a=chess.Board();a.push_uci('e2e4');b=chess.Board(a.fen(en_passant='fen'));b.ep_square=None;self.assertEqual(recognition.position_key(a),recognition.position_key(b))
  for u in ['a7a6','e4e5','d7d5']:a.push_uci(u)
  b=a.copy();b.ep_square=None;self.assertNotEqual(recognition.position_key(a),recognition.position_key(b))
 def test_invalid_pgn_fen_and_no_false_zero_percent(self):
  self.assertEqual(self.post('/api/knowledge/recognize',{'pgn':'1. e4 e5 2. Ke3 *'}).status_code,422)
  self.assertEqual(self.post('/api/knowledge/recognize',{'fen':'8/8/8/8/8/8/8/8 w - - 0 1'}).status_code,422)
  r=self.post('/api/knowledge/recognize',{'fen':chess.STARTING_FEN});self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['match_percent'])
 def test_unknown_player_color_never_contributes_match_percentage(self):
  with core.connection() as db:db.execute('UPDATE users SET chess_username=? WHERE id=?',('unrelated',self.ids[0]))
  r=analysis.report_game(self.gid,self.ids[0]);self.assertIsNone(r['own_color'])
  for c in r['opening']['candidates']:self.assertIsNone(c['match_percent']);self.assertEqual(c['compared_player_moves'],0)
  for o in analysis.profile(self.ids[0])['openings']:self.assertIsNone(o['match_percent'])
 def test_general_identity_never_calls_engine_or_provider(self):
  with patch('studio.teacher_v7.router.fetch_position',side_effect=AssertionError('No position analysis')),patch('studio.teacher_v7.providers.generate',side_effect=AssertionError('No LLM')):
   r=self.post('/api/teacher/chat',{'game_id':self.gid,'ply':1,'question':'من أنت؟'})
  self.assertEqual(r.status_code,200,r.text);data=r.json();self.assertEqual(data['answer_kind'],'general');self.assertIn('Chess Studio',data['explanation_ar']);self.assertEqual(data['scenarios'],[]);self.assertEqual(data['board_actions'],[])
  self.assertEqual(self.clients[1].get('/api/teacher/threads/'+str(data['thread_id'])).status_code,404)
 def test_general_opening_question_has_no_forced_fen(self):
  answer=TutorAnswer(title_ar='الدفاع الصقلي',explanation_ar='افتتاح يبدأ بـ e4 ثم c5.',benefits_ar=[],risks_ar=[],scenario_notes=[],learning_question_ar='')
  with patch.object(dialogue,'provider_status',return_value={'ready':True,'provider':'groq','model':'test'}),patch.object(dialogue,'provider_config',return_value={}),patch.object(dialogue.providers,'generate',return_value=(answer,1,2,'groq','test')) as fake:
   r=self.post('/api/teacher/chat',{'game_id':self.gid,'ply':1,'question':'ما هو الدفاع الصقلي؟'})
  self.assertEqual(r.status_code,200,r.text);ctx=fake.call_args.args[2]['VERIFIED_CONTEXT'];self.assertNotIn('fen',ctx);self.assertEqual(ctx['scenarios'],[]);self.assertTrue(ctx['local_opening_facts'])
 def test_actual_masters_statistics_are_distinct_from_engine(self):
  with patch.object(external,'request_lichess',side_effect=AssertionError('Offline read')):
   r=self.post('/api/knowledge/position',{'fen':chess.STARTING_FEN})
  self.assertEqual(r.status_code,200,r.text);p=r.json();s=p['statistics'];self.assertGreater(s['sample_size'],0);self.assertEqual(s['sample_size'],s['white_wins']+s['draws']+s['black_wins']);self.assertEqual(s['dataset'],'masters')
  self.assertEqual(p['most_popular_uci'],s['moves'][0]['uci']);self.assertIn('الأفضل',p['distinction'])
 def test_syzygy_real_files_and_mate_distance_not_confused(self):
  win=external.tablebase('7k/8/5KQ1/8/8/8/8/8 w - - 0 1');self.assertTrue(win['available']);self.assertEqual(win['wdl'],2);self.assertEqual(win['source'],'Syzygy local')
  draw=external.tablebase('7k/8/5KB1/8/8/8/8/8 w - - 0 1');self.assertEqual(draw['wdl'],0);self.assertIn('ليس',draw['note'])
 def test_puzzle_setup_opponent_move_and_full_solution(self):
  with store.connection() as db:p=dict(db.execute('SELECT * FROM kc_puzzles ORDER BY id LIMIT 1').fetchone())
  line=json.loads(p['moves_json']);board=chess.Board(p['fen']);board.push_uci(line[0]);r=self.post('/api/knowledge/puzzles/start',{'puzzle_id':p['id']});self.assertEqual(r.status_code,200,r.text);g=r.json();self.assertEqual(g['fen'],board.fen());self.assertIsNone(g['solution_uci'])
  sid=g['id'];self.assertEqual(self.post('/api/knowledge/puzzles/'+sid+'/move',{'uci':line[1],'version':0},1).status_code,404)
  while g['status']=='active':
   with core.connection() as db:cursor=db.execute('SELECT cursor FROM knowledge_puzzle_sessions WHERE id=?',(sid,)).fetchone()[0]
   r=self.post('/api/knowledge/puzzles/'+sid+'/move',{'uci':line[cursor],'version':g['version']});self.assertEqual(r.status_code,200,r.text);g=r.json()
  self.assertEqual(g['status'],'solved')
 def test_owner_reports_and_fingerprint_change(self):
  game,moves,boards,sans=recognition.parse_pgn('1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0')
  with core.connection() as db:
   db.execute('INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade,loss_cp,phase) VALUES(?,?,?,?,?,?,?,?,?)',(self.gid,1,'e4','e2e4',boards[0].fen(),boards[1].fen(),'weak',50,'opening'))
  first=analysis.report_game(self.gid,self.ids[0]);self.assertEqual(first['phases']['opening']['errors'],1);self.assertEqual(first['own_color'],'white')
  with core.connection() as db:db.execute('UPDATE moves SET loss_cp=150 WHERE game_id=?',(self.gid,))
  second=analysis.report_game(self.gid,self.ids[0]);self.assertNotEqual(first['fingerprint'],second['fingerprint']);self.assertEqual(self.clients[1].get('/api/knowledge/games/'+str(self.gid)).status_code,404)
  p=analysis.profile(self.ids[0]);self.assertEqual(p['reported_games'],1);self.assertEqual(p['style_indicators']['captures']['denominator'],3)
 def test_explorer_backoff_preserves_cache(self):
  real=httpx.Client
  with patch.object(external.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(429,headers={'Retry-After':'65'})),**kw)):
   with self.assertRaises(HTTPException) as error:external.request_lichess('https://explorer.lichess.org/masters',{})
  self.assertEqual(error.exception.status_code,429)
  with store.connection() as db:r=db.execute("SELECT * FROM kc_network WHERE name='lichess'").fetchone();self.assertGreater(r['next_at'],time.time()+60);self.assertEqual(r['lock_until'],0)
  self.assertTrue(external.explorer(chess.STARTING_FEN,'masters')['cached'])
 def test_uci960_castling_evaluation_is_normalized(self):
  row={'fen':'r3k2r/8/8/8/8/8/8/R3K2R w KQkq -','evals':[{'depth':25,'pvs':[{'cp':0,'line':'e1h1'}]}]}
  with store.connection() as db:importer.eval_record(db,row,'test');record=db.execute("SELECT pv_json FROM kc_evaluations WHERE position_key=? AND source='lichess-eval'",(recognition.position_key(chess.Board(row['fen']+' 0 1')),)).fetchone()
  self.assertEqual(json.loads(record['pv_json'])[0]['moves'][0],'e1g1')
 def test_schema_auth_and_read_only_source_access(self):
  self.assertEqual(TestClient(app).get('/api/knowledge/status').status_code,401)
  self.assertEqual(self.clients[0].post('/api/knowledge/recognize',json={'pgn':'1. e4 *'}).status_code,403)
  self.assertEqual(self.post('/api/knowledge/import/resume',{'file':'a.tsv'}).status_code,403)
  count=router.status()['counts'];store.setup();store.setup();self.assertEqual(router.status()['counts'],count)

if __name__=='__main__':unittest.main()
