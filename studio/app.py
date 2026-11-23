"""Private-by-default multi-user beta. Public rollout requires HTTPS and operational hardening."""
import hashlib, hmac, json, logging, os, secrets, time
from typing import Literal
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .core import (connection, setup, passhash, verify, now, safe_user, EMAIL_RE, config,config_set,
  GRADE_LABELS,LEVELS,course_outline,choose_lesson_position,game_analysis_counts,game_moves_from_pgn, user_analysis_speed, _lesson_candidates)

log=logging.getLogger('studio')
COOKIE_SECURE=os.getenv('STUDIO_COOKIE_SECURE','false').lower()=='true'
BASE_URL=os.getenv('STUDIO_BASE_URL','').rstrip('/')
SAME_ORIGIN=urlparse(BASE_URL).netloc if BASE_URL else None
SESSION_AGE=14*86400
app=FastAPI(title='Chess AI Coach Studio v6 Beta',docs_url=None,redoc_url=None,openapi_url=None)
static=Path(__file__).parent/'static'
app.mount('/assets',StaticFiles(directory=static),name='assets')
app.mount('/pieces',StaticFiles(directory=Path(__file__).parent.parent/'web'/'pieces'),name='pieces')

@app.on_event('startup')
def start():
 setup()
 from .teacher_v7.router import setup_teacher
 setup_teacher()
 from .play_groq import setup_play
 setup_play()
 from .knowledge.store import setup as setup_knowledge
 setup_knowledge()

@app.middleware('http')
async def request_language(req:Request,call_next):
 from .locale import LANGUAGE,parse
 token=LANGUAGE.set(parse(req.headers.get('Accept-Language','ar')))
 try:return await call_next(req)
 finally:LANGUAGE.reset(token)

@app.middleware('http')
async def security_headers(req:Request,call_next):
 if req.method in ('POST','PATCH','PUT','DELETE'):
  origin=req.headers.get('origin')
  if origin:
   # HTTP on SSH localhost is accepted in dev, in public mode exact HTTPS origin is required.
   target=BASE_URL or f'{req.url.scheme}://{req.headers.get("host","")}'
   if origin.rstrip('/')!=target.rstrip('/'):
    return Response('Origin mismatch',status_code=403)
 resp=await call_next(req)
 resp.headers['X-Content-Type-Options']='nosniff'
 resp.headers['Referrer-Policy']='no-referrer'
 resp.headers['X-Frame-Options']='DENY'
 # Only public static files may be cached. Account/API responses stay private.
 public_asset=req.method in ('GET','HEAD') and resp.status_code in (200,304) and req.url.path.startswith(('/assets/','/pieces/'))
 if public_asset:
  if req.query_params.get('v'):resp.headers['Cache-Control']='public, max-age=31536000, immutable'
  elif req.url.path.startswith(('/assets/pieces/','/pieces/')):resp.headers['Cache-Control']='public, max-age=86400'
  else:resp.headers['Cache-Control']='public, max-age=0, must-revalidate'
 else:resp.headers['Cache-Control']='no-store'
 resp.headers['Content-Security-Policy']=("default-src 'self'; img-src 'self' data:; style-src 'self'; "
         "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
 return resp

@app.get('/')
def home():return FileResponse(static/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/health')
def health():return {'status':'ok','mode':'completed-games-only','version':'6-beta'}

class Register(BaseModel):
 email:str=Field(min_length=5,max_length=255)
 password:str=Field(min_length=12,max_length=128)
class Login(Register):pass
class Settings(BaseModel):
 chess_username:str=Field(default='',max_length=25)
 theme:str=Field(default='dark',pattern='^(dark|light|system)$')
 board_theme:str=Field(default='classic',pattern='^(classic|green|blue)$')
 target_rating:int=Field(default=1000,ge=400,le=3000)
 rating_format:str=Field(default='rapid',pattern='^(rapid|blitz|bullet|daily)$')
class PasswordChange(BaseModel):
 current_password:str=Field(min_length=1,max_length=128)
 new_password:str=Field(min_length=12,max_length=128)


def ratelimit(key:str,limit=6,window=900):
 now_sec=int(time.time());name=hashlib.sha256(key.encode()).hexdigest()
 with connection() as db:
  row=db.execute('SELECT n,expires_at FROM auth_attempts WHERE key=?',(name,)).fetchone()
  if not row or row['expires_at']<=now_sec:
   db.execute('INSERT OR REPLACE INTO auth_attempts VALUES(?,?,?)',(name,1,now_sec+window))
  else:
   if row['n']>=limit:raise HTTPException(429,'محاولات كثيرة. حاول لاحقاً.')
   db.execute('UPDATE auth_attempts SET n=n+1 WHERE key=?',(name,))

def issue_session(resp:Response,uid:int):
 token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
 with connection() as db:
  db.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES (?,?,?,?)',
      (hashlib.sha256(token.encode()).hexdigest(),uid,csrf,int(time.time())+SESSION_AGE))
 resp.set_cookie('studio_session',token,httponly=True,secure=COOKIE_SECURE,samesite='strict',max_age=SESSION_AGE,path='/')
 return csrf

async def auth(req:Request):
 token=req.cookies.get('studio_session','')
 if not token:raise HTTPException(401,'يجب تسجيل الدخول')
 with connection() as db:
  row=db.execute('''SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0''',
        (hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
 if not row:raise HTTPException(401,'انتهت الجلسة')
 if req.method in ('POST','PUT','PATCH','DELETE'):
  provided=req.headers.get('X-CSRF-Token','')
  if not provided or not hmac.compare_digest(provided,row['csrf']):raise HTTPException(403,'رمز حماية الطلب مفقود')
 from .control_store import authorize
 authorize(dict(row),req)
 return dict(row)

def admin(user=Depends(auth)):
 if user['role']!='admin':raise HTTPException(403,'للمدير فقط')
 return user

@app.post('/api/auth/register',status_code=201)
def register(request:Request,response:Response,data:Register):
 ratelimit(f'register:{request.client.host if request.client else "unknown"}',5)
 email=data.email.strip().lower()
 if not EMAIL_RE.fullmatch(email):raise HTTPException(422,'بريد إلكتروني غير صالح')
 with connection() as db:
  if config(db,'registration_open','true')!='true':raise HTTPException(403,'التسجيل مغلق مؤقتاً')
  if db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():raise HTTPException(409,'البريد مستخدم')
  cur=db.execute('INSERT INTO users(email,pass_hash,created_at) VALUES(?,?,?)',(email,passhash(data.password),now()))
  uid=cur.lastrowid
 return {'ok':True,'csrf':issue_session(response,uid),'email':email}

@app.post('/api/auth/login')
def login(request:Request,response:Response,data:Login):
 email=data.email.strip().lower()
 ratelimit(f'login:{request.client.host if request.client else "unknown"}:{email}',8)
 with connection() as db:row=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
 if not row or not verify(data.password,row['pass_hash']) or row['disabled']:
  raise HTTPException(401,'البريد الإلكتروني أو كلمة المرور غير صحيحة')
 return {'ok':True,'csrf':issue_session(response,row['id']),'email':email}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,user=Depends(auth)):
 token=request.cookies.get('studio_session','')
 with connection() as db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
 response.delete_cookie('studio_session',path='/');return {'ok':True}

@app.get('/api/me')
def me(user=Depends(auth)):
 return {'id':user['id'],'email':user['email'],'chess_username':user['chess_username'],
  'theme':user['theme'],'board_theme':user['board_theme'],'target_rating':user['target_rating'],
  'rating_format':user['rating_format'],'role':user['role'],'csrf':user['csrf'],
  'verified_chess_ownership':False,'notice':'اسم Chess.com يُربط عبر البيانات العامة ولا يثبت ملكية الحساب.'}

@app.put('/api/settings')
def settings(data:Settings,user=Depends(auth)):
 username=data.chess_username.strip().lower()
 if username and not safe_user(username):raise HTTPException(422,'اسم Chess.com غير صالح')
 with connection() as db:
  old=db.execute('SELECT chess_username FROM users WHERE id=?',(user['id'],)).fetchone()['chess_username']
  db.execute('''UPDATE users SET chess_username=?,theme=?,board_theme=?,target_rating=?,rating_format=? WHERE id=?''',
      (username or None,data.theme,data.board_theme,data.target_rating,data.rating_format,user['id']))
  # On profile switch, old imported games must not silently masquerade as new account games.
  if old and old!=username:
   db.execute('DELETE FROM games WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM archive_months WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM ratings WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM lesson_attempts WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM lesson_solves WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM worker_state WHERE key=?',('sync_last_'+str(user['id']),))
 return {'ok':True,'username':username,'archive_reimport':'pending' if old!=username else 'unchanged'}

class SpeedPreference(BaseModel):
 preset: Literal['turbo','fast','balanced','detailed','deep']

@app.get('/api/analysis/speed')
def get_analysis_speed(user=Depends(auth)):
 with connection() as db:
  speed = user_analysis_speed(db, user['id'])
  queue = {r['stage']:r['count'] for r in db.execute(
      'SELECT stage,COUNT(*) AS count FROM games WHERE user_id=? GROUP BY stage', (user['id'],))}
 return {'speed':speed,'queue':queue,
         'note':'الإعداد يطبّق على الوضعية التالية؛ النتائج المحفوظة لا تُعاد تلقائياً، والتحليل مستمر دون المتصفح.'}

@app.put('/api/analysis/speed')
def set_analysis_speed(data:SpeedPreference,user=Depends(auth)):
 with connection() as db:
  db.execute('''INSERT INTO analysis_preferences(user_id,preset) VALUES(?,?)
         ON CONFLICT(user_id) DO UPDATE SET preset=excluded.preset''', (user['id'],data.preset))
  speed = user_analysis_speed(db, user['id'])
 return {'ok':True,'speed':speed,
         'note':'تم الحفظ. يطبق العامل القيمة الجديدة على أول وضعية لم تبدأ بعد؛ البحث الجاري يكمل بميزانيته السابقة.'}

@app.post('/api/password')
def change_password(data:PasswordChange,user=Depends(auth)):
 if not verify(data.current_password,user['pass_hash']):raise HTTPException(403,'كلمة المرور القديمة خاطئة')
 with connection() as db:
  db.execute('UPDATE users SET pass_hash=? WHERE id=?',(passhash(data.new_password),user['id']))
  db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
 return {'ok':True,'message':'أعد تسجيل الدخول بكلمة المرور الجديدة'}

@app.delete('/api/account')
def delete_account(response:Response,user=Depends(auth)):
 with connection() as db:db.execute('DELETE FROM users WHERE id=?',(user['id'],))
 response.delete_cookie('studio_session',path='/');return {'ok':True}

@app.get('/api/dashboard')
def dashboard(user=Depends(auth),summary_only:bool=False):
 with connection() as db:
  u=user['id']
  stat=db.execute("SELECT COUNT(*) total, SUM(stage='done') done, SUM(stage='running') running, SUM(stage='pending') pending FROM games WHERE user_id=?",(u,)).fetchone()
  counts={} if summary_only else game_analysis_counts(db,u)
  ratings=[dict(r) for r in db.execute('SELECT * FROM ratings WHERE user_id=?',(u,))]
  history=[dict(r) for r in db.execute('''SELECT id,white,black,result,finished_at,stage,completed_positions,total_positions,url
      FROM games WHERE user_id=? ORDER BY finished_at DESC LIMIT 8''',(u,))]
  lesson_count=db.execute('SELECT COUNT(*) FROM lesson_attempts WHERE user_id=? AND passed=1',(u,)).fetchone()[0]
 return {'games':dict(stat),'grades':counts,'grade_labels':GRADE_LABELS,'grades_deferred':summary_only,'ratings':ratings,
          'recent':history,'lessons_passed':lesson_count,'lessons_total':len(LEVELS)}

@app.get('/api/ratings')
def ratings(user=Depends(auth)):
 with connection() as db:
  found=[dict(r) for r in db.execute('SELECT * FROM ratings WHERE user_id=?',(user['id'],))]
 return {'source':'Chess.com PubAPI /player/{username}/stats','items':found,
   'notice':'هذه تصنيفات Chess.com المنشورة لكل نمط، وليست تصنيف FIDE أو تقدير Elo من المحرك.'}

@app.get('/api/grades')
def grades(scope:str=Query('mine',pattern='^(mine|both)$'),user=Depends(auth)):
 with connection() as db:
  return {'counts':game_analysis_counts(db,user['id'],scope),'scope':scope,'labels':GRADE_LABELS}

@app.get('/api/games')
def games(page:int=Query(1,ge=1,le=10000),limit:int=Query(20,ge=1,le=50),
 grade:str=Query('all'),scope:str=Query('mine',pattern='^(mine|both)$'),user=Depends(auth)):
 if grade!='all' and grade not in GRADE_LABELS:raise HTTPException(422,'تصنيف غير معروف')
 with connection() as db:
  where='g.user_id=?';args=[user['id']]
  own=' AND ((lower(g.white)=lower(?) AND m.ply%2=1) OR (lower(g.black)=lower(?) AND m.ply%2=0))' if scope=='mine' else ''
  if grade!='all':
   where+=' AND EXISTS(SELECT 1 FROM moves m WHERE m.game_id=g.id AND m.grade=?'+own+')'
   args.append(grade)
   if scope=='mine':args.extend([user['chess_username'] or '',user['chess_username'] or ''])
  total=db.execute('SELECT COUNT(*) FROM games g WHERE '+where,args).fetchone()[0]
  rows=db.execute(f'''SELECT g.id,g.white,g.black,g.result,g.url,g.finished_at,g.stage,g.total_positions,g.completed_positions,
       (SELECT COUNT(*) FROM moves m WHERE m.game_id=g.id AND m.grade=?) grade_count
       FROM games g WHERE {where} ORDER BY g.finished_at DESC LIMIT ? OFFSET ?''',
       [grade,*args,limit,(page-1)*limit]).fetchall()
 return {'games':[dict(x) for x in rows],'total':total,'page':page,'grade':grade,'scope':scope}

@app.get('/api/games/{gid}')
def game(gid:int,user=Depends(auth)):
 with connection() as db:
  g=db.execute('SELECT * FROM games WHERE id=? AND user_id=?',(gid,user['id'])).fetchone()
  if not g:raise HTTPException(404,'المباراة غير موجودة')
  game_data=dict(g)
  moves=[dict(row) for row in db.execute('SELECT * FROM moves WHERE game_id=? ORDER BY ply',(gid,))]
 try:
  _,raw=game_moves_from_pgn(g['pgn']); byply={m['ply']:m for m in moves}
  game_data['moves']=[{'ply':ply,'uci':uci,'san':san,'fen_before':before,'fen_after':after,
       **{k:v for k,v in byply.get(ply,{}).items() if k not in ('game_id','ply','uci','san','fen_before','fen_after')},
       'lines':json.loads(byply[ply]['lines_json']) if ply in byply and byply[ply]['lines_json'] else []}
       for ply,uci,san,before,after in raw]
 except ValueError:game_data['moves']=[]
 game_data.pop('pgn',None)
 game_data['grade_counts']={k:sum(1 for m in moves if m['grade']==k) for k in GRADE_LABELS}
 return game_data

@app.get('/api/games/{gid}/coach/{ply}')
def game_coach(gid:int,ply:int,user=Depends(auth)):
    """Contextual teaching for a specific half-move in the user's completed game."""
    if not 1<=ply<=1000:raise HTTPException(422,'رقم النقلة غير صحيح')
    with connection() as db:
        row=db.execute('''SELECT m.* FROM moves m JOIN games g ON g.id=m.game_id
             WHERE g.id=? AND g.user_id=? AND g.stage='done' AND m.ply=?''',
             (gid,user['id'],ply)).fetchone()
    if row is None:raise HTTPException(404,'التحليل التفصيلي لهذه النقلة لم يكتمل بعد')
    from .coach_teacher import create_teacher_plan
    return create_teacher_plan(row,'تحليل مباراة مكتملة')

@app.get('/api/course')
def course(user=Depends(auth)):
 with connection() as db:
  items=course_outline(db,user['id'])
  target=user['target_rating'];mode=user['rating_format']
  official=db.execute('SELECT rating FROM ratings WHERE user_id=? AND format=?',(user['id'],mode)).fetchone()
  current=official['rating'] if official else None
  primary=db.execute('''SELECT grade,COUNT(*) n FROM moves m JOIN games g ON g.id=m.game_id JOIN users u ON u.id=g.user_id
     WHERE g.user_id=? AND grade IN ('blunder','mistake','missed','weak')
     AND ((lower(g.white)=lower(u.chess_username) AND m.ply%2=1) OR
          (lower(g.black)=lower(u.chess_username) AND m.ply%2=0))
     GROUP BY grade ORDER BY n DESC LIMIT 1''',(user['id'],)).fetchone()
 return {'lessons':items,'current_rating':current,'target_rating':target,'rating_format':mode,
   'improvement_focus':GRADE_LABELS.get(primary['grade']) if primary else None,
   'rating_gap':max(0,target-current) if current is not None else None,
   'notice':'خطة مبنية على أخطاء المباريات التي اكتمل تحليلها. الوصول إلى التصنيف المستهدف ليس مضموناً.'}

@app.get('/api/course/{lid}')
def lesson(lid:str,side:str=Query(default='any',pattern='^(any|white|black)$'),user=Depends(auth)):
 with connection() as db:
  item=next((x for x in course_outline(db,user['id']) if x['id']==lid),None)
  if not item:raise HTTPException(404,'درس غير موجود')
  if not item['unlocked'] and not item['passed']:raise HTTPException(409,'أكمل الدرس السابق وانتظر تحليل مبارياتك')
  row=choose_lesson_position(db,user['id'],lid,side)
  if not row:raise HTTPException(409,'لا تتوفر وضعية محللة بهذا اللون حالياً؛ اختر اللون الآخر أو الكل')
  return {'lesson':item,'position':{'game_id':row['game_id'],'fen':row['fen_before'],
     'played':row['san'],'best_san':row['best_san'],'best_uci':row['best_uci'],'ply':row['ply'],
     'player_color':'white' if row['ply']%2 else 'black','grade':row['grade'],
     'white':row['white'],'black':row['black'],'url':row['url'],
     'hint':'افحص الكش والأسر والتهديدات قبل اختيار النقلة.',
     'legal_moves':[m.uci() for m in __import__('chess').Board(row['fen_before']).legal_moves]}}

@app.get('/api/course/{lid}/coach')
def lesson_coach(lid:str,game_id:int=Query(gt=0),ply:int=Query(gt=0),user=Depends(auth)):
    """Explain a fixed position belonging to the requesting user's completed game."""
    lesson_entry=next((x for x in LEVELS if x[0]==lid),None)
    if not lesson_entry:raise HTTPException(404,'الدرس غير موجود')
    with connection() as db:
        item=next((x for x in course_outline(db,user['id']) if x['id']==lid),None)
        if not item or (not item['unlocked'] and not item['passed']):raise HTTPException(409,'الدرس مقفل')
        row=next((r for r in _lesson_candidates(db,user['id'],lesson_entry[4])
                 if r['game_id']==game_id and r['ply']==ply),None)
    if row is None:raise HTTPException(404,'الموقف غير موجود ضمن مبارياتك المكتملة')
    from .coach_teacher import create_teacher_plan
    return create_teacher_plan(row,lesson_entry[2])

class Attempt(BaseModel):
 uci:str=Field(min_length=4,max_length=5)
 game_id:int|None=Field(default=None,gt=0)
 ply:int|None=Field(default=None,gt=0)
@app.post('/api/course/{lid}/attempt')
def attempt(lid:str,data:Attempt,user=Depends(auth)):
 with connection() as db:
  available=course_outline(db,user['id']);item=next((x for x in available if x['id']==lid),None)
  if not item or (not item['unlocked'] and not item['passed']):raise HTTPException(409,'الدرس مقفل')
  lesson_config=next((x for x in LEVELS if x[0]==lid),None)
  if not lesson_config:raise HTTPException(404,'الدرس غير موجود')
  if data.game_id is not None and data.ply is not None:
   row=next((m for m in _lesson_candidates(db,user['id'],lesson_config[4]) if m['game_id']==data.game_id and m['ply']==data.ply),None)
  else:
   row=choose_lesson_position(db,user['id'],lid)
  if not row:raise HTTPException(409,'التحليل لم يجهز بعد أو الموقف لا يتبع حسابك')
  import chess
  board=chess.Board(row['fen_before'])
  try:move=chess.Move.from_uci(data.uci)
  except ValueError:raise HTTPException(422,'نقلة غير صالحة')
  if move not in board.legal_moves:raise HTTPException(422,'نقلة غير قانونية')
  from .lesson_engine import assess_move
  assessment=assess_move(row,board,move)
  from .coach_teacher import move_facts
  move_teaching=move_facts(board,move)
  correct=assessment['accepted']
  old=db.execute('SELECT passed FROM lesson_attempts WHERE user_id=? AND lesson_id=?',(user['id'],lid)).fetchone()
  already=bool(old and old['passed'])
  if correct:
   db.execute('INSERT OR IGNORE INTO lesson_solves(user_id,lesson_id,game_id,ply,solved_at) VALUES(?,?,?,?,?)',
      (user['id'],lid,row['game_id'],row['ply'],now()))
  solved=db.execute('SELECT COUNT(*) FROM lesson_solves WHERE user_id=? AND lesson_id=?',(user['id'],lid)).fetchone()[0]
  outline=course_outline(db,user['id'])
  required=next(x['required'] for x in outline if x['id']==lid)
  passed=bool(already or (correct and required>0 and solved>=required))
  db.execute('''INSERT INTO lesson_attempts(user_id,lesson_id,passed,attempts,passed_at) VALUES(?,?,?,1,?)
      ON CONFLICT(user_id,lesson_id) DO UPDATE SET passed=MAX(passed,excluded.passed),attempts=attempts+1,
      passed_at=CASE WHEN excluded.passed=1 THEN excluded.passed_at ELSE passed_at END''',
      (user['id'],lid,int(passed),now() if passed else None))
 return {'correct':correct,'passed':passed,'solved':solved,'required':required,'best_san':row['best_san'],
    'best_uci':row['best_uci'],'assessment':assessment['status'],'loss_cp_estimate':assessment.get('loss_cp'),
    'explanation':assessment['explanation'], 'move_teaching':move_teaching,
    'source_game':row['game_id']}

@app.get('/api/admin/overview')
def overview(user=Depends(admin)):
 with connection() as db:
  return {'users':db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
   'games':db.execute('SELECT COUNT(*) FROM games').fetchone()[0],
   'jobs':[dict(r) for r in db.execute('SELECT stage,COUNT(*) n FROM games GROUP BY stage')],
   'config':{k:config(db,k) for k in ('deep_seconds','multipv','worker_paused','archive_refresh_hours','max_games_per_user','registration_open','teacher_daily_limit')}}

class AdminSettings(BaseModel):
 teacher_daily_limit:int=Field(default=20,ge=1,le=100)
 deep_seconds:int=Field(ge=1,le=120)
 multipv:int=Field(ge=1,le=5)
 worker_paused:bool
 archive_refresh_hours:int=Field(ge=1,le=48)
 max_games_per_user:int=Field(ge=50,le=10000)
 registration_open:bool=True
@app.put('/api/admin/settings')
def admin_settings(data:AdminSettings,user=Depends(admin)):
 with connection() as db:
  for k,v in data.model_dump().items():config_set(db,k,str(v).lower() if isinstance(v,bool) else v)
  from .control_store import audit
  audit(db,user['id'],'engine.settings','platform',data.model_dump())
 return {'ok':True,'note':'إعدادات البحث تُقرأ قبل الوضعية التالية، ولا تقاطع البحث الجاري.'}

@app.get('/api/admin/users')
def admin_users(user=Depends(admin)):
 with connection() as db:
  return {'users':[dict(r) for r in db.execute('''SELECT u.id,u.email,u.chess_username,u.role,u.disabled,
      (SELECT COUNT(*) FROM games g WHERE g.user_id=u.id) games FROM users u ORDER BY u.id DESC LIMIT 100''')]}

@app.get('/api/games/{gid}/practice')
def practice_state(gid:int,root_ply:int=Query(0,ge=0,le=1000),trail:str=Query(''),user=Depends(auth)):
    import chess
    if len(trail)>240:raise HTTPException(422,'سلسلة طويلة جداً')
    with connection() as db:
        row=db.execute('SELECT pgn FROM games WHERE id=? AND user_id=?',(gid,user['id'])).fetchone()
    if not row:raise HTTPException(404,'المباراة غير موجودة')
    game,moves=game_moves_from_pgn(row['pgn'])
    if root_ply>len(moves):raise HTTPException(422,'بداية غير صحيحة')
    board=chess.Board(moves[root_ply-1][4] if root_ply else game.board().fen())
    try:
        for notation in [x for x in trail.split(',') if x]:
            m=chess.Move.from_uci(notation)
            if m not in board.legal_moves:raise ValueError('Illegal')
            board.push(m)
    except ValueError:raise HTTPException(422,'سلسلة غير قانونية')
    return {'fen':board.fen(),'legal_moves':[m.uci() for m in board.legal_moves],
            'ended':board.is_game_over(claim_draw=True)}

class PracticeStep(BaseModel):
 root_ply:int=Field(ge=0,le=1000)
 trail:list[str]=Field(default_factory=list,max_length=40)
 uci:str=Field(min_length=4,max_length=5)

@app.post('/api/games/{gid}/practice')
def practice(gid:int,data:PracticeStep,user=Depends(auth)):
 """Sandbox study from a completed, owned game: no live game position accepted."""
 import chess
 with connection() as db:
  row=db.execute('SELECT pgn FROM games WHERE id=? AND user_id=?',(gid,user['id'])).fetchone()
 if not row:raise HTTPException(404,'المباراة غير موجودة')
 _,moves=game_moves_from_pgn(row['pgn'])
 if data.root_ply>len(moves):raise HTTPException(422,'نقطة بداية غير صحيحة')
 board=chess.Board(moves[data.root_ply-1][4] if data.root_ply else chess.Board().fen())
 fens=[board.fen()]
 try:
  for x in [*data.trail,data.uci]:
   mv=chess.Move.from_uci(x)
   if mv not in board.legal_moves:raise ValueError('Illegal')
   board.push(mv);fens.append(board.fen())
 except ValueError:raise HTTPException(422,'تحتوي النقلة على حركة غير قانونية')
 return {'fen':board.fen(),'fens':fens,'legal_moves':[m.uci() for m in board.legal_moves],
         'ended':board.is_game_over(claim_draw=True),'last':data.uci}

@app.get('/api/games/{gid}/scenario/{ply}/{line_index}')
def scenario(gid:int,ply:int,line_index:int,user=Depends(auth)):
 import chess
 if ply<1 or line_index<0 or line_index>4:raise HTTPException(422,'سيناريو غير صالح')
 with connection() as db:
  row=db.execute('''SELECT m.fen_before,m.lines_json FROM moves m JOIN games g ON m.game_id=g.id
        WHERE g.id=? AND g.user_id=? AND m.ply=?''',(gid,user['id'],ply)).fetchone()
 if not row:raise HTTPException(404,'التحليل غير متوفر')
 lines=json.loads(row['lines_json'] or '[]')
 if line_index>=len(lines):raise HTTPException(404,'السيناريو غير موجود')
 selected=lines[line_index];board=chess.Board(row['fen_before']);fens=[board.fen()];san=[];uci=[]
 for text in selected.get('pv_uci',[])[:20]:
  try:move=chess.Move.from_uci(text)
  except ValueError:break
  if move not in board.legal_moves:break
  san.append(board.san(move));uci.append(text);board.push(move);fens.append(board.fen())
 return {'fen_before':fens[0],'fens':fens,'moves':uci,'san':san,
         'evaluation_cp_white':selected.get('eval'),'depth':selected.get('depth'),
         'notice':'سيناريو استنتاجي من المحرك؛ رد الخصم قد يختلف عند اللعب الفعلي.'}

@app.get('/api/ratings/history')
def rating_history(format:str=Query('rapid',pattern='^(rapid|blitz|bullet|daily)$'),user=Depends(auth)):
 import chess.pgn,io
 with connection() as db:
  rows=db.execute('''SELECT pgn,finished_at FROM games WHERE user_id=? AND time_class=?
     ORDER BY finished_at DESC LIMIT 150''',(user['id'],format)).fetchall()
 history=[]
 username=(user['chess_username'] or '').lower()
 for row in reversed(rows):
  try:
   game=chess.pgn.read_game(io.StringIO(row['pgn']))
   is_white=(game.headers.get('White','').lower()==username)
   if not is_white and game.headers.get('Black','').lower()!=username:continue
   rating=int(game.headers.get('WhiteElo' if is_white else 'BlackElo'))
   if rating<100 or rating>4000:continue
   history.append({'date':row['finished_at'],'rating':rating})
  except (ValueError,TypeError,AttributeError):continue
 return {'source':'Chess.com archived game PGN WhiteElo / BlackElo', 'format':format,'items':history}

class UserStatus(BaseModel):disabled:bool
@app.patch('/api/admin/users/{uid}')
def set_user_status(uid:int,data:UserStatus,user=Depends(admin)):
 if uid==user['id']:raise HTTPException(400,'لا يمكن تعطيل حساب المدير الحالي')
 with connection() as db:
  r=db.execute('UPDATE users SET disabled=? WHERE id=? AND role!=?',(int(data.disabled),uid,'admin'))
  if r.rowcount!=1:raise HTTPException(404,'المستخدم غير موجود أو مدير آخر')
  db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
  from .control_store import audit
  audit(db,user['id'],'user.legacy_status',uid,{'disabled':data.disabled})
 return {'ok':True}

@app.post('/api/games/{gid}/retry')
def retry_analysis(gid:int,user=Depends(auth)):
 with connection() as db:
  r=db.execute("UPDATE games SET stage='pending',error=NULL WHERE id=? AND user_id=? AND stage='error'",
    (gid,user['id']))
  if r.rowcount!=1:raise HTTPException(409,'هذه المباراة ليست في حالة خطأ، أو لا تملك صلاحيتها')
 return {'ok':True,'status':'pending'}

# Chess Studio v7 conversational tutor; endpoints inherit Studio session/CSRF protection.
from .teacher_v7.router import install as _install_teacher_v7
_install_teacher_v7(app, auth)

# Independent Groq training games use the same session/CSRF protection.
from .play_groq import install as _install_groq_play
_install_groq_play(app, auth)

# Local-first knowledge center; same account and CSRF boundaries.
from .knowledge.router import install as _install_knowledge
_install_knowledge(app, auth)

from .knowledge.curriculum import install as _install_learning
_install_learning(app, auth)
from .knowledge.placement import install as _install_placement
from .knowledge.learning_plans import install as _install_learning_plans
_install_placement(app, auth)
_install_learning_plans(app, auth)
from .knowledge.daily_exercises import install as _install_daily_exercises
_install_daily_exercises(app, auth)

from .control_api import install as _install_control
_install_control(app, auth, admin)
