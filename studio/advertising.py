"""Manual banner inventory, atomic viewable impressions, and gated AdSense config."""
import hashlib,ipaddress,json,os,secrets,time
from urllib.parse import urlsplit
from fastapi import Depends,HTTPException,Query,Request
from fastapi.responses import PlainTextResponse
from . import core,control_store as store
from .control_models import AdvertisingSettings,BannerContext,BANNER_PLACEMENTS,BANNER_VIEWS

def settings(db):
 row=db.execute("SELECT value FROM control_settings WHERE key='advertising'").fetchone()
 return AdvertisingSettings(**json.loads(row[0])).model_dump(exclude={'confirm_password'}) if row else AdvertisingSettings().model_dump(exclude={'confirm_password'})

def google_ready(cfg):
 if not cfg['enabled'] or not cfg['google_enabled'] or not cfg['google_client'] or not cfg['google_consent_ready']:return False
 url=urlsplit(os.getenv('STUDIO_BASE_URL',''));host=url.hostname or ''
 if url.scheme!='https' or '.' not in host or host.endswith(('.localhost','.local','.test')):return False
 try:ipaddress.ip_address(host);return False
 except ValueError:return True

def public_config(db,request=None,user=None):
 cfg=settings(db);url=urlsplit(os.getenv('STUDIO_BASE_URL',''))
 ready=google_ready(cfg) and bool(request and request.url.hostname==url.hostname) and bool(user and user['role']!='admin')
 return {**cfg,'google_ready':ready,'measurement':'local-visible-50-percent-1-second; Google reporting is separate'}

def allowed(db,row,cfg,user,view,width,now,*,frequency=True):
 if not cfg['enabled'] or user['role']=='admin' or not row['enabled'] or not row['visible'] or row['placement'] not in BANNER_PLACEMENTS:return False
 if not cfg['slots'][row['placement']] or not row['starts_at']<=now<row['ends_at']:return False
 if row['placement'] in ('screen_left','screen_right') and width<cfg['side_min_width']:return False
 if view not in json.loads(row['views_json']):return False
 ent=store.entitlement(user['id'],db)
 if ent['plan']['features'].get('no_ads') or row['plan_id'] and row['plan_id']!=ent['plan']['id']:return False
 if row['kind']=='adsense' and not google_ready(cfg):return False
 if db.execute('SELECT 1 FROM control_ad_dismissals WHERE user_id=? AND campaign_id=? AND until_at>?',(user['id'],row['id'],now)).fetchone():return False
 count=db.execute("SELECT count(*) FROM control_ad_events WHERE user_id=? AND event='banner_visit'",(user['id'],)).fetchone()[0]
 if count<row['after_n']:return False
 if frequency:
  start=now-(now+10800)%86400
  recent=db.execute('SELECT count(CASE WHEN created_at>=? THEN 1 END) daily,max(created_at) last FROM control_ad_deliveries WHERE user_id=? AND campaign_id=? AND shown_at IS NOT NULL',(start,user['id'],row['id'])).fetchone()
  if recent['daily']>=row['daily_cap'] or recent['last'] is not None and recent['last']>now-row['cooldown_minutes']*60:return False
 return True

def bootstrap_nonce(request):
 """Third-party CSP is opt-in, HTTPS-host-bound, and absent for admin/no-ads users."""
 with core.connection() as db:
  cfg=settings(db)
  if not google_ready(cfg) or request.url.hostname!=urlsplit(os.getenv('STUDIO_BASE_URL','')).hostname:return None
  token=request.cookies.get('studio_session','')
  user=db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
  if not user or user['role']=='admin':return None
  entitlement=store.entitlement(user['id'],db)
  if entitlement['plan']['features'].get('no_ads') or not any(cfg['slots'].values()):return None
  now=time.time()
  if not db.execute("SELECT 1 FROM control_ads WHERE enabled=1 AND visible=1 AND kind='adsense' AND starts_at<=? AND ends_at>? AND (plan_id IS NULL OR plan_id=?)",(now,now,entitlement['plan']['id'])).fetchone():return None
 return secrets.token_urlsafe(24)

def google_csp(nonce):
 # Google documents strict-dynamic because downstream serving hosts change.
 # Do not enable unsafe-eval or arbitrary publisher-supplied JavaScript.
 return ("default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
         f"script-src 'nonce-{nonce}' 'strict-dynamic' https:; "
         "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; frame-src https:; connect-src 'self' https:")

def install(app,auth,admin):
 from .promotions import campaign
 @app.get('/api/control/advertising')
 def configuration(user=Depends(admin)):
  with core.connection() as db:return {'settings':settings(db),'google_site_ready':google_ready(settings(db)),'placements':BANNER_PLACEMENTS,'views':BANNER_VIEWS}

 @app.put('/api/control/advertising')
 def configure(data:AdvertisingSettings,user=Depends(admin)):
  from .control_api import reauth
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');previous=settings(db)
   if data.version!=previous['version']:raise HTTPException(409,'Advertising settings changed; reload before saving')
   if (data.google_enabled,data.google_client,data.google_consent_ready)!=(previous['google_enabled'],previous['google_client'],previous['google_consent_ready']):reauth(user,data.confirm_password)
   value=data.model_dump(exclude={'confirm_password'});value['version']+=1
   db.execute("INSERT INTO control_settings VALUES('advertising',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value),))
   store.audit(db,user['id'],'advertising.settings','all',{'enabled':value['enabled'],'google_enabled':value['google_enabled'],'version':value['version']})
  return {'ok':True,'settings':value}

 @app.get('/api/control/advertising/preview')
 def preview(view:str=Query(pattern=r'^(home|games|knowledge|learning|play|grades|course)$'),width:int=Query(ge=0,le=20000),user=Depends(admin)):
  with core.connection() as db:
   cfg=settings(db);now=time.time();items=[]
   rows=db.execute('SELECT * FROM control_ads WHERE enabled=1 AND visible=1 AND starts_at<=? AND ends_at>? ORDER BY priority DESC,id',(now,now)).fetchall()
   for row in rows:
    p=row['placement']
    if p not in BANNER_PLACEMENTS or not cfg['slots'][p] or view not in json.loads(row['views_json']):continue
    if p in ('screen_left','screen_right') and width<cfg['side_min_width']:continue
    items.append(campaign(row))
   return {'config':{**cfg,'google_ready':False},'items':items,'preview':True,'visit_registered':True}

 def select(context,request,user,record):
  now=time.time()
  with core.connection() as db:
   cfg=public_config(db,request,user)
   if not cfg['enabled'] or user['role']=='admin' or store.entitlement(user['id'],db)['plan']['features'].get('no_ads'):return {'config':cfg,'items':[],'visit_registered':False}
   if record:
    from .app import ratelimit
    ratelimit('banner-visit:'+str(user['id']),60,60)
    db.execute('INSERT OR IGNORE INTO control_ad_events VALUES(?,?,?,?)',(user['id'],'banner_visit',context.visit,now))
    db.execute("DELETE FROM control_ad_events WHERE event='banner_visit' AND created_at<?",(now-90*86400,))
   # Strict priority, then least recently shown for this player, then stable ID.
   rows=db.execute('SELECT a.*, (SELECT max(created_at) FROM control_ad_deliveries d WHERE d.user_id=? AND d.campaign_id=a.id AND shown_at IS NOT NULL) last_shown FROM control_ads a WHERE enabled=1 AND visible=1 ORDER BY priority DESC,coalesce(last_shown,0),id',(user['id'],)).fetchall()
   already={r[0] for r in db.execute('SELECT campaign_id FROM control_ad_deliveries WHERE user_id=? AND visit_key=?',(user['id'],context.visit))}
   items=[];counts={}
   for row in rows:
    if allowed(db,row,cfg,user,context.view,context.width,now,frequency=row['id'] not in already):
     p=row['placement']
     if counts.get(p,0)>=3 and row['id'] not in already:continue
     counts[p]=counts.get(p,0)+1;items.append(campaign(row))
   return {'config':cfg,'items':items,'visit_registered':bool(db.execute("SELECT 1 FROM control_ad_events WHERE user_id=? AND event='banner_visit' AND resource=?",(user['id'],context.visit)).fetchone())}

 @app.post('/api/promotions/banners/select')
 def first(context:BannerContext,request:Request,user=Depends(auth)):return select(context,request,user,True)

 @app.get('/api/promotions/banners')
 def refresh(request:Request,view:str=Query(max_length=20,pattern=r'^(home|games|knowledge|learning|play|grades|course)$'),width:int=Query(ge=0,le=20000),visit:str=Query(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9:_-]+$'),user=Depends(auth)):
  return select(BannerContext(view=view,width=width,visit=visit),request,user,False)

 @app.post('/api/promotions/banners/{cid}/impression')
 def impression(cid:str,context:BannerContext,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('banner-impression:'+str(user['id']),60,60);now=time.time()
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');cfg=settings(db);row=db.execute('SELECT * FROM control_ads WHERE id=?',(cid,)).fetchone()
   if not row or not allowed(db,row,cfg,user,context.view,context.width,now,frequency=False):return {'show':False}
   if not db.execute("SELECT 1 FROM control_ad_events WHERE user_id=? AND event='banner_visit' AND resource=?",(user['id'],context.visit)).fetchone():return {'show':False}
   old=db.execute('SELECT id FROM control_ad_deliveries WHERE user_id=? AND campaign_id=? AND visit_key=?',(user['id'],cid,context.visit)).fetchone()
   if old:return {'show':True,'delivery_id':old['id'],'duplicate':True}
   if not allowed(db,row,cfg,user,context.view,context.width,now):return {'show':False}
   existing=db.execute('SELECT banner_placement FROM control_ad_deliveries WHERE user_id=? AND visit_key=?',(user['id'],context.visit)).fetchall()
   if len(existing)>=cfg['max_active'] or any(x[0]==row['placement'] for x in existing):return {'show':False}
   delivery=secrets.token_hex(16)
   db.execute('INSERT INTO control_ad_deliveries(id,user_id,campaign_id,created_at,shown_at,visit_key,banner_placement) VALUES(?,?,?,?,?,?,?)',(delivery,user['id'],cid,now,now,context.visit,row['placement']))
   return {'show':True,'delivery_id':delivery,'duplicate':False}

 @app.post('/api/promotions/banners/{cid}/dismiss')
 def dismiss(cid:str,user=Depends(auth)):
  with core.connection() as db:
   row=db.execute('SELECT dismissible FROM control_ads WHERE id=?',(cid,)).fetchone()
   if not row or not row['dismissible']:raise HTTPException(404,'Dismissible campaign not found')
   until=time.time()+settings(db)['dismiss_hours']*3600
   db.execute('INSERT INTO control_ad_dismissals VALUES(?,?,?) ON CONFLICT(user_id,campaign_id) DO UPDATE SET until_at=excluded.until_at',(user['id'],cid,until))
  return {'ok':True,'until':until}

 @app.get('/ads.txt',response_class=PlainTextResponse)
 def ads_txt():
  with core.connection() as db:cfg=settings(db)
  content='google.com, '+cfg['google_client'].removeprefix('ca-')+', DIRECT, f08c47fec0942fa0\n' if cfg['google_enabled'] and cfg['google_client'] else '# No Google advertising account configured.\n'
  return PlainTextResponse(content,headers={'Cache-Control':'public, max-age=300'})
