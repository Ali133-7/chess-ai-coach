"""Durable post-game queue and published Chess.com rating ingestion for multiple users."""
from __future__ import annotations
import hashlib, json, logging, os, time, io, csv
from pathlib import Path
from datetime import datetime, timezone
import httpx, chess, chess.engine, chess.pgn
from contextlib import ExitStack
from . import analysis_runtime as runtime
from .core import connection, setup, now, config, game_moves_from_pgn, grade_for, phase, user_analysis_speed
from move_quality import candidate_sacrifice

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('studio.worker')
UA='ChessAICoachStudio/6 user-directed completed-game study (https://chess.com)'
STOCKFISH=os.getenv('STOCKFISH_PATH','/usr/games/stockfish')
RETRYABLE={429,500,502,503,504}

# Curated standard opening branches, NOT Chess.com's proprietary book. Other lines remain unmarked.
OPENING_LINES=[
 ('Italian Game','1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3'),
 ('Italian Four Knights','1. e4 e5 2. Nf3 Nc6 3. Nc3 Nf6 4. Bc4 Bc5'),
 ('Ruy Lopez','1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7'),
 ('Scotch Game','1. e4 e5 2. Nf3 Nc6 3. d4 exd4 4. Nxd4 Bc5'),
 ('Petrov Defense','1. e4 e5 2. Nf3 Nf6 3. Nxe5 d6 4. Nf3 Nxe4'),
 ('Vienna Game','1. e4 e5 2. Nc3 Nf6 3. f4 d5'),
 ('Four Knights Game','1. e4 e5 2. Nf3 Nc6 3. Nc3 Nf6'),
 ('Sicilian Defense','1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6'),
 ('Sicilian Dragon','1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 g6'),
 ('French Defense','1. e4 e6 2. d4 d5 3. Nc3 Nf6 4. e5 Nfd7'),
 ('Caro-Kann','1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 Bf5'),
 ('Scandinavian','1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5'),
 ('Pirc Defense','1. e4 d6 2. d4 Nf6 3. Nc3 g6 4. Nf3 Bg7'),
 ('Queen Gambit Declined','1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7'),
 ('Queen Gambit Accepted','1. d4 d5 2. c4 dxc4 3. Nf3 Nf6'),
 ('Slav Defense','1. d4 d5 2. c4 c6 3. Nf3 Nf6 4. Nc3 dxc4'),
 ('London System','1. d4 d5 2. Bf4 Nf6 3. e3 e6 4. Nf3 Bd6'),
 ('King Indian Defense','1. d4 Nf6 2. c4 g6 3. Nc3 Bg7 4. e4 d6 5. Nf3 O-O'),
 ('Nimzo-Indian Defense','1. d4 Nf6 2. c4 e6 3. Nc3 Bb4'),
 ('English Opening','1. c4 e5 2. Nc3 Nf6 3. g3 d5 4. cxd5 Nxd5'),
 ('Dutch Defense','1. d4 f5 2. c4 Nf6 3. g3 e6'),
 ('Queens Indian Defense','1. d4 Nf6 2. c4 e6 3. Nf3 b6'),
]

def opening_positions():
 mapping={};valid=[]
 for name,pgn in OPENING_LINES:
  try:
   game=chess.pgn.read_game(io.StringIO(pgn))
   board=game.board();count=0
   for move in game.mainline_moves():
    if move not in board.legal_moves:raise ValueError(f'Illegal opening {name}')
    board.push(move);count+=1
    # Record only positions at or after 1 ply, using FEN's four non-counter fields.
    key=' '.join(board.fen().split(' ')[:4]);mapping.setdefault(key,name)
   if count<3:raise ValueError('Opening too short')
   valid.append(name)
  except Exception as exc:log.warning('Skipped invalid opening %s: %s',name,exc)
 log.info('Opening-book branches checked: %s',len(valid))
 return mapping
BOOK=opening_positions()
BOOK_SOURCE='Curated baseline of named legal opening lines; extended with CC0 lichess-org/chess-openings when available.'

def refresh_book():
 """Best effort: import public domain ECO catalogue; never block chess analysis."""
 global BOOK,BOOK_SOURCE
 cache=Path(os.getenv('STUDIO_OPENING_CACHE','/studio-data/book_catalogue.json'))
 if cache.exists():
  try:
   parsed=json.loads(cache.read_text(encoding='utf-8'))
   if len(parsed)>500:
    BOOK=parsed;BOOK_SOURCE='lichess-org/chess-openings CC0 dataset (cached)'
    return
  except (ValueError,OSError):pass
 result=dict(BOOK)
 try:
  with httpx.Client(timeout=18,headers={'User-Agent':UA},follow_redirects=False) as client:
   for part in 'abcde':
    url=f'https://raw.githubusercontent.com/lichess-org/chess-openings/master/{part}.tsv'
    res=client.get(url);res.raise_for_status()
    for row in csv.DictReader(io.StringIO(res.text),delimiter='\t'):
     try:
      game=chess.pgn.read_game(io.StringIO(row.get('pgn','')))
      if not game:continue
      pos=game.board()
      for mv in game.mainline_moves():
       if mv not in pos.legal_moves:break
       pos.push(mv)
       result[' '.join(pos.fen().split(' ')[:4])]=row.get('name','')[:130]
     except (ValueError,TypeError):continue
  if len(result)>500:
   cache.parent.mkdir(parents=True,exist_ok=True)
   cache.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
   BOOK=result;BOOK_SOURCE='lichess-org/chess-openings CC0 dataset (downloaded)'
   log.info('Opening catalogue ready, unique positions=%d',len(BOOK))
 except Exception as exc:log.warning('Opening catalogue unavailable; curated fallback remains: %s',type(exc).__name__)


def get_json(client,url):
 for attempt in range(4):
  try:
   r=client.get(url)
   if r.status_code==404:return None
   if r.status_code in RETRYABLE:
    time.sleep(min(90,2**attempt*3));continue
   r.raise_for_status();return r.json()
  except httpx.TransportError as exc:
   log.warning('Chess.com temporary failure: %s',type(exc).__name__);time.sleep(3*(attempt+1))
 raise RuntimeError('Chess.com request failed after retries')

def sync_user(user):
 uid,username=user['id'],user['chess_username']
 if not username:return
 prefix=f'https://api.chess.com/pub/player/{username}/games/'
 with httpx.Client(timeout=25,headers={'User-Agent':UA,'Accept':'application/json'},follow_redirects=False) as client:
  stats=get_json(client,f'https://api.chess.com/pub/player/{username}/stats') or {}
  with connection() as db:
   for fmt in ('rapid','blitz','bullet','daily'):
    cat=stats.get('chess_'+fmt) or {}
    if not cat.get('last'):continue
    record=cat.get('record') or {}
    db.execute('''INSERT INTO ratings(user_id,format,rating,best,wins,losses,draws,updated_at)
     VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,format) DO UPDATE SET
     rating=excluded.rating,best=excluded.best,wins=excluded.wins,losses=excluded.losses,
     draws=excluded.draws,updated_at=excluded.updated_at''',
     (uid,fmt,cat['last'].get('rating'),(cat.get('best') or {}).get('rating'),
       record.get('win',0),record.get('loss',0),record.get('draw',0),now()))
  response=get_json(client,f'https://api.chess.com/pub/player/{username}/games/archives') or {}
  paths=[u for u in response.get('archives',[]) if isinstance(u,str) and u.startswith(prefix) and
     u[len(prefix):].replace('/','').isdigit()]
  # Backfill from newest to oldest. A month is refreshed after configured interval.
  with connection() as db:
   refresh=int(config(db,'archive_refresh_hours','6'))*3600
   maximum=int(config(db,'max_games_per_user','3000'))
  for url in reversed(paths):
   with connection() as db:
    row=db.execute('SELECT checked_at FROM archive_months WHERE user_id=? AND path=?',(uid,url)).fetchone()
    count=db.execute('SELECT COUNT(*) FROM games WHERE user_id=?',(uid,)).fetchone()[0]
   if count>=maximum:break
   if row and datetime.fromisoformat(row['checked_at']).timestamp()>time.time()-refresh:continue
   payload=get_json(client,url) or {}
   items=payload.get('games',[])
   imported=0
   for item in items:
    url_game=item.get('url')
    if not isinstance(url_game,str) or not url_game.startswith('https://www.chess.com/game/'):
     continue
    if not item.get('end_time') or not item.get('pgn'):continue
    try:
     parsed,moves=game_moves_from_pgn(item['pgn'])
     if username not in (parsed.headers.get('White','').lower(),parsed.headers.get('Black','').lower()):continue
     external_id=hashlib.sha256(url_game.encode()).hexdigest()[:30]
     with connection() as db:
      db.execute('''INSERT OR IGNORE INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,time_class,
        total_positions,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (uid,external_id,url_game,item['pgn'],int(item['end_time']),parsed.headers.get('White',''),
        parsed.headers.get('Black',''),parsed.headers.get('Result',''),item.get('time_class',''),len(moves)+1,now()))
     imported+=1
    except (ValueError,TypeError):continue
   with connection() as db:
    db.execute('INSERT OR REPLACE INTO archive_months(user_id,path,checked_at) VALUES(?,?,?)',(uid,url,now()))
   log.info('Archive uid=%d month=%s entries=%d',uid,url[-7:],imported)
   time.sleep(.3)

def eval_white(info):
 score=info['score'].pov(chess.WHITE)
 if score.is_mate():
  mate=score.mate() or 0
  return (1500-min(abs(mate),40)*7)*(1 if mate>0 else -1)
 return max(-1500,min(1500,score.score() or 0))

def scan_position(engine,board,multipv,seconds):
 if board.is_game_over(claim_draw=True):
  outcome=board.outcome(claim_draw=True)
  cp=0 if not outcome or outcome.winner is None else (1500 if outcome.winner==chess.WHITE else -1500)
  return {'eval':cp,'lines':[],'terminal':True}
 infos=engine.analyse(board,chess.engine.Limit(time=seconds),multipv=multipv)
 if isinstance(infos,dict):infos=[infos]
 lines=[]
 for info in infos:
  pv=info.get('pv',[])
  if not pv or pv[0] not in board.legal_moves:continue
  san=[];temp=board.copy()
  for m in pv[:12]:
   if m not in temp.legal_moves:break
   san.append(temp.san(m));temp.push(m)
  lines.append({'uci':pv[0].uci(),'san':san[0],'eval':eval_white(info),
     'pv_uci':[m.uci() for m in pv[:12]],'line':san,'depth':info.get('depth')})
 return {'eval':eval_white(infos[0]),'lines':lines,'terminal':False}

def material_balance(board):
 vals={chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}
 return sum(vals.get(p.piece_type,0)*(1 if p.color else -1) for p in board.piece_map().values())

def analyze_game(row):
 gid=row['id'];user_id=row['user_id'];token=row.get('_lease');worked=0;started=time.monotonic()
 game,positions=game_moves_from_pgn(row['pgn']);total=len(positions)+1
 def boards():
  board=game.board();yield board
  for _,uci,_,_,_ in positions:
   board.push_uci(uci);yield board
 with connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if not runtime.owns(db,gid,token):return
  db.execute("UPDATE games SET stage='running',total_positions=?,error=NULL,updated_at=? WHERE id=?",(total,now(),gid))
  saved={x['ply']:dict(x) for x in db.execute('SELECT ply,fen,scan_json FROM position_scans WHERE game_id=?',(gid,))}
 with ExitStack() as stack:
  engine=None
  def compute(b,multipv,seconds):
   nonlocal engine
   if engine is None:
    engine=stack.enter_context(chess.engine.SimpleEngine.popen_uci(STOCKFISH));opts={}
    if 'Threads' in engine.options:opts['Threads']=int(os.getenv('STUDIO_ENGINE_THREADS','1'))
    if 'Hash' in engine.options:opts['Hash']=int(os.getenv('STUDIO_ENGINE_HASH_MB','96'))
    if 'UCI_LimitStrength' in engine.options:opts['UCI_LimitStrength']=False
    if 'Skill Level' in engine.options:opts['Skill Level']=20
    engine.configure(opts)
   return scan_position(engine,b,multipv,seconds)
  for idx,b in enumerate(boards()):
   cached=saved.get(idx)
   if cached and cached['fen']==b.fen():continue
   with connection() as db:
    db.execute('BEGIN IMMEDIATE')
    if not runtime.owns(db,gid,token):return
    runtime.heartbeat(db,gid,token)
    if token and worked and (time.monotonic()-started>=10 or db.execute("SELECT 1 FROM analysis_jobs q JOIN games g ON g.id=q.game_id WHERE q.priority>0 AND q.game_id!=? AND g.stage='pending' LIMIT 1",(gid,)).fetchone()):break
    budget=user_analysis_speed(db,user_id)
    seconds=budget['seconds']
    multipv=budget['multipv']
    paused=budget['worker_paused']
   if paused:
    log.info('Pause requested; will continue after resume.');break
   if token and worked>=runtime.QUANTUM:break
   if idx==0 or idx%8==0:
    log.info('Engine budget game=%s user=%s preset=%s seconds=%s multipv=%s position=%s/%s',
             gid,user_id,budget['preset'],seconds,multipv,idx,total)
   scan,source=runtime.shared_scan(b,seconds,multipv,lambda:compute(b,multipv,seconds))
   if scan is None:row['_backoff']=2;break
   worked+=1
   with connection() as db:
    db.execute('BEGIN IMMEDIATE')
    if not runtime.owns(db,gid,token):return
    runtime.heartbeat(db,gid,token)
    db.execute('''INSERT INTO position_scans(game_id,ply,fen,scan_json) VALUES(?,?,?,?)
      ON CONFLICT(game_id,ply) DO UPDATE SET fen=excluded.fen,scan_json=excluded.scan_json''',
      (gid,idx,b.fen(),json.dumps(scan,ensure_ascii=False)))
    db.execute('UPDATE games SET completed_positions=?,updated_at=? WHERE id=?',(idx+1,now(),gid))
   if idx%8==0:log.info('Studio analysis game=%s user=%s %s/%s',gid,user_id,idx,total)
 with connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if not runtime.owns(db,gid,token):return
  scans=[dict(r) for r in db.execute('SELECT ply,scan_json FROM position_scans WHERE game_id=? AND ply>=0 AND ply<? ORDER BY ply',(gid,total))]
  if len(scans)!=total:
   db.execute("UPDATE games SET stage='pending',updated_at=? WHERE id=?",(now(),gid))
   return
  analyses=[json.loads(r['scan_json']) for r in scans]
  for (ply,uci,san,before,after),pre,post in zip(positions,analyses[:-1],analyses[1:]):
   iswhite=chess.Board(before).turn==chess.WHITE
   best=pre['lines'][0] if pre['lines'] else None
   best_uci=best['uci'] if best else None
   best_san=best['san'] if best else None
   score_before=pre['eval']*(1 if iswhite else -1)
   score_after=post['eval']*(1 if iswhite else -1)
   loss=max(0,min(3000,score_before-score_after))
   book_name=BOOK.get(' '.join(after.split(' ')[:4])) if ply<=18 else None
   if book_name and loss<=80:grade='book'
   elif best:
    b=chess.Board(before)
    mv=chess.Move.from_uci(uci)
    if uci==best_uci and loss<=20 and candidate_sacrifice(b,mv,best.get('line',[]),score_before,score_after):
     grade='brilliant'
    else:grade=grade_for(uci==best_uci,loss,score_before,score_after,b,mv,book_name)
   else:grade='unrated'
   db.execute('''INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade,loss_cp,eval_cp_white,
     best_uci,best_san,book_name,lines_json,phase) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(game_id,ply) DO UPDATE SET grade=excluded.grade,loss_cp=excluded.loss_cp,
     eval_cp_white=excluded.eval_cp_white,best_uci=excluded.best_uci,best_san=excluded.best_san,
     book_name=excluded.book_name,lines_json=excluded.lines_json,phase=excluded.phase''',
     (gid,ply,san,uci,before,after,grade,loss,post['eval'],best_uci,best_san,book_name,
      json.dumps(pre['lines'],ensure_ascii=False),phase(chess.Board(before))))
  db.execute("UPDATE games SET stage='done',completed_positions=?,updated_at=?,error=NULL WHERE id=?",(total,now(),gid))
 log.info('Finished game %d (%d moves)',gid,len(positions))

def job():
 row=runtime.claim()
 if not row:return False
 try:analyze_game(row)
 except Exception as exc:
  log.exception('Game analysis %s failed',row['id'])
  with connection() as db:
   db.execute('BEGIN IMMEDIATE')
   if runtime.owns(db,row['id'],row['_lease']):db.execute("UPDATE games SET stage='error',error=?,updated_at=? WHERE id=?",('analysis_failed',now(),row['id']))
 finally:runtime.release(row['id'],row['_lease'],row.get('_backoff',0))
 return True

def run():
 setup();refresh_book();log.info('Studio v6 deep analysis worker started; independent of browser and archive synchronizer')
 while True:
  try:
   if job():continue
  except Exception:log.exception('Deep analysis worker loop error')
  time.sleep(12)

if __name__=='__main__':run()
