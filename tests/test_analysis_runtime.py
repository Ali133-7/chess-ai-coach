import json,unittest,threading,concurrent.futures
from unittest.mock import patch,MagicMock
import chess
from studio import core,analysis_runtime as r,worker
import test_control_center as common

class RuntimeTests(unittest.TestCase):
 setUp=common.ControlTests.setUp
 tearDown=common.ControlTests.tearDown
 post=common.ControlTests.post
 def game(self,uid=None,suffix='one'):
  pgn='[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'
  with core.connection() as db:
   return db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid or self.uids[1],suffix,'https://example.net/test-fixture',pgn,1,'Fixture White','Fixture Black','1-0',core.now())).lastrowid
 def scan(self,b):
  m=next(iter(b.legal_moves));return {'eval':0,'terminal':False,'lines':[{'uci':m.uci(),'san':b.san(m),'eval':0,'pv_uci':[m.uci()],'line':[b.san(m)],'depth':1}]}
 def test_history_budget_engine_and_halfmove_are_part_of_identity(self):
  b=chess.Board();key=r.position_key(b,1,1,'engine-A')
  self.assertNotEqual(key,r.position_key(b,2,1,'engine-A'));self.assertNotEqual(key,r.position_key(b,1,2,'engine-A'));self.assertNotEqual(key,r.position_key(b,1,1,'engine-B'))
  for u in ['g1f3','g8f6','f3g1','f6g8']:b.push_uci(u)
  self.assertNotEqual(key,r.position_key(b,1,1,'engine-A'))
  b.push_uci('e2e4');fresh=chess.Board(b.fen());self.assertEqual(r.position_key(b,1,1,'engine-A'),r.position_key(fresh,1,1,'engine-A'))
 def test_illegal_cache_is_rejected_and_recomputed(self):
  b=chess.Board();key=r.position_key(b,1,1)
  with core.connection() as db:db.execute('INSERT INTO shared_engine_scans(key,scan_json,created_at) VALUES(?,?,0)',(key,json.dumps({'eval':0,'lines':[{'uci':'e2e5','pv_uci':['e2e5']}]})))
  scan,source=r.shared_scan(b,1,1,lambda:self.scan(b));self.assertEqual(source,'computed');self.assertTrue(r.checked_scan(b,scan))
 def test_shared_cache_single_flight_and_exception_release(self):
  b=chess.Board();started=threading.Event();release=threading.Event();out=[]
  def compute():started.set();release.wait(3);return self.scan(b)
  t=threading.Thread(target=lambda:out.append(r.shared_scan(b,1,1,compute)));t.start();self.assertTrue(started.wait(2))
  try:self.assertEqual(r.shared_scan(b,1,1,lambda:self.fail('duplicate computation')),(None,'busy'))
  finally:release.set();t.join(5)
  self.assertEqual(r.shared_scan(b,1,1,lambda:self.fail('cache miss'))[1],'shared')
  with self.assertRaises(ValueError):r.shared_scan(b,2,1,lambda:(_ for _ in ()).throw(ValueError('synthetic failure')))
  self.assertEqual(r.shared_scan(b,2,1,lambda:self.scan(b))[1],'computed')
 def test_worker_resumes_and_reuses_another_games_scans(self):
  first=self.game();second=self.game(suffix='two');engine=MagicMock();engine.options={}
  with patch.object(worker.chess.engine.SimpleEngine,'popen_uci',return_value=engine),patch.object(worker,'scan_position',side_effect=lambda e,b,m,s:self.scan(b)) as scan:
   for _ in range(6):worker.job()
   self.assertEqual(scan.call_count,5)
  with core.connection() as db:
   self.assertEqual(db.execute("SELECT count(*) FROM games WHERE stage='done'").fetchone()[0],2)
   self.assertEqual(db.execute('SELECT count(*) FROM position_scans').fetchone()[0],10)
   self.assertGreaterEqual(db.execute('SELECT sum(hits) FROM shared_engine_scans').fetchone()[0],5)
 def test_cancel_during_engine_work_fences_all_game_writes(self):
  gid=self.game();job=r.claim()
  def compute(e,b,m,s):r.action(self.uids[1],gid,'cancel');return self.scan(b)
  with patch.object(worker.chess.engine.SimpleEngine,'popen_uci',return_value=MagicMock()),patch.object(worker,'scan_position',side_effect=compute):worker.analyze_game(job)
  with core.connection() as db:
   self.assertEqual(db.execute('SELECT stage FROM games WHERE id=?',(gid,)).fetchone()[0],'cancelled');self.assertEqual(db.execute('SELECT count(*) FROM position_scans').fetchone()[0],0)
  r.action(self.uids[1],gid,'resume');self.assertIsNotNone(r.claim())
 def test_concurrent_workers_never_claim_same_game(self):
  self.game();self.game(suffix='two')
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:claimed=list(pool.map(lambda _:r.claim(),range(4)))
  ids=[x['id'] for x in claimed if x];self.assertEqual(len(ids),2);self.assertEqual(len(set(ids)),2)
 def test_new_foreground_request_yields_at_next_position_boundary(self):
  first=self.game();other=self.game(suffix='urgent');r.action(self.uids[1],first,'prioritize');job=r.claim()
  def scan(e,b,m,s):r.action(self.uids[1],other,'prioritize');return self.scan(b)
  with patch.object(worker.chess.engine.SimpleEngine,'popen_uci',return_value=MagicMock()),patch.object(worker,'scan_position',side_effect=scan):worker.analyze_game(job)
  r.release(first,job['_lease'])
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM position_scans WHERE game_id=?',(first,)).fetchone()[0],1)
  self.assertEqual(r.claim()['id'],other)
 def test_queue_owner_csrf_and_priority_ticket(self):
  gid=self.game();other=self.game(uid=self.uids[0],suffix='other')
  self.assertEqual(self.post(f'/api/analysis/jobs/{other}/action',{'action':'cancel'},1).status_code,404)
  self.assertEqual(self.clients[1].post(f'/api/analysis/jobs/{gid}/action',json={'action':'cancel'}).status_code,403)
  self.assertEqual(self.post(f'/api/analysis/jobs/{gid}/action',{'action':'prioritize'},1).status_code,200)
  job=r.claim();self.assertEqual(job['id'],gid)
  with core.connection() as db:self.assertEqual(db.execute('SELECT priority FROM analysis_jobs WHERE game_id=?',(gid,)).fetchone()[0],0)
  self.assertEqual(self.clients[1].get('/api/analysis/metrics').status_code,403)
 def test_custom_fen_black_to_move_uses_actual_mover_for_loss(self):
  gid=self.game();b=chess.Board();b.turn=chess.BLACK
  pgn='[SetUp "1"]\n[FEN "'+b.fen()+'"]\n[Result "0-1"]\n\n1... e5 0-1'
  with core.connection() as db:db.execute('UPDATE games SET pgn=?,result=? WHERE id=?',(pgn,'0-1',gid))
  def scan(e,b,m,s):return self.scan(b)|{'eval':100 if b.turn==chess.BLACK else 0}
  with patch.object(worker.chess.engine.SimpleEngine,'popen_uci',return_value=MagicMock()),patch.object(worker,'scan_position',side_effect=scan):worker.job()
  with core.connection() as db:self.assertEqual(db.execute('SELECT loss_cp FROM moves WHERE game_id=?',(gid,)).fetchone()[0],0)
 def test_admin_latency_percentile_uses_nearest_rank(self):
  from studio import performance
  with performance._lock:performance._samples['/controlled-unit-fixture'].extend([100,200])
  try:
   result=self.clients[0].get('/api/analysis/metrics');self.assertEqual(result.status_code,200)
   row=next(x for x in result.json()['http'] if x['route']=='/controlled-unit-fixture');self.assertEqual(row['mean_ms'],150);self.assertEqual(row['p95_ms'],200)
  finally:
   with performance._lock:performance._samples.pop('/controlled-unit-fixture',None)

if __name__=='__main__':unittest.main()
