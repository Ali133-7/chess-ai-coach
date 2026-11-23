"""Incremental, owner-scoped reports reusing completed-game engine analysis."""
import hashlib,json
from collections import Counter,defaultdict
import chess
from fastapi import HTTPException
from .. import core
from .recognition import parse_pgn,classify,position_key
from .store import connection,current_revision

BAD={'weak','missed','mistake','blunder'}
def own_color(game,username):
 if username and game['white'].casefold()==username.casefold():return 'white'
 if username and game['black'].casefold()==username.casefold():return 'black'
 return None

def report_game(gid,uid):
 with core.connection() as db:
  row=db.execute('SELECT g.*,u.chess_username FROM games g JOIN users u ON u.id=g.user_id WHERE g.id=? AND g.user_id=?',(gid,uid)).fetchone()
  if not row:raise HTTPException(404,'المباراة غير موجودة ضمن حسابك')
  game=dict(row)
  if game['result'] not in ('1-0','0-1','1/2-1/2') or not game['finished_at']:raise HTTPException(409,'التقرير للمباريات المكتملة فقط')
  rows=[dict(r) for r in db.execute('SELECT ply,uci,fen_before,grade,loss_cp,eval_cp_white,phase,best_uci FROM moves WHERE game_id=? ORDER BY ply',(gid,))]
  cached=db.execute('SELECT * FROM knowledge_game_reports WHERE game_id=? AND user_id=?',(gid,uid)).fetchone()
 with connection() as db:revision=current_revision(db)
 fingerprint=hashlib.sha256(json.dumps(['knowledge-report-v1',game['pgn'],game['stage'],rows,revision,game['chess_username']],sort_keys=True).encode()).hexdigest()
 if cached and cached['fingerprint']==fingerprint:return json.loads(cached['report_json'])
 _,moves,boards,sans=parse_pgn(game['pgn']);side=own_color(game,game['chess_username']);recognized=classify(boards,moves,side or 'white',max_results=3)
 if side is None:
  for candidate in recognized['candidates']:candidate.update(match_percent=None,matched_player_moves=0,compared_player_moves=0)
  if recognized['identified']:recognized['identified']['match_percent']=None
 byply={r['ply']:r for r in rows};phase_stats={};habits=Counter();errors=[];own_indices=[i for i in range(len(moves)) if side and boards[i].turn==(side=='white')]
 phases=defaultdict(lambda:{'moves':0,'errors':0,'blunders':0,'loss_sum':0,'scored':0})
 for i in own_indices:
  before=boards[i];move=moves[i];row=byply.get(i+1);ph=core.phase(before)
  habits['moves']+=1;habits['captures']+=int(before.is_capture(move));habits['checks']+=int(before.gives_check(move));habits['castles']+=int(before.is_castling(move))
  if i<20 and before.piece_type_at(move.from_square)==chess.QUEEN:habits['early_queen_moves']+=1
  if not row:continue
  entry=phases[ph];entry['moves']+=1;entry['errors']+=int(row['grade'] in BAD);entry['blunders']+=int(row['grade']=='blunder')
  if row['loss_cp'] is not None:entry['loss_sum']+=max(0,row['loss_cp']);entry['scored']+=1
  if row['grade'] in BAD:
   tags=[];after=boards[i+1];piece=after.piece_at(move.to_square)
   if piece and piece.piece_type!=chess.KING and (row['loss_cp'] or 0)>=100:
    legal_captures=[m for m in after.legal_moves if m.to_square==move.to_square and after.is_capture(m)]
    if legal_captures and not after.is_attacked_by(before.turn,move.to_square):tags.append('hangingPiece')
   if i<20 and before.piece_type_at(move.from_square)==chess.QUEEN:tags.append('earlyQueen')
   errors.append({'ply':i+1,'san':sans[i],'grade':row['grade'],'loss_cp':row['loss_cp'],'phase':ph,'tags':tags,'best_uci':row['best_uci']})
 for ph,entry in phases.items():
  phase_stats[ph]={**entry,'error_percent':round(entry['errors']*100/entry['moves'],1) if entry['moves'] else None,'mean_loss_cp':round(entry['loss_sum']/entry['scored'],1) if entry['scored'] else None}
 errors.sort(key=lambda e:e['loss_cp'] if e['loss_cp'] is not None else -1,reverse=True)
 deviation=recognized.get('deviation')
 if deviation and deviation['ply'] in byply:deviation['saved_grade']=byply[deviation['ply']]['grade'];deviation['saved_loss_cp']=byply[deviation['ply']]['loss_cp']
 own_result='draw' if game['result']=='1/2-1/2' else ('win' if (game['result']=='1-0')==(side=='white') else 'loss') if side else None
 report={'game_id':gid,'own_color':side,'result':own_result,'opening':recognized,'phases':phase_stats,'style_counts':dict(habits),'errors':errors[:30],
  'coverage':{'saved_positions':len(rows),'game_plies':len(moves),'own_game_moves':len(own_indices),'own_analyzed_moves':sum(v['moves'] for v in phases.values()),'stage':game['stage']},
  'phase_method':'تقريبي: أول 20 نصف نقلة افتتاح؛ بعدها نهاية إن بقيت خمس قطع غير البيادق والملوك أو أقل، وإلا وسط لعب. درجات الأخطاء من التحليل المحفوظ، لا من اسم الافتتاحية.',
  'method':'المطابقة من أوضاع قانونية؛ الأخطاء وخسارة التقييم من Stockfish المحفوظ؛ مؤشرات الأسلوب عدّ للنقلات وليست تشخيصاً للشخصية.',
  'fingerprint':fingerprint}
 with core.connection() as db:db.execute('INSERT OR REPLACE INTO knowledge_game_reports VALUES(?,?,?,?,?)',(gid,uid,fingerprint,json.dumps(report,ensure_ascii=False),core.now()))
 return report

def update_reports(uid,after_id=0,limit=30):
 with core.connection() as db:
  ids=[r['id'] for r in db.execute("SELECT id FROM games WHERE user_id=? AND id>? AND finished_at>0 AND result IN ('1-0','0-1','1/2-1/2') ORDER BY id LIMIT ?",(uid,after_id,limit))]
 processed=0;rejected=[]
 for gid in ids:
  try:report_game(gid,uid);processed+=1
  except HTTPException as e:rejected.append({'game_id':gid,'reason':str(e.detail)})
 last=ids[-1] if ids else after_id
 with core.connection() as db:remaining=db.execute("SELECT count(*) FROM games WHERE user_id=? AND id>? AND finished_at>0 AND result IN ('1-0','0-1','1/2-1/2')",(uid,last)).fetchone()[0]
 return {'processed':processed,'rejected':rejected,'next_after_id':last,'remaining':remaining}

def profile(uid):
 with core.connection() as db:
  raw=db.execute('SELECT report_json,updated_at FROM knowledge_game_reports WHERE user_id=?',(uid,)).fetchall()
  total=db.execute("SELECT count(*) FROM games WHERE user_id=? AND finished_at>0 AND result IN ('1-0','0-1','1/2-1/2')",(uid,)).fetchone()[0]
  prefs=db.execute('SELECT u.target_rating,u.rating_format,r.rating FROM users u LEFT JOIN ratings r ON r.user_id=u.id AND r.format=u.rating_format WHERE u.id=?',(uid,)).fetchone()
 reports=[json.loads(r['report_json']) for r in raw];phase=defaultdict(lambda:Counter());families={};styles=Counter();motifs=Counter();training=[]
 for report in reports:
  styles.update(report['style_counts'])
  for k,v in report['phases'].items():
   for field in ['moves','errors','blunders','loss_sum','scored']:phase[k][field]+=v[field]
  for error in report['errors']:
   motifs.update(error['tags']);training.append({'game_id':report['game_id'],**error})
  opening=report['opening'].get('identified')
  if opening:
   key=opening['family'];item=families.setdefault(key,{'family':key,'games':0,'wins':0,'draws':0,'losses':0,'compatible':0,'compared':0})
   item['games']+=1
   if report['result']:item[{'win':'wins','draw':'draws','loss':'losses'}[report['result']]]+=1
   item['compatible']+=opening.get('matched_player_moves',0);item['compared']+=opening.get('compared_player_moves',0)
 for values in phase.values():
  values['error_percent']=round(100*values['errors']/values['moves'],1) if values['moves'] else None
  values['mean_loss_cp']=round(values['loss_sum']/values['scored'],1) if values['scored'] else None
 for values in families.values():
  denominator=values['wins']+values['draws']+values['losses'];values['win_percent']=round(values['wins']*100/denominator,1) if denominator else None
  values['match_percent']=round(100*values['compatible']/values['compared'],1) if values['compared'] else None
 families=sorted(families.values(),key=lambda x:x['games'],reverse=True)
 training.sort(key=lambda e:e['loss_cp'] if e['loss_cp'] is not None else -1,reverse=True)
 indicators={k:{'count':styles[k],'denominator':styles['moves'],'percent':round(styles[k]*100/styles['moves'],1) if styles['moves'] else None} for k in ['captures','checks','early_queen_moves']}
 return {'reported_games':len(reports),'total_completed_games':total,'coverage_note':'تقارير محلية محفوظة؛ حدّثها بعد اكتمال تحليل جديد لتنعكس أحدث النتائج. المباريات غير المكتملة التحليل تبين تغطيتها داخل التقرير.',
   'phases':dict(phase),'openings':families[:40],'motifs':dict(motifs),'style_indicators':indicators,'castling_games':styles['castles'],
   'training_positions':training[:15],'reference_rating':prefs['rating'] or prefs['target_rating'] if prefs else 1000,
   'rating_basis':'التصنيف المنشور لنمط اللاعب إن توفر، وإلا هدف التدريب الذي اختاره؛ لا يخلط بتصنيف ألغاز Lichess.',
   'sources':'مباريات المستخدم المكتملة + Stockfish المحفوظ + فهرس Lichess المحلي؛ لا نسب عالمية مختلقة.'}

def local_position_stats(key,uid):
 # Each completed game contributes once per move from this position; repeated visits in the same game are deduplicated.
 with core.connection() as db:rows=db.execute("SELECT g.id,g.result,m.uci,m.san,m.ply FROM moves m INDEXED BY idx_knowledge_moves_fen JOIN games g ON g.id=m.game_id WHERE g.user_id=? AND g.result IN ('1-0','0-1','1/2-1/2') AND m.fen_before GLOB ? ORDER BY g.id,m.ply",(uid,key+' *')).fetchall()
 from .external import percentages
 totals=Counter();by=defaultdict(Counter);seen=set()
 for row in rows:
  if row['id'] in seen:continue
  seen.add(row['id'])
  field={'1-0':'w','1/2-1/2':'d','0-1':'b'}[row['result']];totals[field]+=1;by[(row['uci'],row['san'])][field]+=1
 result=percentages(totals['w'],totals['d'],totals['b']);moves=[]
 for (uci,san),counts in by.items():moves.append({'uci':uci,'san':san,**percentages(counts['w'],counts['d'],counts['b'])})
 moves.sort(key=lambda m:m['sample_size'],reverse=True);result.update(moves=moves,source='أرشيف المستخدم المحلل فقط',scope='نتيجة الأبيض/تعادل/الأسود، للزيارة الأولى للوضعية في كل مباراة؛ الأرشيف غير المحلل غير داخل العينة.',most_popular_uci=moves[0]['uci'] if moves else None)
 return result


def recommendation_basis(uid):
 # Compute only the few facts needed by puzzle selection, in SQLite rather than
 # decoding and sorting every full game report/style/opening summary in Python.
 with core.connection() as db:
  prefs=db.execute('SELECT u.target_rating,r.rating FROM users u LEFT JOIN ratings r ON r.user_id=u.id AND r.format=u.rating_format WHERE u.id=?',(uid,)).fetchone()
  phases=db.execute("SELECT COALESCE(SUM(COALESCE(json_extract(report_json,'$.phases.opening.errors'),0)),0) AS opening_errors,COALESCE(SUM(COALESCE(json_extract(report_json,'$.phases.endgame.errors'),0)),0) AS endgame_errors FROM knowledge_game_reports WHERE user_id=?",(uid,)).fetchone()
  hanging=db.execute("SELECT 1 FROM knowledge_game_reports r,json_each(r.report_json,'$.errors') e,json_each(e.value,'$.tags') t WHERE r.user_id=? AND t.value='hangingPiece' LIMIT 1",(uid,)).fetchone() is not None
 return {'reference_rating':(prefs['rating'] or prefs['target_rating']) if prefs else 1000,'theme':'hangingPiece' if hanging else 'endgame' if phases['endgame_errors']>phases['opening_errors'] else ''}
