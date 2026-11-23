"""Source-labelled opening lessons. No invented theory or quality scores."""
import json, threading
import chess, chess.engine
from fastapi import HTTPException
from . import store, recognition
from ..training_teacher import engine_session
LOCK=threading.Lock()
VERSION='study-v2'

def explain(before, move):
 piece=before.piece_at(move.from_square); after=before.copy(); after.push(move)
 dest=chess.square_name(move.to_square); origin=chess.square_name(move.from_square)
 names={1:('البيدق','pawn'),2:('الحصان','knight'),3:('الفيل','bishop'),4:('القلعة','rook'),5:('الوزير','queen'),6:('الملك','king')}
 ar,en=names[piece.piece_type]; benefit=[]; watch=[]
 if before.is_castling(move):benefit.append(('يبيّت الملك ويُدخل القلعة إلى اللعب.','Castles the king and brings the rook into play.'))
 if before.is_capture(move):benefit.append(('يأخذ قطعة الخصم'+(' بالتجاوز.' if before.is_en_passant(move) else '.'),'Captures an opponent’s piece'+(' en passant.' if before.is_en_passant(move) else '.')))
 if piece.piece_type in (chess.BISHOP,chess.KNIGHT) and chess.square_rank(move.from_square)==(0 if piece.color else 7):benefit.append(('يطوّر قطعة خفيفة من الصف الخلفي.','Develops a minor piece from the back rank.'))
 center={chess.D4,chess.E4,chess.D5,chess.E5}; controlled=sorted(chess.square_name(s) for s in after.attacks(move.to_square)&center)
 if controlled:benefit.append(('يراقب مربعات المركز: '+', '.join(controlled)+'.','Controls central squares: '+', '.join(controlled)+'.'))
 if move.to_square in center:benefit.append(('يضع قطعة في المركز. حافظ على دعمها.','Occupies a central square. Keep it supported.'))
 targets=[chess.square_name(s) for s in after.attacks(move.to_square) if after.piece_at(s) and after.color_at(s)!=piece.color and after.piece_type_at(s)!=chess.KING]
 if targets:benefit.append(('يهاجم قطع الخصم على '+', '.join(targets)+'. وجود هجوم لا يضمن كسبها.','Attacks enemy pieces on '+', '.join(targets)+'. An attack does not guarantee winning them.'))
 if piece.piece_type==chess.PAWN:
  opened=[]
  for sq,p in before.piece_map().items():
   if p.color==piece.color and p.piece_type in (chess.BISHOP,chess.QUEEN) and len(after.attacks(sq))>len(before.attacks(sq)):opened.append(chess.square_name(sq))
  if opened:benefit.append(('يوسّع خطوط القطع الموجودة على '+', '.join(opened)+'.','Opens more lines for pieces on '+', '.join(opened)+'.'))
 if after.is_check():benefit.append(('يعطي كشاً؛ يجب على الخصم معالجة الكش أولاً.','Gives check; the opponent must respond to the check.'))
 if piece.piece_type==chess.PAWN:
  watch.append(('تقدّم البيدق لا يمكن التراجع عنه؛ راقب المربعات التي تركها.','A pawn advance cannot be reversed; watch the squares it leaves behind.'))
 if any(m.to_square==move.to_square and after.is_capture(m) for m in after.legal_moves):watch.insert(0,('يستطيع الخصم أخذ القطعة على '+dest+' قانونياً؛ احسب التبادل قبل تكرارها.','The opponent can legally capture on '+dest+'; calculate the exchange before repeating this move.'))
 if piece.piece_type==chess.QUEEN and before.fullmove_number<=8:watch.append(('تحريك الوزير مبكراً قد يسمح للخصم بتطوير قطعه مع مهاجمته.','An early queen move may let the opponent develop with attacks on it.'))
 if not benefit:benefit.append(('ينقل '+ar+' من '+origin+' إلى '+dest+' ويغيّر خطوطه المتاحة.','Moves the '+en+' from '+origin+' to '+dest+' and changes its available lines.'))
 if not watch:watch.append(('راقب الردود القانونية وتنسيق القطع. هذه ملاحظة هندسية، وليست حكماً بأن النقلة هي الأفضل.','Check legal replies and piece coordination. These are board facts, not a claim that this is the best move.'))
 return {lang:{'why':' '.join(x[i] for x in benefit),'watch':watch[0][i]} for i,lang in enumerate(('ar','en'))}

def materialize(moves, catalogue_plies):
 board=chess.Board();steps=[]
 for i,uci in enumerate(moves):
  move=chess.Move.from_uci(uci)
  if move not in board.legal_moves:raise ValueError('Illegal study continuation')
  note=explain(board,move);san=board.san(move);board.push(move)
  steps.append({'fen':board.fen(),'uci':uci,'san':san,'note':note,'source':'catalogue' if i<catalogue_plies else 'engine','legal_moves':[m.uci() for m in board.legal_moves]})
 return steps

def lesson(oid, reserve, branch_id=None):
 from .traps import for_opening,lesson as trap_lesson
 tid=for_opening(oid)
 if tid:return trap_lesson(tid)
 original=recognition.opening(oid);prefix=original['uci'];rev=original['revision']
 with store.connection() as db:
  candidates=[]
  for row in db.execute('SELECT id,name,uci_json,plies FROM kc_openings WHERE revision=? AND plies>=? ORDER BY plies DESC,name',(rev,len(prefix))):
   line=json.loads(row['uci_json'])
   if line[:len(prefix)]==prefix:candidates.append((dict(row),line))
 candidates=candidates or [({'id':oid,'name':original['name'],'plies':len(prefix)},prefix)]
 if len(candidates)>1:
  def priority(x):
   name=x[0]['name'];pianissimo=original['name']=='Italian Game' and 'Giuoco Pianissimo, Main Line' in name
   return (not pianissimo,'Main Line' not in name,any(t in name for t in ('Gambit','Trap','Attack')),-x[0]['plies'],name)
  candidates.sort(key=priority)
 chosen=next((x for x in candidates if x[0]['id']==branch_id),candidates[0]); moves=chosen[1][:40];book=len(moves)
 cache_key=VERSION+':'+rev+':'+oid+':'+chosen[0]['id']
 with LOCK:
  with store.connection() as db:
   cached=db.execute('SELECT value FROM kc_meta WHERE key=?',(cache_key,)).fetchone()
  if cached:payload=json.loads(cached[0])
  else:
   board=chess.Board()
   for u in moves:board.push_uci(u)
   engine_added=False;pending=None
   if len(moves)<24 and not board.is_game_over(claim_draw=True):
    try:
     reserve()
     with engine_session(20) as engine:
      for _ in range(2):
       info=engine.analyse(board,chess.engine.Limit(time=.45));pv=info.get('pv',[])
       if not pv:break
       for m in pv:
        if m not in board.legal_moves or len(moves)>=24 or board.is_game_over(claim_draw=True):break
        moves.append(m.uci());board.push(m);engine_added=True
       if len(moves)>=24 or board.is_game_over(claim_draw=True):break
    except HTTPException as exc:pending='daily_limit' if exc.status_code==429 else 'engine_busy'
   payload={'path':materialize(moves,book),'catalogue_plies':book,'engine_added':engine_added,'continuation_pending':pending}
   if not pending:
    with store.connection() as db:db.execute('INSERT OR REPLACE INTO kc_meta(key,value) VALUES(?,?)',(cache_key,json.dumps(payload,ensure_ascii=False)))

 return {**original,**payload,'definition_plies':len(prefix),'branch':chosen[0]['name'],'branch_id':chosen[0]['id'],'branches':[{'id':x[0]['id'],'name':x[0]['name'],'plies':x[0]['plies']} for x in candidates[:30]],'method':'A matching catalogue branch, preferring named main lines where available; not a popularity ranking. After the catalogue ends, any Stockfish continuation is labelled separately; it is one study line, not complete opening theory.'}
