"""Additive control-centre schema and server-side entitlements."""
import json,time,secrets
from datetime import datetime,timezone
from fastapi import HTTPException
from . import core

FEATURES={'review':('مراجعة المباريات','Game review'),'play':('اللعب والتعلّم','Play and learn'),'knowledge':('مركز المعرفة','Knowledge centre'),'curriculum':('المسار التعليمي','Learning path'),'ai_teacher':('معلّم AI','AI teacher'),'ai_coach':('الشرح الموسّع أثناء التدريب','Expanded training notes'),'ai_plan':('خطة المتابعة الذكية','AI follow-up plan'),'no_ads':('إخفاء الإعلانات','Hide promotions')}
LIMITS={'teacher_daily':20,'coach_daily':40,'plans_daily':3}
DEFAULT_SETTINGS={'ai_enabled':True,'site_name':'Chess Studio','tagline_ar':'تعلّم الشطرنج خطوة بخطوة','tagline_en':'Learn chess one step at a time','support_email':'','maintenance':False,'maintenance_ar':'المنصة قيد الصيانة، حاول لاحقاً.','maintenance_en':'The site is under maintenance. Please try later.','daily_enabled':True,'daily_target':24}

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS control_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_audit(id INTEGER PRIMARY KEY,actor_id INTEGER,action TEXT NOT NULL,target TEXT NOT NULL,details_json TEXT NOT NULL,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_plans(id TEXT PRIMARY KEY,title_ar TEXT NOT NULL,title_en TEXT NOT NULL,description_ar TEXT NOT NULL,description_en TEXT NOT NULL,price_iqd INTEGER NOT NULL CHECK(price_iqd>=0),days INTEGER NOT NULL CHECK(days>0),enabled INTEGER NOT NULL,features_json TEXT NOT NULL,limits_json TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_memberships(user_id INTEGER PRIMARY KEY REFERENCES users(id),plan_id TEXT NOT NULL REFERENCES control_plans(id),starts_at REAL NOT NULL,expires_at REAL NOT NULL,source TEXT NOT NULL,reference TEXT NOT NULL,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_discounts(code TEXT PRIMARY KEY,kind TEXT NOT NULL,value INTEGER NOT NULL CHECK(value>0),enabled INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL,max_uses INTEGER NOT NULL CHECK(max_uses>0),per_user INTEGER NOT NULL CHECK(per_user>0),plan_id TEXT,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_gateways(name TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,environment TEXT NOT NULL DEFAULT 'sandbox',version_id TEXT,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_gateway_versions(id TEXT PRIMARY KEY,name TEXT NOT NULL,environment TEXT NOT NULL,public_json TEXT NOT NULL,secrets_json TEXT NOT NULL,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_orders(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),plan_id TEXT NOT NULL REFERENCES control_plans(id),plan_title TEXT NOT NULL,days INTEGER NOT NULL,original_amount INTEGER NOT NULL,amount INTEGER NOT NULL,currency TEXT NOT NULL DEFAULT 'IQD',discount_code TEXT,gateway TEXT NOT NULL,gateway_version TEXT,status TEXT NOT NULL,provider_id TEXT,checkout_json TEXT,callback_hash TEXT NOT NULL,request_key TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,paid_at REAL,last_check REAL NOT NULL DEFAULT 0,UNIQUE(user_id,request_key),UNIQUE(gateway,provider_id));
 CREATE INDEX IF NOT EXISTS control_order_status ON control_orders(status,created_at);
 CREATE TABLE IF NOT EXISTS control_usage(user_id INTEGER NOT NULL REFERENCES users(id),day TEXT NOT NULL,feature TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day,feature));
 CREATE TABLE IF NOT EXISTS control_ads(id TEXT PRIMARY KEY,title_ar TEXT NOT NULL,title_en TEXT NOT NULL,body_ar TEXT NOT NULL,body_en TEXT NOT NULL,image_path TEXT NOT NULL,link_url TEXT NOT NULL,button_ar TEXT NOT NULL,button_en TEXT NOT NULL,placement TEXT NOT NULL,event TEXT NOT NULL,after_n INTEGER NOT NULL,daily_cap INTEGER NOT NULL,cooldown_minutes INTEGER NOT NULL,plan_id TEXT,enabled INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL,priority INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS control_ad_events(user_id INTEGER NOT NULL REFERENCES users(id),event TEXT NOT NULL,resource TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(user_id,event,resource));
 CREATE TABLE IF NOT EXISTS control_ad_deliveries(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),campaign_id TEXT NOT NULL REFERENCES control_ads(id),created_at REAL NOT NULL,clicked_at REAL);
 CREATE INDEX IF NOT EXISTS control_ad_user ON control_ad_deliveries(user_id,campaign_id,created_at);
 CREATE TABLE IF NOT EXISTS control_play_purchases(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),gateway_version TEXT NOT NULL,product_id TEXT NOT NULL,plan_id TEXT NOT NULL REFERENCES control_plans(id),order_id TEXT NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL,token_ref TEXT NOT NULL,last_check REAL NOT NULL,UNIQUE(order_id));
 ''')
 cols={r['name'] for r in db.execute('PRAGMA table_info(control_ad_deliveries)')}
 if 'shown_at' not in cols:db.execute('ALTER TABLE control_ad_deliveries ADD COLUMN shown_at REAL')
 features={k:k!='no_ads' for k in FEATURES}
 db.execute('INSERT OR IGNORE INTO control_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('free','مجاني','Free','المميزات الحالية متاحة افتراضياً؛ يمكن للمدير تعديلها.','Existing features remain available by default; administrators can edit them.',0,30,1,json.dumps(features),json.dumps(LIMITS),1,core.now()))
 for name in ('zaincash','fib','google_play'):db.execute('INSERT OR IGNORE INTO control_gateways(name,updated_at) VALUES(?,?)',(name,core.now()))

def audit(db,actor,action,target,details=None):
 db.execute('INSERT INTO control_audit(actor_id,action,target,details_json,created_at) VALUES(?,?,?,?,?)',(actor,action,str(target),json.dumps(details or {},ensure_ascii=False),core.now()))

def settings(db=None):
 if db is None:
  with core.connection() as conn:return settings(conn)
 out=dict(DEFAULT_SETTINGS)
 for r in db.execute('SELECT key,value FROM control_settings'):out[r['key']]=json.loads(r['value'])
 return out

def plan(row):
 x=dict(row);x['features']=json.loads(x.pop('features_json'));x['limits']=json.loads(x.pop('limits_json'));x['enabled']=bool(x['enabled']);return x

def entitlement(uid,db=None):
 if db is None:
  with core.connection() as conn:return entitlement(uid,conn)
 m=db.execute('SELECT * FROM control_memberships WHERE user_id=? AND starts_at<=? AND expires_at>?',(uid,time.time(),time.time())).fetchone()
 p=db.execute('SELECT * FROM control_plans WHERE id=?',(m['plan_id'] if m else 'free',)).fetchone()
 hold=db.execute("SELECT 1 FROM control_memberships WHERE user_id=? AND source='admin_block'",(uid,)).fetchone()
 return {'manual_hold':bool(hold),'plan':plan(p),'expires_at':m['expires_at'] if m else None,'source':m['source'] if m else 'default','active_paid':bool(m and p['id']!='free')}

def feature(uid,name,db=None):return bool(entitlement(uid,db)['plan']['features'].get(name,False))

def teacher_limit(uid,db):
 row=db.execute('SELECT role FROM users WHERE id=?',(uid,)).fetchone()
 global_limit=max(1,min(100,int(core.config(db,'teacher_daily_limit','20'))))
 if row and row['role']=='admin':return global_limit
 return min(global_limit,entitlement(uid,db)['plan']['limits'].get('teacher_daily',20))

def grant(db,uid,pid,days,source,reference,*,expiry=None):
 if not db.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone():raise HTTPException(404,'User not found')
 if not db.execute('SELECT id FROM control_plans WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'Plan not found')
 old=db.execute('SELECT * FROM control_memberships WHERE user_id=?',(uid,)).fetchone();start=time.time()
 end=expiry if expiry is not None else max(start,old['expires_at'] if old and old['plan_id']==pid else start)+days*86400
 db.execute('INSERT INTO control_memberships VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET plan_id=excluded.plan_id,starts_at=excluded.starts_at,expires_at=excluded.expires_at,source=excluded.source,reference=excluded.reference,updated_at=excluded.updated_at',(uid,pid,start,end,source,reference,core.now()))

def route_feature(path,method):
 if path.startswith('/api/control/') or path.startswith('/api/billing/') or path.startswith('/api/promotions/'):return None
 if path.startswith('/api/teacher/'):return 'ai_teacher' if method=='POST' else None
 if path=='/api/learning/followup' and method=='POST':return 'ai_plan'
 if path.startswith('/api/play/') and path.endswith('/coach') and method=='POST':return 'play'
 if path.startswith('/api/play/'):return 'play'
 if path.startswith('/api/knowledge/'):return 'knowledge'
 if path.startswith('/api/training/'):return 'knowledge'
 if path.startswith('/api/analysis/jobs'):return 'review'
 if path.startswith('/api/learning'):return 'curriculum'
 if path=='/api/course' or path.startswith('/api/course/'):return 'curriculum'
 if path.startswith('/api/games/') or path=='/api/games':return 'review'
 return None

def authorize(user,request):
 if user['role']=='admin':return
 with core.connection() as db:
  cfg=settings(db)
  if cfg['maintenance'] and request.url.path not in ('/api/me','/api/auth/logout'):raise HTTPException(503,cfg['maintenance_en'] if request.headers.get('Accept-Language','').startswith('en') else cfg['maintenance_ar'])
  name=route_feature(request.url.path,request.method)
  if name and not feature(user['id'],name,db):raise HTTPException(403,{'code':'feature_not_in_plan','feature':name,'message':'هذه الميزة غير متاحة في خطتك الحالية / This feature is not included in your plan'})

def reserve(uid,name,limit):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');day=datetime.now(timezone.utc).date().isoformat()
  r=db.execute('SELECT n FROM control_usage WHERE user_id=? AND day=? AND feature=?',(uid,day,name)).fetchone()
  if r and r['n']>=limit or limit<=0:raise HTTPException(429,'وصلت إلى حد الاستخدام اليومي في خطتك / Daily plan limit reached')
  db.execute('INSERT INTO control_usage VALUES(?,?,?,1) ON CONFLICT(user_id,day,feature) DO UPDATE SET n=n+1',(uid,day,name))
 return day

def refund_usage(uid,name,day):
 with core.connection() as db:db.execute('UPDATE control_usage SET n=max(0,n-1) WHERE user_id=? AND day=? AND feature=?',(uid,day,name))


def global_ai_enabled():
 import sqlite3
 try:return settings()['ai_enabled']
 except sqlite3.OperationalError as e:
  if 'no such table' in str(e):return True
  from .teacher_v7.providers import ProviderError
  raise ProviderError('AI settings unavailable','configuration_unavailable') from None
