"""Deterministic, position-aware Arabic coaching. No invented engine variations.
All scenarios are validated legal sequences from completed PGNs only.
"""
import chess
from typing import Any

PIECES = {chess.PAWN:'البيدق', chess.KNIGHT:'الحصان', chess.BISHOP:'الفيل',chess.ROOK:'القلعة',chess.QUEEN:'الوزير',chess.KING:'الملك'}

def line_insight(board: chess.Board, pv_uci: list[str]) -> dict[str,Any]:
    temp=board.copy(); sans=[]; events=[]
    for idx, code in enumerate(pv_uci[:12]):
        try: move=chess.Move.from_uci(code)
        except ValueError:break
        if move not in temp.legal_moves:break
        actor=temp.piece_at(move.from_square)
        if not actor:break
        role='الطرف صاحب النقلة' if idx%2==0 else 'الخصم'
        if temp.is_castling(move): events.append((idx, f'{role} يؤمّن الملك بالتبييت'))
        if temp.is_capture(move):
            victim=temp.piece_at(move.to_square)
            name=PIECES.get(victim.piece_type,'بيدق') if victim else 'بيدق (أخذ بالتجاوز)'
            events.append((idx,f'{role} يأسر {name} في {chess.square_name(move.to_square)}'))
        if temp.gives_check(move): events.append((idx,f'{role} يهدد الملك بكش يجبر الرد'))
        if move.promotion:events.append((idx,f'{role} يرقي بيدقاً إلى {PIECES.get(move.promotion,"قطعة")}'))
        if actor.piece_type==chess.PAWN and chess.square_file(move.to_square) in (3,4) and idx==0:
            events.append((idx,'تعزيز وجود البيدق في المركز'))
        if actor.piece_type==chess.KING and idx==0 and len(board.piece_map())<16:
            events.append((idx,'تنشيط الملك في نهاية اللعب'))
        sans.append(temp.san(move));temp.push(move)
        if temp.is_checkmate():events.append((idx,'ينتهي هذا الخط بكش مات'));break
    primary=[ev for _,ev in events[:4]]
    if not primary and sans:
        piece=board.piece_at(chess.Move.from_uci(pv_uci[0]).from_square)
        if piece and piece.piece_type in (chess.KNIGHT,chess.BISHOP):primary=['تحسين نشاط '+PIECES[piece.piece_type]+' وتهديد المربعات المهمة']
        elif piece and piece.piece_type==chess.ROOK:primary=['تحسين وضع القلعة لاستغلال الصفوف والأعمدة']
        else:primary=['نقلة هادئة تتطلب فحص رد الخصم والخطة التالية']
    return {'line':sans,'ideas':primary,'position_after':temp.fen(),'moves':pv_uci[:len(sans)]}

def explain(board: chess.Board, played: chess.Move, best: chess.Move|None, quality: str, loss_cp: int, lines: list[dict]) -> dict[str,Any]:
    played_san=board.san(played); best_san=board.san(best) if best in board.legal_moves else played_san
    exact=best==played
    phase='الافتتاح' if board.fullmove_number<=10 else ('النهاية' if len(board.piece_map())<=14 else 'وسط اللعب')
    best_line=next((x for x in lines if x.get('uci')==(best.uci() if best else None)),None)
    suggestion=line_insight(board,(best_line or {}).get('pv_uci',[]) or ([best.uci()] if best else []))
    actual=line_insight(board,[played.uci()])
    intro={'brilliant':'نقلة ذات تضحية تكتيكية تحقق الفكرة المحسوبة في هذا العمق.',
        'excellent':'من أقوى الاختيارات في هذه الوضعية وفق البحث الحالي.',
        'good':'اختيار سليم يحافظ على فرصك، وإن وُجد بديل أدق.',
        'weak':'نقلة أضعفت جودة الوضع قليلاً مقارنة بالبديل الأقوى.',
        'missed':'ضاعت فرصة واضحة كانت متاحة قبل هذه النقلة.',
        'mistake':'هذا القرار أعطى الخصم فرصة لتحسين موقفه.',
        'blunder':'هذه النقلة غيّرت ميزان الموقف بصورة كبيرة.'}.get(quality,'نقلة قيد المراجعة.')
    material='؛ '.join(suggestion['ideas'][:3])
    after=board.copy();after.push(played)
    alerts=[]
    if after.is_check():alerts.append('الخصم الآن في حالة كش')
    if board.is_capture(played):alerts.append('اختيارك تضمن أخذاً؛ احسب الرد المقابل')
    if board.is_castling(played):alerts.append('التبييت غيّر أمان الملك')
    if played.promotion:alerts.append('تمت ترقية البيدق')
    if not alerts:alerts.append('افحص النقلة التالية للخصم قبل تقرير الخطة')
    contextual=f'في {phase}، لعبت {played_san}. '+intro
    if exact: contextual+=f' النقلة تطابق اختيار Stockfish الأول. الفكرة الرئيسية: {material}.'
    else:contextual+=f' البديل {best_san} يتفوق في هذا العمق بمقدار تقريبي {loss_cp/100:.2f} بيدق. الفكرة وراءه: {material}.'
    contextual+=' عند التطبيق: '+'؛ '.join(alerts)+'.'
    return {'text':contextual,'best_reason':material,'played_reason':'؛ '.join(actual['ideas'] or alerts),
            'phase':phase,'alert':alerts,'best':best_san,'played':played_san}
