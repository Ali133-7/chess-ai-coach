"""Versioned engine evidence and owner-scoped, non-destructive deeper searches."""
import json,os,secrets,time
import chess
from .reliability_locale import LocalizedError as HTTPException
from . import core,analysis_runtime

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS analysis_experiments(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,ply INTEGER NOT NULL,seconds INTEGER NOT NULL,multipv INTEGER NOT NULL,status TEXT NOT NULL,token TEXT,lease_until REAL NOT NULL DEFAULT 0,original_json TEXT NOT NULL,result_json TEXT,error TEXT,created_at REAL NOT NULL,finished_at REAL);
 CREATE INDEX IF NOT EXISTS analysis_experiment_queue ON analysis_experiments(status,lease_until,created_at);
 CREATE INDEX IF NOT EXISTS analysis_experiment_owner ON analysis_experiments(user_id,created_at);
 ''')

def metadata(scan,seconds,multipv):
 identity=analysis_runtime.engine_identity()
 return {**scan,'analysis_meta':{'schema':1,'algorithm':analysis_runtime.VERSION,
  'engine_sha256':identity if len(identity)==64 else None,'engine_id':scan.get('engine_id',{}),
  'method':'rules-terminal' if scan.get('terminal') else 'engine-search','elapsed_ms':scan.get('elapsed_ms'),
  'requested_seconds':seconds,'requested_multipv':multipv,
  'threads':int(os.getenv('STUDIO_ENGINE_THREADS','1')),'hash_mb':int(os.getenv('STUDIO_ENGINE_HASH_MB','96')),
  'depth':max((x.get('depth') or 0 for x in scan.get('lines',[])),default=0) or None,
  'computed_at':time.time(),'evaluation_perspective':'white','limited_search':True}}

def summary(scan):
 if not scan:return {'known':False,'reason':'No saved scan'}
 return {'known':bool(scan.get('analysis_meta')),'metadata':scan.get('analysis_meta'),
  'eval_cp_white':scan.get('eval'),'best_uci':scan.get('lines',[{}])[0].get('uci') if scan.get('lines') else None,
  'notice':'Older checkpoints have unknown engine settings. Limited searches can disagree.'}

def position(db,uid,gid,ply):
 game=db.execute("SELECT * FROM games WHERE id=? AND user_id=?",(gid,uid)).fetchone()
 if not game:raise HTTPException(404,'Game not found')
 if game['stage']!='done' or game['result'] not in ('1-0','0-1','1/2-1/2') or not game['finished_at']:raise HTTPException(409,'Completed analysed games only')
 g,moves=core.game_moves_from_pgn(game['pgn'])
 if not 1<=ply<=len(moves):raise HTTPException(404,'Position not found')
 board=g.board()
 for _,uci,_,_,_ in moves[:ply-1]:board.push_uci(uci)
 row=db.execute('SELECT scan_json FROM position_scans WHERE game_id=? AND ply=?',(gid,ply-1)).fetchone()
 return board,json.loads(row[0]) if row else {}

def create(uid,gid,ply,seconds,multipv):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');_,original=position(db,uid,gid,ply)
  if db.execute("SELECT count(*) FROM analysis_experiments WHERE user_id=? AND status IN ('pending','running')",(uid,)).fetchone()[0]>=2:raise HTTPException(429,'Two searches may be outstanding per account')
  if db.execute("SELECT count(*) FROM analysis_experiments WHERE status IN ('pending','running')").fetchone()[0]>=20:raise HTTPException(429,'Search queue full')
  eid=secrets.token_hex(16)
  db.execute('INSERT INTO analysis_experiments(id,user_id,game_id,ply,seconds,multipv,status,original_json,created_at) VALUES(?,?,?,?,?,?,\'pending\',?,?)',(eid,uid,gid,ply,seconds,multipv,json.dumps(original),time.time()))
 return {'id':eid,'status':'pending','original_analysis_unchanged':True}

def read(uid,eid):
 with core.connection() as db:r=db.execute('SELECT * FROM analysis_experiments WHERE id=? AND user_id=?',(eid,uid)).fetchone()
 if not r:raise HTTPException(404,'Search not found')
 original=json.loads(r['original_json']);result=json.loads(r['result_json']) if r['result_json'] else None
 return {'id':eid,'game_id':r['game_id'],'ply':r['ply'],'status':r['status'],'original':summary(original),'search':summary(result),
  'delta_cp_white':result['eval']-original['eval'] if result and isinstance(original.get('eval'),(int,float)) else None,
  'result':result,'error':r['error'],'notice':'The saved game is unchanged. Delta is a difference between searches, not proof that one is correct.'}

def job():
 from . import worker
 token=secrets.token_hex(16);now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if core.config(db,'worker_paused','false')=='true':return False
  r=db.execute("SELECT e.* FROM analysis_experiments e JOIN users u ON u.id=e.user_id WHERE u.disabled=0 AND e.status IN ('pending','running') AND e.lease_until<? ORDER BY e.created_at LIMIT 1",(now,)).fetchone()
  if not r:return False
  db.execute("UPDATE analysis_experiments SET status='running',token=?,lease_until=? WHERE id=?",(token,now+180,r['id']))
 try:
  with core.connection() as db:board,_=position(db,r['user_id'],r['game_id'],r['ply'])
  def compute():
   with chess.engine.SimpleEngine.popen_uci(worker.STOCKFISH) as engine:
    opts={k:v for k,v in {'Threads':int(os.getenv('STUDIO_ENGINE_THREADS','1')),'Hash':int(os.getenv('STUDIO_ENGINE_HASH_MB','96')),'UCI_LimitStrength':False,'Skill Level':20}.items() if k in engine.options}
    engine.configure(opts);return worker.scan_position(engine,board,r['multipv'],r['seconds'])
  scan,source=analysis_runtime.shared_scan(board,r['seconds'],r['multipv'],compute)
  with core.connection() as db:
   if scan is None:db.execute("UPDATE analysis_experiments SET status='pending',token=NULL,lease_until=? WHERE id=? AND token=?",(time.time()+2,r['id'],token))
   else:db.execute("UPDATE analysis_experiments SET status='done',result_json=?,finished_at=?,token=NULL,lease_until=0 WHERE id=? AND token=?",(json.dumps(scan),time.time(),r['id'],token))
 except Exception:
  with core.connection() as db:db.execute("UPDATE analysis_experiments SET status='error',error='analysis_failed',token=NULL,lease_until=0 WHERE id=? AND token=?",(r['id'],token))
 return True

def install(app,auth):
 from fastapi import Depends
 from pydantic import BaseModel,Field
 from typing import Literal
 class Search(BaseModel):
  seconds:Literal[10,30,60,120]=30
  multipv:int=Field(default=3,ge=1,le=3)
 @app.get('/api/games/{gid}/positions/{ply}/evidence')
 def evidence(gid:int,ply:int,user=Depends(auth)):
  with core.connection() as db:board,scan=position(db,user['id'],gid,ply)
  return {'game_id':gid,'ply':ply,'fen':board.fen(),**summary(scan)}
 @app.post('/api/games/{gid}/positions/{ply}/reanalyze',status_code=202)
 def search(gid:int,ply:int,data:Search,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('deeper-search:'+str(user['id']),20,86400)
  return create(user['id'],gid,ply,data.seconds,data.multipv)
 @app.get('/api/analysis/experiments/{eid}')
 def result(eid:str,user=Depends(auth)):return read(user['id'],eid)
