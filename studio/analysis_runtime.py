"""Durable leases, cancellation fences and history-safe shared engine facts."""
import hashlib,json,os,secrets,time
from collections import Counter
from functools import lru_cache
from pathlib import Path
import chess
from fastapi import HTTPException
from . import core

VERSION='stockfish-scan-v2'
QUANTUM=4

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS analysis_jobs(game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,priority INTEGER NOT NULL DEFAULT 0,generation INTEGER NOT NULL DEFAULT 0,token TEXT,lease_until REAL NOT NULL DEFAULT 0,requested_at REAL NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS shared_engine_scans(key TEXT PRIMARY KEY,scan_json TEXT,token TEXT,lease_until REAL NOT NULL DEFAULT 0,created_at REAL NOT NULL,hits INTEGER NOT NULL DEFAULT 0);
 CREATE INDEX IF NOT EXISTS analysis_job_lease ON analysis_jobs(lease_until,priority);
 CREATE INDEX IF NOT EXISTS engine_scan_age ON shared_engine_scans(created_at);
 ''')

@lru_cache(maxsize=4)
def binary_identity(path,size,stamp):
 with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def engine_identity():
 path=Path(os.getenv('STOCKFISH_PATH','/usr/games/stockfish'))
 try:
  s=path.stat();return binary_identity(str(path.resolve()),s.st_size,s.st_mtime_ns)
 except OSError:return 'engine-unavailable'

def position_key(board,seconds,multipv,engine=None):
 # Halfmove clock and repetition rights matter. Ignore the move number, but
 # include the multiset of visited rule states since the last irreversible move.
 b=board.copy(stack=board.halfmove_clock!=0);states=Counter()
 while True:
  states[' '.join(b.fen().split()[:4])]+=1
  if not b.move_stack:break
  move=b.pop()
  if b.is_irreversible(move):break
 context={'fen':' '.join(board.fen().split()[:5]),'history':sorted(states.items()),'seconds':seconds,'multipv':multipv,'engine':engine or engine_identity(),'algorithm':VERSION,'options':{'skill':20,'limit_strength':False,'threads':os.getenv('STUDIO_ENGINE_THREADS','1'),'hash':os.getenv('STUDIO_ENGINE_HASH_MB','96')}}
 return hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()

def checked_scan(board,scan):
 if not isinstance(scan,dict) or not isinstance(scan.get('eval'),(int,float)):return False
 if scan.get('terminal'):return board.is_game_over(claim_draw=True)
 if not isinstance(scan.get('lines'),list) or not scan['lines']:return False
 for line in scan['lines']:
  try:
   b=board.copy();moves=line['pv_uci']
   if not moves or line['uci']!=moves[0]:return False
   for uci in moves:
    m=chess.Move.from_uci(uci)
    if m not in b.legal_moves:return False
    b.push(m)
  except (KeyError,ValueError,TypeError):return False
 return True

def shared_scan(board,seconds,multipv,compute):
 key=position_key(board,seconds,multipv);token=secrets.token_hex(16);now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM shared_engine_scans WHERE key=?',(key,)).fetchone()
  if r and r['scan_json']:
   try:scan=json.loads(r['scan_json'])
   except ValueError:scan=None
   if checked_scan(board,scan):
    db.execute('UPDATE shared_engine_scans SET hits=hits+1 WHERE key=?',(key,));return scan,'shared'
  if r and r['lease_until']>now:return None,'busy'
  db.execute('INSERT INTO shared_engine_scans(key,token,lease_until,created_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET token=excluded.token,lease_until=excluded.lease_until,scan_json=NULL',(key,token,now+max(30,seconds+30),now))
 try:
  scan=compute()
  if not checked_scan(board,scan):raise ValueError('Engine returned an invalid principal variation')
  with core.connection() as db:
   db.execute('UPDATE shared_engine_scans SET scan_json=?,token=NULL,lease_until=0 WHERE key=? AND token=?',(json.dumps(scan),key,token))
   # Bounded retention; never remove active single-flight leases.
   db.execute('DELETE FROM shared_engine_scans WHERE key IN (SELECT key FROM shared_engine_scans WHERE lease_until<? ORDER BY created_at DESC LIMIT -1 OFFSET 20000)',(time.time(),))
  return scan,'computed'
 except BaseException:
  with core.connection() as db:db.execute('UPDATE shared_engine_scans SET lease_until=0,token=NULL WHERE key=? AND token=?',(key,token))
  raise

def claim():
 now=time.time();token=secrets.token_hex(16)
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if core.config(db,'worker_paused','false')=='true':return None
  db.execute("INSERT OR IGNORE INTO analysis_jobs(game_id,requested_at) SELECT id,? FROM games WHERE stage IN ('pending','running')",(now,))
  previous=db.execute("SELECT value FROM worker_state WHERE key='last_user_id'").fetchone();prev=int(previous[0]) if previous else 0
  row=db.execute("SELECT g.* FROM games g JOIN users u ON u.id=g.user_id JOIN analysis_jobs q ON q.game_id=g.id WHERE g.stage IN ('pending','running') AND u.disabled=0 AND q.lease_until<=? ORDER BY q.priority DESC,CASE WHEN g.user_id>? THEN 0 ELSE 1 END,g.user_id,q.requested_at,g.finished_at DESC LIMIT 1",(now,prev)).fetchone()
  if not row:return None
  db.execute('UPDATE analysis_jobs SET token=?,lease_until=?,priority=0 WHERE game_id=?',(token,now+180,row['id']))
  db.execute("UPDATE games SET stage='running',error=NULL WHERE id=?",(row['id'],))
  db.execute("INSERT OR REPLACE INTO worker_state VALUES('last_user_id',?)",(str(row['user_id']),))
  return dict(row)|{'_lease':token}

def owns(db,gid,token):
 if token is None:return True # explicit synchronous/internal test entry point
 return bool(db.execute("SELECT 1 FROM analysis_jobs q JOIN games g ON g.id=q.game_id JOIN users u ON u.id=g.user_id WHERE q.game_id=? AND q.token=? AND g.stage='running' AND u.disabled=0",(gid,token)).fetchone())

def heartbeat(db,gid,token):
 if token:db.execute('UPDATE analysis_jobs SET lease_until=? WHERE game_id=? AND token=?',(time.time()+180,gid,token))

def release(gid,token,delay=0):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if not db.execute('SELECT 1 FROM analysis_jobs WHERE game_id=? AND token=?',(gid,token)).fetchone():return
  db.execute("UPDATE games SET stage=CASE WHEN stage='running' THEN 'pending' ELSE stage END WHERE id=?",(gid,))
  db.execute('UPDATE analysis_jobs SET token=NULL,lease_until=?,requested_at=? WHERE game_id=? AND token=?',(time.time()+delay,time.time(),gid,token))

def action(uid,gid,verb):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');g=db.execute('SELECT stage FROM games WHERE id=? AND user_id=?',(gid,uid)).fetchone()
  if not g:raise HTTPException(404,'Game not found')
  db.execute('INSERT OR IGNORE INTO analysis_jobs(game_id) VALUES(?)',(gid,))
  if verb=='cancel':
   if g['stage']=='done':raise HTTPException(409,'Completed analysis cannot be cancelled')
   db.execute("UPDATE games SET stage='cancelled',updated_at=? WHERE id=?",(core.now(),gid))
   db.execute('UPDATE analysis_jobs SET generation=generation+1,token=NULL,lease_until=0 WHERE game_id=?',(gid,))
  elif verb=='prioritize':
   # One foreground game per account, never monopolize the global queue.
   db.execute('UPDATE analysis_jobs SET priority=0 WHERE game_id IN (SELECT id FROM games WHERE user_id=?)',(uid,))
   db.execute('UPDATE analysis_jobs SET priority=10,requested_at=? WHERE game_id=?',(time.time(),gid))
  elif verb in ('resume','retry'):
   if g['stage'] not in ('cancelled','error','pending'):raise HTTPException(409,'Game is already running or completed')
   db.execute("UPDATE games SET stage='pending',error=NULL,updated_at=? WHERE id=?",(core.now(),gid))
   db.execute('UPDATE analysis_jobs SET requested_at=? WHERE game_id=?',(time.time(),gid))
 return {'ok':True}

def jobs(uid):
 with core.connection() as db:return {'items':[dict(r) for r in db.execute('SELECT g.id,g.white,g.black,g.stage,g.completed_positions,g.total_positions,g.updated_at,coalesce(q.priority,0) priority,coalesce(q.generation,0) generation FROM games g LEFT JOIN analysis_jobs q ON q.game_id=g.id WHERE g.user_id=? ORDER BY CASE WHEN g.stage IN (\'running\',\'pending\') THEN 0 ELSE 1 END,g.finished_at DESC LIMIT 30',(uid,))],'quantum_positions':QUANTUM,'cancellation':'Between engine positions; in-flight computation is fenced from committing after cancellation.'}

def install(app,auth):
 from fastapi import Depends
 from pydantic import BaseModel,ConfigDict
 from typing import Literal
 class Command(BaseModel):
  model_config=ConfigDict(extra='forbid')
  action:Literal['prioritize','cancel','resume','retry']
 @app.get('/api/analysis/jobs')
 def list_jobs(user=Depends(auth)):return jobs(user['id'])
 @app.post('/api/analysis/jobs/{gid}/action')
 def command(gid:int,data:Command,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('analysis-action:'+str(user['id']),30,60)
  return action(user['id'],gid,data.action)
