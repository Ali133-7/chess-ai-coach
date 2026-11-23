"""Independent training games against Stockfish with Groq teaching. Boards start here, never from client FEN."""
from __future__ import annotations
import json, logging, secrets, time, uuid
from datetime import datetime, timezone
from typing import Literal
import chess
import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .core import connection, now
from .teacher_v7.service import provider_config
from .teacher_v7.providers import read_key, ProviderError
from .training_teacher import engine_ready, choose_stockfish_move, LEVELS

log=logging.getLogger('studio.play')
DAILY_AI_LIMIT=160
MAX_PLIES=600

class NewGame(BaseModel):
    model_config=ConfigDict(extra='forbid')
    color:Literal['white','black']='white'
    level:Literal['calm','balanced','strong']='strong'

class Version(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=0,le=MAX_PLIES)

class HumanMove(Version):
    uci:str=Field(pattern=r'^[a-h][1-8][a-h][1-8][qrbn]?$',max_length=5)


def setup_play():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS groq_training_games (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          player_color TEXT NOT NULL, moves_json TEXT NOT NULL DEFAULT '[]',
          version INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
          busy_token TEXT, busy_until REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_groq_training_owner ON groq_training_games(user_id,updated_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_groq_one_active ON groq_training_games(user_id) WHERE status='active';
        CREATE TABLE IF NOT EXISTS groq_training_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day));
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(groq_training_games)')}
        if 'level' not in columns:
            db.execute("ALTER TABLE groq_training_games ADD COLUMN level TEXT NOT NULL DEFAULT 'strong'")
    from .training_routes import setup_coaching
    setup_coaching()


def groq_settings():
    try:
        settings=provider_config()['providers'].get('groq')
        if not settings:raise ProviderError('Groq not selected')
        secret=read_key(settings['key_file'])
        return settings,secret
    except ProviderError:
        raise HTTPException(503,'شرح Groq غير جاهز. التعليم الأساسي من المحرك متاح.') from None


def owned(db,gid,uid):
    row=db.execute('SELECT * FROM groq_training_games WHERE id=? AND user_id=?',(gid,uid)).fetchone()
    if not row:raise HTTPException(404,'المباراة التدريبية غير موجودة ضمن حسابك')
    return dict(row)


def replay(row):
    board=chess.Board();moves=json.loads(row['moves_json']);history=[]
    for uci in moves:
        move=chess.Move.from_uci(uci)
        if move not in board.legal_moves:raise RuntimeError('Saved training game is invalid')
        history.append({'uci':uci,'san':board.san(move)})
        board.push(move)
    return board,history


def pack(row):
    board,history=replay(row)
    outcome=board.outcome(claim_draw=True)
    player_turn=board.turn==(row['player_color']=='white')
    active=row['status']=='active' and outcome is None and len(history)<MAX_PLIES
    thinking=active and row['busy_until']>time.time() and bool(row['busy_token'])
    result=outcome.result() if outcome else None
    if row['status']=='resigned':result='0-1' if row['player_color']=='white' else '1-0'
    if row['status']=='finished' and not outcome:result='1/2-1/2'
    state='thinking' if thinking else ('your_turn' if player_turn else 'ai_turn') if active else 'finished'
    if state=='your_turn':message='دورك. اختر قطعة ثم مربع الوصول.'
    elif state=='ai_turn':message='دور الخصم.'
    elif state=='thinking':message='المحرك يفكر في نقلته…'
    elif row['status']=='abandoned':message='بدأت مباراة تدريبية جديدة.'
    elif row['status']=='resigned':message='انتهت المباراة بالاستسلام.'
    elif board.is_checkmate():message='كش مات. انتهت المباراة.'
    else:message='انتهت المباراة بالتعادل.'
    if active and board.is_check() and not thinking:message='كش! '+message
    return {'id':row['id'],'fen':board.fen(),'player_color':row['player_color'],'opponent':'stockfish','level':row.get('level','strong'),'level_ar':LEVELS.get(row.get('level','strong'),LEVELS['strong'])['label'],
            'version':row['version'],'state':state,'status':row['status'],'message':message,
            'legal_moves':[m.uci() for m in board.legal_moves] if active and player_turn and not thinking else [],
            'moves':history,'last_move':history[-1]['uci'] if history else None,'result':result,
            'check':board.is_check(),'retry_after':max(0,int(row['busy_until']-time.time())+1) if thinking else 0}


def install(app,auth):
    from .training_routes import install as install_coaching
    install_coaching(app,auth)
    @app.get('/api/play/status')
    def status(user=Depends(auth)):
        ready=engine_ready()
        try:groq_settings();teacher_ready=True
        except HTTPException:teacher_ready=False
        day=datetime.now(timezone.utc).date().isoformat()
        with connection() as db:
            r=db.execute('SELECT requests FROM groq_training_usage WHERE user_id=? AND day=?',(user['id'],day)).fetchone()
        return {'ready':ready,'provider':'stockfish','teacher_ready':teacher_ready,'teacher_provider':'groq','levels':{k:v['label'] for k,v in LEVELS.items()},'daily_limit':DAILY_AI_LIMIT,'requests_today':r['requests'] if r else 0}

    @app.get('/api/play/current')
    def current(user=Depends(auth)):
        with connection() as db:
            row=db.execute("SELECT * FROM groq_training_games WHERE user_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1",(user['id'],)).fetchone()
        return {'game':pack(dict(row)) if row else None}

    @app.get('/api/play/games/{gid}')
    def get_game(gid:str,user=Depends(auth)):
        with connection() as db:return pack(owned(db,gid,user['id']))

    @app.post('/api/play/games')
    def create(data:NewGame,user=Depends(auth)):
        if not engine_ready():raise HTTPException(503,'محرك Stockfish غير متاح على الخادم حالياً')
        gid=uuid.uuid4().hex;uid=user['id']
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            busy=db.execute("SELECT id FROM groq_training_games WHERE user_id=? AND status='active' AND busy_until>?",(uid,time.time())).fetchone()
            if busy:raise HTTPException(409,'انتظر اكتمال نقلة الخصم قبل بدء مباراة جديدة')
            db.execute("UPDATE groq_training_games SET status='abandoned',updated_at=? WHERE user_id=? AND status='active'",(now(),uid))
            db.execute('INSERT INTO groq_training_games(id,user_id,player_color,level,created_at,updated_at) VALUES(?,?,?,?,?,?)',(gid,uid,data.color,data.level,now(),now()))
            row=owned(db,gid,uid)
        return pack(row)

    @app.post('/api/play/games/{gid}/move')
    def move(gid:str,data:HumanMove,user=Depends(auth)):
        with connection() as db:
            db.execute('BEGIN IMMEDIATE');row=owned(db,gid,user['id']);board,history=replay(row)
            if row['version']!=data.version:raise HTTPException(409,'تغيرت الرقعة. جارٍ تحديث المباراة.')
            if row['status']!='active' or board.outcome(claim_draw=True) or len(history)>=MAX_PLIES:raise HTTPException(409,'هذه المباراة منتهية')
            if row['busy_until']>time.time() or board.turn!=(row['player_color']=='white'):raise HTTPException(409,'انتظر دورك')
            candidate=chess.Move.from_uci(data.uci)
            if candidate not in board.legal_moves:raise HTTPException(422,'هذه النقلة غير قانونية')
            board.push(candidate);moves=[m['uci'] for m in history]+[data.uci]
            status='finished' if board.outcome(claim_draw=True) or len(moves)>=MAX_PLIES else 'active'
            db.execute('UPDATE groq_training_games SET moves_json=?,version=version+1,status=?,updated_at=? WHERE id=?',(json.dumps(moves),status,now(),gid))
            row=owned(db,gid,user['id'])
        return pack(row)

    @app.post('/api/play/games/{gid}/ai')
    def ai(gid:str,data:Version,user=Depends(auth)):
        uid=user['id'];token=secrets.token_hex(16);day=datetime.now(timezone.utc).date().isoformat()
        with connection() as db:
            db.execute('BEGIN IMMEDIATE');row=owned(db,gid,uid);board,history=replay(row)
            if row['version']!=data.version:raise HTTPException(409,'تغيرت الرقعة. حدّث المباراة.')
            if row['status']!='active' or board.outcome(claim_draw=True) or len(history)>=MAX_PLIES:raise HTTPException(409,'هذه المباراة منتهية')
            if board.turn==(row['player_color']=='white'):raise HTTPException(409,'الدور لك الآن')
            if row['busy_until']>time.time():raise HTTPException(409,'المحرك يفكر بالفعل. انتظر قليلاً.')
            usage=db.execute('SELECT requests FROM groq_training_usage WHERE user_id=? AND day=?',(uid,day)).fetchone()
            if usage and usage['requests']>=DAILY_AI_LIMIT:raise HTTPException(429,'وصلت إلى حد النقلات اليومي للتدريب')
            db.execute('INSERT INTO groq_training_usage(user_id,day,requests) VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET requests=requests+1',(uid,day))
            db.execute('UPDATE groq_training_games SET busy_token=?,busy_until=? WHERE id=?',(token,time.time()+70,gid))
        try:
            uci=choose_stockfish_move(board,row.get('level','strong'))
            if uci not in {m.uci() for m in board.legal_moves}:
                raise HTTPException(503,'رفض الخادم نقلة غير قانونية من المحرك')
        except Exception:
            with connection() as db:db.execute('UPDATE groq_training_games SET busy_token=NULL,busy_until=0 WHERE id=? AND busy_token=?',(gid,token))
            raise
        with connection() as db:
            db.execute('BEGIN IMMEDIATE');row=owned(db,gid,uid)
            if row['busy_token']!=token or row['version']!=data.version or row['status']!='active':raise HTTPException(409,'تغيرت المباراة أثناء التفكير. حدّث الرقعة.')
            board,history=replay(row);candidate=chess.Move.from_uci(uci)
            if candidate not in board.legal_moves:
                db.execute('UPDATE groq_training_games SET busy_token=NULL,busy_until=0 WHERE id=?',(gid,))
                raise HTTPException(503,'رفض الخادم نقلة غير قانونية من المحرك')
            board.push(candidate);moves=[m['uci'] for m in history]+[uci]
            status='finished' if board.outcome(claim_draw=True) or len(moves)>=MAX_PLIES else 'active'
            db.execute('UPDATE groq_training_games SET moves_json=?,version=version+1,status=?,busy_token=NULL,busy_until=0,updated_at=? WHERE id=?',(json.dumps(moves),status,now(),gid))
            row=owned(db,gid,uid)
        return pack(row)

    @app.post('/api/play/games/{gid}/resign')
    def resign(gid:str,data:Version,user=Depends(auth)):
        with connection() as db:
            db.execute('BEGIN IMMEDIATE');row=owned(db,gid,user['id'])
            if row['version']!=data.version or row['status']!='active':raise HTTPException(409,'تغيرت المباراة. حدّث الرقعة.')
            db.execute("UPDATE groq_training_games SET status='resigned',version=version+1,busy_token=NULL,busy_until=0,updated_at=? WHERE id=?",(now(),gid))
            row=owned(db,gid,user['id'])
        return pack(row)
