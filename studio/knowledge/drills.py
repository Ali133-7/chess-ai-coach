import json,secrets
import chess
from fastapi import HTTPException
from .. import core
from .store import connection

def setup():
 with core.connection() as db:
  db.executescript('''CREATE TABLE IF NOT EXISTS knowledge_puzzle_history(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,status TEXT NOT NULL,first_seen_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,puzzle_id));
  CREATE INDEX IF NOT EXISTS puzzle_session_owner ON knowledge_puzzle_sessions(user_id,puzzle_id,status);''')
  db.execute('''INSERT OR IGNORE INTO knowledge_puzzle_history SELECT user_id,puzzle_id,CASE max(CASE status WHEN 'solved' THEN 3 WHEN 'revealed' THEN 2 WHEN 'skipped' THEN 2 ELSE 1 END) WHEN 3 THEN 'solved' WHEN 2 THEN 'reviewed' ELSE 'started' END,min(created_at),max(created_at) FROM knowledge_puzzle_sessions GROUP BY user_id,puzzle_id''')

def remember(db,uid,pid,status):
 db.execute('''INSERT INTO knowledge_puzzle_history VALUES(?,?,?,?,?) ON CONFLICT(user_id,puzzle_id) DO UPDATE SET status=CASE WHEN knowledge_puzzle_history.status='solved' THEN 'solved' ELSE excluded.status END,updated_at=excluded.updated_at''',(uid,pid,status,core.now(),core.now()))

def list_puzzles(rating=1000,theme='',opening='',limit=20,uid=None,broaden=False,source='all',daily_priority=False):
 where='1=1' if broaden else '(p.rating BETWEEN ? AND ? OR g.puzzle_id IS NOT NULL)';args=[] if broaden else [max(0,rating-350),min(5000,rating+350)]
 if theme:where+=" AND (instr(' '||p.themes||' ',' '||?||' ')>0"+(' OR g.puzzle_id IS NOT NULL)' if daily_priority else ')');args.append(theme)
 if opening:where+=' AND p.opening_tags LIKE ?';args.append('%'+opening[:100].replace(' ','_')+'%')
 if source=='generated':where+=' AND g.puzzle_id IS NOT NULL'
 if source=='original':where+=' AND g.puzzle_id IS NULL'
 with connection() as db:
  if uid is not None:
   db.execute('ATTACH DATABASE ? AS learner',(str(core.DB),));where+=' AND NOT EXISTS(SELECT 1 FROM learner.knowledge_puzzle_history h WHERE h.user_id=? AND h.puzzle_id=p.id)';args.append(uid)
  rows=db.execute('''SELECT p.id,CASE WHEN g.puzzle_id IS NOT NULL THEN NULL ELSE p.rating END AS rating,p.themes,p.opening_tags,g.day AS generated_day FROM kc_puzzles p LEFT JOIN kc_generated_exercises g ON g.puzzle_id=p.id WHERE '''+where+''' ORDER BY CASE WHEN g.puzzle_id IS NOT NULL THEN 0 ELSE 1 END,g.day DESC,abs(p.rating-?),p.id LIMIT ?''',args+[rating,limit]).fetchall()
 return {'items':[dict(r) for r in rows],'rating_basis':'ألغاز فعلية من Lichess ضمن ±350 من المستوى المرجعي. تصنيف اللغز ليس Elo المحرك.','sample_scope':'عينة محلية موثقة؛ ليست جميع ألغاز Lichess.'}

def puzzle(pid):
 with connection() as db:row=db.execute('SELECT * FROM kc_puzzles WHERE id=?',(pid,)).fetchone()
 if not row:raise HTTPException(404,'التمرين غير مستورد محلياً')
 return dict(row)

def packed(session,item):
 board=chess.Board(item['fen']);line=json.loads(item['moves_json'])
 played=json.loads(session['played_json']) if session.get('played_json') else line[:session['cursor']]
 for uci in played:board.push_uci(uci)
 active=session['status']=='active'
 from .daily_exercises import details
 generated=details(item['id'],include_solution=not active)
 return {'id':session['id'],'puzzle_id':item['id'],'fen':board.fen(),'version':session['version'],'status':session['status'],'rating':None if generated else item['rating'],'generated':generated,'themes':item['themes'].split(),
  'player_color':'white' if chess.Board(item['setup_fen']).turn else 'black','legal_moves':[m.uci() for m in board.legal_moves] if active else [],'mistakes':session['mistakes'],
  'last_move':played[-1] if played else None,'source':'Stockfish + AI; derived Lichess broadcast position, CC BY-SA 4.0' if generated else 'Lichess puzzles, CC0-1.0','message':'أحسنت، اكتمل الحل.' if session['status']=='solved' else 'تم تجاوز التمرين ولن يظهر ضمن الجديد.' if session['status']=='skipped' else 'الحل ظاهر للمراجعة.' if session['status']=='revealed' else 'دورك. ابحث عن أفضل استمرار.',
  'solution_uci':line[1:] if session['status']=='revealed' else None}

def start(pid,uid):
 item=puzzle(pid);sid=secrets.token_hex(16)
 with core.connection() as db:
  old=db.execute("SELECT * FROM knowledge_puzzle_sessions WHERE user_id=? AND puzzle_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",(uid,pid)).fetchone()
  if old:return packed(dict(old),item)
  db.execute('INSERT INTO knowledge_puzzle_sessions(id,user_id,puzzle_id,created_at) VALUES(?,?,?,?)',(sid,uid,pid,core.now()))
  remember(db,uid,pid,'started')
  session=dict(db.execute('SELECT * FROM knowledge_puzzle_sessions WHERE id=?',(sid,)).fetchone())
 return packed(session,item)

def move(sid,uid,uci,version,reveal=False):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM knowledge_puzzle_sessions WHERE id=? AND user_id=?',(sid,uid)).fetchone()
  if not row:raise HTTPException(404,'جلسة التدريب ليست ضمن حسابك')
  session=dict(row);item=puzzle(session['puzzle_id']);line=json.loads(item['moves_json'])
  if session['version']!=version or session['status']!='active':raise HTTPException(409,'تغيرت جلسة التمرين أو انتهت')
  if reveal:
   session.update(status='revealed',version=version+1);db.execute("UPDATE knowledge_puzzle_sessions SET status='revealed',version=version+1 WHERE id=?",(sid,));remember(db,uid,item['id'],'revealed');return packed(session,item)
  board=chess.Board(item['fen'])
  for token in line[:session['cursor']]:board.push_uci(token)
  try:candidate=board.parse_uci(uci)
  except ValueError:raise HTTPException(422,'نقلة غير قانونية') from None
  if candidate not in board.legal_moves:raise HTTPException(422,'نقلة غير قانونية')
  board.push(candidate);alternate_mate=board.is_checkmate()
  if uci!=line[session['cursor']] and not alternate_mate:
   db.execute('UPDATE knowledge_puzzle_sessions SET mistakes=mistakes+1,version=version+1 WHERE id=?',(sid,));session.update(mistakes=session['mistakes']+1,version=version+1)
   result=packed(session,item);result.update(correct=False,message='ليست نقلة الحل المسجل. جرّب من جديد؛ يمكن أن تحتاج البدائل إلى تحليل إضافي.');return result
  cursor=session['cursor']+1
  if alternate_mate and uci!=line[session['cursor']]:
   # Keep a valid replay for the legitimate alternate mate-in-one solution.
   item=dict(item);line=line[:session['cursor']]+[uci];item['moves_json']=json.dumps(line)
  if cursor<len(line):board.push_uci(line[cursor]);cursor+=1
  status='solved' if cursor>=len(line) or alternate_mate else 'active'
  db.execute('UPDATE knowledge_puzzle_sessions SET cursor=?,version=version+1,status=?,played_json=? WHERE id=?',(cursor,status,json.dumps(line[:cursor]),sid))
  if status=='solved':remember(db,uid,item['id'],'solved')
  session.update(cursor=cursor,version=version+1,status=status,played_json=json.dumps(line[:cursor]));result=packed(session,item);result['correct']=True;return result

def skip(sid,uid,version):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM knowledge_puzzle_sessions WHERE id=? AND user_id=?',(sid,uid)).fetchone()
  if not r:raise HTTPException(404,'جلسة التدريب ليست ضمن حسابك')
  r=dict(r)
  if r['version']!=version or r['status']!='active':raise HTTPException(409,'تغيرت جلسة التمرين أو انتهت')
  db.execute("UPDATE knowledge_puzzle_sessions SET status='skipped',version=version+1 WHERE id=?",(sid,));remember(db,uid,r['puzzle_id'],'skipped');r.update(status='skipped',version=version+1);return packed(r,puzzle(r['puzzle_id']))

def history(uid):
 with core.connection() as db:
  counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM knowledge_puzzle_history WHERE user_id=? GROUP BY status',(uid,))};rows=[dict(r) for r in db.execute('SELECT puzzle_id,status,updated_at FROM knowledge_puzzle_history WHERE user_id=? ORDER BY updated_at DESC LIMIT 20',(uid,))]
 return {'counts':counts,'recent':rows}
