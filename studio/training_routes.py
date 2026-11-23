"""Owned, cached move annotations for independent training boards only."""
from __future__ import annotations
import copy,json,secrets,time
from datetime import datetime,timezone
import chess
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .core import connection
from .training_teacher import analyze_move,PLAY_INSTRUCTIONS
from .teacher_v7.providers import generate,ProviderError
from .teacher_v7.router import vetted_reply

MAX_ANALYSES=192
MAX_EXPLANATIONS=40
class CoachRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ply:int=Field(ge=1,le=600)
    elaborate:bool=False
    question:str=Field(default='',max_length=500)


def setup_coaching():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS training_move_coaching (
          game_id TEXT NOT NULL REFERENCES groq_training_games(id) ON DELETE CASCADE,
          ply INTEGER NOT NULL, analysis_json TEXT, reply_json TEXT,
          lock_token TEXT, lock_until REAL NOT NULL DEFAULT 0, PRIMARY KEY(game_id,ply));
        CREATE TABLE IF NOT EXISTS training_coach_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL, analyses INTEGER NOT NULL DEFAULT 0, explanations INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,day));
        ''')


def reserve(db,uid,field,limit):
    # All names are constants supplied by this module, never request values.
    if field not in ('analyses','explanations'):raise ValueError()
    day=datetime.now(timezone.utc).date().isoformat()
    row=db.execute('SELECT '+field+' FROM training_coach_usage WHERE user_id=? AND day=?',(uid,day)).fetchone()
    if limit<=0 or row and row[field]>=limit:raise HTTPException(429,'وصلت إلى حد التعليم اليومي. الشروح المحفوظة تبقى متاحة.')
    db.execute('INSERT INTO training_coach_usage(user_id,day,'+field+') VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET '+field+'='+field+'+1',(uid,day))


def get_annotation(gid,data,user):
    from .play_groq import owned,replay,groq_settings
    from .locale import language
    lang=language()
    uid=user['id'];token=secrets.token_hex(16)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE');row=owned(db,gid,uid);board,history=replay(row)
        if data.ply>len(history):raise HTTPException(404,'هذه النقلة ليست ضمن المباراة المحفوظة')
        cached=db.execute('SELECT * FROM training_move_coaching WHERE game_id=? AND ply=?',(gid,data.ply)).fetchone()
        analysis=json.loads(cached['analysis_json']) if cached and cached['analysis_json'] else None
        reply=json.loads(cached['reply_json']) if cached and cached['reply_json'] and not data.question.strip() else None
        if reply and reply.get('language','ar')!=lang:reply=None
        need_analysis=analysis is None;need_reply=data.elaborate and reply is None
        if need_reply:
            from .control_store import feature,settings as control_settings
            role=db.execute('SELECT role FROM users WHERE id=?',(uid,)).fetchone()['role']
            if role!='admin' and not feature(uid,'ai_coach',db):raise HTTPException(403,'الشرح الموسع غير متاح في خطتك / Expanded notes are not included in your plan')
            if not control_settings(db)['ai_enabled']:raise HTTPException(503,'AI services are paused')
        if need_analysis or need_reply:
            if cached and cached['lock_until']>time.time():raise HTTPException(409,'المعلّم يراجع هذه النقلة بالفعل. انتظر قليلاً ثم أعد المحاولة.')
            if need_analysis:reserve(db,uid,'analyses',MAX_ANALYSES)
            if need_reply:
                from .control_store import entitlement
                reserve(db,uid,'explanations',min(MAX_EXPLANATIONS,entitlement(uid,db)['plan']['limits']['coach_daily']))
            db.execute('INSERT INTO training_move_coaching(game_id,ply,lock_token,lock_until) VALUES(?,?,?,?) ON CONFLICT(game_id,ply) DO UPDATE SET lock_token=excluded.lock_token,lock_until=excluded.lock_until',(gid,data.ply,token,time.time()+90))
    explanation_error=None
    try:
        if need_analysis:
            before=chess.Board()
            for item in history[:data.ply-1]:before.push_uci(item['uci'])
            move=chess.Move.from_uci(history[data.ply-1]['uci'])
            analysis=analyze_move(before,move,row['player_color'],data.ply)
            with connection() as db:
                db.execute('UPDATE training_move_coaching SET analysis_json=? WHERE game_id=? AND ply=? AND lock_token=?',(json.dumps(analysis,ensure_ascii=False),gid,data.ply,token))
        if need_reply:
            try:
                settings,_=groq_settings()
                # Fixed Groq selection; never send this game to an unselected fallback.
                cfg={'primary':'groq','fallback':[],'providers':{'groq':copy.deepcopy(settings)}}
                from .teacher_v7.grounding import enrich,audit
                question=data.question.strip() or 'علّمني فكرة هذه النقلة: فائدتها، خطرها، وما البديل الأفضل إن وجد.'
                context=enrich(analysis['_verified_context'],question)
                answer,ins,outs,provider,model=generate(cfg,PLAY_INSTRUCTIONS,{
                    'VERIFIED_CONTEXT':context,
                    'QUESTION_AR':question,'RECENT_DISCUSSION':[]})
                reply=vetted_reply(answer,analysis['scenarios'])
                reply.update(audit(answer,context))
                reply.update(language=lang,provider=provider,model=model,source='Groq + Stockfish',
                    disclaimer='شرح تدريبي لمباراة مستقلة داخل المنصة؛ التقييم والحركات من المحرك، والنص التفسيري قد يحتاج مراجعة.')
                if not data.question.strip():
                    with connection() as db:db.execute('UPDATE training_move_coaching SET reply_json=? WHERE game_id=? AND ply=? AND lock_token=?',(json.dumps(reply,ensure_ascii=False),gid,data.ply,token))
            except (ProviderError,HTTPException):
                explanation_error='تعذر الشرح الموسّع الآن. تقييم Stockfish والفوائد والمخاطر أدناه ما زالت متاحة.'
    finally:
        if need_analysis or need_reply:
            with connection() as db:db.execute('UPDATE training_move_coaching SET lock_token=NULL,lock_until=0 WHERE game_id=? AND ply=? AND lock_token=?',(gid,data.ply,token))
    public={key:value for key,value in analysis.items() if not key.startswith('_')}
    public.update(game_id=gid,explanation=reply,explanation_error=explanation_error,cached=not need_analysis and not need_reply)
    return public


def install(app,auth):
    @app.post('/api/play/games/{gid}/coach')
    def coach(gid:str,data:CoachRequest,user=Depends(auth)):
        return get_annotation(gid,data,user)
