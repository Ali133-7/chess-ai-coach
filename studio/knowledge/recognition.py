import hashlib,io,json,re
import chess,chess.pgn
from fastapi import HTTPException
from .store import connection,current_revision

ALIASES={'Sicilian Defense':'الصقلي الدفاع الصقلي','French Defense':'الفرنسي الدفاع الفرنسي','Caro-Kann Defense':'كارو كان','Italian Game':'الإيطالي الايطالي','Ruy Lopez':'الإسباني الاسباني روي لوبيز','Queen’s Gambit':'جامبيت الوزير','Queen\'s Gambit':'جامبيت الوزير','London System':'لندن نظام لندن','English Opening':'الإنجليزي الانجليزي','King\'s Indian Defense':'الهندي الملكي','Scandinavian Defense':'الاسكندنافي','Slav Defense':'السلافي','Dutch Defense':'الهولندي','Pirc Defense':'بيرك','Vienna Game':'فيينا','Scotch Game':'الاسكتلندي','Petrov\'s Defense':'بتروف الروسي'}
MATCH_FORMULA='التوافق = 100 × نقلات اللاعب المتوافقة ÷ نقلات اللاعب المقارنة في الجزء الملعوب من الخط (حتى 40 نصف نقلة). تُحتسب النقلة إذا طابقت حافة في الخط؛ وعند الوصول إلى الوضعية نفسها في العدد نفسه من أنصاف النقلات، تُحتسب المقدمات كتبديل ترتيب صحيح. النقلات التي لم تُلعب لا تدخل المقام. هذه نسبة توافق مسار، لا نسبة إتقان أو جودة.'
def position_key(board):return ' '.join(board.fen(en_passant='legal').split()[:4])
def valid_board(fen):
 try:
  parts=fen.strip().split();board=chess.Board(fen+' 0 1' if len(parts)==4 else fen)
  if not board.is_valid():raise ValueError()
  return board
 except (ValueError,TypeError):raise HTTPException(422,'FEN غير صالح للشطرنج القياسي') from None

def parse_pgn(pgn,max_plies=600):
 if len(pgn)>100000:raise HTTPException(422,'ملف PGN أكبر من الحد المسموح')
 try:
  game=chess.pgn.read_game(io.StringIO(pgn))
  if not game or game.errors or game.headers.get('Variant','Standard') not in ('Standard','Chess'):raise ValueError()
  board=game.board()
  if not board.is_valid():raise ValueError()
  moves=list(game.mainline_moves())
  if len(moves)>max_plies:raise ValueError()
  boards=[board.copy(stack=False)];sans=[]
  for move in moves:
   if move not in board.legal_moves:raise ValueError()
   sans.append(board.san(move));board.push(move);boards.append(board.copy(stack=False))
  return game,moves,boards,sans
 except (ValueError,TypeError):raise HTTPException(422,'PGN غير صالح أو يحتوي نقلات غير قانونية') from None

def search(q='',limit=40,offset=0):
 q=q.strip()[:120];terms=[q]
 for family,arabic in ALIASES.items():
  if q and (family.lower() in q.lower() or any(token in q for token in arabic.split() if len(token)>2 and token not in {'الدفاع','جامبيت','الوزير','نظام'}) or arabic in q):terms.append(family)
 with connection() as db:
  rev=current_revision(db);where='revision=?';args=[rev]
  if q:
   where+=' AND ('+' OR '.join('(name LIKE ? OR eco LIKE ?)' for _ in terms)+')'
   for term in terms:args.extend(['%'+term+'%','%'+term+'%'])
  count=db.execute('SELECT count(*) FROM kc_openings WHERE '+where,args).fetchone()[0]
  rows=db.execute('SELECT id,eco,name,family,plies,pgn,terminal_key FROM kc_openings WHERE '+where+' ORDER BY eco,name LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
 from .perspectives import decorate
 return {'items':decorate([dict(r) for r in rows]),'total':count,'offset':offset,'revision':rev}

def opening(oid):
 with connection() as db:
  rev=current_revision(db);row=db.execute('SELECT * FROM kc_openings WHERE revision=? AND id=?',(rev,oid)).fetchone()
  if not row:raise HTTPException(404,'الافتتاحية غير موجودة في النسخة النشطة')
  result=dict(row);path=[dict(p) for p in db.execute('SELECT ply,fen,uci,san,before_key,position_key FROM kc_paths WHERE revision=? AND opening_id=? ORDER BY ply',(rev,oid))]
  from .perspectives import orientation
  from .traps import for_opening
  result['trap_id']=for_opening(oid)
  result['orientation']=orientation(result['name'],result['family'])
  result.update(path=path,uci=json.loads(result.pop('uci_json')),source='lichess-org/chess-openings',license='CC0-1.0')
  return result

def classify(boards,moves,side='white',max_results=8,only_ids=None):
 boards=boards[:41];moves=moves[:40];keys=[position_key(b) for b in boards];move_edges={(keys[i],m.uci()) for i,m in enumerate(moves)}
 with connection() as db:
  rev=current_revision(db)
  if not rev:return {'identified':None,'candidates':[],'coverage':'فهرس الافتتاحيات غير مستورد','formula':MATCH_FORMULA}
  unique=list(dict.fromkeys(keys));marks=','.join('?'*len(unique))
  named=[dict(r) for r in db.execute('SELECT id,eco,name,family,plies,terminal_key,uci_json FROM kc_openings WHERE revision=? AND terminal_key IN ('+marks+')',(rev,*unique))]
  named.sort(key=lambda r:(max(i for i,k in enumerate(keys) if k==r['terminal_key']),r['plies']),reverse=True)
  chosen=named[:max_results]
  if only_ids:
   chosen=[]
   for oid in only_ids[:8]:
    row=db.execute('SELECT id,eco,name,family,plies,terminal_key,uci_json FROM kc_openings WHERE revision=? AND id=?',(rev,oid)).fetchone()
    if row:chosen.append(dict(row))
  if not chosen and not only_ids:
   ids=db.execute('SELECT DISTINCT opening_id FROM kc_paths WHERE revision=? AND position_key=? LIMIT ?',(rev,keys[-1],max_results)).fetchall()
   for i in ids:
    row=db.execute('SELECT id,eco,name,family,plies,terminal_key,uci_json FROM kc_openings WHERE revision=? AND id=?',(rev,i[0])).fetchone()
    if row:chosen.append(dict(row))
  candidates=[]
  for row in chosen:
   path=[dict(r) for r in db.execute('SELECT ply,before_key,position_key,uci FROM kc_paths WHERE revision=? AND opening_id=? ORDER BY ply',(rev,row['id']))]
   horizon=min(len(moves),len(path));player_indices=[i for i in range(horizon) if boards[i].turn==(side=='white')]
   edges={(p['before_key'],p['uci']) for p in path};anchor=max((i for i in range(1,min(len(keys),len(path)+1)) if keys[i]==path[i-1]['position_key']),default=0) if boards[0].fen()==chess.STARTING_FEN else 0
   matched=[i for i in player_indices if i<anchor or (keys[i],moves[i].uci()) in edges]
   reached=max((i for i,k in enumerate(keys) if k==row['terminal_key']),default=None)
   canonical=json.loads(row.pop('uci_json'))
   row.update(matched_player_moves=len(matched),compared_player_moves=len(player_indices),compared_plies=horizon,
              match_percent=round(100*len(matched)/len(player_indices),1) if player_indices else None,
              recognized_at_ply=reached,transposition=bool(boards[0].fen()==chess.STARTING_FEN and reached is not None and [m.uci() for m in moves[:reached]]!=canonical),partial_history=boards[0].fen()!=chess.STARTING_FEN,
              coverage_plies=min(len(moves),row['plies']),formula=MATCH_FORMULA)
   candidates.append(row)
  deviation=None
  for i,m in enumerate(moves):
   known=db.execute('SELECT 1 FROM kc_paths WHERE revision=? AND before_key=? LIMIT 1',(rev,keys[i])).fetchone()
   if known and not db.execute('SELECT 1 FROM kc_paths WHERE revision=? AND before_key=? AND uci=? LIMIT 1',(rev,keys[i],m.uci())).fetchone() and not db.execute('SELECT 1 FROM kc_paths WHERE revision=? AND position_key=? LIMIT 1',(rev,keys[i+1])).fetchone():
    deviation={'ply':i+1,'uci':m.uci(),'san':boards[i].san(m),'meaning':'خروج عن الفروع المسجلة؛ ليس خطأً شطرنجياً بحد ذاته'};break
 return {'identified':next((r for r in candidates if r['recognized_at_ply'] is not None),None),'candidates':candidates,
         'deviation':deviation,'formula':MATCH_FORMULA,'revision':rev,'opening_window_plies':40}

def recognize_fen(fen):
 board=valid_board(fen);key=position_key(board)
 with connection() as db:
  rev=current_revision(db);exact=[dict(r) for r in db.execute('SELECT id,eco,name,family,plies FROM kc_openings WHERE revision=? AND terminal_key=? ORDER BY plies DESC LIMIT 15',(rev,key))]
 return {'fen':board.fen(),'key':key,'exact_openings':exact,'match_percent':None,'reason':'FEN يثبت الوضعية، لكنه لا يثبت تاريخ النقلات أو نسبة توافق اللاعب.'}
