import os,json,csv,tempfile,unittest,io,hashlib
from pathlib import Path
from unittest.mock import patch
import chess,chess.engine,chess.pgn
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import store,drills,daily_exercises as d,masters
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play

class DailyExerciseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'main.sqlite3';self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'kb.sqlite3')});self.env.start();core.setup();setup_teacher();setup_play();store.setup();self.client=TestClient(app);self.client.post('/api/auth/register',json={'email':'daily@example.net','password':'daily-tests-password-123'});me=self.client.get('/api/me').json();self.uid=me['id'];self.headers={'X-CSRF-Token':me['csrf']}
  rows=sorted(csv.DictReader((store.DATA/'puzzles-sample.csv').read_text(encoding='utf8').splitlines()),key=lambda r:abs(int(r['Rating'])-1000))[:12];self.ids=[]
  with store.connection() as db:
   for r in rows:
    b=chess.Board(r['FEN']);moves=r['Moves'].split();b.push_uci(moves[0]);self.ids.append(r['PuzzleId']);db.execute('insert into kc_puzzles values(?,?,?,?,?,?,?,?,?)',(r['PuzzleId'],r['FEN'],b.fen(),json.dumps(moves),int(r['Rating']),r['Themes'],r.get('OpeningTags',''),r['GameUrl'],'public-test-fixture'))
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def err(self,code,fn,*args,**kw):
  with self.assertRaises(Exception) as e:fn(*args,**kw)
  self.assertEqual(e.exception.status_code,code)
 def source_row(self):
  fixture=next(p for p in [Path(__file__).parent/'fixtures/master-first.pgn',Path(__file__).parent/'master-test-fixtures/master-first.pgn'] if p.exists());masters.import_pgn(fixture,hashlib.sha256(fixture.read_bytes()).hexdigest(),'https://database.lichess.org/#broadcasts')
  with store.connection() as db:
   gid=db.execute('select id from kc_master_games limit 1').fetchone()[0];root=db.execute('select * from kc_master_moves where game_id=? and ply=12',(gid,)).fetchone();prev=db.execute('select fen from kc_master_moves where game_id=? and ply=11',(gid,)).fetchone()[0]
  b=chess.Board(root['fen']);m=next(iter(b.legal_moves));proof={'best_uci':m.uci(),'best_san':b.san(m),'pv':[m.uci()],'runner_pv':[],'best':{'cp_white':100,'mate_white':None,'depth':10},'runner':{'cp_white':-100,'mate_white':None,'depth':10},'gap_cp_reference':200,'engine':'MOCK ENGINE FIXTURE','nodes':500000,'depth':10,'verified_at':core.now(),'checkmate_after_move':False,'facts':{'ar':{'why':'وقائع اختبار'},'en':{'why':'Test facts'}}};position=d.key(b);pid='g'+position[:16]
  row={'puzzle_id':pid,'position_key':position,'day':d.today(),'source_game':gid,'source_ply':12,'fen_before':prev,'setup_uci':root['uci'],'root_fen':root['fen'],'proof_json':json.dumps(proof),'status':'engine_ready','created_at':core.now()}
  with store.connection() as db:db.execute('insert into kc_generated_exercises('+','.join(row)+') values('+','.join('?' for _ in row)+')',tuple(row.values()))
  notes={'id':pid,'title':{'ar':'بيانات اختبار آلي فقط','en':'Automated test fixture only'},'instruction':{'ar':'اختر نقلة','en':'Choose a move'},'explanation':{'ar':'شرح تجريبي','en':'Test explanation'},'check':{'ar':'تحقق','en':'Check'}}
  return row,notes
 def test_no_repeat_after_five_or_after_twelve_and_reload(self):
  seen=[]
  for _ in range(12):
   rows=drills.list_puzzles(1000,uid=self.uid)['items'];self.assertTrue(rows);pid=rows[0]['id'];self.assertNotIn(pid,seen);s=drills.start(pid,self.uid);drills.skip(s['id'],self.uid,s['version']);seen.append(pid)
  self.assertEqual(len(set(seen)),12);self.assertEqual(drills.list_puzzles(1000,uid=self.uid)['items'],[]);drills.setup();self.assertEqual(drills.list_puzzles(1000,uid=self.uid)['items'],[])
 def test_solved_puzzle_is_excluded(self):
  s=drills.start(self.ids[0],self.uid);line=json.loads(drills.puzzle(self.ids[0])['moves_json'])
  while s['status']=='active':
   with core.connection() as db:cursor=db.execute('select cursor from knowledge_puzzle_sessions where id=?',(s['id'],)).fetchone()[0]
   s=drills.move(s['id'],self.uid,line[cursor],s['version'])
  self.assertEqual(s['status'],'solved');self.assertNotIn(self.ids[0],{x['id'] for x in drills.list_puzzles(1000,uid=self.uid)['items']})
 def test_revealed_and_opened_are_not_in_new_queue(self):
  s=drills.start(self.ids[0],self.uid);self.assertNotIn(self.ids[0],{x['id'] for x in drills.list_puzzles(1000,uid=self.uid)['items']});drills.move(s['id'],self.uid,'',s['version'],True);self.assertNotIn(self.ids[0],{x['id'] for x in drills.list_puzzles(1000,uid=self.uid)['items']})
 def test_resume_active_session_instead_of_duplicating(self):
  a=drills.start(self.ids[0],self.uid);b=drills.start(self.ids[0],self.uid);self.assertEqual(a['id'],b['id'])
 def test_skip_is_owned_and_versioned(self):
  s=drills.start(self.ids[0],self.uid);self.err(404,drills.skip,s['id'],self.uid+1,0);r=drills.skip(s['id'],self.uid,0);self.assertEqual(r['status'],'skipped');self.err(409,drills.skip,s['id'],self.uid,0)
 def test_history_is_isolated_between_users(self):
  s=drills.start(self.ids[0],self.uid);drills.skip(s['id'],self.uid,0);self.assertIn(self.ids[0],{x['id'] for x in drills.list_puzzles(1000,uid=self.uid+1)['items']});self.assertEqual(drills.history(self.uid+1)['counts'],{})
 def test_legacy_sessions_are_backfilled_idempotently(self):
  with core.connection() as db:db.execute('insert into knowledge_puzzle_sessions(id,user_id,puzzle_id,status,created_at) values(?,?,?,?,?)',('legacy',self.uid,self.ids[0],'solved',core.now()))
  drills.setup();drills.setup();self.assertEqual(drills.history(self.uid)['counts']['solved'],1);self.assertNotIn(self.ids[0],{x['id'] for x in drills.list_puzzles(1000,uid=self.uid)['items']})
 def test_position_keys_ignore_move_clocks(self):
  b=chess.Board();x=b.copy();x.fullmove_number=98;x.halfmove_clock=27;self.assertEqual(d.key(b),d.key(x));x.turn=not x.turn;self.assertNotEqual(d.key(b),d.key(x))
 def test_two_engine_passes_require_stable_best_and_gap(self):
  b=chess.Board('6k1/5ppp/8/8/8/8/6PP/4R1K1 w - - 0 1');m=b.parse_san('Re8#');runner=next(x for x in b.legal_moves if x!=m)
  class Engine:
   options={};id={'name':'MOCK ENGINE FIXTURE'}
   def analyse(self,*args,**kw):return [{'pv':[m],'score':chess.engine.PovScore(chess.engine.Cp(500),b.turn),'depth':12},{'pv':[runner],'score':chess.engine.PovScore(chess.engine.Cp(0),b.turn),'depth':12}]
  e=Engine();r=d.analyse(e,b);self.assertTrue(r['checkmate_after_move']);self.assertEqual(r['best_uci'],m.uci());self.assertEqual(r['nodes'],500000)
  e.analyse=lambda *a,**k:[{'pv':[m],'score':chess.engine.PovScore(chess.engine.Cp(100),b.turn)},{'pv':[runner],'score':chess.engine.PovScore(chess.engine.Cp(90),b.turn)}];self.assertIsNone(d.analyse(e,b))
 def test_illegal_engine_pv_is_rejected(self):
  with self.assertRaises(ValueError):d.replay(chess.Board(),[chess.Move.from_uci('a1a8')])
 def test_source_provenance_and_publish_are_validated(self):
  row,notes=self.source_row();bad=dict(row);bad['source_ply']=13
  with self.assertRaises(ValueError):d.publish(bad,notes,'mock','fixture')
  d.publish(row,notes,'mock','fixture');r=drills.puzzle(row['puzzle_id']);self.assertEqual(chess.Board(r['setup_fen']).fen(),row['root_fen']);self.assertEqual(len(json.loads(r['moves_json'])),2)
 def test_generated_rating_is_not_fabricated_and_source_is_preserved(self):
  row,n=self.source_row();d.publish(row,n,'mock','fixture');s=drills.start(row['puzzle_id'],self.uid);self.assertIsNone(s['rating']);self.assertFalse(s['generated']['rating_calibrated']);self.assertEqual(s['generated']['source']['license'],'CC BY-SA 4.0');self.assertNotIn('proof',s['generated']);self.assertNotIn('explanation',s['generated'])
 def test_generated_solution_and_notes_appear_after_attempt(self):
  row,n=self.source_row();d.publish(row,n,'mock','fixture');s=drills.start(row['puzzle_id'],self.uid);r=drills.move(s['id'],self.uid,json.loads(row['proof_json'])['best_uci'],0);self.assertEqual(r['status'],'solved');self.assertIn('proof',r['generated']);self.assertTrue(r['generated']['explanation']['en'])
 def test_generated_positions_cannot_be_duplicated(self):
  row,n=self.source_row()
  with store.connection() as db:
   with self.assertRaises(Exception):db.execute('insert into kc_generated_exercises(puzzle_id,position_key,day,source_game,source_ply,fen_before,setup_uci,root_fen,proof_json,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?)',('other',row['position_key'],d.today(),row['source_game'],12,row['fen_before'],row['setup_uci'],row['root_fen'],row['proof_json'],'engine_ready',core.now()))
 def test_invalid_ai_ids_cannot_be_published(self):
  row,n=self.source_row();n['id']='invented';answer=d.Batch(items=[n])
  with patch.object(d.service,'provider_config',return_value={}),patch.object(d.providers,'generate',return_value=(answer,1,1,'mock','fixture')):
   with self.assertRaises(d.providers.ProviderError):d.explain_batch([row])
  self.assertEqual(d.status()['published_today'],0)
 def test_ai_failure_keeps_engine_rows_for_resume(self):
  row,n=self.source_row()
  with patch.object(d.service,'provider_status',return_value={'ready':False}):r=d.run()
  self.assertEqual(r['run']['status'],'retry_pending');self.assertEqual(r['published_today'],0)
  with store.connection() as db:self.assertEqual(db.execute('select status from kc_generated_exercises').fetchone()[0],'engine_ready')
 def test_concurrent_generation_lease(self):
  with store.connection() as db:db.execute('insert into kc_daily_runs(day,target,status,lease_until,updated_at) values(?,?,?,?,?)',(d.today(),24,'running',__import__('time').time()+600,core.now()))
  self.assertEqual(d.run()['status'],'already_running')
 def test_recommendations_broaden_without_replaying_seen_ids(self):
  with core.connection() as db:
   for pid in self.ids:drills.remember(db,self.uid,pid,'skipped')
  r=self.client.get('/api/knowledge/recommendations');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['items'],[]);self.assertTrue(r.json()['broadened']);self.assertEqual(r.json()['history']['counts']['skipped'],12)
 def test_http_auth_csrf_and_source_validation(self):
  anon=TestClient(app);self.assertEqual(anon.get('/api/knowledge/daily/status').status_code,401);self.assertEqual(self.client.get('/api/knowledge/daily/status').headers['cache-control'],'no-store');self.assertEqual(self.client.get('/api/knowledge/puzzles?source=invented').status_code,422);s=drills.start(self.ids[0],self.uid);url='/api/knowledge/puzzles/'+s['id']+'/skip';self.assertEqual(self.client.post(url,json={'version':0}).status_code,403);self.assertEqual(self.client.post(url,json={'version':0},headers=self.headers).status_code,200)
 def test_daily_target_is_above_twenty_and_bounded(self):
  self.assertEqual(d.TARGET,24)
  with self.assertRaises(ValueError):d.run(target=20)
 def test_source_eval_is_only_candidate_prefilter_not_an_elo(self):
  self.assertTrue(d.promising_source(json.dumps({'cp_white':250}),json.dumps({'cp_white':0}),chess.WHITE));self.assertFalse(d.promising_source(json.dumps({'cp_white':250}),json.dumps({'cp_white':0}),chess.BLACK));self.assertFalse(d.promising_source(None,None,chess.WHITE))
 def test_generated_priority_does_not_get_trapped_in_small_profile_theme(self):
  row,n=self.source_row();d.publish(row,n,'mock','fixture');r=drills.list_puzzles(1000,theme='a-theme-that-has-no-original-items',uid=self.uid,daily_priority=True);self.assertEqual(r['items'][0]['id'],row['puzzle_id']);self.assertIsNone(r['items'][0]['rating'])

if __name__=='__main__':unittest.main()
