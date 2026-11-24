"""Disposable browser-test server. Never opens or seeds a deployment database."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temporary=tempfile.TemporaryDirectory(prefix='chess-browser-tests-')
root=Path(temporary.name)
os.environ.update(STUDIO_DB=str(root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(root/'knowledge.sqlite3'),STUDIO_BASE_URL='http://127.0.0.1:18024',STUDIO_COOKIE_SECURE='false',CONTROL_PRIVATE_DIR=str(root/'private'),TEACHER_PROVIDERS_FILE=str(root/'no-provider.json'),TEACHER_KEY_FILE=str(root/'no-key'))
from studio.app import app,start
import studio.app as app_module
from studio import core
from studio.knowledge import importer
start();importer.seed()
# This disposable harness repeatedly signs in the same four accounts. Keep
# production rate limits intact; increase only fixture login budgets here.
original_limit=app_module.ratelimit
def fixture_limit(key,limit=6,window=900):return original_limit(key,limit*20 if key.startswith(('login:','login-ip:')) else limit,window)
app_module.ratelimit=fixture_limit
with core.connection() as db:
 for index in range(4):
  uid=db.execute('INSERT INTO users(email,pass_hash,chess_username,role,created_at) VALUES(?,?,?,?,?)',(f'browser{index}@example.test',core.passhash('browser-fixture-only-password'),f'browser_fixture{index}','admin' if index==3 else 'user',core.now())).lastrowid
  pgn='[Event "Disposable browser-test fixture"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'
  db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid,'fixture','https://example.test/disposable-fixture',pgn,1,'Browser Fixture','Test Opponent','1-0',core.now()))
  gid=db.execute("INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at,stage) VALUES(?,?,?,?,?,?,?,?,?,'done')",(uid,'fixture-done','https://example.test/unscored-browser-fixture',pgn,2,f'browser_fixture{index}','Test Opponent','1-0',core.now())).lastrowid
  # Legal moves, deliberately unrated: browser fixtures must not invent engine scores.
  _,positions=core.game_moves_from_pgn(pgn)
  for ply,uci,san,before,after in positions:db.execute("INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade,phase) VALUES(?,?,?,?,?,?,'unrated','opening')",(gid,ply,san,uci,before,after))
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18024,access_log=False,log_level='warning')
