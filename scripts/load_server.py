"""Disposable, loopback-only mixed-load fixture. Never opens a deployment database."""
import argparse,json,os,secrets,subprocess,sys,time,random
import chess,chess.pgn
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=18026);p.add_argument('--engine',action='store_true');a=p.parse_args()
 a.root.mkdir(mode=0o700,parents=True,exist_ok=True)
 os.environ.update(STUDIO_DB=str(a.root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(a.root/'knowledge.sqlite3'),STUDIO_TELEMETRY_DB=str(a.root/'telemetry.sqlite3'),STUDIO_BASE_URL=f'http://127.0.0.1:{a.port}',STUDIO_COOKIE_SECURE='false',CONTROL_PRIVATE_DIR=str(a.root/'private'),TEACHER_PROVIDERS_FILE=str(a.root/'no-provider.json'),TEACHER_KEY_FILE=str(a.root/'no-key'),STUDIO_SMTP_HOST='',STUDIO_REQUIRE_ADMIN_MFA='false')
 from studio.app import app,start
 from studio import core,account_security
 from studio.knowledge import importer
 start();importer.seed();credentials=[];fixture_nonce=secrets.token_hex(24)
 pgn='[Event "Synthetic disposable load fixture; not a historical game"]\n[White "load_fixture"]\n[Black "fixture_opponent"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'
 encoded=core.passhash(secrets.token_urlsafe(32))
 with core.connection() as db:
  core.config_set(db,'deep_seconds',1);core.config_set(db,'multipv',1)
  for index in range(50):
   game=chess.pgn.Game();game.headers.update(Event='Synthetic disposable load fixture; not a historical game',White='load_fixture',Black='fixture_opponent',Result='1-0');board=game.board();node=game;rng=random.Random(index)
   for _ in range(8):
    if board.is_game_over():break
    move=rng.choice(list(board.legal_moves));node=node.add_variation(move);board.push(move)
   pgn=str(game)
   uid=db.execute('INSERT INTO users(email,pass_hash,chess_username,created_at) VALUES(?,?,?,?)',(f'load{index}@example.test',encoded,'load_fixture',core.now())).lastrowid
   account_security.security(db,uid);token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
   db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(account_security.digest(token),uid,csrf,int(time.time())+3600));account_security.record_session(db,account_security.digest(token))
   db.execute("INSERT INTO analysis_preferences VALUES(?,'turbo')",(uid,))
   db.execute('INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid,'fixture','https://example.test/synthetic-load-fixture',pgn,1,'load_fixture','fixture_opponent','1-0',core.now()))
   credentials.append({'cookie':token,'csrf':csrf})
 fd=os.open(a.root/'credentials.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as out:json.dump({'nonce':fixture_nonce,'users':credentials},out)
 @app.middleware('http')
 async def fixture_tag(request,call_next):
  response=await call_next(request);response.headers['X-Chess-Load-Fixture']=fixture_nonce;return response
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=a.port,log_level='warning',access_log=False)
if __name__=='__main__':main()
