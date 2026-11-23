"""Position-grounded Arabic teaching from *completed* Chess.com games.

Explanations never invent engine continuations: show only legal saved PVs and
clearly distinguish observed facts, tactical warnings and engine estimates.
This is a transparent rule-based tutor; it is not an LLM or certified coach.
"""
from __future__ import annotations
import json
import chess

PIECES={chess.PAWN:'بيدق',chess.KNIGHT:'حصان',chess.BISHOP:'فيل',chess.ROOK:'قلعة',chess.QUEEN:'وزير',chess.KING:'ملك'}
FILES='abcdefgh'

def piece_name(t):return PIECES.get(t,'قطعة')
def side_name(c):return 'الأبيض' if c==chess.WHITE else 'الأسود'
def evaluation_ar(cp):
    if cp is None:return 'لا يتوفر تقييم موثوق لهذه الاستمرارية.'
    try: value=float(cp)/100
    except (ValueError,TypeError):return 'لا يتوفر تقييم موثوق لهذه الاستمرارية.'
    if abs(value)<.15:return 'الموقف متقارب تقريباً بحسب تقدير المحرك.'
    return f'أفضلية تقديرية لـ{side_name(chess.WHITE if value>0 else chess.BLACK)} بمقدار {abs(value):.2f} من قيمة البيدق.'

def compact_score(loss):
    if loss is None:return 'غير محسوب'
    try:return f'{max(0,float(loss)/100):.2f} من قيمة البيدق تقريباً'
    except (ValueError,TypeError):return 'غير محسوب'

def square_name(sq):return chess.square_name(sq)
def move_facts(board:chess.Board,move:chess.Move):
    """Verifiable board observations, not speculative strategic certainty."""
    if move not in board.legal_moves:raise ValueError('نقلة غير قانونية')
    name=piece_name(board.piece_type_at(move.from_square))
    side=board.turn
    san=board.san(move)
    capture=board.is_capture(move)
    ep=board.is_en_passant(move)
    victim=board.piece_at(move.to_square)
    if ep:victim=chess.Piece(chess.PAWN,not side)
    check=board.gives_check(move)
    castle=board.is_castling(move)
    move_color=side_name(side)
    benefits=[];risks=[]
    if capture and victim:benefits.append(f'تأخذ {piece_name(victim.piece_type)} الخصم على {square_name(move.to_square)}، فتغيّر توازن القطع فعلياً.')
    if check:benefits.append('تعطي كشاً للملك؛ يجب على الخصم التعامل مع الكش قبل تنفيذ خطته.')
    if castle:benefits.append('تُبيّت الملك وتُشرك القلعة في اللعب، ما يساعد غالباً على أمان الملك والتواصل بين القطع.')
    if move.promotion:benefits.append(f'ترقّي البيدق إلى {piece_name(move.promotion)}، وتغيّر القوة المادية جذرياً.')
    if board.piece_type_at(move.from_square)==chess.PAWN and chess.square_file(move.to_square) in (3,4):
        benefits.append('تحرّك بيدقاً في عمودي المركز d أو e، وقد يؤثر ذلك في المساحة وخطوط القطع.')
    if board.piece_type_at(move.from_square) in (chess.KNIGHT,chess.BISHOP) and chess.square_rank(move.from_square) in (0,7):
        benefits.append('تُخرج قطعة خفيفة من صفها الخلفي وتزيد إمكانيات مشاركتها في اللعب.')
    next_board=board.copy();next_board.push(move)
    # Concrete newly attacked opposing pieces by the moved piece.
    moving_piece=next_board.piece_at(move.to_square)
    if moving_piece:
        newly_attacked=[]
        for sq in next_board.attacks(move.to_square):
            victim_piece=next_board.piece_at(sq)
            if victim_piece and victim_piece.color!=side and victim_piece.piece_type!=chess.KING:
                # A direct attack is observable, but not necessarily a winning tactic.
                newly_attacked.append((PIECES[victim_piece.piece_type],square_name(sq)))
        if newly_attacked and not capture:
            first=', '.join(f'{p} على {sq}' for p,sq in newly_attacked[:2])
            benefits.append(f'من موقع {square_name(move.to_square)} أصبحت القطعة تهدّد {first}. افحص إن كان الخصم يستطيع الدفاع أو التبادل.')
    if board.is_check():benefits.append('النقلة تزيل الكش الموجود على ملكك بطريقة قانونية.')
    if moving_piece and moving_piece.piece_type==chess.PAWN:
        rank=chess.square_rank(move.to_square)
        if (side==chess.WHITE and rank>=5) or (side==chess.BLACK and rank<=2):
            benefits.append('البيدق بات قريباً من صف الترقية؛ تحقق من المربعات التي تمنع تقدّمه.')
    if next_board.is_checkmate():benefits.append('هذه النقلة تحقق كش مات وتنهي اللعبة مباشرة.')
    if next_board.is_stalemate():risks.append('هذه النقلة تُحدث تعادلاً بالخنق؛ تأكد أن التعادل هو النتيجة المطلوبة.')
    new_square=move.to_square
    if board.piece_type_at(move.from_square)!=chess.KING and next_board.is_attacked_by(not side,new_square):
        if not next_board.is_attacked_by(side,new_square):risks.append(f'{name} على {square_name(new_square)} مكشوف لهجوم الخصم ولا تحميه قطعة مباشرة؛ افحص إمكان أخذه وردودك.')
        else:risks.append(f'{name} على {square_name(new_square)} تحت هجوم مباشر لكنه محمي؛ احسب التبادلات قبل الاطمئنان.')
    if not benefits:benefits.append(f'تُنقل {name} {move_color} من {square_name(move.from_square)} إلى {square_name(move.to_square)}؛ قيّم نشاطه وتناسقه مع بقية قطعك.')
    if not risks:risks.append('لا يظهر من هذه النقلة وحدها خطر مباشر مؤكد على القطعة المنقولة؛ راقب رد الخصم والكش والأسر والتهديدات التالية.')
    # Warn about concrete immediate legal tactical forcing replies, without claiming inevitability.
    if not next_board.is_game_over(claim_draw=True):
        replies=list(next_board.legal_moves)
        checks=sum(1 for m in replies if next_board.gives_check(m))
        caps=sum(1 for m in replies if next_board.is_capture(m))
        if checks:risks.append(f'للخصم {checks} رد/ردود قانونية تعطي كشاً. ليست كلها بالضرورة جيدة؛ اعرض السيناريو للتحقق.')
        elif caps:risks.append(f'للخصم {caps} خيار/خيارات للأخذ مباشرة؛ ليست جميعها بالضرورة مربحة.')
    return {'uci':move.uci(),'san':san,'from':square_name(move.from_square),'to':square_name(move.to_square),
            'piece':name,'side':move_color,'benefits':benefits[:4],'risks':risks[:4],
            'summary':f'{move_color}: {san} — {name} من {square_name(move.from_square)} إلى {square_name(move.to_square)}.'}

def position_observations(board:chess.Board):
    turn=board.turn
    observations=[];questions=[];arrows=[]
    if board.is_check():observations.append(f'{side_name(turn)} تحت كش الآن؛ لا توجد حرية لاختيار نقلة تتجاهل الكش.')
    hanging=[]
    for sq,piece in board.piece_map().items():
        if piece.color!=turn or piece.piece_type==chess.KING:continue
        if board.is_attacked_by(not turn,sq) and not board.is_attacked_by(turn,sq):
            hanging.append((PIECES[piece.piece_type],square_name(sq)))
    if hanging:
        text='، '.join(f'{x} على {y}' for x,y in hanging[:3]);observations.append('قطعك التي تتعرض لهجوم مباشر من دون حماية مباشرة: '+text+'؛ احسب ما إذا كان أسرها ممكناً ومربحاً.')
        for _,target in hanging[:2]:
            attackers=sorted(board.attackers(not turn,chess.parse_square(target)))
            if attackers:arrows.append({'uci':chess.square_name(attackers[0])+target,'color':'red'})
        questions.append('هل لديك قطعة مهددة يجب الدفاع عنها، أم توجد نقلة أقوى في المقابل؟')
    checks=[m for m in board.legal_moves if board.gives_check(m)]
    captures=[m for m in board.legal_moves if board.is_capture(m)]
    observations.append(f'لديك {len(checks)} نقلة تعطي كشاً و{len(captures)} نقلة تأخذ قطعة قانونياً. ليست جميعها بالضرورة قوية.')
    if checks:questions.append('ماذا سيحدث بعد نقلة الكش؟ وهل لها رد سهل؟')
    if captures:questions.append('هل توجد عملية أخذ مربحة بعد حساب رد الخصم؟')
    questions.extend(['ما التهديد المباشر الذي ينفذه خصمك في الدور القادم؟','أي قطعة ستصبح أضعف إذا حركتها الآن؟'])
    if board.fullmove_number<=12:
        home=chess.E1 if turn==chess.WHITE else chess.E8
        if board.king(turn)==home and board.has_castling_rights(turn):
            observations.append('ملكك ما زال في مربعه الأصلي والتبييت قد يكون متاحاً لاحقاً؛ افحص تأمين الملك مع تطوير القطع.')
        still_home=0
        for sq in ((chess.B1,chess.G1,chess.C1,chess.F1) if turn==chess.WHITE else (chess.B8,chess.G8,chess.C8,chess.F8)):
            pc=board.piece_at(sq)
            if pc and pc.color==turn and pc.piece_type in (chess.KNIGHT,chess.BISHOP):still_home+=1
        if still_home:
            observations.append(f'لديك {still_home} قطعة/قطع خفيفة ما زالت على مربعات البداية؛ تطويرها قد يكون هدفاً جيداً إذا لم يوجد تهديد عاجل.')
    if not board.is_check():observations.append('المهمة: افحص الكش أولاً، ثم الأسر، ثم التهديدات، وبعد ذلك حدد خطة تحسين القطع.')
    return {'observations':observations,'questions':questions[:4],'arrows':arrows}

def _from_lines(row):
    try:value=json.loads(row.get('lines_json') or '[]')
    except (ValueError,TypeError):return []
    return value if isinstance(value,list) else []

def _safe_scenario(board:chess.Board,moves:list[str],label:str,score=None,kind='engine',number=1):
    b=board.copy();start=b.fen();fens=[start];steps=[];valid=[]
    for entry in moves[:12]:
        try:m=chess.Move.from_uci(entry)
        except (ValueError,TypeError):break
        if m not in b.legal_moves:break
        info=move_facts(b,m)
        b.push(m);fens.append(b.fen());steps.append(info);valid.append(m.uci())
    if not valid:return None
    return {'id':kind+'-'+str(number),'label':label,'type':kind,'moves':valid,'fens':fens,
       'steps':steps,'eval_cp_white':score,'evaluation':evaluation_ar(score),
       'source_note':'خط استرشادي محفوظ من بحث Stockfish، وليس توقعاً مؤكداً لرد الخصم.' if kind=='engine' else
          'هذه هي النقلة التي لعبتها في المباراة الأصلية. لا نختلق ردوداً لاحقة لم يُحللها المحرك لهذا الفرع.'}

def create_teacher_plan(row,lesson_title='درس من مبارياتك'):
    """Build legal board explanations using ONLY this user's already-finished position."""
    r=dict(row);board=chess.Board(r['fen_before'])
    result=position_observations(board)
    best_uci=r.get('best_uci');original_san=r.get('san','')
    scenarios=[];seen=set()
    for i,l in enumerate(_from_lines(r)):
        if not isinstance(l,dict):continue
        pv=l.get('pv_uci') or ([l.get('uci')] if l.get('uci') else [])
        if not isinstance(pv,list) or not pv:continue
        if pv[0] in seen:continue
        score=l.get('eval')
        try:score=int(score) if score is not None else None
        except (ValueError,TypeError):score=None
        scenario=_safe_scenario(board,pv,'خيار المحرك '+str(i+1),score,'engine',i+1)
        if scenario:scenarios.append(scenario);seen.add(scenario['moves'][0])
    if best_uci and best_uci not in seen:
        scenario=_safe_scenario(board,[best_uci],'الخيار الأقوى المحفوظ',None,'engine',0)
        if scenario:scenarios.insert(0,scenario);seen.add(best_uci)
    try:
        actual=board.parse_san(original_san)
        if actual.uci() not in seen:
            scenario=_safe_scenario(board,[actual.uci()],'نقلتك في المباراة',None,'played',0)
            if scenario:scenarios.append(scenario)
    except (ValueError,chess.IllegalMoveError,chess.AmbiguousMoveError):pass
    # Prefer available engine options and one observed move; never fabricate continuations.
    scenarios=scenarios[:4]
    original_grade=r.get('grade','unrated')
    loss=r.get('loss_cp')
    difference=('هذا تقدير لتراجع الأفضلية، وليس عدد البيادق التي خسرتها فعلياً.' if loss is not None else 'لا يتوفر قياس دقيق لهذا الفرق حالياً.')
    if loss is not None:
        comparison=f'المحرك قدّر تراجع وضعك بما يعادل {compact_score(loss)}. {difference}'
    else:comparison='فارق التقييم لم يُحسب لهذا الموقف.'
    if original_grade in ('blunder','mistake','missed','weak'):
        takeaway='في المباراة الأصلية كان هناك بديل أقوى. ادرس ردود الخصم في الفرعين ولا تعتمد على حفظ النقلة وحدها.'
    elif original_grade in ('excellent','good','book','brilliant'):
        takeaway='نقلتك الأصلية تبدو مقبولة ضمن التصنيف المحفوظ؛ راجع سبب قوتها قبل إكمال الدرس.'
    else:takeaway='تصنيف هذه النقلة غير محسوم. ركز على الموقف الحقيقي والتهديدات المحددة.'
    return {'lesson_title':lesson_title,'fen':board.fen(),'side':side_name(board.turn),
       'position':result,'source_grade':original_grade,'played_san':original_san,
       'best_uci':best_uci,'best_san':r.get('best_san'),
       'comparison':comparison,'takeaway':takeaway,
       'scenarios':scenarios,
       'terminology':{
         'eval':'التقييم: رقم تقديري لقوة الموقف. الرقم الموجب لصالح الأبيض والسالب لصالح الأسود.',
         'centipawn':'100 جزء من المئة من قيمة البيدق = 1 بيدق في مقياس المحرك. هذه وحدة تقييم وليست خسارة قطعة فعلية.',
         'line':'السيناريو: تسلسل نقلات محتمل حسب بحث Stockfish، وليس مساراً إجبارياً على الخصم.'},
       'notice':'شرح مرتبط بالوضعية الفعلية وقواعد الشطرنج، وليس رأياً من مدرب بشري. المحرك يقدّم تقديراً، وقد تتغير التقييمات مع عمق البحث.'}
