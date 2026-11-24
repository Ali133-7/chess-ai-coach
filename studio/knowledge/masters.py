"""Licensed, completed GM games; additive local catalogue and reproducible analysis."""
import hashlib,io,json,re,sqlite3
from datetime import datetime,timezone
import chess,chess.pgn
from fastapi import HTTPException
from . import store,study,recognition
LICENSE='CC-BY-SA-4.0'

def setup():
 with store.connection() as db:
  db.executescript("""
  CREATE TABLE IF NOT EXISTS kc_master_games(id TEXT PRIMARY KEY,white TEXT NOT NULL,black TEXT NOT NULL,white_title TEXT NOT NULL,black_title TEXT NOT NULL,date TEXT NOT NULL,year INTEGER NOT NULL,event TEXT NOT NULL,result TEXT NOT NULL,eco TEXT NOT NULL,opening TEXT NOT NULL,plies INTEGER NOT NULL,initial_fen TEXT NOT NULL,pgn TEXT NOT NULL,source_url TEXT NOT NULL,archive_sha TEXT NOT NULL,license TEXT NOT NULL,content_hash TEXT NOT NULL UNIQUE);
  CREATE INDEX IF NOT EXISTS kc_master_year ON kc_master_games(year DESC,date DESC,id);
  CREATE TABLE IF NOT EXISTS kc_master_moves(game_id TEXT NOT NULL REFERENCES kc_master_games(id) ON DELETE CASCADE,ply INTEGER NOT NULL,uci TEXT NOT NULL,san TEXT NOT NULL,fen TEXT NOT NULL,note_json TEXT NOT NULL,material_white INTEGER NOT NULL,imported_eval TEXT,PRIMARY KEY(game_id,ply));
  CREATE TABLE IF NOT EXISTS kc_master_evals(fen_key TEXT PRIMARY KEY,payload TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS kc_master_imports(sha TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending');
  """)
  columns={row['name'] for row in db.execute('PRAGMA table_info(kc_master_moves)')}
  if 'imported_eval' not in columns:db.execute('ALTER TABLE kc_master_moves ADD COLUMN imported_eval TEXT')

def seed(path=None,expected_sha=None):
 """Explicit, idempotent data merge. Never runs during web requests/startup."""
 from pathlib import Path
 path=Path(path) if path else store.DATA/'master-games.sqlite3'
 if expected_sha is None:expected_sha=json.loads((store.DATA/'master-games-manifest.json').read_text(encoding='utf8'))['seed_sha256']
 if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:raise ValueError('Master seed checksum mismatch')
 setup()
 with store.connection() as db:
  db.execute('ATTACH DATABASE ? AS master_seed',(str(path.resolve()),))
  if db.execute('PRAGMA master_seed.integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid master seed')
  expected=db.execute('SELECT count(*) FROM master_seed.kc_master_games').fetchone()[0]
  db.execute('BEGIN IMMEDIATE')
  for table in ('kc_master_games','kc_master_moves','kc_master_evals'):
   db.execute('INSERT OR IGNORE INTO '+table+' SELECT * FROM master_seed.'+table)
  present=db.execute('SELECT count(*) FROM kc_master_games g JOIN master_seed.kc_master_games s ON s.id=g.id').fetchone()[0]
  if present!=expected:raise ValueError('Master data merge incomplete')
  if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kc_sources'").fetchone():
   db.execute('INSERT OR REPLACE INTO kc_sources VALUES(?,?,?,?,?,?)',('master-games-broadcasts','https://database.lichess.org/#broadcasts',LICENSE,expected_sha,str(expected)+' completed, legally validated GM-vs-GM games; source evaluations plus local bounded Stockfish analysis; adapted game data CC BY-SA 4.0.',datetime.now(timezone.utc).isoformat()))
 return {'seed_games':expected,'present':present,'sha256':expected_sha}

def eval_key(board):return ' '.join(board.fen(en_passant='legal').split()[:5])

def clean_game(game,build_notes=True):
 if game.errors or game.headers.get('Variant','Standard') not in ('Standard','Chess'):raise ValueError('nonstandard or invalid PGN')
 h=game.headers;date=h.get('Date','').replace('-','.');h['Date']=date;white=h.get('White','').strip();black=h.get('Black','').strip()
 if h.get('WhiteTitle')!='GM' or h.get('BlackTitle')!='GM':raise ValueError('GM titles required')
 if not white or not black or white=='?' or black=='?' or len(white)>160 or len(black)>160:raise ValueError('player names required')
 if not re.fullmatch(r'(19|20)\d{2}\.(\d{2}|\?\?)\.(\d{2}|\?\?)',date):raise ValueError('known year required')
 result=h.get('Result');moves=list(game.mainline_moves());b=game.board()
 if result not in ('1-0','0-1','1/2-1/2') or not 10<=len(moves)<=600 or not b.is_valid() or b.chess960:raise ValueError('completed legal standard game required')
 initial=b.fen();steps=[];keys=[]
 for i,node in enumerate(game.mainline()):
  m=node.move
  if m not in b.legal_moves or b.is_game_over():raise ValueError('invalid continuation')
  note=study.explain(b,m) if build_notes else None;san=b.san(m) if build_notes else '';b.push(m);keys.append(recognition.position_key(b))
  if not build_notes:continue
  material=sum((1 if pc.color else -1)*{1:1,2:3,3:3,4:5,5:9,6:0}[pc.piece_type] for pc in b.piece_map().values())
  # Source engine annotations retain their provenance; their engine settings are unknown.
  score=node.eval();source_eval=None
  if score is not None:
   pov=score.pov(chess.WHITE);source_eval=json.dumps({'cp_white':pov.score(),'mate_white':pov.mate(),'depth':node.eval_depth(),'engine':'Lichess broadcast annotation','source':'broadcast-eval','nodes':None,'pv':[]})
  steps.append((i+1,m.uci(),san,b.fen(),json.dumps(note,ensure_ascii=False),material,source_eval))
 outcome=b.outcome()
 if outcome and outcome.result()!=result:raise ValueError('result contradicts board')
 identity=json.dumps([white.casefold(),black.casefold(),date,h.get('Event',''),h.get('Round',''),initial,[m.uci() for m in moves]],ensure_ascii=False,separators=(',',':'))
 gid=hashlib.sha256(identity.encode()).hexdigest();exporter=chess.pgn.StringExporter(headers=True,variations=False,comments=False)
 raw=game.accept(exporter)
 return gid,steps,keys,raw

def import_pgn(path,archive_sha,default_url):
 setup();sha=hashlib.sha256(path.read_bytes()).hexdigest()
 with store.connection() as db:
  db.execute('INSERT OR IGNORE INTO kc_master_imports(sha) VALUES(?)',(sha,));job=db.execute('SELECT * FROM kc_master_imports WHERE sha=?',(sha,)).fetchone();cursor=job['cursor'];accepted=job['accepted'];rejected=job['rejected']
  if job['status']=='complete':return dict(job)
 with path.open(encoding='utf8') as f:
  index=0
  while True:
   game=chess.pgn.read_game(f)
   if not game:break
   index+=1
   if index<=cursor:continue
   try:gid,steps,keys,raw=clean_game(game)
   except (ValueError,TypeError):rejected+=1
   else:
    h=game.headers;url=h.get('GameURL','');url=url if re.fullmatch(r'https://lichess\.org/broadcast/[a-zA-Z0-9/_-]+',url) else default_url
    with store.connection() as db:
     rev=store.current_revision(db);opening=None
     if keys:
      limited=keys[:40];rows=db.execute('SELECT eco,name,terminal_key FROM kc_openings WHERE revision=? AND terminal_key IN ('+','.join('?'*len(limited))+')',(rev,*limited)).fetchall()
      opening=max(rows,key=lambda r:max(i for i,k in enumerate(limited) if k==r['terminal_key']),default=None)
     inserted=db.execute('INSERT OR IGNORE INTO kc_master_games VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(gid,h['White'],h['Black'],'GM','GM',h['Date'],int(h['Date'][:4]),h.get('Event',''),h['Result'],opening['eco'] if opening else h.get('ECO',''),opening['name'] if opening else h.get('Opening',''),len(steps),game.board().fen(),raw,url,archive_sha,LICENSE,gid)).rowcount
     if inserted:
      db.executemany('INSERT INTO kc_master_moves VALUES(?,?,?,?,?,?,?,?)',[(gid,*s) for s in steps]);accepted+=1
     db.execute('UPDATE kc_master_imports SET cursor=?,accepted=?,rejected=? WHERE sha=?',(index,accepted,rejected,sha))
   if index%100==0:print('MASTER_IMPORT',index,accepted,rejected,flush=True)
   with store.connection() as db:db.execute('UPDATE kc_master_imports SET cursor=?,accepted=?,rejected=? WHERE sha=?',(index,accepted,rejected,sha))
 with store.connection() as db:db.execute("UPDATE kc_master_imports SET status='complete' WHERE sha=?",(sha,))
 return {'accepted':accepted,'rejected':rejected,'cursor':index,'sha':sha}

def search(q='',year=None,result=None,limit=12,offset=0,scope='gm'):
 from . import game_library
 if game_library.available():
  with game_library.connection(store.db_path()) as db:return game_library.search_local(db,q,year,result,limit,offset,scope)
 where=[];args=[]
 if q:
  where.append('(white LIKE ? ESCAPE \'!\' OR black LIKE ? ESCAPE \'!\' OR event LIKE ? ESCAPE \'!\' OR opening LIKE ? ESCAPE \'!\' OR eco LIKE ? ESCAPE \'!\')')
  escaped=q.replace('!','!!').replace('%','!%').replace('_','!_');args.extend(['%'+escaped+'%']*5)
 if year:where.append('year=?');args.append(year)
 if result:where.append('result=?');args.append(result)
 clause=' WHERE '+' AND '.join(where) if where else ''
 with store.connection() as db:
  total=db.execute('SELECT count(*) FROM kc_master_games'+clause,args).fetchone()[0]
  rows=db.execute('SELECT id,white,black,white_title,black_title,date,year,event,result,eco,opening,plies FROM kc_master_games'+clause+' ORDER BY date DESC,id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
  years=[r[0] for r in db.execute('SELECT DISTINCT year FROM kc_master_games ORDER BY year DESC')];all_count=db.execute('SELECT count(*) FROM kc_master_games').fetchone()[0]
 return {'items':[dict(r) for r in rows],'total':total,'all_count':all_count,'years':years,'offset':offset,'license':LICENSE,'source':'Lichess official broadcasts'}

def detail(gid):
 with store.connection() as db:
  row=db.execute('SELECT * FROM kc_master_games WHERE id=?',(gid,)).fetchone()
  if not row:
   from .game_library import detail as library_detail
   return library_detail(gid)
  result=dict(row);rows=db.execute('SELECT * FROM kc_master_moves WHERE game_id=? ORDER BY ply',(gid,)).fetchall();cache={r['fen_key']:json.loads(r['payload']) for r in db.execute('SELECT fen_key,payload FROM kc_master_evals WHERE fen_key IN ('+','.join('?'*(len(rows)+1))+')',tuple([eval_key(chess.Board(result['initial_fen']))]+[eval_key(chess.Board(r['fen'])) for r in rows]))}
 b=chess.Board(result['initial_fen']);previous=cache.get(eval_key(b));steps=[]
 for r in rows:
  move=chess.Move.from_uci(r['uci']);white=b.turn;best=(previous.get('pv') or [None])[0] if previous else None;best_san=b.san(chess.Move.from_uci(best)) if best and chess.Move.from_uci(best) in b.legal_moves else None
  b.push(move);current=json.loads(r['imported_eval']) if r['imported_eval'] else cache.get(eval_key(b));loss=None
  if r['ply']==len(rows) and b.is_game_over():current={'source':'terminal-rules','terminal':True,'result':b.result(),'engine':'python-chess legal terminal','cp_white':0 if b.outcome().winner is None else None,'mate_white':None,'pv':[],'nodes':0,'depth':0}
  if previous and current and previous.get('source')==current.get('source') and previous.get('cp_white') is not None and current.get('cp_white') is not None:loss=max(0,(previous['cp_white']-current['cp_white'])*(1 if white else -1))
  steps.append({'fen':r['fen'],'san':r['san'],'uci':r['uci'],'source':'master','note':json.loads(r['note_json']),'legal_moves':[m.uci() for m in b.legal_moves],'evaluation':current,'loss_cp_estimate':loss,'engine_choice_san':best_san,'material_white':r['material_white']});previous=current
 result.update(path=steps,initial_legal_moves=[m.uci() for m in chess.Board(result['initial_fen']).legal_moves],analysis_coverage=sum(s['evaluation'] is not None for s in steps),license_url='https://creativecommons.org/licenses/by-sa/4.0/',attribution='Lichess official broadcasts. Filtered, validated, deduplicated; board explanations and local Stockfish estimates added. Adapted game data: CC BY-SA 4.0.')
 result.pop('content_hash');return result
