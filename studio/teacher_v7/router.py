"""Authenticated completed-game AI tutoring; limits, ownership, cache, threads."""
from __future__ import annotations
import hashlib, json, logging, sqlite3
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from ..core import connection, config, now, game_moves_from_pgn
from .engine import verified_context, approved_board_actions
from ..locale import language
from .service import configured, call_teacher, provider_status, provider_config, PROMPT_VERSION
from .providers import identity, ProviderError

log = logging.getLogger('studio.teacher.v7')

class TeacherRequest(BaseModel):
    game_id:int=Field(gt=0)
    ply:int=Field(ge=1,le=1000)
    question:str=Field(default='', max_length=500)
    thread_id:int|None=Field(default=None,gt=0)


def setup_teacher():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS teacher_threads (
          id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_teacher_threads ON teacher_threads(user_id,updated_at DESC);
        CREATE TABLE IF NOT EXISTS teacher_messages (
          id INTEGER PRIMARY KEY,thread_id INTEGER NOT NULL REFERENCES teacher_threads(id) ON DELETE CASCADE,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          ply INTEGER NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_teacher_messages ON teacher_messages(thread_id,id);
        CREATE TABLE IF NOT EXISTS teacher_cache (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          key TEXT NOT NULL,reply_json TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(user_id,key));
        CREATE TABLE IF NOT EXISTS teacher_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL,requests INTEGER NOT NULL DEFAULT 0,
          input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,day));
        ''')
        db.execute('INSERT OR IGNORE INTO app_config(key,value) VALUES(?,?)',('teacher_daily_limit','20'))


def fetch_position(user_id, game_id, ply):
    """Prefer deep saved analysis, but support an on-demand *bounded* scan of a
    position in an already FINISHED public archive game. Never inspect live games.
    """
    with connection() as db:
        game=db.execute('SELECT id,pgn,result,finished_at,stage FROM games WHERE id=? AND user_id=?',
                        (game_id,user_id)).fetchone()
        if not game:
            raise HTTPException(404,'المباراة غير موجودة ضمن حسابك')
        existing=db.execute('SELECT * FROM moves WHERE game_id=? AND ply=?',(game_id,ply)).fetchone()
        if not game['finished_at'] or game['result'] not in ('1-0','0-1','1/2-1/2'):
            raise HTTPException(409,'لا نقدّم تحليلاً لمباراة ما زالت جارية')
        if existing and game['stage']=='done':
            return dict(existing), 'deep'
        scan=db.execute('SELECT scan_json FROM position_scans WHERE game_id=? AND ply=?',
                        (game_id,ply-1)).fetchone()
    if not game['finished_at'] or game['result'] not in ('1-0','0-1','1/2-1/2'):
        raise HTTPException(409,'لا نقدّم تحليلاً لمباراة ما زالت جارية')
    try:
        _,game_moves=game_moves_from_pgn(game['pgn'])
        move=game_moves[ply-1]
        if move[0]!=ply:raise IndexError()
    except (IndexError,ValueError,TypeError):
        raise HTTPException(404,'تعذر التحقق من النقلة في مباراة مكتملة')
    _,uci,san,fen_before,fen_after=move
    saved=None
    if scan:
        try:saved=json.loads(scan['scan_json'])
        except (TypeError,ValueError):saved=None
    if not saved:
        import chess, chess.engine
        import os
        board=chess.Board(fen_before)
        stockfish=os.getenv('STOCKFISH_PATH','/usr/games/stockfish')
        try:
            with chess.engine.SimpleEngine.popen_uci(stockfish,timeout=6) as engine:
                # A quick, fixed-budget read-only analysis; does not consume or alter background jobs.
                infos=engine.analyse(board,chess.engine.Limit(time=1.2),multipv=2)
            if isinstance(infos,dict):infos=[infos]
            lines=[]
            for info in infos:
                pv=info.get('pv') or []
                if not pv or pv[0] not in board.legal_moves:continue
                line_board=board.copy();safe=[]
                for candidate in pv[:8]:
                    if candidate not in line_board.legal_moves:break
                    safe.append(candidate.uci());line_board.push(candidate)
                if safe:
                    score=info['score'].pov(chess.WHITE)
                    cp=(1400 if score.mate()>0 else -1400) if score.is_mate() else score.score()
                    lines.append({'pv_uci':safe,'eval':cp,'depth':info.get('depth')})
            saved={'lines':lines}
        except Exception:
            log.warning('Fast Stockfish scan failed for game %s ply %s',game_id,ply,exc_info=True)
            raise HTTPException(503,'تعذر تحليل هذا الموقف بسرعة. يمكن إعادة المحاولة بعد قليل.')
    lines=saved.get('lines',[]) if isinstance(saved,dict) else []
    first=lines[0] if lines else {}
    try:
        import chess
        board=chess.Board(fen_before)
        best=chess.Move.from_uci(first['pv_uci'][0]) if first.get('pv_uci') else None
        best_san=board.san(best) if best and best in board.legal_moves else None
    except (ValueError,KeyError):
        best_san=None
    return {'fen_before':fen_before,'fen_after':fen_after,'uci':uci,'san':san,
            'grade':'unrated','loss_cp':None,'best_san':best_san,
            'lines_json':json.dumps(lines,ensure_ascii=False)}, 'quick'


def guard_quota(user_id):
    today=datetime.now(timezone.utc).date().isoformat()
    with connection() as db:
        # sqlite write lock serializes concurrent usage reservations across web workers.
        db.execute('BEGIN IMMEDIATE')
        lim=max(1,min(100,int(config(db,'teacher_daily_limit','20'))))
        row=db.execute('SELECT requests FROM teacher_usage WHERE user_id=? AND day=?',(user_id,today)).fetchone()
        if row and row['requests']>=lim:
            raise HTTPException(429,'وصلت إلى الحد اليومي لأسئلة المعلّم؛ حاول غداً')
        db.execute('''INSERT INTO teacher_usage(user_id,day,requests) VALUES(?,?,1)
            ON CONFLICT(user_id,day) DO UPDATE SET requests=requests+1''',(user_id,today))
    return today


def add_usage(user_id,day,input_tokens,output_tokens):
    with connection() as db:
        db.execute('''UPDATE teacher_usage SET input_tokens=input_tokens+?,output_tokens=output_tokens+?
            WHERE user_id=? AND day=?''',(max(0,input_tokens),max(0,output_tokens),user_id,day))


def vetted_reply(answer, scenarios):
    allow={s['id'] for s in scenarios}
    notes=[n.model_dump() for n in answer.scenario_notes if n.scenario_id in allow]
    ids=list(dict.fromkeys(n['scenario_id'] for n in notes))
    def trim(s):return s.strip()[:2400]
    return {'title_ar':trim(answer.title_ar),
        'explanation_ar':trim(answer.explanation_ar),
        'benefits_ar':[trim(x) for x in answer.benefits_ar[:5]],
        'risks_ar':[trim(x) for x in answer.risks_ar[:5]],
        'scenario_notes':notes[:3],
        'learning_question_ar':trim(answer.learning_question_ar),
        'board_actions':approved_board_actions(scenarios,ids),
        'scenarios':scenarios, 'source':'AI + verified archived Stockfish lines',
        'disclaimer':'تقييم المحرك تقديري. تحليل خاص بمباراة مكتملة فقط.'}


def install(app,auth):
    @app.get('/api/teacher/status')
    def status(user=Depends(auth)):
        day=datetime.now(timezone.utc).date().isoformat()
        with connection() as db:
            r=db.execute('SELECT requests,input_tokens,output_tokens FROM teacher_usage WHERE user_id=? AND day=?',
                         (user['id'],day)).fetchone()
            lim=max(1,min(100,int(config(db,'teacher_daily_limit','20'))))
        return {**provider_status(),'requests_today':r['requests'] if r else 0,
                'daily_limit':lim,'input_tokens_today':r['input_tokens'] if r else 0,
                'output_tokens_today':r['output_tokens'] if r else 0}

    def generate(data,user,conversation=False):
        uid=user['id']
        with connection() as db:
            if not db.execute('SELECT id FROM games WHERE id=? AND user_id=?',(data.game_id,uid)).fetchone():
                raise HTTPException(404,'هذه المباراة غير موجودة ضمن حسابك')
            day=datetime.now(timezone.utc).date().isoformat()
            lim=max(1,min(100,int(config(db,'teacher_daily_limit','20'))))
            usage=db.execute('SELECT requests FROM teacher_usage WHERE user_id=? AND day=?',(uid,day)).fetchone()
        from .dialogue import kind as question_kind, generate as general_answer
        actual_question=data.question.strip()
        if actual_question and question_kind(actual_question)!='position':
            if question_kind(actual_question)=='general' and usage and usage['requests']>=lim:raise HTTPException(429,'وصلت إلى الحد اليومي لأسئلة المعلّم')
            return general_answer(data,user,actual_question,conversation)
        if not configured():raise HTTPException(503,'إعداد مزود المعلّم غير جاهز على السيرفر')
        if usage and usage['requests']>=lim:
            raise HTTPException(429,'وصلت إلى الحد اليومي لأسئلة المعلّم')
        r,depth_mode=fetch_position(uid,data.game_id,data.ply)
        try:context,scenarios=verified_context(r)
        except ValueError:raise HTTPException(409,'تعذر التحقق من الموقف المحفوظ')
        question=data.question.strip() or 'اشرح لي هذه النقلة وفوائدها ومخاطرها ثم اختبر فهمي.'
        history=[];tid=data.thread_id
        if conversation and tid:
            with connection() as db:
                thread=db.execute('SELECT id FROM teacher_threads WHERE id=? AND user_id=? AND game_id=?',
                                  (tid,uid,data.game_id)).fetchone()
                if not thread:raise HTTPException(404,'محادثة غير موجودة ضمن حسابك وهذه المباراة')
                history=[{'role':x['role'],'text':x['content'][:800]} for x in db.execute(
                    'SELECT role,content FROM teacher_messages WHERE thread_id=? ORDER BY id DESC LIMIT 6',(tid,))]
            history.reverse()
        cfg=provider_config()
        ckey=hashlib.sha256(json.dumps({'context':context,'question':question,'provider_config':identity(cfg),'prompt':PROMPT_VERSION,'language':language()},
                         sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if not conversation:
            with connection() as db:
                cached=db.execute('SELECT reply_json FROM teacher_cache WHERE user_id=? AND key=?',(uid,ckey)).fetchone()
            if cached:return {'cached':True,'thread_id':None,**json.loads(cached['reply_json'])}
        day=guard_quota(uid)
        try:
            answer,ins,outs,provider,model=call_teacher(context,question,history,cfg)
        except ProviderError as error:
            log.warning('Teacher API request failed for user %s: %s', uid, error.code)
            messages = {
                'rate_limited':'وصل مزود الذكاء الاصطناعي إلى حد الاستخدام مؤقتاً. انتظر دقيقة ثم أعد المحاولة.',
                'network_timeout':'انتهت مهلة الاتصال بمزود الذكاء الاصطناعي. أعد المحاولة بعد قليل.',
                'output_truncated':'لم يكتمل رد المعلّم. جرّب سؤالاً أقصر أو أعد المحاولة.',
                'invalid_output':'لم يطابق رد المعلّم قواعد التحقق. أعد المحاولة؛ لم نعرض رداً غير متحقق منه.',
                'http_401':'رفض مزود الذكاء الاصطناعي المفتاح. يحتاج إعداد المفتاح إلى مراجعة على الخادم.',
                'http_403':'رفض مزود الذكاء الاصطناعي صلاحية الوصول. راجع صلاحيات الحساب والنموذج.',
            }
            raise HTTPException(503,messages.get(error.code,'تعذر إكمال طلب المعلّم حالياً. أعد المحاولة بعد قليل.'))
        except Exception:
            log.warning('Teacher API request failed for user %s: internal_error',uid)
            raise HTTPException(503,'تعذر الحصول على شرح توليدي حالياً. جرّب لاحقاً أو استخدم شرح Stockfish المحفوظ.')
        add_usage(uid,day,ins,outs)
        result=vetted_reply(answer,scenarios)
        result['provider']=provider
        result['model']=model
        result['source']=provider+' + verified archived Stockfish lines'
        result['analysis_mode']=depth_mode
        if depth_mode=='quick':
            result['disclaimer']='تحليل سريع مؤقت لهذه النقلة من مباراة منتهية؛ سيصبح أدق عند اكتمال تحليل Stockfish العميق.'
        if conversation:
            with connection() as db:
                if tid is None:
                    cur=db.execute('INSERT INTO teacher_threads(user_id,game_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',
                                   (uid,data.game_id,question[:110],now(),now()))
                    tid=cur.lastrowid
                db.execute('INSERT INTO teacher_messages(thread_id,user_id,ply,role,content,created_at) VALUES(?,?,?,?,?,?)',
                           (tid,uid,data.ply,'user',question,now()))
                db.execute('INSERT INTO teacher_messages(thread_id,user_id,ply,role,content,created_at) VALUES(?,?,?,?,?,?)',
                           (tid,uid,data.ply,'assistant',result['explanation_ar'],now()))
                db.execute('UPDATE teacher_threads SET updated_at=? WHERE id=? AND user_id=?',(now(),tid,uid))
        else:
            with connection() as db:
                db.execute('INSERT OR REPLACE INTO teacher_cache(user_id,key,reply_json,created_at) VALUES(?,?,?,?)',
                           (uid,ckey,json.dumps(result,ensure_ascii=False),now()))
        return {'cached':False,'thread_id':tid if conversation else None,**result}

    @app.post('/api/teacher/explain')
    def explain(data:TeacherRequest,user=Depends(auth)):
        return generate(data,user)

    @app.post('/api/teacher/chat')
    def chat(data:TeacherRequest,user=Depends(auth)):
        if not data.question.strip():raise HTTPException(422,'اكتب سؤالك للمعلّم')
        return generate(data,user,True)

    @app.get('/api/teacher/threads')
    def threads(game_id:int=Query(gt=0),user=Depends(auth)):
        with connection() as db:
            rows=db.execute('''SELECT t.id,t.game_id,t.title,t.created_at,t.updated_at,
                (SELECT COUNT(*) FROM teacher_messages m WHERE m.thread_id=t.id) message_count
                FROM teacher_threads t WHERE t.user_id=? AND t.game_id=? ORDER BY updated_at DESC LIMIT 30''',
                (user['id'],game_id)).fetchall()
        return {'threads':[dict(r) for r in rows]}

    @app.get('/api/teacher/threads/{thread_id}')
    def thread(thread_id:int,user=Depends(auth)):
        with connection() as db:
            t=db.execute('SELECT * FROM teacher_threads WHERE id=? AND user_id=?',(thread_id,user['id'])).fetchone()
            if not t:raise HTTPException(404,'محادثة غير موجودة')
            rows=db.execute('SELECT ply,role,content,created_at FROM teacher_messages WHERE thread_id=? ORDER BY id LIMIT 100',
                            (thread_id,)).fetchall()
        return {'thread':dict(t),'messages':[dict(r) for r in rows]}
