"""Disposable browser-test server. Never opens or seeds a deployment database."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temporary=tempfile.TemporaryDirectory(prefix='chess-browser-tests-')
root=Path(temporary.name)
os.environ.update(STUDIO_DB=str(root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(root/'knowledge.sqlite3'),STUDIO_BASE_URL='http://127.0.0.1:18024',STUDIO_COOKIE_SECURE='false',CONTROL_PRIVATE_DIR=str(root/'private'),TEACHER_PROVIDERS_FILE=str(root/'no-provider.json'),TEACHER_KEY_FILE=str(root/'no-key'))
from studio.app import app,start
from studio import core
from studio.knowledge import importer
start();importer.seed()
with core.connection() as db:
 for index in range(4):
  uid=db.execute('INSERT INTO users(email,pass_hash,chess_username,role,created_at) VALUES(?,?,?,?,?)',(f'browser{index}@example.test',core.passhash('browser-fixture-only-password'),f'browser_fixture{index}','admin' if index==3 else 'user',core.now())).lastrowid
  db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid,'fixture','https://example.test/disposable-fixture','[Event "Disposable browser-test fixture"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0',1,'Browser Fixture','Test Opponent','1-0',core.now()))
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18024,access_log=False,log_level='warning')
