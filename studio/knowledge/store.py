from contextlib import contextmanager
from pathlib import Path
import os,sqlite3
from .. import core

DATA=Path(__file__).parent/'data'
def db_path():return Path(os.getenv('CHESS_KNOWLEDGE_DB',str(core.DB.parent/'knowledge.sqlite3')))
@contextmanager
def connection():
 path=db_path();path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(str(path),timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=15000')
 try:yield db;db.commit()
 except BaseException:db.rollback();raise
 finally:db.close()

def setup():
 with connection() as db:
  db.execute('PRAGMA journal_mode=WAL')
  db.executescript('''
  CREATE TABLE IF NOT EXISTS kc_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS kc_sources(key TEXT PRIMARY KEY,url TEXT NOT NULL,license TEXT NOT NULL,revision TEXT,scope TEXT,updated_at TEXT);
  CREATE TABLE IF NOT EXISTS kc_imports(key TEXT PRIMARY KEY,kind TEXT NOT NULL,filename TEXT NOT NULL,sha256 TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',last_error TEXT,updated_at TEXT);
  CREATE TABLE IF NOT EXISTS kc_openings(revision TEXT NOT NULL,id TEXT NOT NULL,eco TEXT NOT NULL,name TEXT NOT NULL,family TEXT NOT NULL,pgn TEXT NOT NULL,uci_json TEXT NOT NULL,terminal_key TEXT NOT NULL,plies INTEGER NOT NULL,PRIMARY KEY(revision,id));
  CREATE INDEX IF NOT EXISTS kc_opening_name ON kc_openings(revision,name);
  CREATE INDEX IF NOT EXISTS kc_opening_terminal ON kc_openings(revision,terminal_key);
  CREATE TABLE IF NOT EXISTS kc_paths(revision TEXT NOT NULL,opening_id TEXT NOT NULL,ply INTEGER NOT NULL,before_key TEXT NOT NULL,position_key TEXT NOT NULL,fen TEXT NOT NULL,uci TEXT NOT NULL,san TEXT NOT NULL,PRIMARY KEY(revision,opening_id,ply),FOREIGN KEY(revision,opening_id) REFERENCES kc_openings(revision,id));
  CREATE INDEX IF NOT EXISTS kc_path_position ON kc_paths(revision,position_key);
  CREATE INDEX IF NOT EXISTS kc_path_before ON kc_paths(revision,before_key);
  CREATE TABLE IF NOT EXISTS kc_positions(key TEXT PRIMARY KEY,fen TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS kc_edges(position_key TEXT NOT NULL,uci TEXT NOT NULL,after_key TEXT NOT NULL,san TEXT NOT NULL,PRIMARY KEY(position_key,uci));
  CREATE TABLE IF NOT EXISTS kc_puzzles(id TEXT PRIMARY KEY,fen TEXT NOT NULL,setup_fen TEXT NOT NULL,moves_json TEXT NOT NULL,rating INTEGER NOT NULL,themes TEXT NOT NULL,opening_tags TEXT NOT NULL,game_url TEXT NOT NULL,source_sha TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS kc_puzzle_rating ON kc_puzzles(rating);
  CREATE TABLE IF NOT EXISTS kc_evaluations(position_key TEXT NOT NULL,source TEXT NOT NULL,depth INTEGER NOT NULL,cp_white INTEGER,mate_white INTEGER,pv_json TEXT NOT NULL,fen TEXT NOT NULL,engine TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(position_key,source));
  CREATE TABLE IF NOT EXISTS kc_external_cache(kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(kind,key));
  CREATE TABLE IF NOT EXISTS kc_network(name TEXT PRIMARY KEY,next_at REAL NOT NULL DEFAULT 0,last_status INTEGER,lock_until REAL NOT NULL DEFAULT 0,lock_token TEXT);
  INSERT OR IGNORE INTO kc_network(name,next_at) VALUES('lichess',0);
  INSERT OR REPLACE INTO kc_meta VALUES('schema_version','1');
  ''')
 with core.connection() as db:
  db.executescript('''
  CREATE INDEX IF NOT EXISTS idx_knowledge_moves_fen ON moves(fen_before,game_id);
  CREATE TABLE IF NOT EXISTS knowledge_game_reports(game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,fingerprint TEXT NOT NULL,report_json TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS knowledge_reports_owner ON knowledge_game_reports(user_id,game_id);
  CREATE TABLE IF NOT EXISTS knowledge_usage(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,day TEXT NOT NULL,engine_calls INTEGER NOT NULL DEFAULT 0,external_calls INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day));
  CREATE TABLE IF NOT EXISTS knowledge_puzzle_sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',mistakes INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,played_json TEXT);
  ''')
  cols={r['name'] for r in db.execute('PRAGMA table_info(knowledge_puzzle_sessions)')}
  if 'played_json' not in cols:db.execute('ALTER TABLE knowledge_puzzle_sessions ADD COLUMN played_json TEXT')
 from .masters import setup as setup_masters
 setup_masters()
 from . import daily_exercises,drills
 daily_exercises.setup();drills.setup()
 from .curriculum import setup as setup_curriculum
 setup_curriculum()


def current_revision(db):
 row=db.execute("SELECT value FROM kc_meta WHERE key='opening_revision'").fetchone();return row['value'] if row else ''
