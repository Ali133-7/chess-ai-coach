"""Text-only campaigns, controlled image uploads and atomic per-user frequency caps."""
import json,time,secrets,re
from fastapi import Depends,HTTPException,Query,Request
from fastapi.responses import FileResponse
from . import core,control_store as store
from .control_models import Campaign,AdEvent

def campaign(row):
 x=dict(row);x['enabled']=bool(x['enabled']);return x

def install(app,auth,admin):
 @app.get('/api/control/campaigns')
 def campaigns(user=Depends(admin)):
  with core.connection() as db:return {'items':[campaign(x) for x in db.execute('SELECT a.*,(SELECT count(*) FROM control_ad_deliveries WHERE campaign_id=a.id) deliveries,(SELECT count(*) FROM control_ad_deliveries WHERE campaign_id=a.id AND shown_at IS NOT NULL) displays,(SELECT count(*) FROM control_ad_deliveries WHERE campaign_id=a.id AND clicked_at IS NOT NULL) clicks FROM control_ads a ORDER BY updated_at DESC')],'events':['home_visit','knowledge_visit','play_visit','login','lesson_complete','puzzle_solved','game_finished','review_opened']}

 @app.put('/api/control/campaigns/{cid}')
 def save_campaign(cid:str,data:Campaign,user=Depends(admin)):
  if cid=='new':
   if data.id or data.version:raise HTTPException(422,'New campaign ID must be empty')
   cid=secrets.token_hex(16)
  elif cid!=data.id:raise HTTPException(422,'Campaign ID mismatch')
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT version FROM control_ads WHERE id=?',(cid,)).fetchone()
   if data.version!=(old['version'] if old else 0):raise HTTPException(409,'Campaign changed; reload before saving')
   if data.plan_id and not db.execute('SELECT id FROM control_plans WHERE id=?',(data.plan_id,)).fetchone():raise HTTPException(422,'Unknown plan')
   if data.image_path:
    from .control_api import media_root
    if not (media_root()/data.image_path.rsplit('/',1)[1]).is_file():raise HTTPException(422,'Upload the campaign image first')
   vals=(data.title_ar,data.title_en,data.body_ar,data.body_en,data.image_path,data.link_url,data.button_ar,data.button_en,data.placement,data.event,data.after_n,data.daily_cap,data.cooldown_minutes,data.plan_id,int(data.enabled),data.starts_at,data.ends_at,data.priority,data.version+1,core.now())
   if old:db.execute('UPDATE control_ads SET title_ar=?,title_en=?,body_ar=?,body_en=?,image_path=?,link_url=?,button_ar=?,button_en=?,placement=?,event=?,after_n=?,daily_cap=?,cooldown_minutes=?,plan_id=?,enabled=?,starts_at=?,ends_at=?,priority=?,version=?,updated_at=? WHERE id=?',(*vals,cid))
   else:db.execute('INSERT INTO control_ads VALUES('+','.join('?'*21)+')',(cid,*vals))
   store.audit(db,user['id'],'campaign.save',cid,{'enabled':data.enabled,'event':data.event,'placement':data.placement,'version':data.version+1})
  return {'id':cid,'ok':True}

 @app.post('/api/control/media')
 async def upload(request:Request,user=Depends(admin)):
  from .control_api import bounded_body,media_root
  raw=await bounded_body(request,2*1024*1024)
  ext=None
  if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24:ext='png'
  elif raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9'):ext='jpg'
  elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP':ext='webp'
  if not ext:raise HTTPException(422,'Upload a PNG, JPEG or WebP image; SVG and HTML are not accepted')
  name=secrets.token_hex(16)+'.'+ext;p=media_root()/name;p.write_bytes(raw)
  with core.connection() as db:store.audit(db,user['id'],'media.upload',name,{'bytes':len(raw)})
  return {'path':'/api/promotions/media/'+name}

 @app.get('/api/promotions/media/{name}')
 def media(name:str):
  from .control_api import media_root
  if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|webp)',name):raise HTTPException(404,'Image not found')
  p=media_root()/name
  if not p.is_file() or p.is_symlink():raise HTTPException(404,'Image not found')
  return FileResponse(p,media_type={'png':'image/png','jpg':'image/jpeg','webp':'image/webp'}[name.rsplit('.',1)[1]])

 @app.post('/api/promotions/event')
 def event(data:AdEvent,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('promotion-event:'+str(user['id']),60,60)
  now=time.time();uid=user['id'];start=now-(now+10800)%86400
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');ent=store.entitlement(uid,db)
   if ent['plan']['features'].get('no_ads') or user['role']=='admin':return {'items':[]}
   # Learning completion events must refer to an owned server-confirmed completion.
   checks={'lesson_complete':("SELECT 1 FROM learning_sessions WHERE id=? AND user_id=? AND json_extract(state_json,'$.completed')=1",(data.resource,uid)),
           'puzzle_solved':("SELECT 1 FROM knowledge_puzzle_sessions WHERE id=? AND user_id=? AND status='solved'",(data.resource,uid)),
           'game_finished':("SELECT 1 FROM groq_training_games WHERE id=? AND user_id=? AND status!='active'",(data.resource,uid)),
           'review_opened':('SELECT 1 FROM games WHERE id=? AND user_id=?',(data.resource,uid))}
   if data.event in checks:
    sql,args=checks[data.event]
    if not db.execute(sql,args).fetchone():raise HTTPException(422,'Event is not an owned completed activity')
   inserted=db.execute('INSERT OR IGNORE INTO control_ad_events VALUES(?,?,?,?)',(uid,data.event,data.resource,now)).rowcount
   if not inserted:return {'items':[]}
   count=db.execute('SELECT count(*) FROM control_ad_events WHERE user_id=? AND event=?',(uid,data.event)).fetchone()[0]
   # Prune only browser visit telemetry; owned learning completion deduplication remains durable.
   db.execute("DELETE FROM control_ad_events WHERE created_at<? AND event IN ('home_visit','knowledge_visit','play_visit','login')",(now-86400*90,))
   rows=db.execute('SELECT * FROM control_ads WHERE enabled=1 AND starts_at<=? AND ends_at>? AND event=? AND after_n<=? AND (plan_id IS NULL OR plan_id=?) ORDER BY priority DESC,updated_at DESC',(now,now,data.event,count,ent['plan']['id'])).fetchall();out=[];modal=False;placements=set()
   for row in rows:
    if row['placement']=='modal' and modal or row['placement'] in placements:continue
    recent=db.execute('SELECT count(*) n,max(created_at) last FROM control_ad_deliveries WHERE user_id=? AND campaign_id=? AND created_at>?',(uid,row['id'],min(start,now-row['cooldown_minutes']*60))).fetchone()
    daily=db.execute('SELECT count(*) FROM control_ad_deliveries WHERE user_id=? AND campaign_id=? AND created_at>=?',(uid,row['id'],start)).fetchone()[0]
    if daily>=row['daily_cap'] or recent['last'] and recent['last']>now-row['cooldown_minutes']*60:continue
    delivery=secrets.token_hex(16);db.execute('INSERT INTO control_ad_deliveries(id,user_id,campaign_id,created_at,clicked_at) VALUES(?,?,?,?,NULL)',(delivery,uid,row['id'],now));out.append(campaign(row)|{'delivery_id':delivery})
    modal=modal or row['placement']=='modal';placements.add(row['placement'])
   return {'items':out}

 @app.post('/api/promotions/{delivery}/display')
 def display(delivery:str,user=Depends(auth)):
  with core.connection() as db:
   row=db.execute('SELECT a.* FROM control_ad_deliveries d JOIN control_ads a ON a.id=d.campaign_id WHERE d.id=? AND d.user_id=?',(delivery,user['id'])).fetchone()
   ent=store.entitlement(user['id'],db)
   if not row or not row['enabled'] or not row['starts_at']<=time.time()<row['ends_at'] or ent['plan']['features'].get('no_ads') or row['plan_id'] and row['plan_id']!=ent['plan']['id']:return {'show':False}
   db.execute('UPDATE control_ad_deliveries SET shown_at=coalesce(shown_at,?) WHERE id=?',(time.time(),delivery))
   return {'show':True,'campaign':campaign(row)|{'delivery_id':delivery}}

 @app.post('/api/promotions/{delivery}/click')
 def click(delivery:str,user=Depends(auth)):
  with core.connection() as db:
   r=db.execute('UPDATE control_ad_deliveries SET clicked_at=coalesce(clicked_at,?) WHERE id=? AND user_id=? AND shown_at IS NOT NULL',(time.time(),delivery,user['id']))
   if not r.rowcount:raise HTTPException(404,'Delivery not found')
  return {'ok':True}
