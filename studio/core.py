"""Studio v6 multi-user domain. All tables use user_id and no legacy data is exposed."""
from __future__ import annotations
import hashlib, hmac, io, json, os, re, secrets, sqlite3, time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import chess, chess.pgn
from .analysis_speed import DEFAULT_PRESET, effective_budget

DB = Path(os.getenv('STUDIO_DB', '/studio-data/studio.sqlite3'))
USERNAME_RE = re.compile(r'^[A-Za-z0-9_-]{3,25}$')
EMAIL_RE = re.compile(r'^[^\s@]{1,64}@[^\s@]{1,190}$')
LEVELS = [
    ('01', 1, 'افحص التهديدات قبل كل نقلة', 'تجنب الأخطاء الفادحة', ['blunder', 'mistake']),
    ('02', 1, 'لا تترك قطعك دون حماية', 'اكتشاف النقلات الضعيفة', ['mistake', 'weak']),
    ('03', 2, 'لا تفوّت النقلة الحاسمة', 'معالجة الفرص الضائعة', ['missed', 'blunder']),
    ('04', 2, 'طوّر النقلات الجيدة إلى ممتازة', 'المقارنة بين بدائل المحرك', ['weak', 'mistake', 'good']),
    ('05', 3, 'إتقان وسط اللعب من مبارياتك', 'مراجعة قرارات فعلية', ['blunder', 'mistake', 'missed', 'weak']),
    ('06', 3, 'اختبار المستوى وإعادة المراجعة', 'اختبار تطبيقي قبل التخرج', ['blunder', 'mistake', 'missed', 'weak']),
]
GRADE_LABELS = {'book':'من الكتاب','brilliant':'مدهشة','excellent':'ممتازة','good':'جيدة',
                'weak':'ضعيفة','missed':'ضياع فرصة','mistake':'خطأ','blunder':'خطأ فادح', 'unrated':'غير مُقيّمة'}

def now():return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(str(DB),timeout=40)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=40000')
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except:
        db.rollback();raise
    finally:db.close()

def setup():
 with connection() as db:
  db.execute('PRAGMA journal_mode=WAL')
  db.executescript('''
  CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, pass_hash TEXT NOT NULL,
       chess_username TEXT, theme TEXT NOT NULL DEFAULT 'dark', board_theme TEXT DEFAULT 'classic', target_rating INTEGER DEFAULT 1000,
       rating_format TEXT DEFAULT 'rapid', role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL,
       disabled INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       csrf TEXT NOT NULL,expires_at INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS auth_attempts(key TEXT PRIMARY KEY, n INTEGER, expires_at INTEGER);
  CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       external_id TEXT NOT NULL,url TEXT NOT NULL,pgn TEXT NOT NULL,finished_at INTEGER NOT NULL,
       white TEXT NOT NULL, black TEXT NOT NULL, result TEXT NOT NULL, time_class TEXT,
       stage TEXT NOT NULL DEFAULT 'pending', completed_positions INTEGER DEFAULT 0,total_positions INTEGER DEFAULT 0,
       error TEXT,created_at TEXT NOT NULL, updated_at TEXT,
       UNIQUE(user_id,external_id));
  CREATE INDEX IF NOT EXISTS idx_studio_games ON games(user_id,finished_at DESC);
  CREATE INDEX IF NOT EXISTS idx_studio_queue ON games(stage,finished_at DESC);
  CREATE TABLE IF NOT EXISTS moves(game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,ply INTEGER,
       san TEXT NOT NULL,uci TEXT NOT NULL,fen_before TEXT NOT NULL,fen_after TEXT NOT NULL,
       grade TEXT NOT NULL, loss_cp INTEGER, eval_cp_white INTEGER, best_uci TEXT,best_san TEXT,
       book_name TEXT, lines_json TEXT, phase TEXT, PRIMARY KEY(game_id,ply));
  CREATE INDEX IF NOT EXISTS idx_studio_move_grade ON moves(game_id,grade);
  CREATE TABLE IF NOT EXISTS position_scans(game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,ply INTEGER,
       fen TEXT NOT NULL, scan_json TEXT NOT NULL, PRIMARY KEY(game_id,ply));
  CREATE TABLE IF NOT EXISTS archive_months(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       path TEXT, checked_at TEXT, PRIMARY KEY(user_id,path));
  CREATE TABLE IF NOT EXISTS ratings(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       format TEXT, rating INTEGER, best INTEGER, wins INTEGER,losses INTEGER,draws INTEGER,updated_at TEXT,
       PRIMARY KEY(user_id,format));
  CREATE TABLE IF NOT EXISTS lesson_attempts(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       lesson_id TEXT, passed INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,passed_at TEXT,
       PRIMARY KEY(user_id,lesson_id));
  CREATE TABLE IF NOT EXISTS lesson_solves(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       lesson_id TEXT,game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
       ply INTEGER, solved_at TEXT,PRIMARY KEY(user_id,lesson_id,game_id,ply));
  CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS worker_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS analysis_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
       preset TEXT NOT NULL DEFAULT 'fast' CHECK(preset IN ('turbo','fast','balanced','detailed','deep')));
  ''')
  for key,val in [('deep_seconds','120'),('multipv','3'),('worker_paused','false'),('archive_refresh_hours','6'),('max_games_per_user','3000'),('registration_open','true')]:
   db.execute('INSERT OR IGNORE INTO app_config(key,value) VALUES (?,?)',(key,val))

  from .control_store import setup as setup_control
  setup_control(db)
  from .analysis_runtime import setup as setup_analysis_runtime
  setup_analysis_runtime(db)
  from .adaptive_training import setup as setup_adaptive
  setup_adaptive(db)
  from .analysis_evidence import setup as setup_evidence
  setup_evidence(db)
  from .player_diagnostics import setup as setup_diagnostics
  setup_diagnostics(db)
  from .account_security import setup as setup_accounts
  setup_accounts(db)

def passhash(password):
 salt=secrets.token_bytes(16)
 digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
 return 'pbkdf2_sha256$600000$'+salt.hex()+'$'+digest.hex()

def verify(password,encoded):
 try:
  algorithm,iters,salt,key=encoded.split('$')
  return algorithm=='pbkdf2_sha256' and 300000<=int(iters)<=1000000 and hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(iters)),bytes.fromhex(key))
 except (ValueError,TypeError):return False

def safe_user(u):return bool(USERNAME_RE.fullmatch(u))

def config(db,key,default=''):
 row=db.execute('SELECT value FROM app_config WHERE key=?',(key,)).fetchone()
 return row['value'] if row else default

def config_set(db,key,val):db.execute('UPDATE app_config SET value=? WHERE key=?',(str(val),key))

def user_analysis_speed(db, user_id):
    """Read preference and shared worker limits; use for every new engine scan."""
    row = db.execute('SELECT preset FROM analysis_preferences WHERE user_id=?', (user_id,)).fetchone()
    preset = row['preset'] if row else DEFAULT_PRESET
    budget = effective_budget(preset, config(db, 'deep_seconds', '120'), config(db, 'multipv', '3'))
    budget['worker_paused'] = config(db, 'worker_paused', 'false') == 'true'
    return budget


def grade_for(played_is_best, loss, before, after, before_board, move, book_name=''):
 if book_name and played_is_best:return 'book'
 if not played_is_best and before>=300 and after<80 and loss>=180:return 'missed'
 if loss>=280:return 'blunder'
 if loss>=130:return 'mistake'
 if loss>=45:return 'weak'
 if played_is_best and loss<=12:
  # Brilliant reserved for verified non-obvious material sacrifice; not awarded heuristically.
  return 'excellent'
 return 'good'

def phase(board: chess.Board):
 if board.fullmove_number<=10:return 'opening'
 nonpawn=sum(1 for p in board.piece_map().values() if p.piece_type not in (chess.PAWN,chess.KING))
 return 'endgame' if nonpawn<=5 else 'middlegame'

OWN_MOVE_SQL = "((lower(g.white)=lower(u.chess_username) AND m.ply%2=1) OR (lower(g.black)=lower(u.chess_username) AND m.ply%2=0))"

def _lesson_candidates(db,user_id,categories,side='any'):
    if side not in ('any','white','black'):
        raise ValueError('Invalid lesson side')
    base="FROM moves m JOIN games g ON m.game_id=g.id JOIN users u ON u.id=g.user_id WHERE g.user_id=? AND m.best_uci IS NOT NULL AND "+OWN_MOVE_SQL
    if side=='white':base+=' AND m.ply%2=1'
    if side=='black':base+=' AND m.ply%2=0'
    found=[];seen=set()
    for wanted in (categories,['blunder','mistake','missed','weak'],['good','excellent','book']):
        clauses=','.join('?'*len(wanted))
        rows=db.execute(f"SELECT m.*,g.white,g.black,g.url,g.id game_id {base} AND m.grade IN ({clauses}) ORDER BY COALESCE(m.loss_cp,0) DESC,g.finished_at DESC LIMIT 100",[user_id,*wanted]).fetchall()
        for item in rows:
            key=(item['game_id'],item['ply'])
            if key not in seen:found.append(item);seen.add(key)
            if len(found)>=30:return found
    return found

def course_outline(db,user_id):
    attempts={r['lesson_id']:dict(r) for r in db.execute('SELECT * FROM lesson_attempts WHERE user_id=?',(user_id,))}
    result=[];all_prev_passed=True
    for lid,stage,title,goal,categories in LEVELS:
        pool=_lesson_candidates(db,user_id,categories)
        a=attempts.get(lid,{})
        progress=db.execute('SELECT COUNT(*) FROM lesson_solves WHERE user_id=? AND lesson_id=?',(user_id,lid)).fetchone()[0]
        required=min(3,len(pool))
        unlocked=all_prev_passed and required>0
        result.append({'id':lid,'stage':stage,'title':title,'goal':goal,
          'source_positions':len(pool),'solved':progress,'required':required,
          'source_grade':pool[0]['grade'] if pool else None,
          'passed':bool(a.get('passed')),'attempts':a.get('attempts',0),'unlocked':unlocked})
        if not a.get('passed'):all_prev_passed=False
    return result

def choose_lesson_position(db,user_id,lid,side='any'):
    """Pick *the player's* next lesson position; mix black/white when both are available."""
    lesson=next((l for l in LEVELS if l[0]==lid),None)
    if not lesson:return None
    if side not in ('any','white','black'):raise ValueError('Invalid lesson side')
    solved={(x['game_id'],x['ply']) for x in db.execute(
        'SELECT game_id,ply FROM lesson_solves WHERE user_id=? AND lesson_id=?',(user_id,lid))}
    if side!='any':
        pool=_lesson_candidates(db,user_id,lesson[4],side)
        return next((m for m in pool if (m['game_id'],m['ply']) not in solved),pool[0] if pool else None)
    white=_lesson_candidates(db,user_id,lesson[4],'white')
    black=_lesson_candidates(db,user_id,lesson[4],'black')
    last=db.execute("""SELECT m.ply FROM lesson_solves ls
        JOIN moves m ON ls.game_id=m.game_id AND ls.ply=m.ply
        WHERE ls.user_id=? AND ls.lesson_id=? ORDER BY ls.solved_at DESC LIMIT 1""",
        (user_id,lid)).fetchone()
    # After a white exercise prefer black; after black prefer white. On new lessons prefer black.
    prefer_black=not last or last['ply']%2==1
    ordered=(black+white) if prefer_black else (white+black)
    return next((m for m in ordered if (m['game_id'],m['ply']) not in solved),ordered[0] if ordered else None)

def game_analysis_counts(db,user_id,scope='mine'):
    data={k:0 for k in GRADE_LABELS}
    where='AND '+OWN_MOVE_SQL if scope=='mine' else ''
    for row in db.execute(f"SELECT m.grade,COUNT(*) n FROM moves m JOIN games g ON m.game_id=g.id JOIN users u ON u.id=g.user_id WHERE g.user_id=? {where} GROUP BY m.grade",(user_id,)):
        data[row['grade']]=row['n']
    return data

def game_moves_from_pgn(pgn):
 game=chess.pgn.read_game(io.StringIO(pgn))
 if not game or game.headers.get('Result') not in ('1-0','0-1','1/2-1/2'):raise ValueError('Unfinished/invalid PGN')
 board=game.board();out=[]
 for ply,move in enumerate(game.mainline_moves(),1):
  if move not in board.legal_moves:raise ValueError('Illegal move')
  before=board.fen();san=board.san(move);uci=move.uci()
  board.push(move);out.append((ply,uci,san,before,board.fen()))
 return game,out
