from typing import Literal
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
import chess
from fastapi import Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from .. import core
from . import store,recognition,external,analysis,drills,importer

class Input(BaseModel):
 model_config=ConfigDict(extra='forbid')
class Recognize(Input):
 pgn:str=Field(default='',max_length=100000)
 fen:str=Field(default='',max_length=120)
 side:Literal['white','black']='white'
class Position(Input):
 fen:str=Field(max_length=120)
 dataset:Literal['masters','lichess','local']='masters'
 refresh_stats:bool=False
 refresh_engine:bool=False
 refresh_tablebase:bool=False
class StudyMove(Input):
 fen:str=Field(max_length=120)
 uci:str=Field(pattern='^[a-h][1-8][a-h][1-8][qrbn]?$',max_length=5)
class PuzzleStart(Input):
 puzzle_id:str=Field(min_length=1,max_length=20,pattern='^[a-zA-Z0-9]+$')
class PuzzleMove(Input):
 uci:str=Field(default='',max_length=5,pattern='^$|^[a-h][1-8][a-h][1-8][qrbn]?$')
 version:int=Field(ge=0,le=100)
 reveal:bool=False
class PuzzleSkip(Input):
 version:int=Field(ge=0,le=100)
class Update(Input):
 after_id:int=Field(default=0,ge=0)
 limit:int=Field(default=25,ge=1,le=50)
class ImportResume(Input):
 file:Literal['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv','puzzles-sample.csv','evaluations-sample.jsonl']

def status():
 with store.connection() as db:
  rev=store.current_revision(db)
  counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['kc_positions','kc_puzzles','kc_evaluations']}
  counts.update(openings=db.execute('SELECT count(*) FROM kc_openings WHERE revision=?',(rev,)).fetchone()[0],opening_steps=db.execute('SELECT count(*) FROM kc_paths WHERE revision=?',(rev,)).fetchone()[0])
  sources=[dict(r) for r in db.execute('SELECT * FROM kc_sources')];imports=[dict(r) for r in db.execute('SELECT filename,kind,cursor,accepted,rejected,status,last_error,updated_at FROM kc_imports ORDER BY filename')]
  themes={}
  for row in db.execute('SELECT themes FROM kc_puzzles'):
   for theme in set(row['themes'].split()):themes[theme]=themes.get(theme,0)+1
 return {'counts':counts,'revision':rev,'sources':sources,'imports':imports,'themes':sorted([{'theme':k,'count':v} for k,v in themes.items()],key=lambda x:x['count'],reverse=True),
         'tablebase_files':len(list((store.DATA/'syzygy').glob('*.rtb*'))),'coverage_note':'فهرس الافتتاحيات كامل بالنسبة لنسخة المصدر المحددة؛ التمارين والتقييمات عينات محدودة؛ Syzygy محلي لأساسيات ثلاث قطع، وليس كل نهايات الشطرنج.'}

def reserve_resource(uid,field):
 if field not in ('engine_calls','external_calls'):raise ValueError()
 cap=180 if field=='engine_calls' else 80;day=datetime.now(timezone.utc).date().isoformat()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT '+field+' FROM knowledge_usage WHERE user_id=? AND day=?',(uid,day)).fetchone()
  if row and row[0]>=cap:raise HTTPException(429,'وصلت إلى حد استعلامات المركز اليومي. البيانات المحفوظة تبقى متاحة.')
  db.execute('INSERT INTO knowledge_usage(user_id,day,'+field+') VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET '+field+'='+field+'+1',(uid,day))

def opening_position(fen,uid,dataset='masters',refresh_stats=False,refresh_engine=False,refresh_tb=False):
 board=recognition.valid_board(fen);key=recognition.position_key(board)
 if refresh_engine:reserve_resource(uid,'engine_calls')
 if refresh_stats or refresh_tb:reserve_resource(uid,'external_calls')
 with store.connection() as db:
  rev=store.current_revision(db)
  rows=db.execute('SELECT uci,san,position_key AS after_key,count(DISTINCT opening_id) AS catalogue_branches FROM kc_paths WHERE revision=? AND before_key=? GROUP BY uci,san,position_key ORDER BY catalogue_branches DESC',(rev,key)).fetchall()
  children=[dict(r) for r in rows]
  for child in children:
   after=board.copy();after.push_uci(child['uci']);child['fen_after']=after.fen()
 own=analysis.local_position_stats(key,uid)
 stats=own if dataset=='local' else external.explorer(board.fen(),dataset,refresh_stats)
 engine=external.evaluation(board.fen(),refresh_engine)
 tb=external.tablebase(board.fen(),refresh_tb) if len(board.piece_map())<=7 else {'available':False}
 return {'fen':board.fen(),'legal_moves':[m.uci() for m in board.legal_moves],'key':key,'opening':recognition.recognize_fen(board.fen()),'children':children,'statistics':stats,'local_statistics':own,'engine':engine,'tablebase':tb,
         'engine_best_uci':engine.get('pvs',[{}])[0].get('moves',[None])[0] if engine.get('pvs') else None,'most_popular_uci':stats.get('most_popular_uci'),
         'distinction':'الأفضل من تقييم المحرك؛ الأكثر شيوعاً من عدد مباريات العينة. عدد فروع الفهرس ليس شعبية بين اللاعبين.'}

class LessonInput(Input):
 branch_id:str|None=Field(default=None,max_length=100)

def install(app,auth):
 @app.get('/api/knowledge/traps')
 def trap_list(q:str=Query(default='',max_length=120),side:Literal['all','white','black']='all',limit:int=Query(default=12,ge=1,le=24),offset:int=Query(default=0,ge=0,le=1000),user=Depends(auth)):
  from .traps import search
  return search(q,side,limit,offset)
 @app.get('/api/knowledge/traps/{tid}')
 def trap_lesson(tid:str,variant:Literal['trap','safe']='trap',user=Depends(auth)):
  if len(tid)>100:raise HTTPException(404,'الفخ غير موجود')
  from .traps import lesson
  return lesson(tid,variant)

 @app.get('/api/knowledge/masters')
 def master_games(q:str=Query(default='',max_length=120),year:int|None=Query(default=None,ge=1700,le=2100),result:Literal['1-0','0-1','1/2-1/2']|None=None,limit:int=Query(default=12,ge=1,le=24),offset:int=Query(default=0,ge=0,le=5000000),scope:Literal['gm','all']='gm',user=Depends(auth)):
  from .masters import search
  return search(q,year,result,limit,offset,scope)
 @app.get('/api/knowledge/masters/library-status')
 def master_library_status(user=Depends(auth)):
  from .game_library import status
  return status()
 @app.get('/api/knowledge/masters/{gid}/pgn')
 def master_game_pgn(gid:str,user=Depends(auth)):
  from fastapi.responses import Response
  from .masters import detail
  if len(gid)!=64:raise HTTPException(404,'المباراة غير موجودة')
  game=detail(gid)
  import io,chess.pgn
  exported=chess.pgn.read_game(io.StringIO(game['pgn']))
  exported.headers['Source']=game['source_url']
  exported.headers['License']='CC BY-SA 4.0; https://creativecommons.org/licenses/by-sa/4.0/'
  exported.headers['Attribution']='Lichess official broadcasts; filtered and validated game data'
  payload=exported.accept(chess.pgn.StringExporter(headers=True,variations=False,comments=False))+'\n'
  return Response(payload,media_type='application/x-chess-pgn',headers={'Content-Disposition':'attachment; filename=gm-'+gid[:12]+'.pgn'})
 @app.get('/api/knowledge/masters/{gid}')
 def master_game(gid:str,user=Depends(auth)):
  if len(gid)!=64:raise HTTPException(404,'المباراة غير موجودة')
  from .masters import detail
  return detail(gid)

 @app.post('/api/knowledge/openings/{oid}/study')
 def study_lesson(oid:str,data:LessonInput,user=Depends(auth)):
  from .study import lesson
  return lesson(oid,lambda:reserve_resource(user['id'],'engine_calls'),data.branch_id)

 @app.get('/api/knowledge/status')
 def get_status(user=Depends(auth)):return status()
 @app.post('/api/knowledge/maintenance/warm')
 def warm_openings(data:Update,user=Depends(auth)):
  if user['role']!='admin':raise HTTPException(403,'التحليل الجماعي لمدير المنصة فقط')
  from .jobs import warm
  return warm(min(5,data.limit))
 @app.get('/api/knowledge/openings')
 def openings(q:str=Query(default='',max_length=120),limit:int=Query(default=40,ge=1,le=100),offset:int=Query(default=0,ge=0,le=20000),user=Depends(auth)):return recognition.search(q,limit,offset)
 @app.get('/api/knowledge/openings/{oid}')
 def opening(oid:str,user=Depends(auth)):return recognition.opening(oid)
 @app.post('/api/knowledge/openings/{oid}/match')
 def match_opening(oid:str,data:Recognize,user=Depends(auth)):
  recognition.opening(oid)
  if data.fen or not data.pgn:raise HTTPException(422,'نسبة التوافق تتطلب تسلسل PGN، لا FEN وحده')
  _,moves,boards,_=recognition.parse_pgn(data.pgn);return recognition.classify(boards,moves,data.side,only_ids=[oid])
 @app.post('/api/knowledge/recognize')
 def recognize(data:Recognize,user=Depends(auth)):
  if bool(data.fen)==bool(data.pgn):raise HTTPException(422,'أرسل PGN أو FEN واحداً فقط')
  if data.fen:return recognition.recognize_fen(data.fen)
  _,moves,boards,_=recognition.parse_pgn(data.pgn);return recognition.classify(boards,moves,data.side)
 @app.post('/api/knowledge/position')
 def position(data:Position,user=Depends(auth)):
  # Explicit refresh only. No automatic external requests while navigating the tree.
  return opening_position(data.fen,user['id'],data.dataset,data.refresh_stats,data.refresh_engine,data.refresh_tablebase)
 @app.post('/api/knowledge/move')
 def study_move(data:StudyMove,user=Depends(auth)):
  board=recognition.valid_board(data.fen)
  try:move=board.parse_uci(data.uci)
  except ValueError:raise HTTPException(422,'نقلة غير قانونية') from None
  san=board.san(move);board.push(move);return {'fen':board.fen(),'san':san,'uci':move.uci()}
 @app.get('/api/knowledge/profile')
 def profile(user=Depends(auth)):return analysis.profile(user['id'])
 @app.post('/api/knowledge/profile/update')
 def update(data:Update,user=Depends(auth)):return analysis.update_reports(user['id'],data.after_id,data.limit)
 @app.get('/api/knowledge/games/{gid}')
 def game(gid:int,user=Depends(auth)):return analysis.report_game(gid,user['id'])
 @app.get('/api/knowledge/games/{gid}/opening')
 def game_opening(gid:int,ply:int=Query(default=40,ge=0,le=600),user=Depends(auth)):
  with core.connection() as db:row=db.execute('SELECT g.*,u.chess_username FROM games g JOIN users u ON u.id=g.user_id WHERE g.id=? AND g.user_id=?',(gid,user['id'])).fetchone()
  if not row:raise HTTPException(404,'المباراة ليست ضمن حسابك')
  if row['result'] not in ('1-0','0-1','1/2-1/2') or not row['finished_at']:raise HTTPException(409,'للمباريات المكتملة فقط')
  _,moves,boards,_=recognition.parse_pgn(row['pgn']);side=analysis.own_color(row,row['chess_username']) or 'white'
  return recognition.classify(boards[:ply+1],moves[:ply],side)
 @app.get('/api/knowledge/play/{gid}')
 def play_opening(gid:str,user=Depends(auth)):
  from ..play_groq import owned,replay
  with core.connection() as db:row=owned(db,gid,user['id'])
  board,history=replay(row);b=chess.Board();boards=[b.copy(stack=False)];moves=[]
  for item in history:
   move=b.parse_uci(item['uci']);moves.append(move);b.push(move);boards.append(b.copy(stack=False))
  result=recognition.classify(boards,moves,row['player_color']);result['current_fen']=board.fen();return result
 @app.get('/api/knowledge/puzzles')
 def puzzles(rating:int=Query(default=1000,ge=0,le=5000),theme:str=Query(default='',max_length=60),opening:str=Query(default='',max_length=100),source:Literal['all','generated','original']='all',user=Depends(auth)):return drills.list_puzzles(rating,theme,opening,uid=user['id'],source=source)
 @app.get('/api/knowledge/recommendations')
 def recommendations(source:Literal['all','generated','original']='all',user=Depends(auth)):
  basis=analysis.recommendation_basis(user['id']);theme=basis['theme']
  from ..adaptive_training import evidence
  skills=evidence(user['id'])
  if skills:
   theme=skills[0]['theme'];basis['reference_rating']=max(0,min(5000,basis['reference_rating']+round(300*(skills[0]['mastery']-.5))))
  result=drills.list_puzzles(basis['reference_rating'],theme,uid=user['id'],source=source,daily_priority=True);broadened=False
  if not result['items']:
   result=drills.list_puzzles(basis['reference_rating'],uid=user['id'],broaden=True,source=source);broadened=True
  from .daily_exercises import status as daily_status
  result.update(recommended_theme=theme if not broadened else '',reason='تمارين جديدة دون تكرار؛ وُسعت المرشحات عند الحاجة' if broadened else 'تمارين لم تُعرض عليك من قبل، حسب المرجع المتاح',reference_rating=basis['reference_rating'],broadened=broadened,daily=daily_status(),history=drills.history(user['id']));return result
 @app.post('/api/knowledge/puzzles/start')
 def puzzle_start(data:PuzzleStart,user=Depends(auth)):return drills.start(data.puzzle_id,user['id'])
 @app.post('/api/knowledge/puzzles/{sid}/move')
 def puzzle_move(sid:str,data:PuzzleMove,user=Depends(auth)):return drills.move(sid,user['id'],data.uci,data.version,data.reveal)
 @app.post('/api/knowledge/puzzles/{sid}/skip')
 def puzzle_skip(sid:str,data:PuzzleSkip,user=Depends(auth)):return drills.skip(sid,user['id'],data.version)
 @app.get('/api/knowledge/puzzles/history')
 def puzzle_history(user=Depends(auth)):return drills.history(user['id'])
 @app.post('/api/knowledge/import/resume')
 def resume(data:ImportResume,user=Depends(auth)):
  if user['role']!='admin':raise HTTPException(403,'الاستيراد لمدير المنصة فقط')
  return importer.import_file(data.file,300)
