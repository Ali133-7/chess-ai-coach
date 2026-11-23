"""Small readiness sample plus separately reported published Chess.com Glicko.
No psychometric calibration, conversion to Elo, or completion credits inferred.
"""
from datetime import datetime,timezone,timedelta
import json,secrets,time,random,hashlib
import chess,httpx
from fastapi import HTTPException,Depends
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .. import core
from . import curriculum as c

VERSION='placement-20261122-v1'
QUIZZES=['board-rook','safety-routine','pin','sicilian','candidates','pawn-structure','opposition','prophylaxis']
BOARDS=['knight','mate-one','fork','sicilian','intermezzo','weaknesses','passed-pawn','resilient-defence']
def setup():
 with core.connection() as db:db.executescript('''
 CREATE TABLE IF NOT EXISTS learning_placement_sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,revision TEXT NOT NULL,version INTEGER NOT NULL,state_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS placement_session_owner ON learning_placement_sessions(user_id,updated_at);
 CREATE TABLE IF NOT EXISTS learning_placement_results(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,revision TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS placement_result_owner ON learning_placement_results(user_id,created_at);
 CREATE TABLE IF NOT EXISTS learning_rating_snapshots(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,username TEXT NOT NULL,payload TEXT NOT NULL,fetched_at REAL NOT NULL);
 ''')
def rating_stage(rating):return next((i+1 for i,t in enumerate([600,900,1200,1400,1600,1800,2000]) if rating<t),8)
def snapshot(uid,refresh=False):
 with core.connection() as db:
  u=db.execute('SELECT chess_username FROM users WHERE id=?',(uid,)).fetchone();username=u['chess_username'] if u else None
  cached=db.execute('SELECT * FROM learning_rating_snapshots WHERE user_id=?',(uid,)).fetchone()
 if not username:return {'source':'unlinked','ratings':{},'fetched_at':None,'notice':'not_linked'}
 if cached and cached['username']==username and time.time()-cached['fetched_at']<43200:return json.loads(cached['payload'])
 if refresh and core.USERNAME_RE.fullmatch(username):
  try:
   with httpx.Client(timeout=httpx.Timeout(8,connect=3),follow_redirects=False,trust_env=False) as client:
    with client.stream('GET','https://api.chess.com/pub/player/'+username.lower()+'/stats',headers={'User-Agent':'ChessAI-Coach-Learning/1.0','Accept':'application/json'}) as response:
     response.raise_for_status();raw=bytearray()
     for chunk in response.iter_bytes():
      if len(raw)+len(chunk)>131072:raise ValueError()
      raw.extend(chunk)
   upstream=json.loads(raw);ratings={}
   if not isinstance(upstream,dict):raise ValueError()
   for fmt in ['rapid','blitz','bullet','daily']:
    st=upstream.get('chess_'+fmt) or {};last=st.get('last') or {};record=st.get('record') or {};r=last.get('rating')
    if type(r) is not int or not 0<r<5000:continue
    games=sum(max(0,int(record.get(k,0))) for k in ['win','loss','draw']);date=last.get('date');rd=last.get('rd')
    recent=type(date) in (int,float) and 0<=time.time()-date<180*86400
    reliable=games>=20 and recent and type(rd) in (int,float) and 0<=rd<=110
    ratings[fmt]={'rating':r,'games':games,'last_game_at':date,'rd':rd,'reliable':reliable,'readiness_stage':rating_stage(r)}
   result={'source':'chess.com-pubapi','ratings':ratings,'fetched_at':time.time(),'notice':'published_glicko_not_test_elo'}
   with core.connection() as db:db.execute('INSERT INTO learning_rating_snapshots VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,payload=excluded.payload,fetched_at=excluded.fetched_at',(uid,username,json.dumps(result),time.time()))
   return result
  except (httpx.HTTPError,ValueError,TypeError,OverflowError):pass
 # Old snapshots and legacy sync rows remain visible but cannot raise placement.
 if cached and cached['username']==username:
  result=json.loads(cached['payload']);result['source']='stale-cache';result['notice']='refresh_unavailable'
  for r in result['ratings'].values():r['reliable']=False
  return result
 with core.connection() as db:rows=db.execute('SELECT format,rating,wins,losses,draws,updated_at FROM ratings WHERE user_id=?',(uid,)).fetchall()
 return {'source':'local-sync','fetched_at':None,'notice':'refresh_unavailable','ratings':{r['format']:{'rating':r['rating'],'games':sum(r[k] or 0 for k in ['wins','losses','draws']),'last_game_at':None,'rd':None,'reliable':False,'readiness_stage':rating_stage(r['rating'])} for r in rows if r['rating'] and r['format'] in ['rapid','blitz','bullet','daily']}}
def latest(uid):
 with core.connection() as db:row=db.execute('SELECT result_json FROM learning_placement_results WHERE user_id=? AND revision=? ORDER BY created_at DESC LIMIT 1',(uid,VERSION)).fetchone()
 return json.loads(row[0]) if row else None
def tasks():
 result=[]
 for i,(qid,bid) in enumerate(zip(QUIZZES,BOARDS),1):
  for kind,lid in [('quiz',qid),('board',bid)]:result.append({'stage':i,'kind':kind,'lid':lid})
 return result
def pack(row):
 s=json.loads(row['state_json']);index=s['cursor'];out={'id':row['id'],'version':row['version'],'cursor':index,'total':16,'complete':index==16,'format':s['format'],'rating':s['rating'],'result':s.get('result')}
 if index<16:
  task=tasks()[index];x=c.lesson(task['lid']);q=x['quiz'];out['task']={'stage':task['stage'],'kind':task['kind'],'title':x['title']}
  if task['kind']=='quiz':out['task'].update(question=q['question'],options=[q['options'][i] for i in s['orders'][index]])
  else:
   b=c.board_for(x,x['practice_from']);out['task'].update(fen=b.fen(),side='white' if b.turn else 'black',legal_moves=[m.uci() for m in b.legal_moves],objective=x['objective'],reference_note={'ar':'اختبار قصير للتطبيق المرجعي؛ نقلة أخرى قانونية لا تعني بالضرورة أنها سيئة.','en':'A short reference exercise; another legal move is not necessarily bad.'})
 return out
def start(uid,fmt='rapid',restart=False):
 with core.connection() as db:
  old=db.execute('SELECT * FROM learning_placement_sessions WHERE user_id=? AND revision=? AND updated_at>? ORDER BY updated_at DESC LIMIT 1',(uid,VERSION,(c.utc()-timedelta(days=1)).isoformat())).fetchone()
 if old and not restart and json.loads(old['state_json'])['cursor']<16:return pack(dict(old))
 rating=snapshot(uid,True);orders=[]
 for _ in range(16):o=[0,1,2];random.SystemRandom().shuffle(o);orders.append(o)
 s={'cursor':0,'answers':[],'orders':orders,'rating':rating,'format':fmt};now=core.now();sid=secrets.token_hex(16)
 with core.connection() as db:
  db.execute('INSERT INTO learning_placement_sessions VALUES(?,?,?,?,?,?,?)',(sid,uid,VERSION,0,json.dumps(s),now,now));row=dict(db.execute('SELECT * FROM learning_placement_sessions WHERE id=?',(sid,)).fetchone())
 return pack(row)
def recommend(answers,rating,fmt):
 scores=[{'stage':i,'correct':sum(a['correct'] for a in answers if a['stage']==i),'total':2} for i in range(1,9)]
 test_stage=next((x['stage'] for x in scores if x['correct']<2),8);chosen=rating['ratings'].get(fmt);cap=chosen['readiness_stage']+1 if chosen and chosen['reliable'] else 8
 stage=min(test_stage,cap,8)
 return {'status':'assessed','start_stage':stage,'test_stage':test_stage,'rating_cap_stage':min(cap,8),'format':fmt,'rating':rating,'correct':sum(a['correct'] for a in answers),'total':16,'scores':scores,'readiness_percent':round(100*sum(a['correct'] for a in answers)/16),'basis':'earliest stage below 2/2; capped at selected reliable published rating stage + 1; thresholds are curricular heuristics, not a calibrated Elo conversion','created_at':core.now()}
def answer(sid,uid,version,answer=None,uci='',skip=False):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM learning_placement_sessions WHERE id=? AND user_id=?',(sid,uid)).fetchone()
  if not r:raise HTTPException(404,'Assessment session not found')
  row=dict(r);s=json.loads(row['state_json'])
  if row['version']!=version or s['cursor']>=16 or row['updated_at']<(c.utc()-timedelta(days=1)).isoformat():raise HTTPException(409,'Assessment changed or expired')
  task=tasks()[s['cursor']];x=c.lesson(task['lid']);correct=False
  if not skip:
   if task['kind']=='quiz':
    if answer is None or not 0<=answer<3:raise HTTPException(422,'Select an answer')
    correct=s['orders'][s['cursor']][answer]==x['quiz']['answer']
   else:
    b=c.board_for(x,x['practice_from'])
    try:m=b.parse_uci(uci)
    except ValueError:raise HTTPException(422,'Illegal move') from None
    b.push(m);correct=b.is_checkmate() if task['lid']=='mate-one' else uci==x['example']['moves'][x['practice_from']]
  s['answers'].append({'stage':task['stage'],'kind':task['kind'],'correct':bool(correct),'skipped':skip});s['cursor']+=1
  if s['cursor']==16:
   s['result']=recommend(s['answers'],s['rating'],s['format']);db.execute('INSERT INTO learning_placement_results VALUES(?,?,?,?,?)',(sid,uid,VERSION,json.dumps(s['result']),core.now()))
  row['version']+=1;row['state_json']=json.dumps(s);row['updated_at']=core.now();db.execute('UPDATE learning_placement_sessions SET version=?,state_json=?,updated_at=? WHERE id=?',(row['version'],row['state_json'],row['updated_at'],sid))
 return pack(row)
def skip_placement(uid):
 result={'status':'skipped','start_stage':1,'created_at':core.now(),'scores':[]}
 with core.connection() as db:db.execute('INSERT INTO learning_placement_results VALUES(?,?,?,?,?)',(secrets.token_hex(16),uid,VERSION,json.dumps(result),core.now()))
 return result
def install(app,auth):
 class Start(BaseModel):
  model_config=ConfigDict(extra='forbid')
  format:Literal['rapid','blitz','bullet','daily']='rapid'
  restart:bool=False
 class Answer(BaseModel):
  model_config=ConfigDict(extra='forbid')
  version:int=Field(ge=0,le=16)
  answer:int|None=Field(default=None,ge=0,le=2)
  uci:str=Field(default='',max_length=5,pattern='^$|^[a-h][1-8][a-h][1-8][qrbn]?$')
  skip:bool=False
 @app.get('/api/learning/placement')
 def status(user=Depends(auth)):return {'latest':latest(user['id']),'rating':snapshot(user['id'])}
 @app.post('/api/learning/placement/start')
 def begin(body:Start,user=Depends(auth)):return start(user['id'],body.format,body.restart)
 @app.post('/api/learning/placement/skip')
 def skip(user=Depends(auth)):return skip_placement(user['id'])
 @app.post('/api/learning/placement/{sid}/answer')
 def submit(sid:str,body:Answer,user=Depends(auth)):return answer(sid,user['id'],body.version,body.answer,body.uci,body.skip)
