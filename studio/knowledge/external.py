import hashlib,json,math,os,secrets,time
from pathlib import Path
import chess,chess.engine,chess.syzygy,httpx
from fastapi import HTTPException
from . import store
from .recognition import valid_board,position_key
from ..teacher_v7.providers import read_key,ProviderError
from ..training_teacher import engine_session
from .importer import stamp

FILTERS={'speeds':['rapid','classical'],'ratings':[1600,1800,2000,2200]}
def cache_key(board,dataset):return position_key(board)+(':'+json.dumps(FILTERS,sort_keys=True) if dataset=='lichess' else '')
def percentages(w,d,b):
 n=w+d+b
 return {'sample_size':n,'white_wins':w,'draws':d,'black_wins':b,'white_percent':round(w*100/n,1) if n else None,'draw_percent':round(d*100/n,1) if n else None,'black_percent':round(b*100/n,1) if n else None}

def import_explorer_payload(fen,data,filters=None,dataset='lichess'):
 board=valid_board(fen)
 def counts(row):
  values=[row.get(k,0) for k in ['white','draws','black']]
  if any(type(v) is not int or v<0 for v in values):raise ValueError('Invalid counts')
  return percentages(*values)
 result=counts(data);moves=[]
 for row in data.get('moves',[])[:30]:
  move=board.parse_uci(row['uci'])
  if move not in board.legal_moves:raise ValueError('Illegal explorer move')
  item=counts(row);item.update(uci=move.uci(),san=board.san(move),average_rating=row.get('averageRating'))
  item['frequency_percent']=round(item['sample_size']*100/result['sample_size'],1) if result['sample_size'] else None;moves.append(item)
 moves.sort(key=lambda x:x['sample_size'],reverse=True)
 result.update(moves=moves,most_popular_uci=moves[0]['uci'] if moves else None,source='Lichess Opening Explorer / '+dataset,
   dataset=dataset,filters=FILTERS if dataset=='lichess' else {},scope='Rated rapid/classical; rating buckets 1600/1800/2000/2200' if dataset=='lichess' else 'Masters database aggregate; not all Lichess games',
   interpretation='نسب نتائج العينة المسجلة، وليست احتمال فوز اللاعب أو تقييماً للمحرك.',retrieved_at=stamp())
 with store.connection() as db:db.execute('INSERT OR REPLACE INTO kc_external_cache VALUES(?,?,?,?)',('explorer-'+dataset,cache_key(board,dataset),json.dumps(result),time.time()))
 return result

def request_lichess(url,params,token=False):
 lease=secrets.token_hex(12);now=time.time()
 with store.connection() as db:
  db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT * FROM kc_network WHERE name='lichess'").fetchone()
  wait=max(row['next_at'],row['lock_until'])-now
  if wait>0:raise HTTPException(429,'طلبات المصدر متسلسلة. انتظر '+str(math.ceil(wait))+' ثانية ثم أعد المحاولة.')
  db.execute("UPDATE kc_network SET next_at=?,lock_until=?,lock_token=? WHERE name='lichess'",(now+3,now+60,lease))
 headers={'User-Agent':'ChessKnowledgeCenter/1 educational cached queries'}
 path=Path(os.getenv('LICHESS_TOKEN_FILE','/studio-data/.lichess_api_token'))
 if token and path.exists():
  try:headers['Authorization']='Bearer '+read_key(path)
  except ProviderError:
   with store.connection() as db:db.execute("UPDATE kc_network SET lock_until=0,lock_token=NULL WHERE name='lichess' AND lock_token=?",(lease,))
   raise HTTPException(503,'ملف رمز Lichess غير صالح أو ليس خاصاً') from None
 status=None
 try:
  with httpx.Client(timeout=httpx.Timeout(18,connect=5),follow_redirects=False,trust_env=False) as client:
   with client.stream('GET',url,params=params,headers=headers) as response:
    status=response.status_code
    if status==429:
     retry=response.headers.get('Retry-After','60')
     delay=max(60,min(3600,int(retry) if retry.isdigit() else 60))
     with store.connection() as db:db.execute("UPDATE kc_network SET next_at=? WHERE name='lichess'",(time.time()+delay,))
     raise HTTPException(429,'وصل المصدر إلى حد الطلبات. تم تعليق الاستعلامات دقيقة على الأقل؛ البيانات المحفوظة باقية.')
    if status==401:raise HTTPException(503,'إحصائيات لاعبي Lichess تحتاج مصادقة حالياً. جرّب Masters أو الإحصائيات المحلية.')
    if status!=200:raise HTTPException(503,'المصدر الخارجي غير متاح حالياً؛ لم تُستبدل بيانات محفوظة بقيم تخمينية.')
    raw=bytearray();deadline=time.time()+25
    for chunk in response.iter_bytes():
     if len(raw)+len(chunk)>262144 or time.time()>deadline:raise ValueError()
     raw.extend(chunk)
  return json.loads(raw)
 except HTTPException:raise
 except Exception:raise HTTPException(503,'تعذر جلب بيانات المصدر الآن. استخدم البيانات المحلية أو أعد المحاولة لاحقاً.') from None
 finally:
  with store.connection() as db:db.execute("UPDATE kc_network SET lock_until=0,lock_token=NULL,last_status=? WHERE name='lichess' AND lock_token=?",(status,lease))

def explorer(fen,dataset='masters',refresh=False):
 board=valid_board(fen)
 if dataset not in ('masters','lichess'):raise HTTPException(422,'مصدر إحصاءات غير معروف')
 with store.connection() as db:row=db.execute('SELECT * FROM kc_external_cache WHERE kind=? AND key=?',('explorer-'+dataset,cache_key(board,dataset))).fetchone()
 if row and not refresh:
  result=json.loads(row['payload']);result.update(cached=True,age_seconds=round(time.time()-row['updated_at']));return result
 if not refresh:return {'available':False,'source':dataset,'reason':'لم تُجلب إحصائيات هذه الوضعية بعد؛ لا توجد نسب معروضة دون عينة.'}
 params={'fen':board.fen(),'topGames':0,'moves':12}
 if dataset=='lichess':params.update(variant='standard',speeds=','.join(FILTERS['speeds']),ratings=','.join(map(str,FILTERS['ratings'])),recentGames=0)
 data=request_lichess('https://explorer.lichess.org/'+dataset,params,token=dataset=='lichess')
 result=import_explorer_payload(board.fen(),data,dataset=dataset);result['cached']=False;return result

def evaluation(fen,refresh=False):
 board=valid_board(fen);key=position_key(board);local_key=key+' '+str(board.halfmove_clock)
 with store.connection() as db:
  rows=db.execute("SELECT * FROM kc_evaluations WHERE (position_key=? AND source='stockfish-local') OR (position_key=? AND source='lichess-eval') ORDER BY (source='stockfish-local') DESC,depth DESC",(local_key,key)).fetchall()
 if rows and not refresh:
  result=dict(rows[0]);result['pvs']=json.loads(result.pop('pv_json'));result['cached']=True;result['halfmove_clock_assumed_zero']=result['source']=='lichess-eval';return result
 if not refresh:return {'available':False,'reason':'لا يوجد تقييم محفوظ لهذه الوضعية. اطلب تحليل Stockfish عند الحاجة.'}
 if board.is_game_over(claim_draw=True):return {'source':'terminal-rules','terminal':True,'result':board.result(claim_draw=True),'pvs':[],'depth':0,'cp_white':0 if board.outcome(claim_draw=True).winner is None else None,'mate_white':None}
 with engine_session(20) as engine:infos=engine.analyse(board,chess.engine.Limit(time=.8),multipv=min(3,board.legal_moves.count()))
 if isinstance(infos,dict):infos=[infos]
 pvs=[]
 for info in infos:
  current=board.copy();moves=[];sans=[]
  for move in info.get('pv',[])[:12]:
   if move not in current.legal_moves:break
   sans.append(current.san(move));moves.append(move.uci());current.push(move)
  if not moves:continue
  score=info['score'].pov(chess.WHITE);pvs.append({'moves':moves,'san':sans,'cp_white':score.score(),'mate_white':score.mate()})
 if not pvs:raise HTTPException(503,'لم يكتمل تحليل المحرك')
 result={'position_key':local_key,'source':'stockfish-local','depth':infos[0].get('depth',0),'cp_white':pvs[0]['cp_white'],'mate_white':pvs[0]['mate_white'],'pvs':pvs,'fen':board.fen(),'engine':'Stockfish, full skill, 1 thread, 0.8 seconds','updated_at':stamp(),'cached':False,'halfmove_clock_assumed_zero':False}
 with store.connection() as db:db.execute('INSERT OR REPLACE INTO kc_evaluations VALUES(?,?,?,?,?,?,?,?,?)',(local_key,result['source'],result['depth'],result['cp_white'],result['mate_white'],json.dumps(pvs),board.fen(),result['engine'],result['updated_at']))
 return result

def tablebase(fen,refresh=False):
 board=valid_board(fen)
 if len(board.piece_map())>7 or board.castling_rights:return {'available':False,'reason':'Syzygy يتطلب نهاية قليلة القطع دون حقوق تبييت؛ التغطية المحلية الأساسية ثلاث قطع.'}
 path=Path(os.getenv('CHESS_SYZYGY_DIR',str(store.DATA/'syzygy')))
 try:
  with chess.syzygy.open_tablebase(str(path)) as tb:
   wdl=tb.probe_wdl(board);dtz=tb.probe_dtz(board);moves=[]
   for move in board.legal_moves:
    child=board.copy();child.push(move)
    if child.is_checkmate():value=2;distance=1
    elif child.is_game_over(claim_draw=True):value=0;distance=0
    else:
     try:value=-tb.probe_wdl(child);distance=-tb.probe_dtz(child)
     except KeyError:continue
    moves.append({'uci':move.uci(),'san':board.san(move),'wdl_for_mover':value,'dtz_after':distance})
   moves.sort(key=lambda m:(-m['wdl_for_mover'],abs(m['dtz_after'])))
   return {'available':True,'source':'Syzygy local','wdl':wdl,'wdl_pov':'side-to-move','category':{2:'win',1:'cursed-win',0:'draw',-1:'blessed-loss',-2:'loss'}[wdl],'dtz':dtz,'halfmove_clock':board.halfmove_clock,'claimable_fifty_move_draw':board.can_claim_fifty_moves(),'rule50_caution':abs(wdl)==1 or board.halfmove_clock+abs(dtz)>100,'moves':moves,'note':'DTZ ليس المسافة إلى المات. النتيجة من منظور صاحب الدور؛ يجب مراعاة قاعدة الخمسين نقلة وتكرار الوضعية.'}
 except (KeyError,OSError,ValueError):pass
 key=board.fen()
 with store.connection() as db:cached=db.execute("SELECT payload FROM kc_external_cache WHERE kind='tablebase' AND key=?",(key,)).fetchone()
 if cached and not refresh:return json.loads(cached['payload'])
 if not refresh:return {'available':False,'reason':'هذه النهاية خارج ملفات Syzygy المحلية. يمكن جلب نتيجة خارجية وحفظها عند الطلب.'}
 result=request_lichess('https://tablebase.lichess.ovh/standard',{'fen':board.fen()})
 result['moves']=[m for m in result.get('moves',[]) if chess.Move.from_uci(m['uci']) in board.legal_moves]
 result.update(available=True,source='Lichess Syzygy API cached',fen=board.fen(),note='الفئة من منظور صاحب الدور، وفئات النقلات من منظور الوضعية التالية. DTZ ليس ماتاً.')
 with store.connection() as db:db.execute("INSERT OR REPLACE INTO kc_external_cache VALUES('tablebase',?,?,?)",(key,json.dumps(result),time.time()))
 return result
