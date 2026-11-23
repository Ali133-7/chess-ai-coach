"""V3 engine review, coaching metrics, and persistent issue journal.

Analyses ONLY Chess.com archived completed games. Never accepts arbitrary positions
for engine analysis or accepts a current live game identifier.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import asyncio
from datetime import datetime, timezone
from math import exp
import io
import json
import logging
import statistics
from typing import Any

import chess
import chess.engine
import chess.pgn
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

import main as core
import coach_plus as plus
import move_quality as grades
import coach_brain as brain

LOG = logging.getLogger('chess_coach.advanced')
_bulk = {'running':False,'requested':0,'done':0,'failed':0,'last_error':None}
_background_tasks: set[asyncio.Task] = set()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def probability(cp: int) -> float:
    """Transparent, approximate logistic centipawn -> win chance (not Chess.com formula)."""
    return 100 / (1 + exp(-max(-1500, min(1500, cp)) / 245))

def cp_from(info: dict, color=chess.WHITE) -> tuple[int, int | None]:
    pov = info['score'].pov(color)
    mate = pov.mate() if pov.is_mate() else None
    cp = pov.score(mate_score=1500)
    return max(-1500, min(1500, cp or 0)), mate

def classify(loss: float, best: bool, winning_chance_drop: float) -> tuple[str, str]:
    code=grades.classify(loss,best,winning_chance_drop)
    return grades.label(code),code


def label_move(board, best_move, played, quality_code):
    if best_move is None: return 'انتهى الموقف أو تعذّر استخلاص نقلة بديلة.'
    concept,tip=plus.classify_concept(board,best_move)
    best_san=board.san(best_move)
    desc={
      'brilliant':'تضحية محسوبة يرشحها المحرك ضمن معاييرنا التقريبية؛ راقب الردود الإجبارية.',
      'excellent':'نقلة قوية متوافقة مع تحليل المحرك في هذا العمق.',
      'good':'نقلة سليمة إجمالاً وتحافظ على فرصك.',
      'weak':'نقلة ضعيفة نسبياً؛ توجد فكرة أدق في هذا الموقف.',
      'missed':'ضاعت فرصة كبيرة لتحويل الأفضلية إلى نتيجة أفضل.',
      'mistake':'خطأ واضح منح خصمك فرصاً إضافية.',
      'blunder':'خطأ فادح غيّر التقييم بدرجة كبيرة.'
    }.get(quality_code,'نقلة بحاجة إلى مراجعة.')
    return f'{desc} الفكرة: {concept}. {tip} قارن بين {board.san(played)} و{best_san} مع متابعة رد الخصم.'


def analyze_pgn_advanced(pgn_text: str, username: str) -> dict[str, Any]:
    game = plus.completed_game(pgn_text)
    color = (chess.WHITE if game.headers.get('White','').casefold() == username.casefold() else chess.BLACK)
    if username.casefold() not in {game.headers.get('White','').casefold(),game.headers.get('Black','').casefold()}:
        raise ValueError('User not in completed game')
    nodes=list(game.mainline())
    moves = [n.move for n in nodes]
    if len(moves) > plus.MAX_PGN_PLIES:
        raise ValueError('PGN exceeds allowed move limit')
    board = game.board()
    positions = [board.copy()]
    for m in moves:
        if m not in board.legal_moves:
            raise ValueError('Illegal PGN move')
        board.push(m)
        positions.append(board.copy())
    scans=[]
    limit=chess.engine.Limit(time=max(.35, min(3.0, core.ANALYSIS_TIME_SECONDS)))
    with chess.engine.SimpleEngine.popen_uci(core.STOCKFISH_PATH) as engine:
        if 'Threads' in engine.options: engine.configure({'Threads':1})
        if 'Hash' in engine.options: engine.configure({'Hash':32})
        for pos in positions:
            if pos.is_game_over(claim_draw=True):
                outcome=pos.outcome(claim_draw=True)
                cp=0 if not outcome or outcome.winner is None else (1500 if outcome.winner==chess.WHITE else -1500)
                scans.append({'cp_white':cp,'mate':None,'lines':[]});continue
            infos=engine.analyse(pos,limit,multipv=3)
            if not isinstance(infos,list): infos=[infos]
            cp,mate=cp_from(infos[0],chess.WHITE)
            lines=[{'uci':x['pv'][0].uci(),'san':pos.san(x['pv'][0]),'line':core.pv_to_san(pos,x['pv'],12),
                 'pv_uci':[m.uci() for m in x['pv'][:12]],'cp_white':cp_from(x,chess.WHITE)[0],
                 'depth':x.get('depth')} for x in infos if x.get('pv') and x['pv'][0] in pos.legal_moves]
            scans.append({'cp_white':cp,'mate':mate,'lines':lines})
    return analysis_from_scans(pgn_text,username,scans,limit.time)


def analysis_from_scans(pgn_text: str, username: str, scans: list[dict], seconds: float) -> dict[str,Any]:
    game=plus.completed_game(pgn_text)
    color = chess.WHITE if game.headers.get('White','').casefold()==username.casefold() else chess.BLACK
    if username.casefold() not in {game.headers.get('White','').casefold(),game.headers.get('Black','').casefold()}:
        raise ValueError('Player mismatch')
    nodes=list(game.mainline());moves=[n.move for n in nodes]
    board=game.board();positions=[board.copy()]
    for m in moves:
        if m not in board.legal_moves:raise ValueError('Illegal PGN move')
        board.push(m);positions.append(board.copy())
    if len(scans)!=len(positions):raise ValueError('Incomplete deep scans')
    history=[]
    own=[]
    clock_by_color={'white':None,'black':None}
    tc=game.headers.get('TimeControl','')
    try:
        initial_seconds=int(tc.split('+')[0])
    except (ValueError,TypeError):
        initial_seconds=None
    try:
        increment=int(tc.split('+')[1]) if '+' in tc else 0
    except (ValueError,TypeError):
        increment=0
    for i,m in enumerate(moves):
        prev,next_=positions[i],positions[i+1]
        san=prev.san(m)
        mover='white' if prev.turn else 'black'
        remaining=nodes[i].clock()
        last_clock=clock_by_color[mover]
        think_seconds=(max(0,round((last_clock if last_clock is not None else initial_seconds)+increment-remaining,2))
                       if remaining is not None and (last_clock is not None or initial_seconds is not None) else None)
        if remaining is not None:clock_by_color[mover]=remaining
        sgn=1 if prev.turn==chess.WHITE else -1
        before=scans[i]['cp_white']*sgn
        after=scans[i+1]['cp_white']*sgn
        drop=max(0.0,probability(before)-probability(after))
        loss=max(0, min(3000,before-after))
        first=scans[i]['lines'][0] if scans[i]['lines'] else None
        best_move=chess.Move.from_uci(first['uci']) if first else None
        is_best=best_move == m
        pv=first['line'] if first else [san]
        missed=grades.clear_missed_chance(before,after,loss)
        brilliant=bool(is_best and grades.candidate_sacrifice(prev,m,pv,before,after))
        code=grades.classify(loss,is_best,drop,missed=missed,brilliant=brilliant)
        label=grades.label(code)
        explain=brain.explain(prev,m,best_move,code,loss,scans[i]['lines'])
        scenarios=[]
        for rank,variant in enumerate(scans[i]['lines'][:3],start=1):
            insight=brain.line_insight(prev,variant.get('pv_uci',[]))
            scenarios.append({'rank':rank,'first':variant.get('san'),'uci':variant.get('uci'),
               'pv_uci':insight['moves'],'moves':insight['line'],'ideas':insight['ideas'],
               'cp_white':variant.get('cp_white'),'depth':variant.get('depth'),
               'summary':'؛ '.join(insight['ideas'])})
        # Include the played move and the engine's strongest reply, not merely
        # three counterfactual recommendations from the original position.
        reply=scans[i+1]['lines'][0] if scans[i+1]['lines'] else None
        actual_pv=[m.uci()]+((reply or {}).get('pv_uci') or [])[:11]
        actual_insight=brain.line_insight(prev,actual_pv)
        if not is_best:
            scenarios.append({'rank':0,'kind':'played','first':san,
                'uci':m.uci(),'pv_uci':actual_insight['moves'],
                'moves':actual_insight['line'],'ideas':actual_insight['ideas'],
                'cp_white':scans[i+1]['cp_white'],
                'depth':(reply or {}).get('depth'),
                'summary':'السيناريو بعد نقلة المباراة الفعلية: '+'؛ '.join(actual_insight['ideas'])})
        if reply and not is_best:
            explain['text'] += ' ردّ الخصم الأقوى على نقلة المباراة بحسب هذا التحليل: '+reply['san']+'.'
        item={'ply':i+1,'move_number':i//2+1,'color':mover,'played':san,'uci':m.uci(),
              'best': first['san'] if first else san,'best_uci':first['uci'] if first else m.uci(),
              'best_line':pv,'top_lines':scans[i]['lines'],
              'loss_cp':loss,'win_chance_drop':round(drop,2),'quality':label,'quality_code':code,
              'fen_before':prev.fen(),'fen_after':next_.fen(),
              'eval_white_cp':scans[i+1]['cp_white'], 'eval_white_mate':scans[i+1]['mate'],
              'win_chance_white':round(probability(scans[i+1]['cp_white']),1),
              'move_accuracy':round(100*exp(-loss/250),1),
              'phase':plus.phase(next_,i+1),
              'clock_remaining':remaining,'think_seconds':think_seconds,
              'explanation_ar':explain['text'], 'coaching':explain, 'scenarios':scenarios}
        history.append(item)
        if prev.turn==color: own.append(item)
    bad=[x for x in own if x['quality_code'] in grades.ERROR_CODES]
    per_color={}
    for who in ('white','black'):
        group=[x for x in history if x['color']==who]
        per_color[who]={'moves':len(group),
          'accuracy':round(statistics.mean(x['move_accuracy'] for x in group),1) if group else None,
          'acpl':round(statistics.mean(x['loss_cp'] for x in group),1) if group else None,
          'mistakes':sum(x['quality_code'] in grades.ERROR_CODES for x in group)}
    thought=[x['think_seconds'] for x in own if x['think_seconds'] is not None]
    time_management={'average_think_seconds':round(statistics.mean(thought),1) if thought else None,
      'time_pressure_moves':sum(x['clock_remaining'] is not None and x['clock_remaining']<30 for x in own)}
    by_phase={}
    for ph in ('opening','middlegame','endgame'):
        group=[x for x in own if x['phase']==ph]
        by_phase[ph]={'moves':len(group),'accuracy':round(statistics.mean(x['move_accuracy'] for x in group),1) if group else None,
                      'acpl':round(statistics.mean(x['loss_cp'] for x in group),1) if group else None,
                      'errors':sum(x['quality_code'] in grades.ERROR_CODES for x in group)}
    return {'schema_version':5,'engine':'Stockfish','analysis_seconds_per_position':seconds,
            'player':username,'white':game.headers.get('White',''),'black':game.headers.get('Black',''),
            'result':game.headers['Result'],
            'note':'دقة وتوقع الفوز محسوبان بنموذج تقريبي مستقل؛ ليست مؤشرات Chess.com الرسمية.',
            'moves_reviewed':len(own),'errors':len(bad),
            'accuracy_estimate':round(statistics.mean(x['move_accuracy'] for x in own),1) if own else None,
            'average_centipawn_loss':round(statistics.mean(x['loss_cp'] for x in own),1) if own else None,
            'phases':by_phase,'players_comparison':per_color,'time_management':time_management,
            'quality_counts':dict(Counter(x['quality_code'] for x in own)),
            'priority_lessons':sorted(bad,key=lambda x:x['loss_cp'],reverse=True)[:12],
            'all_player_moves':own,'all_moves':history,
            'evaluation_graph':[{'ply':0,'cp':scans[0]['cp_white'],'white_win_chance':round(probability(scans[0]['cp_white']),1)}]+
               [{'ply':i,'cp':v['cp_white'],'white_win_chance':round(probability(v['cp_white']),1)} for i,v in enumerate(scans[1:],1)]}


def init_issue_db():
    with core.db_connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS issue_journal (
            game_id TEXT NOT NULL, ply INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','practicing','resolved')),
            notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            PRIMARY KEY (game_id,ply), FOREIGN KEY(game_id) REFERENCES games(id)
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS ix_issue_status ON issue_journal(status)')

class VariationMoves(BaseModel):
    moves: list[str] = Field(default_factory=list,max_length=80)

class TryMove(BaseModel):
    uci: str = Field(min_length=4,max_length=5,pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")

class IssueUpdate(BaseModel):
    status: str = Field(pattern='^(open|practicing|resolved)$')
    notes: str = Field(default='', max_length=500)

def issue_feed(limit=100, status='all'):
    with core.db_connect() as db:
        rows=db.execute('SELECT * FROM games ORDER BY finished_at DESC LIMIT 300').fetchall()
        journal={(r['game_id'],r['ply']):dict(r) for r in db.execute('SELECT * FROM issue_journal')}
        progress={(r['game_id'],r['ply']):dict(r) for r in db.execute('SELECT * FROM puzzle_progress')}
    result=[]
    for row in rows:
        analysis=plus.analysis_for(row)
        player_color='white' if row['white'].casefold()==core.USERNAME else 'black'
        for x in analysis.get('all_player_moves',[]):
            if x.get('quality_code') not in ('blunder','mistake','inaccuracy','weak','missed') and x.get('quality') not in ('هفوة كبيرة','خطأ','عدم دقة','خطأ فادح','ضعيفة','ضياع فرصة'):
                continue
            ply=x.get('ply') or 2*int(x.get('move_number',0))-(1 if player_color=='white' else 0)
            j=journal.get((row['id'],ply),{})
            p=progress.get((row['id'],ply),{})
            item={'game_id':row['id'],'ply':ply,'move_number':x.get('move_number'),
                  'played':x.get('played'),'best':x.get('best'),'fen':x.get('fen_before'),
                  'quality':x.get('quality'),'loss_cp':x.get('loss_cp'),
                  'phase':x.get('phase') or ('opening' if ply<=20 else 'middlegame' if ply<=60 else 'endgame'),
                  'status':j.get('status','open'),'notes':j.get('notes',''),
                  'solves':p.get('solves',0),'attempts':p.get('attempts',0),
                  'next_due_at':p.get('next_due_at'),
                  'finished_at':row['finished_at'], 'url':row['url']}
            if status=='all' or item['status']==status: result.append(item)
    return sorted(result,key=lambda x:(x['status']=='resolved',-x['finished_at'],-(x['loss_cp'] or 0)))[:limit]

def detailed_metrics(gid):
    row=plus.get_row(gid)
    review=plus.review_data(row)
    analysis=plus.analysis_for(row)
    own=analysis.get('all_player_moves',[])
    return {'id':gid,'opening':review['opening'],'player_color':review['player_color'],
            'result':review['result'],'accuracy_estimate':analysis.get('accuracy_estimate'),
            'average_centipawn_loss':analysis.get('average_centipawn_loss'),
            'quality_counts':analysis.get('quality_counts',{}),
            'phases':analysis.get('phases',{}),
            'players_comparison':analysis.get('players_comparison',{}),
            'time_management':analysis.get('time_management',{}),'errors':analysis.get('errors',0),
            'reviewed':analysis.get('moves_reviewed',0),
            'evaluation_graph':analysis.get('evaluation_graph',[]),
            'all_moves':analysis.get('all_moves',[]),
            'note':analysis.get('note','تحليل سابق: أعد تحليل المباراة لعرض مؤشرات الإصدار الجديد.')}

def install(app):
    @app.get('/api/pro/v3/game/{gid}', dependencies=[Depends(core.auth)])
    def game_report(gid:str):
        return detailed_metrics(gid)

    @app.post('/api/pro/v3/game/{gid}/try/{ply}', dependencies=[Depends(core.auth)])
    def try_historical_position(gid:str,ply:int,request:TryMove):
        # Review only an archived, completed game position, not arbitrary FEN.
        row=plus.get_row(gid)
        game=plus.completed_game(row['pgn'])
        moves=list(game.mainline_moves())
        if ply<0 or ply>len(moves):raise HTTPException(status_code=404,detail='Unknown position')
        board=game.board()
        for m in moves[:ply]:board.push(m)
        if board.is_game_over(claim_draw=True):raise HTTPException(status_code=409,detail='Position is terminal')
        move=chess.Move.from_uci(request.uci)
        if move not in board.legal_moves:raise HTTPException(status_code=422,detail='Illegal move')
        san=board.san(move)
        board.push(move)
        return {'fen':board.fen(),'uci':move.uci(),'san':san,'legal_moves':[m.uci() for m in board.legal_moves],
                'note':'مراجعة خطوة واحدة من مباراة مكتملة، دون تحليل حي.'}

    @app.post('/api/pro/v3/game/{gid}/variation/{ply}', dependencies=[Depends(core.auth)])
    def variation(gid:str,ply:int,request:VariationMoves):
        # No engine query: only legal move exploration from an archived game.
        row=plus.get_row(gid)
        game=plus.completed_game(row['pgn'])
        recorded=list(game.mainline_moves())
        if ply<0 or ply>len(recorded):raise HTTPException(status_code=404,detail='Unknown position')
        board=game.board()
        for m in recorded[:ply]:board.push(m)
        sans=[]
        for code in request.moves:
            try:mv=chess.Move.from_uci(code)
            except ValueError:raise HTTPException(status_code=422,detail='Invalid UCI move')
            if mv not in board.legal_moves:raise HTTPException(status_code=422,detail='Illegal variation move')
            sans.append(board.san(mv))
            board.push(mv)
        return {'fen':board.fen(),'legal_moves':[m.uci() for m in board.legal_moves],
                'san':sans,'done':board.is_game_over(claim_draw=True),
                'note':'تجربة نقلات قانونية من مباراة مكتملة بدون تشغيل المحرك على مباريات مباشرة.'}

    @app.get('/api/pro/v3/issues', dependencies=[Depends(core.auth)])
    def issues(status:str=Query(default='all',pattern='^(all|open|practicing|resolved)$'),limit:int=Query(100,ge=1,le=300)):
        rows=issue_feed(limit,status)
        counts=Counter(x['status'] for x in issue_feed(300,'all'))
        return {'issues':rows,'total':len(rows),'counts':dict(counts)}

    @app.post('/api/pro/v3/issues/{gid}/{ply}', dependencies=[Depends(core.auth)])
    def issue_update(gid:str,ply:int,update:IssueUpdate):
        if ply<1 or ply>plus.MAX_PGN_PLIES:raise HTTPException(status_code=404,detail='Unknown position')
        row=plus.get_row(gid)
        a=plus.analysis_for(row)
        player_color='white' if row['white'].casefold()==core.USERNAME else 'black'
        errors=[]
        for x in a.get('all_player_moves',[]):
            if x.get('quality_code') not in ('blunder','mistake','inaccuracy','weak','missed') and x.get('quality') not in ('هفوة كبيرة','خطأ','عدم دقة','خطأ فادح','ضعيفة','ضياع فرصة'):
                continue
            n=x.get('ply') or 2*int(x.get('move_number',0))-(1 if player_color=='white' else 0)
            errors.append(n)
        if ply not in errors:raise HTTPException(status_code=404,detail='No coaching issue at this move')
        with core.db_connect() as db:
            db.execute('''INSERT INTO issue_journal(game_id,ply,status,notes,updated_at) VALUES (?,?,?,?,?)
              ON CONFLICT(game_id,ply) DO UPDATE SET status=excluded.status,notes=excluded.notes,updated_at=excluded.updated_at''',
              (gid,ply,update.status,update.notes,now_iso()))
        return {'ok':True,'status':update.status,'game_id':gid,'ply':ply}

    @app.post('/api/pro/v3/reanalyze-legacy', dependencies=[Depends(core.auth)])
    async def reanalyze_legacy(limit:int=Query(default=5,ge=1,le=15)):
        if _bulk['running']:
            raise HTTPException(status_code=409, detail='Bulk analysis already running')
        with core.db_connect() as db:
            rows=db.execute('SELECT id,pgn,analysis_json FROM games ORDER BY finished_at DESC LIMIT 300').fetchall()
        eligible=[]
        for row in rows:
            if plus.analysis_for(row).get('schema_version') in (4,5):continue
            try:plus.completed_game(row['pgn'])
            except HTTPException:continue
            eligible.append((row['id'],row['pgn']))
            if len(eligible)>=limit:break
        _bulk.update(running=bool(eligible),requested=len(eligible),done=0,failed=0,last_error=None)
        async def runner():
            try:
                async with core.coach.lock:
                    for gid,pgn in eligible:
                        try:
                            analyzed=await asyncio.to_thread(analyze_pgn_advanced,pgn,core.USERNAME)
                            with core.db_connect() as db:
                                db.execute('UPDATE games SET analysis_json=?,analysis_error=NULL WHERE id=?',
                                        (json.dumps(analyzed,ensure_ascii=False),gid))
                            _bulk['done']+=1
                        except Exception as exc:
                            LOG.exception('Failed to reanalyse archived game %s',gid)
                            _bulk['failed']+=1
                            _bulk['last_error']=str(exc)[:120]
            finally:
                _bulk['running']=False
        if eligible:
            task=asyncio.create_task(runner())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        return {'queued':len(eligible),'running':_bulk['running']}

    @app.get('/api/pro/v3/reanalyze-status', dependencies=[Depends(core.auth)])
    def reanalyze_status():
        return dict(_bulk)

    @app.get('/api/pro/v3/progress', dependencies=[Depends(core.auth)])
    def progress():
        with core.db_connect() as db:
            rows=db.execute('SELECT * FROM games ORDER BY finished_at DESC LIMIT 250').fetchall()
            tries=db.execute('SELECT attempts,solves,streak FROM puzzle_progress').fetchall()
            resolved=db.execute("SELECT COUNT(*) AS n FROM issue_journal WHERE status='resolved'").fetchone()['n']
        points=[]
        for row in reversed(rows):
            a=plus.analysis_for(row)
            if not a: continue
            points.append({'id':row['id'],'date':row['finished_at'],'accuracy':a.get('accuracy_estimate'), 'schema_version':a.get('schema_version'),
                'acpl':a.get('average_centipawn_loss'),'errors':a.get('errors',0)})
        return {'games_analyzed':len(points),'legacy_games':sum(x['schema_version'] not in (4,5) for x in points),
                'trend':points,
                'puzzles_attempted':sum(r['attempts'] for r in tries),
                'puzzles_solved':sum(r['solves'] for r in tries),
                'resolved_issues':resolved,
                'note':'الإحصاءات التحليلية تقديرية وليست نظام تقييم Elo ولا دقة Chess.com الرسمية.'}

