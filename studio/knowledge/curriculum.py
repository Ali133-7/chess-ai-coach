"""Local, versioned teaching path. Account-owned progress; server-checked practice.

Completion is an activity measure, never an Elo estimate or a professional title.
The source line is a reference exercise, not a claim that all alternatives lose.
"""
from functools import lru_cache
from datetime import datetime,timezone,timedelta
from pathlib import Path
import copy,json,secrets,random
import chess
from fastapi import HTTPException
from .. import core
from . import study

def setup():
 with core.connection() as db:
  db.executescript('''
  CREATE TABLE IF NOT EXISTS learning_progress(
   user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   revision TEXT NOT NULL,lesson_id TEXT NOT NULL,completed_at TEXT NOT NULL,
   independent INTEGER NOT NULL DEFAULT 0,review_count INTEGER NOT NULL DEFAULT 0,
   due_at TEXT NOT NULL,last_session TEXT NOT NULL,
   PRIMARY KEY(user_id,revision,lesson_id));
  CREATE INDEX IF NOT EXISTS learning_due ON learning_progress(user_id,revision,due_at);
  CREATE TABLE IF NOT EXISTS learning_sessions(
   id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   revision TEXT NOT NULL,lesson_id TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,
   state_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS learning_session_owner ON learning_sessions(user_id,revision,lesson_id,updated_at);
  ''')
 from . import placement,learning_plans
 placement.setup();learning_plans.setup()

@lru_cache(maxsize=1)
def data():return json.loads((Path(__file__).parent/'data/curriculum.json').read_text(encoding='utf8'))
def lesson(lid):
 item=next((x for x in data()['lessons'] if x['id']==lid),None)
 if not item:raise HTTPException(404,'Learning lesson not found')
 return item
def utc():return datetime.now(timezone.utc)
def catalog(uid):
 d=data();now=core.now()
 with core.connection() as db:
  progress={r['lesson_id']:dict(r) for r in db.execute('SELECT lesson_id,completed_at,independent,review_count,due_at FROM learning_progress WHERE user_id=? AND revision=?',(uid,d['revision']))}
  resume=db.execute('SELECT lesson_id,id FROM learning_sessions WHERE user_id=? AND revision=? AND updated_at>? ORDER BY updated_at DESC LIMIT 1',(uid,d['revision'],(utc()-timedelta(days=1)).isoformat())).fetchone()
 items=[]
 for x in d['lessons']:
  p=progress.get(x['id']);items.append({k:copy.deepcopy(x[k]) for k in ('id','stage','order','title','objective')}|{'completed':bool(p),'progress':p,'due':bool(p and p['due_at']<=now)})
 from .placement import latest
 placement=latest(uid);start_stage=placement['start_stage'] if placement else 1
 assigned=[x for x in items if x['stage']>=start_stage];due=[x['id'] for x in assigned if x['due']];unfinished=next((x['id'] for x in assigned if not x['completed']),None)
 return {'revision':d['revision'],'stages':copy.deepcopy(d['stages']),'lessons':items,'completed':len(progress),'total':len(items),'independent':sum(bool(x['independent']) for x in progress.values()),'due_count':len(due),'recommended':due[0] if due else unfinished,'resume':dict(resume) if resume else None,'sources':copy.deepcopy(d['sources']),'measure':'completed activities / 48; not a rating or title','review_intervals_days':d['review_intervals_days'],'placement':placement,'start_stage':start_stage,'assigned_total':len(assigned),'assigned_completed':sum(x['completed'] for x in assigned),'route_completed':all(x['completed'] for x in assigned)}

@lru_cache(maxsize=60)
def demo(lid):
 x=lesson(lid);e=x['example'];b=chess.Board(e['fen']);path=materialize(e)
 return {'fen':b.fen(),'path':path,'source':copy.deepcopy(e['source'])}
def materialize(e):
 b=chess.Board(e['fen']);result=[]
 for u in e['moves']:
  m=chess.Move.from_uci(u)
  if m not in b.legal_moves:raise ValueError('Invalid curriculum line')
  note=study.explain(b,m);san=b.san(m);number=b.fullmove_number;side='white' if b.turn else 'black';b.push(m)
  if b.is_checkmate():note={lang:{'why':text,'watch':note[lang]['watch']} for lang,text in [('ar','مات: الملك تحت الكش ولا يوجد رد قانوني.'),('en','Checkmate: the king is in check with no legal reply.')]}
  if b.is_stalemate():note={lang:{'why':text,'watch':note[lang]['watch']} for lang,text in [('ar','بات: لا يوجد كش ولا نقلة قانونية. النتيجة تعادل.'),('en','Stalemate: no check and no legal move. The result is a draw.')]}
  result.append({'uci':u,'san':san,'fen':b.fen(),'move_number':number,'mover':side,'note':note,'checkmate':b.is_checkmate(),'stalemate':b.is_stalemate()})
 return result
def detail(lid):
 x=lesson(lid);result={k:copy.deepcopy(x[k]) for k in ('id','stage','order','title','theory','objective','resource')};result['demo']=copy.deepcopy(demo(lid));result['practice_from']=x['practice_from'];result['quiz']={'question':copy.deepcopy(x['quiz']['question'])}
 result['extra_examples']=[]
 for e in x.get('extra_examples',[]):result['extra_examples'].append({'title':e['title'],'fen':e['fen'],'path':materialize(e),'source':e['source']})
 return result

def board_for(x,cursor):
 b=chess.Board(x['example']['fen'])
 for u in x['example']['moves'][:cursor]:b.push_uci(u)
 return b
def packed(s,x,message='',correct=None,animation=None):
 state=json.loads(s['state_json']);b=board_for(x,state['cursor']);q=x['quiz']
 return {'id':s['id'],'lesson_id':x['id'],'revision':s['revision'],'version':s['version'],'fen':b.fen(),'legal_moves':[m.uci() for m in b.legal_moves] if not state['practice'] else [],'side':state['side'],'cursor':state['cursor'],'practice_total':len(x['example']['moves']),'steps':{k:state[k] for k in ('theory','demo','practice','quiz')},'mistakes':state['mistakes'],'assisted':state['assisted'],'completed':state['completed'],'independent':state['completed'] and not state['assisted'] and not state['mistakes'],'quiz_options':[q['options'][i] for i in state['options']],'quiz_explanation':copy.deepcopy(q.get('explanation')) if message in ('quiz_retry','quiz_correct','lesson_complete') else None,'message':message,'correct':correct,'hint_uci':state.get('hint'),'revealed':state.get('revealed',False),'animation':animation or [],'checkmate':b.is_checkmate(),'stalemate':b.is_stalemate()}

def start(lid,uid,restart=False):
 x=lesson(lid);revision=data()['revision']
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  if not restart:
   old=db.execute('SELECT * FROM learning_sessions WHERE user_id=? AND revision=? AND lesson_id=? AND updated_at>? ORDER BY updated_at DESC LIMIT 1',(uid,revision,lid,(utc()-timedelta(days=1)).isoformat())).fetchone()
   if old and not json.loads(old['state_json'])['completed']:return packed(dict(old),x)
  side='white' if board_for(x,x['practice_from']).turn else 'black';options=list(range(len(x['quiz']['options'])));random.SystemRandom().shuffle(options)
  state={'cursor':x['practice_from'],'side':side,'options':options,'theory':False,'demo':False,'practice':False,'quiz':False,'mistakes':0,'assisted':False,'completed':False,'hint':None}
  now=core.now();sid=secrets.token_hex(16)
  db.execute('INSERT INTO learning_sessions(id,user_id,revision,lesson_id,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(sid,uid,revision,lid,json.dumps(state),now,now))
  return packed(dict(db.execute('SELECT * FROM learning_sessions WHERE id=?',(sid,)).fetchone()),x)

def action(sid,uid,version,kind,uci='',answer=None):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM learning_sessions WHERE id=? AND user_id=?',(sid,uid)).fetchone()
  if not row:raise HTTPException(404,'Learning session not found')
  s=dict(row)
  if s['revision']!=data()['revision'] or s['updated_at']<(utc()-timedelta(days=1)).isoformat():raise HTTPException(409,'Learning session expired; reopen the lesson')
  if s['version']!=version:raise HTTPException(409,'Learning session changed; reopen the lesson')
  x=lesson(s['lesson_id']);state=json.loads(s['state_json']);line=x['example']['moves'];animation=[];correct=None;message=''
  if state['completed']:raise HTTPException(409,'Lesson completed; start a new review')
  if kind in ('theory','demo'):state[kind]=True
  elif kind=='quiz':
   if answer is None or not 0<=answer<len(state['options']):raise HTTPException(422,'Choose an answer')
   correct=state['options'][answer]==x['quiz']['answer']
   if correct:state['quiz']=True;message='quiz_correct'
   else:state['mistakes']+=1;message='quiz_retry'
  elif kind in ('hint','reveal'):
   state['assisted']=True
   if state['cursor']<len(line):state['hint']=line[state['cursor']]
   if kind=='reveal':
    state['revealed']=True;message='revealed_restart'
    b=board_for(x,state['cursor'])
    for u in line[state['cursor']:]:san=b.san(chess.Move.from_uci(u));b.push_uci(u);animation.append({'uci':u,'san':san,'fen':b.fen()})
  elif kind=='move':
   if state.get('revealed'):raise HTTPException(409,'Restart to attempt after viewing the answer')
   if state['practice']:raise HTTPException(409,'Practice already completed')
   b=board_for(x,state['cursor'])
   try:m=b.parse_uci(uci)
   except ValueError:raise HTTPException(422,'Illegal move') from None
   if m.uci()!=line[state['cursor']]:state['mistakes']+=1;correct=False;message='different_reference'
   else:
    correct=True;state['hint']=None
    while True:
     u=line[state['cursor']];san=b.san(chess.Move.from_uci(u));b.push_uci(u);state['cursor']+=1;animation.append({'uci':u,'san':san,'fen':b.fen()})
     if state['cursor']>=len(line) or ('white' if b.turn else 'black')==state['side']:break
    state['practice']=state['cursor']>=len(line);message='practice_complete' if state['practice'] else 'your_turn'
  else:raise HTTPException(422,'Unknown learning action')
  if all(state[k] for k in ('theory','demo','practice','quiz')) and not state.get('revealed'):
   state['completed']=True;now=utc();p=db.execute('SELECT * FROM learning_progress WHERE user_id=? AND revision=? AND lesson_id=?',(uid,s['revision'],x['id'])).fetchone()
   independent=int(not state['mistakes'] and not state['assisted']);count=0
   # A review interval can advance only when actually due, once per completed session.
   if p:
    count=p['review_count']
    if p['due_at']<=now.isoformat():count=min(count+1,4) if independent else 0
    due=now+timedelta(days=data()['review_intervals_days'][count]) if p['due_at']<=now.isoformat() else datetime.fromisoformat(p['due_at'])
    db.execute('UPDATE learning_progress SET independent=?,review_count=?,due_at=?,last_session=? WHERE user_id=? AND revision=? AND lesson_id=?',(independent,count,due.isoformat(),sid,uid,s['revision'],x['id']))
   else:
    due=now+timedelta(days=1);db.execute('INSERT INTO learning_progress VALUES(?,?,?,?,?,?,?,?)',(uid,s['revision'],x['id'],now.isoformat(),independent,count,due.isoformat(),sid))
   message='lesson_complete'
  s['version']+=1;s['state_json']=json.dumps(state);s['updated_at']=core.now()
  db.execute('UPDATE learning_sessions SET version=?,state_json=?,updated_at=? WHERE id=?',(s['version'],s['state_json'],s['updated_at'],sid))
  return packed(s,x,message,correct,animation)

def install(app,auth):
 from fastapi import Depends
 from pydantic import BaseModel,ConfigDict,Field
 from typing import Literal
 class Start(BaseModel):
  model_config=ConfigDict(extra='forbid')
  restart:bool=False
 class Action(BaseModel):
  model_config=ConfigDict(extra='forbid')
  version:int=Field(ge=0,le=10000)
  kind:Literal['theory','demo','quiz','move','hint','reveal']
  uci:str=Field(default='',max_length=5,pattern='^$|^[a-h][1-8][a-h][1-8][qrbn]?$')
  answer:int|None=Field(default=None,ge=0,le=2)
 @app.get('/api/learning')
 def path(user=Depends(auth)):return catalog(user['id'])
 @app.get('/api/learning/lessons/{lid}')
 def get(lid:str,user=Depends(auth)):return detail(lid)
 @app.post('/api/learning/lessons/{lid}/start')
 def begin(lid:str,body:Start,user=Depends(auth)):return start(lid,user['id'],body.restart)
 @app.post('/api/learning/sessions/{sid}/action')
 def update(sid:str,body:Action,user=Depends(auth)):return action(sid,user['id'],body.version,body.kind,body.uci,body.answer)
