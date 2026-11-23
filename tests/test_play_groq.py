import json,tempfile,unittest,threading
from pathlib import Path
from unittest.mock import patch
import chess,httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException
from studio import core,play_groq as play
from studio.app import app
from studio.teacher_v7.router import setup_teacher

class PlayTests(unittest.TestCase):
 def setUp(self):
  self.old=core.DB;self.temp=tempfile.TemporaryDirectory();core.DB=Path(self.temp.name)/'test.sqlite3'
  core.setup();setup_teacher();play.setup_play()
  self.clients=[TestClient(app),TestClient(app)];self.headers=[];self.uids=[]
  for i,c in enumerate(self.clients):
   r=c.post('/api/auth/register',json={'email':f'play{i}@example.net','password':'test-training-pass-12345'})
   self.assertEqual(r.status_code,201,r.text)
   me=c.get('/api/me').json();self.headers.append({'X-CSRF-Token':me['csrf']});self.uids.append(me['id'])
  self.patcher=patch.object(play,'groq_settings',return_value=({'model':'openai/gpt-oss-120b'},'fake-private-secret-123'))
  self.patcher.start();self.addCleanup(self.patcher.stop)
  ready=patch.object(play,'engine_ready',return_value=True);ready.start();self.addCleanup(ready.stop)
 def tearDown(self):core.DB=self.old;self.temp.cleanup()
 def post(self,path,body,who=0):return self.clients[who].post(path,json=body,headers=self.headers[who])
 def new(self,color='white'):
  r=self.post('/api/play/games',{'color':color});self.assertEqual(r.status_code,200,r.text);return r.json()
 def test_auth_csrf_owner_and_no_external_positions(self):
  self.assertEqual(TestClient(app).get('/api/play/current').status_code,401)
  self.assertEqual(self.clients[0].post('/api/play/games',json={'color':'white'}).status_code,403)
  self.assertEqual(self.post('/api/play/games',{'color':'white','fen':chess.STARTING_FEN}).status_code,422)
  g=self.new();self.assertEqual(self.clients[1].get('/api/play/games/'+g['id']).status_code,404)
  self.assertEqual(self.post('/api/play/games/'+g['id']+'/move',{'uci':'e2e4','version':0},1).status_code,404)
 def test_move_ai_resume_and_stale_request(self):
  g=self.new();gid=g['id'];self.assertEqual(g['state'],'your_turn');self.assertEqual(len(g['legal_moves']),20)
  self.assertEqual(self.post(f'/api/play/games/{gid}/move',{'uci':'e2e5','version':0}).status_code,422)
  g=self.post(f'/api/play/games/{gid}/move',{'uci':'e2e4','version':0}).json();self.assertEqual(g['state'],'ai_turn')
  self.assertEqual(self.post(f'/api/play/games/{gid}/move',{'uci':'d2d4','version':0}).status_code,409)
  with patch.object(play,'choose_stockfish_move',return_value='e7e5'):
   r=self.post(f'/api/play/games/{gid}/ai',{'version':1});self.assertEqual(r.status_code,200,r.text)
  g=r.json();self.assertEqual(g['state'],'your_turn');self.assertEqual(g['version'],2)
  self.assertEqual(self.clients[0].get('/api/play/current').json()['game']['fen'],g['fen'])
  self.assertEqual(g['moves'],[{'uci':'e2e4','san':'e4'},{'uci':'e7e5','san':'e5'}])
 def test_ai_error_preserves_board_and_unlocks_retry(self):
  g=self.new('black');gid=g['id']
  with patch.object(play,'choose_stockfish_move',side_effect=HTTPException(503,'unavailable')):
   self.assertEqual(self.post(f'/api/play/games/{gid}/ai',{'version':0}).status_code,503)
  after=self.clients[0].get('/api/play/games/'+gid).json()
  self.assertEqual(after['fen'],chess.STARTING_FEN);self.assertEqual(after['state'],'ai_turn')
  with patch.object(play,'choose_stockfish_move',return_value='e2e4'):
   self.assertEqual(self.post(f'/api/play/games/{gid}/ai',{'version':0}).status_code,200)
 def test_duplicate_ai_requests_and_resign_while_thinking(self):
  g=self.new('black');gid=g['id'];started=threading.Event();release=threading.Event();responses=[]
  def think(board,level='strong'):started.set();release.wait(8);return 'e2e4'
  def request():responses.append(self.post(f'/api/play/games/{gid}/ai',{'version':0}))
  with patch.object(play,'choose_stockfish_move',side_effect=think) as fake:
   thread=threading.Thread(target=request);thread.start();self.assertTrue(started.wait(3))
   try:
    self.assertEqual(self.post(f'/api/play/games/{gid}/ai',{'version':0}).status_code,409)
    self.assertEqual(self.post('/api/play/games',{'color':'white'}).status_code,409)
    resigned=self.post(f'/api/play/games/{gid}/resign',{'version':0});self.assertEqual(resigned.status_code,200)
   finally:release.set();thread.join(5)
   self.assertFalse(thread.is_alive());self.assertEqual(fake.call_count,1)
  self.assertEqual(responses[0].status_code,409)
  after=self.clients[0].get('/api/play/games/'+gid).json();self.assertEqual(after['fen'],chess.STARTING_FEN);self.assertEqual(after['result'],'1-0')
 def test_game_over_and_repetition(self):
  g=self.new();gid=g['id'];moves=['f2f3','e7e5','g2g4','d8h4']
  with core.connection() as db:db.execute("UPDATE groq_training_games SET moves_json=?,version=4,status='finished' WHERE id=?",(json.dumps(moves),gid))
  result=self.clients[0].get('/api/play/games/'+gid).json();self.assertEqual(result['result'],'0-1');self.assertEqual(result['legal_moves'],[])
  self.assertEqual(self.post(f'/api/play/games/{gid}/move',{'version':4,'uci':'e2e4'}).status_code,409)
  row={'moves_json':json.dumps(['g1f3','g8f6','f3g1','f6g8']*2),'player_color':'white','status':'finished','busy_until':0,'busy_token':None,'id':gid,'version':8}
  self.assertEqual(play.pack(row)['result'],'1/2-1/2')
 def test_promotion_castling_and_en_passant_are_legal(self):
  g=self.new();gid=g['id']
  fixtures=[
   (['a2a4','h7h5','a4a5','h5h4','a5a6','h4h3','a6b7','h3g2'],'b7a8n',{'a8':'N'}),
   (['e2e4','e7e5','g1f3','b8c6','f1c4','g8f6'],'e1g1',{'g1':'K','f1':'R','e1':None,'h1':None}),
   (['e2e4','a7a6','e4e5','d7d5'],'e5d6',{'d6':'P','d5':None}),
  ]
  for moves,uci,expected in fixtures:
   with core.connection() as db:db.execute("UPDATE groq_training_games SET moves_json=?,version=?,status='active' WHERE id=?",(json.dumps(moves),len(moves),gid))
   r=self.post(f'/api/play/games/{gid}/move',{'version':len(moves),'uci':uci});self.assertEqual(r.status_code,200,r.text)
   board=chess.Board(r.json()['fen'])
   for square,symbol in expected.items():
    piece=board.piece_at(chess.parse_square(square));self.assertEqual(piece.symbol() if piece else None,symbol)
 def test_illegal_ai_move_is_rejected_and_does_not_lock_board(self):
  g=self.new('black');gid=g['id']
  with patch.object(play,'choose_stockfish_move',return_value='e2e5'):
   self.assertEqual(self.post(f'/api/play/games/{gid}/ai',{'version':0}).status_code,503)
  state=self.clients[0].get('/api/play/games/'+gid).json()
  self.assertEqual(state['fen'],chess.STARTING_FEN);self.assertEqual(state['state'],'ai_turn')
 def test_daily_limit_and_single_active_game(self):
  g=self.new('black');nextgame=self.new('black');self.assertNotEqual(g['id'],nextgame['id'])
  self.assertEqual(self.clients[0].get('/api/play/games/'+g['id']).json()['status'],'abandoned')
  day=play.datetime.now(play.timezone.utc).date().isoformat()
  with core.connection() as db:db.execute('INSERT INTO groq_training_usage(user_id,day,requests) VALUES(?,?,?)',(self.uids[0],day,play.DAILY_AI_LIMIT))
  with patch.object(play,'choose_stockfish_move') as fake:
   self.assertEqual(self.post(f"/api/play/games/{nextgame['id']}/ai",{'version':0}).status_code,429);fake.assert_not_called()
 def test_opponent_level_and_readiness_do_not_depend_on_groq(self):
  with patch.object(play,'groq_settings',side_effect=HTTPException(503,'no Groq')):
   g=self.new('black');self.assertEqual(g['opponent'],'stockfish');self.assertEqual(g['level'],'strong')
   with patch.object(play,'choose_stockfish_move',return_value='e2e4') as engine:
    response=self.post(f"/api/play/games/{g['id']}/ai",{'version':0})
    self.assertEqual(response.status_code,200,response.text);self.assertEqual(engine.call_args.args[1],'strong')
  self.assertEqual(self.post('/api/play/games',{'color':'white','level':'impossible'}).status_code,422)

if __name__=='__main__':unittest.main()
