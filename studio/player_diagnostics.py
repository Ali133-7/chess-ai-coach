"""Reproducible observations, not psychological diagnoses or player Elo estimates."""
import hashlib,json
from collections import Counter
import chess
from .reliability_locale import LocalizedError as HTTPException
from . import core

SKILLS={'hangingPiece':('ترك قطعة بلا حماية','Unprotected piece'),'fork':('السماح بشوكة','Allowing a fork'),'opening':('قرارات الافتتاح','Opening decisions'),'middlegame':('قرارات وسط اللعب','Middlegame decisions'),'endgame':('قرارات النهايات','Endgame decisions')}
VERSION='observations-v1'

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS player_skill_games(game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,fingerprint TEXT NOT NULL,finished_at INTEGER NOT NULL,counts_json TEXT NOT NULL,updated_at TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS player_skill_chronology ON player_skill_games(user_id,finished_at,game_id);
 CREATE TABLE IF NOT EXISTS player_skill_observations(game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,ply INTEGER NOT NULL,skill TEXT NOT NULL,loss_cp INTEGER NOT NULL,evidence_json TEXT NOT NULL,PRIMARY KEY(game_id,ply,skill));
 CREATE INDEX IF NOT EXISTS player_skill_examples ON player_skill_observations(user_id,skill,loss_cp);
 ''')

def fork_targets(board,reply,mover):
 if reply not in board.legal_moves:return []
 b=board.copy();b.push(reply);piece=b.piece_at(reply.to_square)
 if not piece:return []
 targets=[s for s in b.attacks(reply.to_square) if (p:=b.piece_at(s)) and p.color==mover and p.piece_type in (chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING)]
 return [chess.square_name(s) for s in targets] if len(targets)>=2 else []

def update_game(gid,uid=None):
 with core.connection() as db:
  g=db.execute('SELECT g.*,u.chess_username FROM games g JOIN users u ON u.id=g.user_id WHERE g.id=?'+(' AND g.user_id=?' if uid is not None else ''),(gid,uid) if uid is not None else (gid,)).fetchone()
  if not g:raise HTTPException(404,'Game not found')
  if g['stage']!='done' or g['result'] not in ('1-0','0-1','1/2-1/2') or not g['finished_at']:raise HTTPException(409,'Completed analysed games only')
  rows=[dict(x) for x in db.execute('SELECT ply,uci,san,grade,loss_cp,phase FROM moves WHERE game_id=? ORDER BY ply',(gid,))]
  fingerprint=hashlib.sha256(json.dumps([VERSION,g['pgn'],g['chess_username'],rows],sort_keys=True).encode()).hexdigest()
  previous=db.execute('SELECT fingerprint FROM player_skill_games WHERE game_id=?',(gid,)).fetchone()
  if previous and previous[0]==fingerprint:return False
 username=(g['chess_username'] or '').casefold()
 color=chess.WHITE if username and username==g['white'].casefold() else chess.BLACK if username and username==g['black'].casefold() else None
 if color is None:raise HTTPException(409,'Linked username does not identify a side in this game')
 game,positions=core.game_moves_from_pgn(g['pgn']);board=game.board();by_ply={r['ply']:r for r in rows}
 counts=Counter();observations=[]
 for i,(ply,uci,san,_,_) in enumerate(positions):
  move=chess.Move.from_uci(uci);mover=board.turn;phase=core.phase(board);board.push(move)
  if mover!=color:continue
  counts['own_game_moves']+=1;r=by_ply.get(ply)
  if not r or r['loss_cp'] is None or r['grade']=='unrated':continue
  counts['analysed']+=1;counts[phase+'_moves']+=1
  if r['grade'] not in ('weak','missed','mistake','blunder') or r['loss_cp']<45:continue
  evidence={'san':san,'actual_uci':uci,'loss_cp':r['loss_cp'],'phase':phase,'source':'saved engine grading','version':VERSION}
  motifs=[phase];piece=board.piece_at(move.to_square)
  if piece and piece.piece_type!=chess.KING and r['loss_cp']>=100:
   captures=[x.uci() for x in board.legal_moves if x.to_square==move.to_square and board.is_capture(x)]
   if captures and not board.is_attacked_by(mover,move.to_square):motifs.append('hangingPiece');evidence['legal_captures']=captures[:8]
  if i+1<len(positions):
   reply=chess.Move.from_uci(positions[i+1][1]);targets=fork_targets(board,reply,mover)
   if targets:motifs.append('fork');evidence['actual_reply_uci']=reply.uci();evidence['fork_targets']=targets
  for skill in motifs:
   counts[skill+'_errors']+=1;observations.append((gid,g['user_id'],ply,skill,r['loss_cp'],json.dumps(evidence)))
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  # Never attach another account's results if the game was deleted/replaced meanwhile.
  current=db.execute('SELECT pgn,user_id FROM games WHERE id=?',(gid,)).fetchone()
  if not current or current['user_id']!=g['user_id'] or current['pgn']!=g['pgn']:return False
  db.execute('DELETE FROM player_skill_observations WHERE game_id=?',(gid,))
  db.executemany('INSERT INTO player_skill_observations VALUES(?,?,?,?,?,?)',observations)
  db.execute('INSERT OR REPLACE INTO player_skill_games VALUES(?,?,?,?,?,?)',(gid,g['user_id'],fingerprint,g['finished_at'],json.dumps(counts),core.now()))
 return True

def profile(uid):
 with core.connection() as db:
  games=[dict(x) for x in db.execute('SELECT * FROM player_skill_games WHERE user_id=? ORDER BY finished_at,game_id',(uid,))]
  examples=[dict(x) for x in db.execute('SELECT game_id,ply,skill,loss_cp,evidence_json FROM player_skill_observations WHERE user_id=? ORDER BY loss_cp DESC,game_id DESC LIMIT 40',(uid,))]
  total=db.execute("SELECT count(*) FROM games WHERE user_id=? AND stage='done'",(uid,)).fetchone()[0]
 rows=[json.loads(g['counts_json']) for g in games]
 def aggregate(group):
  c=Counter()
  for row in group:c.update(row)
  return c
 all_counts=aggregate(rows);mid=len(rows)//2;earlier=aggregate(rows[:mid]);recent=aggregate(rows[mid:]);skills=[]
 for skill,titles in SKILLS.items():
  denominator=skill+'_moves' if skill in ('opening','middlegame','endgame') else 'analysed'
  n=all_counts[denominator];errors=all_counts[skill+'_errors'];trend=None
  if len(rows)>=10 and earlier[denominator]>=30 and recent[denominator]>=30:
   old=100*earlier[skill+'_errors']/earlier[denominator];new=100*recent[skill+'_errors']/recent[denominator]
   trend={'earlier_errors':earlier[skill+'_errors'],'earlier_moves':earlier[denominator],'recent_errors':recent[skill+'_errors'],'recent_moves':recent[denominator],'earlier_percent':round(old,2),'recent_percent':round(new,2),'change_percentage_points':round(new-old,2)}
  skills.append({'skill':skill,'title_ar':titles[0],'title_en':titles[1],'errors':errors,'analysed_moves':n,'error_percent':round(100*errors/n,2) if n else None,'trend':trend,
   'examples':[{**{k:v for k,v in x.items() if k!='evidence_json'},'evidence':json.loads(x['evidence_json'])} for x in examples if x['skill']==skill][:3]})
 skills.sort(key=lambda x:(-(x['error_percent'] or 0),-x['errors']))
 return {'games_processed':len(games),'completed_games':total,'own_game_moves':all_counts['own_game_moves'],'analysed_moves':all_counts['analysed'],'skills':skills,
  'method':'Error rate = observed engine-graded errors / analysed own moves eligible for that category. Opening/middlegame/endgame denominators use their phase only. Fork is an actual legal reply attacking at least two king/minor/major targets; this does not prove forced material loss. Hanging piece requires a legal capture, no own defender, and saved loss >=100cp.',
  'trend_method':'Chronological halves of processed games, at least 10 games and 30 eligible moves per half; descriptive, not a causal or statistical significance claim.',
  'limitations':'Linked public username is not ownership verification. Missing engine analysis is excluded. These indicators are not player Elo.'}

def install(app,auth):
 from fastapi import Depends
 from pydantic import BaseModel,Field
 class Refresh(BaseModel):limit:int=Field(default=20,ge=1,le=20)
 @app.get('/api/training/diagnostics')
 def get_profile(user=Depends(auth)):return profile(user['id'])
 @app.post('/api/training/diagnostics/refresh')
 def refresh(data:Refresh,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('diagnostics-refresh:'+str(user['id']),6,3600)
  with core.connection() as db:ids=[r[0] for r in db.execute("SELECT id FROM games WHERE user_id=? AND stage='done' ORDER BY finished_at DESC,id DESC LIMIT ?",(user['id'],data.limit))]
  changed=0;unidentified=0
  for gid in ids:
   try:changed+=int(update_game(gid,user['id']))
   except HTTPException as e:
    if e.status_code==409:unidentified+=1
    else:raise
  return {'updated':changed,'unidentified_side':unidentified,**profile(user['id'])}
 @app.get('/api/training/diagnostics/exercises')
 def exercises(skill:str,user=Depends(auth)):
  if skill not in SKILLS:raise HTTPException(422,'Unknown skill')
  from .knowledge import drills,analysis
  rating=analysis.recommendation_basis(user['id'])['reference_rating']
  result=drills.list_puzzles(rating,skill,uid=user['id'],limit=3)
  return {**result,'requested_skill':skill,'basis':'Saved own-game observations; unseen exercises matching the requested theme. Puzzle rating is not player Elo.'}
