"""Small, versioned trap lessons. Every line is illustrative and rules-validated."""
from functools import lru_cache
import copy,json
import chess
from fastapi import HTTPException
from . import store,study,perspectives

@lru_cache(maxsize=1)
def catalogue():return json.loads((store.DATA/'trap-lessons.json').read_text(encoding='utf8'))

def for_opening(oid):return next((p['id'] for p in catalogue()['items'] if p.get('opening_id')==oid),None)

def label(ply,san):return str((ply+1)//2)+('. ' if ply%2 else '... ')+san

@lru_cache(maxsize=64)
def _lesson(tid,variant):
 p=next((x for x in catalogue()['items'] if x['id']==tid),None)
 if not p:raise HTTPException(404,'الفخ غير موجود في المكتبة الحالية')
 if variant not in ('trap','safe'):raise HTTPException(422,'مسار غير معروف')
 moves=p['moves'] if variant=='trap' else p['safe_moves']
 path=study.materialize(moves,len(moves));board=chess.Board();timing={};ends_in_mate=chess.Board(path[-1]['fen']).is_checkmate()
 for i,s in enumerate(path,1):
  s['mover']='white' if board.turn else 'black';s['move_number']=board.fullmove_number
  s['source']='trap-example' if variant=='trap' or i<=p['mistake_ply'] else 'engine'
  event=None
  if i==p['setup_ply']:event='setup'
  if variant=='trap' and i==p['mistake_ply']:event='trigger'
  if variant=='trap' and i==p['punish_ply']:event='punish'
  if variant=='safe' and i==p['mistake_ply']:event='avoid'
  s['trap_event']=event
  if event:
   addition=p['idea'] if event=='setup' else p['benefit'] if event=='punish' else p['avoid'] if event=='avoid' else p['warning']
   for language in ('ar','en'):
    s['note'][language]['why']=addition[language]+' '+s['note'][language]['why']
    s['note'][language]['watch']=p['avoid'][language] if event!='avoid' else p['warning'][language]
  board.push_uci(s['uci'])
  if ends_in_mate and i==len(path)-1:
   s['trap_event']='before-mate'
   s['note']['ar']['why']='في هذا المثال تأتي بعد هذه النقلة '+path[-1]['san']+' بالمات. الوصول إلى هذه الشبكة قد يكون نتيجة خطأ أسبق. '+s['note']['ar']['why']
   s['note']['en']['why']='In this example the next move, '+path[-1]['san']+', is checkmate. Reaching this net can be the result of an earlier mistake. '+s['note']['en']['why']
  if board.is_checkmate():
   s['trap_event']='checkmate'
   s['note']['ar']['why']='مات: الملك تحت الكش ولا توجد نقلة قانونية تزيله. '+p['benefit']['ar']
   s['note']['en']['why']='Checkmate: the king is in check and no legal move removes it. '+p['benefit']['en']
   s['note']['ar']['watch']=p['warning']['ar']
   s['note']['en']['watch']=p['warning']['en']
  if i in (p['setup_ply'],p['mistake_ply'],p['punish_ply']):timing[str(i)]=label(i,s['san'])
 profile={k:copy.deepcopy(p[k]) for k in ('id','name','name_ar','side','setup_ply','mistake_ply','punish_ply','safe_san','idea','benefit','avoid','warning','classification','evidence','source','opening_id')}
 main_board=chess.Board();main_sans=[]
 for u in p['moves']:
  move=chess.Move.from_uci(u);main_sans.append(main_board.san(move));main_board.push(move)
 profile['timing']={key:label(p[key],main_sans[p[key]-1]) for key in ('setup_ply','mistake_ply','punish_ply')}
 return {'id':p['id'],'name':p['name'],'name_ar':p['name_ar'],'family':p['name'].split(':')[0],'eco':p['eco'],'kind':'trap','variant':variant,'path':path,'definition_plies':p.get('source_plies',0) or len(p['moves']),'catalogue_plies':p.get('source_plies',0),'branches':[],'branch_id':tid,'branch':p['name'],'orientation':perspectives.orientation(p['name']),'trap':profile,'initial_fen':chess.STARTING_FEN,'initial_legal_moves':[m.uci() for m in chess.Board().legal_moves],'end':{'checkmate':board.is_checkmate(),'result':board.result() if board.is_game_over() else None,'material_white':sum((1 if pc.color else -1)*{1:1,2:3,3:3,4:5,5:9,6:0}[pc.piece_type] for pc in board.piece_map().values())}}

def lesson(tid,variant='trap'):return copy.deepcopy(_lesson(tid,variant))

def search(q='',side='all',limit=12,offset=0):
 items=[];q=q.casefold().strip()
 for p in catalogue()['items']:
  if side!='all' and p['side']!=side:continue
  if q and q not in (p['name']+' '+p['name_ar']).casefold():continue
  row={k:p[k] for k in ('id','name','name_ar','side','classification','opening_id')};g=_lesson(p['id'],'trap');row.update(timing=g['trap']['timing'],idea=p['idea']);items.append(row)
 return {'items':items[offset:offset+limit],'total':len(items),'all_count':catalogue()['count'],'catalogue_entries':catalogue()['catalogue_entries'],'scope':catalogue()['method']}
