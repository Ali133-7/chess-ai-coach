"""Compact, separately distributed public games. Read-only during ordinary browsing."""
import calendar,hashlib,io,json,os,re,sqlite3,zlib
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
import chess,chess.pgn

LICENSE='CC-BY-SA-4.0'
LICENSE_URL='https://creativecommons.org/licenses/by-sa/4.0/'
SOURCE='https://database.lichess.org/#broadcasts'
SCHEMA=2
READABLE_SCHEMAS={'1','2'}
CATALOGUE_PAGE='https://github.com/Ali133-7/chess-ai-coach/blob/main/docs/GAME_SOURCE_RESEARCH.md'
GAME_COLUMNS=('id','white','black','white_title','black_title','date','year','event','result','eco','opening','plies','initial_fen','pgn_z','evals_z','source_url','archive_url','license','source_eval_count')

def path():
 from .. import core
 return Path(os.getenv('CHESS_LIBRARY_DB',str(core.DB.parent/'master-library.sqlite3')))
@contextmanager
def connection(filename=None,write=False):
 target=Path(filename) if filename else path()
 if write:
  target.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(target.resolve().as_uri()+'?mode=rwc',uri=True,timeout=300)
 else:db=sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
 # Offline FTS checkpoints can hold the single writer while IO is throttled.
 # Web readers keep their independent short timeout on the immutable catalogue.
 db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=300000' if write else 'PRAGMA busy_timeout=5000')
 try:yield db;db.commit()
 except BaseException:db.rollback();raise
 finally:db.close()

def setup(filename):
 with connection(filename,True) as db:
  if db.execute("SELECT 1 FROM sqlite_master WHERE name='library_meta'").fetchone():
   version=db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
   if version and version[0] not in READABLE_SCHEMAS:raise ValueError('Unsupported library schema; preserve existing database')
  db.execute('PRAGMA journal_mode=WAL')
  db.executescript('''
  CREATE TABLE IF NOT EXISTS library_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS library_archives(url TEXT PRIMARY KEY,sha256 TEXT NOT NULL,scope TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,skipped INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',reasons_json TEXT NOT NULL DEFAULT '{}',source_id TEXT NOT NULL DEFAULT 'lichess-broadcasts');
  CREATE TABLE IF NOT EXISTS library_games(id TEXT PRIMARY KEY,white TEXT NOT NULL,black TEXT NOT NULL,white_title TEXT NOT NULL,black_title TEXT NOT NULL,date TEXT NOT NULL,year INTEGER NOT NULL,event TEXT NOT NULL,result TEXT NOT NULL,eco TEXT NOT NULL,opening TEXT NOT NULL,plies INTEGER NOT NULL,initial_fen TEXT NOT NULL,pgn_z BLOB NOT NULL,evals_z BLOB NOT NULL,source_url TEXT NOT NULL,archive_url TEXT NOT NULL REFERENCES library_archives(url),license TEXT NOT NULL,source_eval_count INTEGER NOT NULL);
  CREATE INDEX IF NOT EXISTS library_games_date ON library_games(date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_year ON library_games(year,date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_gm ON library_games(white_title,black_title,date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_eco ON library_games(eco,date DESC,id);
  CREATE TABLE IF NOT EXISTS library_provenance(game_id TEXT NOT NULL REFERENCES library_games(id) ON DELETE CASCADE,archive_url TEXT NOT NULL REFERENCES library_archives(url),ordinal INTEGER NOT NULL,PRIMARY KEY(game_id,archive_url));
  CREATE VIRTUAL TABLE IF NOT EXISTS library_search USING fts5(white,black,event,opening,eco,content='library_games',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2');
  CREATE TRIGGER IF NOT EXISTS library_search_insert AFTER INSERT ON library_games BEGIN INSERT INTO library_search(rowid,white,black,event,opening,eco) VALUES(new.rowid,new.white,new.black,new.event,new.opening,new.eco); END;
  ''')
  db.execute('CREATE TABLE IF NOT EXISTS library_sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,page TEXT NOT NULL,license TEXT NOT NULL,license_url TEXT NOT NULL,attribution TEXT NOT NULL,evidence TEXT NOT NULL,category TEXT NOT NULL)')
  db.execute('CREATE TABLE IF NOT EXISTS library_merges(id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,source_schema INTEGER NOT NULL,games_read INTEGER NOT NULL,games_added INTEGER NOT NULL,duplicates INTEGER NOT NULL,merged_at TEXT NOT NULL)')
  from .library_sources import SOURCES
  for source in SOURCES.values():
   db.execute('INSERT OR IGNORE INTO library_sources VALUES(?,?,?,?,?,?,?,?)',tuple(source[k] for k in ('id','name','page','license','license_url','attribution','evidence','category')))
  if 'source_id' not in {r['name'] for r in db.execute('PRAGMA table_info(library_archives)')}:
   # SQLite cannot add a REFERENCES column with a non-null default to populated
   # databases. Registry membership is checked explicitly by the importer/verifier.
   db.execute("ALTER TABLE library_archives ADD COLUMN source_id TEXT NOT NULL DEFAULT 'lichess-broadcasts'")
  db.execute('CREATE INDEX IF NOT EXISTS library_archive_source ON library_archives(source_id)')
  db.execute('CREATE INDEX IF NOT EXISTS library_game_archive ON library_games(archive_url,date DESC,id)')
  db.execute('CREATE INDEX IF NOT EXISTS library_provenance_archive ON library_provenance(archive_url,game_id)')
  db.execute('INSERT OR REPLACE INTO library_meta VALUES(?,?)',('schema_version',str(SCHEMA)))
  db.execute('INSERT OR REPLACE INTO library_meta VALUES(?,?)',('license',LICENSE))
  db.execute('INSERT OR REPLACE INTO library_meta VALUES(?,?)',('source_page',SOURCE))

def available():
 if not path().is_file():return False
 try:
  with connection() as db:return db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()[0] in READABLE_SCHEMAS
 except (OSError,sqlite3.Error,TypeError):return False

def unpack(blob,maximum=2*1024*1024):
 stream=zlib.decompressobj();raw=stream.decompress(blob,maximum+1)
 if len(raw)>maximum or stream.unconsumed_tail or stream.unused_data or not stream.eof:raise ValueError('Invalid or oversized library payload')
 return raw.decode('utf8')

def repetition_key(board):
 # Public board attributes; legal en-passant and castling rights affect repetition.
 return (board.pawns,board.knights,board.bishops,board.rooks,board.queens,board.kings,board.occupied_co[chess.WHITE],board.occupied_co[chess.BLACK],board.turn,board.clean_castling_rights(),board.ep_square if board.has_legal_en_passant() else None)

def pack_game(game,archive_url,body_result=None,source_id='lichess-broadcasts'):
 from .library_sources import get
 source=get(source_id)
 h=game.headers
 if game.errors or h.get('Variant','Standard') not in ('Standard','Chess'):raise ValueError('invalid_or_nonstandard')
 date=h.get('Date','')
 if not re.fullmatch(r'(17|18|19|20)\d{2}\.(\d{2}|\?\?)\.(\d{2}|\?\?)',date):date=h.get('UTCDate','')
 if not re.fullmatch(r'(17|18|19|20)\d{2}\.(\d{2}|\?\?)\.(\d{2}|\?\?)',date):raise ValueError('unknown_year')
 if date[5:7]!='??' and not 1<=int(date[5:7])<=12:raise ValueError('invalid_date')
 if date[8:]!='??' and not 1<=int(date[8:])<=31:raise ValueError('invalid_date')
 if '??' not in date and int(date[8:])>calendar.monthrange(int(date[:4]),int(date[5:7]))[1]:raise ValueError('invalid_date')
 for key in ('White','Black'):
  if not h.get(key,'').strip() or h[key]=='?' or len(h[key])>160:raise ValueError('missing_player_name')
 result=h.get('Result')
 if result not in ('1-0','0-1','1/2-1/2') or body_result!=result:raise ValueError('unfinished_or_truncated')
 board=game.board()
 if not board.is_valid() or board.chess960 or board.has_chess960_castling_rights():raise ValueError('invalid_initial_position')
 initial=board.fen();moves=[];evals=[];seen=Counter({repetition_key(board):1})
 for node in game.mainline():
  move=node.move
  # Legal-move membership already rules out continuation after mate/stalemate.
  # Count repetition incrementally rather than replaying the history every ply.
  if len(moves)>=600 or move not in board.legal_moves or board.is_insufficient_material() or board.halfmove_clock>=150 or seen[repetition_key(board)]>=5:raise ValueError('invalid_continuation')
  moves.append(move.uci());board.push(move);seen[repetition_key(board)]+=1;evaluation=node.eval()
  if evaluation is None:evals.append(None)
  else:
   score=evaluation.pov(chess.WHITE);evals.append([score.score(),score.mate(),node.eval_depth()])
 if not moves:raise ValueError('no_recorded_moves')
 outcome=board.outcome()
 if outcome and outcome.result()!=result:raise ValueError('result_contradicts_board')
 h['Date']=date
 identity=json.dumps([h['White'].strip().casefold(),h['Black'].strip().casefold(),date,h.get('Event',''),h.get('Round',''),initial,moves],ensure_ascii=False,separators=(',',':'))
 gid=hashlib.sha256(identity.encode()).hexdigest()
 # No human annotations or side variations are silently relicensed/imported.
 raw=game.accept(chess.pgn.StringExporter(headers=True,variations=False,comments=False))
 if len(raw.encode())>1024*1024:raise ValueError('oversized_game')
 url=h.get('GameURL','')
 if source_id!='lichess-broadcasts':url=source['page']
 elif not re.fullmatch(r'https://lichess\.org/broadcast/[A-Za-z0-9/_-]+',url):url=archive_url
 return (gid,h['White'].strip(),h['Black'].strip(),h.get('WhiteTitle',''),h.get('BlackTitle',''),date,int(date[:4]),h.get('Event','')[:500],result,h.get('ECO','')[:10],h.get('Opening','')[:300],len(moves),initial,zlib.compress(raw.encode(),9),zlib.compress(json.dumps(evals,separators=(',',':')).encode(),9),url,archive_url,source['license'],sum(x is not None for x in evals))

def sources_for(db):
 from .library_sources import get
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='library_sources'").fetchone():
  return [dict(r) for r in db.execute('SELECT DISTINCT s.* FROM library_sources s JOIN library_archives a ON a.source_id=s.id ORDER BY s.id')]
 return [get('lichess-broadcasts')]

def archive_source(db,url):
 from .library_sources import get
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='library_sources'").fetchone():
  row=db.execute('SELECT s.* FROM library_sources s JOIN library_archives a ON a.source_id=s.id WHERE a.url=?',(url,)).fetchone()
  if row:return dict(row)
  raise ValueError('Missing source policy for archive')
 return get('lichess-broadcasts')

def detail(gid):
 from fastapi import HTTPException
 if not re.fullmatch('[0-9a-f]{64}',gid) or not available():raise HTTPException(404,'المباراة غير موجودة')
 with connection() as db:
  row=db.execute('SELECT * FROM library_games WHERE id=?',(gid,)).fetchone()
  if not row:raise HTTPException(404,'المباراة غير موجودة')
  source=archive_source(db,row['archive_url'])
  provenance=[dict(x) for x in db.execute('SELECT a.url,a.sha256,p.ordinal FROM library_provenance p JOIN library_archives a ON a.url=p.archive_url WHERE p.game_id=?',(gid,))]
 result=dict(row);raw=unpack(result.pop('pgn_z'));evals=json.loads(unpack(result.pop('evals_z')))
 game=chess.pgn.read_game(io.StringIO(raw));board=game.board();steps=[];previous=None
 from .study import explain
 for index,move in enumerate(game.mainline_moves()):
  if move not in board.legal_moves:raise ValueError('Corrupt library game')
  san=board.san(move);note=explain(board,move);mover=board.turn;board.push(move);score=evals[index]
  current={'cp_white':score[0],'mate_white':score[1],'depth':score[2],'engine':source['name']+' annotation; engine settings unknown','source':'broadcast-eval' if source['id']=='lichess-broadcasts' else 'archive-eval','nodes':None,'pv':[]} if score else None
  # Source scores can come from different engines/budgets. Never grade moves by their difference.
  loss=None
  if board.is_game_over():current={'source':'terminal-rules','terminal':True,'result':board.result(),'engine':'python-chess legal terminal','cp_white':0 if board.outcome().winner is None else None,'mate_white':None,'pv':[],'nodes':0,'depth':0}
  material=sum((1 if p.color else -1)*{1:1,2:3,3:3,4:5,5:9,6:0}[p.piece_type] for p in board.piece_map().values())
  steps.append({'fen':board.fen(),'san':san,'uci':move.uci(),'source':'master','note':note,'legal_moves':[m.uci() for m in board.legal_moves],'evaluation':current,'loss_cp_estimate':loss,'engine_choice_san':None,'material_white':material});previous=current
 if len(steps)!=result['plies'] or len(evals)!=len(steps):raise ValueError('Incomplete library game')
 result.update(pgn=raw,path=steps,initial_legal_moves=[m.uci() for m in game.board().legal_moves],analysis_coverage=sum(s['evaluation'] is not None for s in steps),license_url=source['license_url'],attribution=source['attribution']+' Changes: complete legal mainlines, normalized metadata and deduplication. Original board-fact notes: CC BY-SA 4.0.',notes_license=LICENSE,provenance=provenance,source=source,storage='compact-local-library',analysis_notice='Source scores have unknown engine settings; missing evaluations remain unscored. Board-fact explanations are not a claim of best play.')
 return result

def search_local(db,q='',year=None,result=None,limit=12,offset=0,scope='gm',source_id=None):
 """Merge immutable catalogue with the existing seed, excluding identical game IDs.

 FTS uses ANDed word prefixes; parameters never become executable FTS syntax.
 Legacy small seed keeps literal substring matching for backwards compatibility.
 """
 target=path().resolve().as_uri()+'?mode=ro'
 db.execute('ATTACH DATABASE ? AS library',(target,))
 multi=db.execute("SELECT 1 FROM library.sqlite_master WHERE name='library_sources'").fetchone() is not None
 catalog_sources=[dict(r) for r in db.execute('SELECT DISTINCT s.* FROM library.library_sources s JOIN library.library_archives a ON a.source_id=s.id ORDER BY s.id')] if multi else []
 columns='id,white,black,white_title,black_title,date,year,event,result,eco,opening,plies'
 seed_where=[];large_where=[];seed_args=[];large_args=[]
 from . import player_names
 player=player_names.resolve(q)
 if source_id:
  if source_id!='lichess-broadcasts':seed_where.append('0')
  if multi:
   large_where.append('id IN (SELECT p.game_id FROM library.library_provenance p JOIN library.library_archives a ON a.url=p.archive_url WHERE a.source_id=?)');large_args.append(source_id)
  elif source_id!='lichess-broadcasts':large_where.append('0')
 if scope=='gm':
  seed_where.append("white_title='GM' AND black_title='GM'");large_where.append("white_title='GM' AND black_title='GM'")
 if player:
  clause,values=player_names.seed_filter(db,player);seed_where.append(clause);seed_args.extend(values)
  large_where.append('rowid IN (SELECT rowid FROM library.library_search WHERE library_search MATCH ?)');large_args.append(player_names.fts_query(player))
 elif q:
  escaped=q.replace('!','!!').replace('%','!%').replace('_','!_')
  seed_where.append('('+' OR '.join(c+" LIKE ? ESCAPE '!'" for c in ('white','black','event','opening','eco'))+')');seed_args.extend(['%'+escaped+'%']*5)
  words=re.findall(r'[^\W_]+',q,flags=re.UNICODE)[:12]
  if words and len(''.join(words))>=2:
   large_where.append('rowid IN (SELECT rowid FROM library.library_search WHERE library_search MATCH ?)');large_args.append(' AND '.join('"'+word+'"*' for word in words))
  else:large_where.append('0')
 for key,value in (('year',year),('result',result)):
  if value is not None:
   seed_where.append(key+'=?');large_where.append(key+'=?');seed_args.append(value);large_args.append(value)
 large_filter=' AND '.join(large_where) if large_where else '1'
 large_where.append('NOT EXISTS (SELECT 1 FROM seed_matches seed WHERE seed.id=library_games.id)')
 seed_sql='SELECT '+columns+' FROM main.kc_master_games'+(' WHERE '+' AND '.join(seed_where) if seed_where else '')
 prefix='WITH seed_matches AS ('+seed_sql+') '
 sql='SELECT * FROM seed_matches UNION ALL SELECT '+columns+' FROM library.library_games WHERE '+' AND '.join(large_where)
 args=(*seed_args,*large_args)
 rows=db.execute(prefix+'SELECT * FROM ('+sql+') ORDER BY date DESC,id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
 total=db.execute(prefix+'SELECT (SELECT count(*) FROM seed_matches)+(SELECT count(*) FROM library.library_games WHERE '+large_filter+')-(SELECT count(*) FROM library.library_games WHERE '+large_filter+' AND id IN (SELECT id FROM seed_matches))',(*seed_args,*large_args,*large_args)).fetchone()[0]
 # Walk distinct indexed year boundaries instead of reading a year from every
 # game. This matters on cold million-record catalogues with bounded RAM.
 years=[r[0] for r in db.execute('''WITH RECURSIVE archive_years(year) AS (
  SELECT max(year) FROM library.library_games
  UNION ALL
  SELECT (SELECT max(g.year) FROM library.library_games g WHERE g.year<archive_years.year)
  FROM archive_years WHERE year IS NOT NULL
 ) SELECT year FROM main.kc_master_games
 UNION SELECT year FROM archive_years WHERE year IS NOT NULL ORDER BY year DESC''')]
 all_count=db.execute('SELECT (SELECT count(*) FROM main.kc_master_games)+(SELECT count(*) FROM library.library_games)-(SELECT count(*) FROM main.kc_master_games seed JOIN library.library_games g ON g.id=seed.id)').fetchone()[0]
 return {'items':[dict(r) for r in rows],'total':total,'all_count':all_count,'years':years,'offset':offset,'license':LICENSE,'source':'Licensed public archives' if multi else 'Lichess official broadcasts','sources':catalog_sources,'source_id':source_id,'scope':scope,'expanded_library':True,'search_mode':'known-player-alias' if player else 'word-prefixes','player_match':player_names.public(player),'coverage_notice':'Only accepted records in the installed archives; not all chess games. Source numerical scores have unknown engine settings; titles are never inferred from player names.'}

def status():
 if not available():return {'installed':False,'games':0,'gm_vs_gm':0,'source_page':SOURCE,'license':LICENSE}
 with connection() as db:
  stats=dict(db.execute("SELECT count(*) games,coalesce(sum(white_title='GM' AND black_title='GM'),0) gm_vs_gm,coalesce(sum(plies),0) plies,coalesce(sum(source_eval_count),0) source_evaluations,min(year) first_year,max(year) last_year FROM library_games").fetchone())
  archives=[dict(x) for x in db.execute('SELECT * FROM library_archives ORDER BY url')]
  sources=sources_for(db)
 return {'installed':True,**stats,'archives':archives,'sources':sources,'source_page':sources[0]['page'] if len(sources)==1 else CATALOGUE_PAGE,'license':LICENSE,'license_url':LICENSE_URL,'file_bytes':path().stat().st_size,'scope_notice':'Coverage is limited to listed source archives and accepted records. This is not every chess game ever played or the Chessgames.com archive.'}
