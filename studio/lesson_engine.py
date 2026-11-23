"""Bounded coaching comparison for already-finished games, never live competitive play."""
from __future__ import annotations
import json,os
import chess, chess.engine

MAX_ACCEPTABLE_CP=45

def _score_from_line(line,color):
    try:return int(line['eval'])*(1 if color==chess.WHITE else -1)
    except (KeyError,TypeError,ValueError):return None

def assess_move(row,board,move):
    """Accept the best saved move and comparably good engine-verified alternatives.

    An unknown move is *not* automatically described as a blunder. If the engine
    cannot be reached, only saved evaluations are used, clearly labelled.
    """
    uci=move.uci()
    if uci==row['best_uci']:
        return {'accepted':True,'status':'best','loss_cp':0,
                'explanation':'أحسنت! هذه النقلة تطابق أفضل استمرارية محفوظة للموقف. استعرض ردود الخصم لفهم الفكرة وليس فقط حفظ الحركة.'}
    try:lines=json.loads(row['lines_json'] or '[]')
    except (ValueError,TypeError):lines=[]
    if lines and isinstance(lines,list):
        primary=_score_from_line(lines[0],board.turn)
        for line in lines:
            if not isinstance(line,dict) or line.get('uci')!=uci:continue
            score=_score_from_line(line,board.turn)
            if primary is None or score is None:break
            delta=max(0,primary-score)
            return {'accepted':delta<=MAX_ACCEPTABLE_CP,'status':'acceptable' if delta<=MAX_ACCEPTABLE_CP else 'weaker',
                    'loss_cp':delta,'explanation':
                    ('أحسنت! هذه ليست أول نقلة للمحرك لكنها بديل قوي قريب في التقييم. قارن خطها بالاختيار الأول.' if delta<=MAX_ACCEPTABLE_CP else
                     'النقلة قانونية، لكنها أضعف من الخيار الأول بمقدار تقريبي '+str(delta)+' سنتي بيدق. جرّب التلميح وقارن الردود.')}
    # For an unlisted legal choice compare the best and submitted move under the same
    # short analysis budget, not against scores from a different search depth.
    try:
        path=os.getenv('STOCKFISH_PATH','/usr/games/stockfish')
        with chess.engine.SimpleEngine.popen_uci(path,timeout=4) as engine:
            opts={}
            if 'Threads' in engine.options:opts['Threads']=1
            if 'Hash' in engine.options:opts['Hash']=16
            if 'UCI_LimitStrength' in engine.options:opts['UCI_LimitStrength']=False
            if 'Skill Level' in engine.options:opts['Skill Level']=20
            if opts:engine.configure(opts)
            limit=chess.engine.Limit(time=.45)
            first=engine.analyse(board,limit)
            second=engine.analyse(board,limit,root_moves=[move])
            a=first['score'].pov(board.turn).score(mate_score=10000)
            b=second['score'].pov(board.turn).score(mate_score=10000)
            if a is None or b is None:raise ValueError('Score not available')
            delta=max(0,int(a-b))
            accepted=delta<=MAX_ACCEPTABLE_CP
            return {'accepted':accepted,'status':'acceptable' if accepted else 'weaker','loss_cp':delta,
               'explanation':('أحسنت! نقلة قوية بديلة، والفارق التقريبي عن أفضل رد صغير.' if accepted else
                   'فارق تقريبي '+str(delta)+' سنتي بيدق مقارنة بأفضل رد في هذا الفحص. استخدم السهم لمعرفة البديل الأقوى.')}
    except (OSError,ValueError,TimeoutError,chess.engine.EngineError,chess.engine.EngineTerminatedError) as exc:
        return {'accepted':False,'status':'unverified','loss_cp':None,
                'explanation':'النقلة قانونية، لكن المحرك لم يتمكن من فحص هذا البديل الآن. لا يمكن وصفها بأنها خطأ مؤكّد؛ اعرض الحل المحفوظ أو أعد المحاولة.'}
