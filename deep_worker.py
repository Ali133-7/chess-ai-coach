"""Restart-safe completed-game archive importer + isolated deep Stockfish worker.
Runs in a separate Compose container, never receives active-game moves.
Each position is committed transactionally, so a restart resumes at next ply.
"""
from __future__ import annotations
import hashlib, io, json, logging, os, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
import httpx, chess, chess.pgn, chess.engine
import main as core
import coach_plus as plus
import coach_advanced as advanced

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('deep_worker')
SECONDS=max(0.35,min(120.0,float(os.getenv('DEEP_SECONDS_PER_POSITION','120'))))
THREADS=max(1,min(8,int(os.getenv('DEEP_THREADS','1'))))
HASH=max(16,min(1024,int(os.getenv('DEEP_HASH_MB','128'))))
MULTIPV=max(1,min(4,int(os.getenv('DEEP_MULTIPV','3'))))
INTERVAL=max(1,int(os.getenv('ARCHIVE_REFRESH_HOURS','6')))*3600
VERSION=f'stockfish-v5-time{SECONDS}-t{THREADS}-h{HASH}-multi{MULTIPV}'

def conn():
    db=core.db_connect();db.execute('PRAGMA busy_timeout=30000');return db

def init():
    core.init_db()
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS deep_jobs(
            game_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
            total_plies INTEGER NOT NULL DEFAULT 0, completed_positions INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            worker_version TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS deep_scans(
            game_id TEXT NOT NULL, ply INTEGER NOT NULL, version TEXT NOT NULL,
            fen TEXT NOT NULL, scan_json TEXT NOT NULL,
            PRIMARY KEY(game_id,ply))''')
        db.execute('''CREATE TABLE IF NOT EXISTS archive_state(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        db.execute("UPDATE deep_jobs SET status='pending' WHERE status='running'")
        # A changed engine budget/settings invalidate the previous deep scans.
        db.execute("UPDATE deep_jobs SET status='pending',completed_positions=0,attempts=0 WHERE worker_version != ?",(VERSION,))
        db.execute('CREATE INDEX IF NOT EXISTS ix_jobs_status ON deep_jobs(status,updated_at)')

def save_game(item):
    if not all(item.get(k) for k in ('url','pgn','end_time')):return False
    pgn=item['pgn']
    try: game=plus.completed_game(pgn)
    except Exception:return False
    if core.USERNAME.casefold() not in {game.headers.get('White','').casefold(),game.headers.get('Black','').casefold()}:return False
    url=item['url'];gid=core.game_id(url);now=datetime.now(timezone.utc).isoformat()
    with conn() as db:
        db.execute('''INSERT OR IGNORE INTO games(id,url,username,pgn,finished_at,white,black,result,inserted_at)
          VALUES(?,?,?,?,?,?,?,?,?)''',(gid,url,core.USERNAME,pgn,int(item['end_time']),
          game.headers.get('White',''),game.headers.get('Black',''),game.headers.get('Result',''),now))
        db.execute('''INSERT OR IGNORE INTO deep_jobs(game_id,status,total_plies,updated_at,worker_version)
          VALUES(?,?,?,?,?)''',(gid,'pending',game.end().ply(),now,VERSION))
    return True

def state(key,value):
    with conn() as db:db.execute('INSERT INTO archive_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))

def get_state(key,default=None):
    with conn() as db:row=db.execute('SELECT value FROM archive_state WHERE key=?',(key,)).fetchone()
    return row['value'] if row else default

def fetch_json(client,url):
    for attempt in range(5):
        try:
            res=client.get(url)
            if res.status_code==404:return None
            if res.status_code in (429,500,502,503,504):
                secs=min(180,int(res.headers.get('Retry-After','0') or 0) or min(120,2**(attempt+1)*3))
                log.warning('Chess API %s, retry in %ss',res.status_code,secs);time.sleep(secs);continue
            res.raise_for_status();return res.json()
        except (httpx.TimeoutException,httpx.TransportError):
            time.sleep(min(100,3*(attempt+1)**2))
    raise RuntimeError('Chess.com request retries exhausted')

def import_all():
    if not core.USERNAME:raise RuntimeError('CHESS_USERNAME is empty')
    headers={'User-Agent':'ChessAICoach/5 personal post-game studies','Accept':'application/json'}
    with httpx.Client(timeout=30,headers=headers,follow_redirects=False) as client:
        archives=fetch_json(client,f'https://api.chess.com/pub/player/{core.USERNAME}/games/archives')
        if not archives:raise RuntimeError('No archives response from Chess.com')
        paths=archives.get('archives',[])
        state('archive_total_months',str(len(paths)));count=0
        for url in paths:
            # Defensive source restriction: do not fetch arbitrary URLs from a payload.
            prefix=f'https://api.chess.com/pub/player/{core.USERNAME}/games/'
            if not isinstance(url,str) or not url.startswith(prefix):continue
            try: payload=fetch_json(client,url)
            except Exception:
                log.exception('Unable to import archive month %s',url);continue
            for item in (payload or {}).get('games',[]):
                if save_game(item):count+=1
            state('archive_last_month',url[len(prefix):]);time.sleep(.35)
        state('archive_checked_at',datetime.now(timezone.utc).isoformat())
        log.info('Imported/verified %d completed archive entries across %d months',count,len(paths))

def analyze_job(row):
    gid=row['game_id']
    with conn() as db:
        record=db.execute('SELECT * FROM games WHERE id=?',(gid,)).fetchone()
    if record is None:return
    game=plus.completed_game(record['pgn']);nodes=list(game.mainline_moves())
    if len(nodes)>plus.MAX_PGN_PLIES:raise ValueError('PGN exceeds review limit')
    board=game.board();positions=[board.copy()]
    for move in nodes:
        if move not in board.legal_moves:raise ValueError('Invalid archived PGN')
        board.push(move);positions.append(board.copy())
    with conn() as db:
        db.execute('UPDATE deep_jobs SET status=?,total_plies=?,updated_at=?,last_error=NULL,worker_version=? WHERE game_id=?',('running',len(nodes),datetime.now(timezone.utc).isoformat(),VERSION,gid))
        db.execute('DELETE FROM deep_scans WHERE game_id=? AND version != ?',(gid,VERSION))
    with chess.engine.SimpleEngine.popen_uci(core.STOCKFISH_PATH) as engine:
        settings={}
        if 'Threads' in engine.options:settings['Threads']=THREADS
        if 'Hash' in engine.options:settings['Hash']=HASH
        if 'Skill Level' in engine.options:settings['Skill Level']=20
        if 'UCI_LimitStrength' in engine.options:settings['UCI_LimitStrength']=False
        if settings:engine.configure(settings)
        for i,pos in enumerate(positions):
            fen=pos.fen()
            with conn() as db:
                scan_row=db.execute('SELECT version,fen,scan_json FROM deep_scans WHERE game_id=? AND ply=?',(gid,i)).fetchone()
            if scan_row and scan_row['version']==VERSION and scan_row['fen']==fen:continue
            if pos.is_game_over(claim_draw=True):
                outcome=pos.outcome(claim_draw=True)
                cp=0 if not outcome or outcome.winner is None else (1500 if outcome.winner==chess.WHITE else -1500)
                scan={'cp_white':cp,'mate':None,'lines':[],'terminal':True}
            else:
                infos=engine.analyse(pos,chess.engine.Limit(time=SECONDS),multipv=MULTIPV)
                if not isinstance(infos,list):infos=[infos]
                cp,mate=advanced.cp_from(infos[0],chess.WHITE)
                lines=[{'uci':x['pv'][0].uci(),'san':pos.san(x['pv'][0]),'line':core.pv_to_san(pos,x['pv'],12),
                   'pv_uci':[m.uci() for m in x['pv'][:12]], 'cp_white':advanced.cp_from(x,chess.WHITE)[0],
                   'depth':x.get('depth'),'nodes':x.get('nodes')} for x in infos if x.get('pv') and x['pv'][0] in pos.legal_moves]
                scan={'cp_white':cp,'mate':mate,'lines':lines,'depth':infos[0].get('depth'),'nodes':infos[0].get('nodes')}
            with conn() as db:
                db.execute('''INSERT INTO deep_scans(game_id,ply,version,fen,scan_json) VALUES(?,?,?,?,?)
                   ON CONFLICT(game_id,ply) DO UPDATE SET version=excluded.version,fen=excluded.fen,scan_json=excluded.scan_json''',
                   (gid,i,VERSION,fen,json.dumps(scan,ensure_ascii=False)))
                db.execute('UPDATE deep_jobs SET completed_positions=?,updated_at=? WHERE game_id=?',
                   (i+1,datetime.now(timezone.utc).isoformat(),gid))
            if i%8==0:log.info('Deep analysis game %s position %s/%s',gid,i,len(nodes))
    with conn() as db:
        scans=[json.loads(r['scan_json']) for r in db.execute('SELECT scan_json FROM deep_scans WHERE game_id=? AND version=? ORDER BY ply',(gid,VERSION))]
    result=advanced.analysis_from_scans(record['pgn'],core.USERNAME,scans,SECONDS)
    result['deep_analysis']={'version':VERSION,'completed_at':datetime.now(timezone.utc).isoformat(),
          'seconds_budget_per_position':SECONDS,'multipv':MULTIPV,'threads':THREADS,'hash_mb':HASH}
    with conn() as db:
        db.execute('UPDATE games SET analysis_json=?,analysis_error=NULL WHERE id=?',(json.dumps(result,ensure_ascii=False),gid))
        db.execute("UPDATE deep_jobs SET status='done',last_error=NULL,updated_at=? WHERE game_id=?",(datetime.now(timezone.utc).isoformat(),gid))
    log.info('Finished deep review %s: %d plies',gid,len(nodes))

def work_once():
    with conn() as db:
        done=db.execute("SELECT COUNT(*) FROM deep_jobs WHERE status='done'").fetchone()[0]
        direction='ASC' if done % 4 == 0 else 'DESC'
        # order direction is fixed internally, never derived from client input.
        row=db.execute(f"""SELECT j.* FROM deep_jobs j JOIN games g ON j.game_id=g.id
          WHERE j.status='pending' OR (j.status='error' AND j.attempts<3 AND datetime(j.updated_at) < datetime('now','-30 minutes'))
          ORDER BY g.finished_at {direction} LIMIT 1""").fetchone()
    if not row:return False
    try:analyze_job(row)
    except Exception as exc:
        log.exception('Deep analysis error %s',row['game_id'])
        with conn() as db:db.execute("UPDATE deep_jobs SET status='error',attempts=attempts+1,last_error=?,updated_at=? WHERE game_id=?",
                (str(exc)[:250],datetime.now(timezone.utc).isoformat(),row['game_id']))
    return True

def run():
    init();next_import=0
    log.info('Deep worker ready: %ss/position, MultiPV=%s, single worker; closing browser has no effect',SECONDS,MULTIPV)
    while True:
        try:
            if time.time()>=next_import:
                try:import_all()
                except Exception:log.exception('Full archive import failed; will retry')
                next_import=time.time()+INTERVAL
            if work_once():continue
        except Exception:log.exception('Worker cycle failure')
        time.sleep(40)

if __name__=='__main__':run()
