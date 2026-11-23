"""Authenticated administration, billing and campaign APIs using Studio's CSRF boundary."""
import json,time,secrets,os,re,hashlib
from pathlib import Path
from fastapi import Depends,HTTPException,Query,Request
from fastapi.responses import FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from . import core,control_store as store,control_secrets as vault,payment_providers as pay,billing,google_play
from .control_models import Plan,Membership,UserChange,Discount,Campaign,SiteSettings,ProviderSettings,Gateway,Checkout,AdEvent,PlayPurchase

def reauth(user,password):
 if not core.verify(password,user['pass_hash']):raise HTTPException(403,'أعد إدخال كلمة مرور حسابك لتأكيد الإجراء / Confirm your account password')

def media_root():
 p=core.DB.parent/'control-media';p.mkdir(mode=0o700,parents=True,exist_ok=True);return p

async def bounded_body(request,maximum):
 out=bytearray()
 async for block in request.stream():
  if len(out)+len(block)>maximum:raise HTTPException(413,'Request is too large')
  out.extend(block)
 return bytes(out)

def install(app,auth,admin):
 @app.exception_handler(RequestValidationError)
 async def safe_validation(request,exc):
  if request.url.path.startswith(('/api/control/','/api/billing/')):
   return JSONResponse(status_code=422,content={'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]})
  return await request_validation_exception_handler(request,exc)

 @app.get('/api/control/overview')
 def overview(user=Depends(admin)):
  with core.connection() as db:
   stats={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','games','control_plans','control_ads')}
   stats['paid_memberships']=db.execute("SELECT count(*) FROM control_memberships WHERE plan_id!='free' AND expires_at>?",(time.time(),)).fetchone()[0]
   stats['verified_revenue_iqd']=db.execute("SELECT coalesce(sum(amount),0) FROM control_orders WHERE status='paid'").fetchone()[0]
   stats['pending_orders']=db.execute("SELECT count(*) FROM control_orders WHERE status IN ('creating','pending')").fetchone()[0]
   jobs=[dict(x) for x in db.execute('SELECT stage,count(*) n FROM games GROUP BY stage')]
  try:
   from .knowledge.daily_exercises import status
   daily=status()
  except Exception:daily={'error':'daily_status_unavailable'}
  return {'stats':stats,'jobs':jobs,'daily':daily,'features':store.FEATURES,'default_limits':store.LIMITS,'gateway_notes':{'google_play':'Android app + Play Console products required; no website Google Play checkout is simulated.'}}

 @app.get('/api/control/users')
 def users(q:str=Query('',max_length=120),page:int=Query(1,ge=1),limit:int=Query(25,ge=1,le=100),user=Depends(admin)):
  where=' WHERE (?="" OR email LIKE ? OR chess_username LIKE ?)';args=(q,'%'+q+'%','%'+q+'%')
  with core.connection() as db:
   total=db.execute('SELECT count(*) FROM users'+where,args).fetchone()[0]
   rows=[dict(x) for x in db.execute('SELECT id,email,chess_username,role,disabled,created_at,(SELECT count(*) FROM games WHERE user_id=users.id) games FROM users'+where+' ORDER BY id DESC LIMIT ? OFFSET ?',(*args,limit,(page-1)*limit))]
   for x in rows:x['membership']=store.entitlement(x['id'],db)
  return {'items':rows,'total':total,'page':page,'limit':limit}

 @app.put('/api/control/users/{uid}')
 def update_user(uid:int,data:UserChange,user=Depends(admin)):
  reauth(user,data.confirm_password)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT id,role,disabled FROM users WHERE id=?',(uid,)).fetchone()
   if not old:raise HTTPException(404,'User not found')
   if uid==user['id'] and (data.disabled or data.role!='admin'):raise HTTPException(409,'You cannot remove your own administration access')
   if old['role']=='admin' and (data.disabled or data.role!='admin') and db.execute("SELECT count(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0]<=1:raise HTTPException(409,'Keep at least one active administrator')
   db.execute('UPDATE users SET role=?,disabled=? WHERE id=?',(data.role,int(data.disabled),uid));db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
   store.audit(db,user['id'],'user.update',uid,{'role':data.role,'disabled':data.disabled,'reason':data.reason})
  return {'ok':True}

 @app.post('/api/control/users/{uid}/logout')
 def logout_user(uid:int,user=Depends(admin)):
  with core.connection() as db:
   if not db.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone():raise HTTPException(404,'User not found')
   db.execute('DELETE FROM sessions WHERE user_id=?',(uid,));store.audit(db,user['id'],'user.sessions_revoked',uid)
  return {'ok':True}

 @app.put('/api/control/users/{uid}/membership')
 def assign(uid:int,data:Membership,user=Depends(admin)):
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');store.grant(db,uid,data.plan_id,data.days,'admin',secrets.token_hex(16));store.audit(db,user['id'],'membership.grant',uid,{'plan_id':data.plan_id,'days':data.days,'reason':data.reason})
  return {'ok':True,'membership':store.entitlement(uid)}

 @app.delete('/api/control/users/{uid}/membership')
 def revoke(uid:int,reason:str=Query(min_length=3,max_length=500),user=Depends(admin)):
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');store.grant(db,uid,'free',1,'admin_block',reason,expiry=time.time())
   store.audit(db,user['id'],'membership.revoke',uid,{'reason':reason})
  return {'ok':True}

 @app.get('/api/control/plans')
 def plans(user=Depends(admin)):
  with core.connection() as db:return {'items':[store.plan(x) for x in db.execute('SELECT * FROM control_plans ORDER BY price_iqd,id')]}

 @app.put('/api/control/plans/{pid}')
 def save_plan(pid:str,data:Plan,user=Depends(admin)):
  if pid!=data.id:raise HTTPException(422,'Plan ID mismatch')
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT version FROM control_plans WHERE id=?',(pid,)).fetchone()
   if data.version!=(old['version'] if old else 0):raise HTTPException(409,'Plan changed; reload before saving')
   args=(data.title_ar,data.title_en,data.description_ar,data.description_en,data.price_iqd,data.days,int(data.enabled),json.dumps(data.features),json.dumps(data.limits),data.version+1,core.now(),pid)
   if old:db.execute('UPDATE control_plans SET title_ar=?,title_en=?,description_ar=?,description_en=?,price_iqd=?,days=?,enabled=?,features_json=?,limits_json=?,version=?,updated_at=? WHERE id=?',args)
   else:db.execute('INSERT INTO control_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(pid,*args[:-1]))
   store.audit(db,user['id'],'plan.save',pid,{'version':data.version+1,'price_iqd':data.price_iqd,'enabled':data.enabled})
  return {'ok':True}

 @app.get('/api/control/discounts')
 def discounts(user=Depends(admin)):
  with core.connection() as db:return {'items':[dict(x) for x in db.execute("SELECT d.*,(SELECT count(*) FROM control_orders o WHERE o.discount_code=d.code AND o.status='paid') paid_uses FROM control_discounts d ORDER BY updated_at DESC")]}

 @app.put('/api/control/discounts/{code}')
 def save_discount(code:str,data:Discount,user=Depends(admin)):
  if code!=data.code:raise HTTPException(422,'Discount code mismatch')
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT version FROM control_discounts WHERE code=?',(code,)).fetchone()
   if data.version!=(old['version'] if old else 0):raise HTTPException(409,'Discount changed; reload before saving')
   if data.plan_id and not db.execute('SELECT id FROM control_plans WHERE id=?',(data.plan_id,)).fetchone():raise HTTPException(422,'Unknown plan')
   vals=(data.kind,data.value,int(data.enabled),data.starts_at,data.ends_at,data.max_uses,data.per_user,data.plan_id,data.version+1,core.now())
   if old:db.execute('UPDATE control_discounts SET kind=?,value=?,enabled=?,starts_at=?,ends_at=?,max_uses=?,per_user=?,plan_id=?,version=?,updated_at=? WHERE code=?',(*vals,code))
   else:db.execute('INSERT INTO control_discounts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(code,*vals))
   store.audit(db,user['id'],'discount.save',code,{'enabled':data.enabled,'version':data.version+1})
  return {'ok':True}

 @app.get('/api/control/providers')
 def providers(user=Depends(admin)):return vault.provider_public()
 @app.put('/api/control/providers')
 def save_providers(data:ProviderSettings,user=Depends(admin)):
  reauth(user,data.confirm_password)
  result=vault.save_providers(data)
  with core.connection() as db:db.execute('INSERT INTO control_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('ai_enabled',json.dumps(data.enabled)))
  result['enabled']=data.enabled
  with core.connection() as db:store.audit(db,user['id'],'providers.save','ai',{'primary':data.primary,'fallback':data.fallback,'keys_replaced':list(data.keys)})
  return result

 @app.get('/api/control/gateways')
 def gateways(user=Depends(admin)):
  with core.connection() as db:
   items=billing.gateways_public(db)
   for item in items:
    row=db.execute('SELECT v.* FROM control_gateways g JOIN control_gateway_versions v ON v.id=g.version_id WHERE g.name=?',(item['name'],)).fetchone()
    item['public']=json.loads(row['public_json']) if row else {};item['configured_secrets']={k:True for k in json.loads(row['secrets_json'])} if row else {}
   return {'items':items}

 @app.put('/api/control/gateways/{name}')
 def save_gateway(name:str,data:Gateway,user=Depends(admin)):
  reauth(user,data.confirm_password)
  public,required=pay.validate(name,data.environment,dict(data.public),data.secrets)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');g=db.execute('SELECT * FROM control_gateways WHERE name=?',(name,)).fetchone()
   if not g:raise HTTPException(404,'Unknown gateway')
   old=db.execute('SELECT * FROM control_gateway_versions WHERE id=?',(g['version_id'],)).fetchone()
   refs=json.loads(old['secrets_json']) if old and old['environment']==data.environment else {}
   for key,value in data.secrets.items():
    if value:refs[key]=vault.put(name+'-'+key,value)
   if name=='google_play':
    for plan_id in public.get('products',{}).values():
     if not db.execute("SELECT id FROM control_plans WHERE id=? AND id!='free'",(plan_id,)).fetchone():raise HTTPException(422,'Map Play products to existing paid plans')
   if data.enabled and not pay.ready(name,public|{'_environment':data.environment},refs):raise HTTPException(422,'Complete the gateway settings and credentials before enabling')
   version=secrets.token_hex(16);db.execute('INSERT INTO control_gateway_versions VALUES(?,?,?,?,?,?)',(version,name,data.environment,json.dumps(public),json.dumps(refs),core.now()))
   db.execute('UPDATE control_gateways SET enabled=?,environment=?,version_id=?,updated_at=? WHERE name=?',(int(data.enabled),data.environment,version,core.now(),name));store.audit(db,user['id'],'gateway.save',name,{'enabled':data.enabled,'environment':data.environment,'secrets_replaced':list(data.secrets)})
  return {'ok':True}

 @app.post('/api/control/gateways/{name}/test')
 def test_gateway(name:str,user=Depends(admin)):
  from .app import ratelimit
  ratelimit('gateway-test:'+str(user['id']),10,900)
  with core.connection() as db:_,profile=billing.gateway_profile(db,name)
  pay.token(profile)
  with core.connection() as db:store.audit(db,user['id'],'gateway.auth_test',name,{'success':True,'environment':profile['environment']})
  return {'authenticated':True,'environment':profile['environment']}

 @app.get('/api/control/orders')
 def orders(page:int=Query(1,ge=1),status:str=Query('',max_length=20),user=Depends(admin)):
  with core.connection() as db:
   total=db.execute('SELECT count(*) FROM control_orders WHERE (?="" OR status=?)',(status,status)).fetchone()[0]
   rows=[billing.public_order(x)|{'user_id':x['user_id'],'provider_id':x['provider_id']} for x in db.execute('SELECT * FROM control_orders WHERE (?="" OR status=?) ORDER BY created_at DESC LIMIT 50 OFFSET ?',(status,status,(page-1)*50))]
   play=[{k:x[k] for k in ('user_id','product_id','plan_id','order_id','expires_at','state','last_check')} for x in db.execute('SELECT * FROM control_play_purchases ORDER BY last_check DESC LIMIT 50')]
  return {'items':rows,'total':total,'page':page,'google_play':play}
 @app.post('/api/control/orders/{oid}/verify')
 def verify_order(oid:str,user=Depends(admin)):return billing.reconcile(oid,actor=user['id'])

 @app.get('/api/control/settings')
 def get_settings(user=Depends(admin)):return store.settings()
 @app.put('/api/control/settings')
 def save_settings(data:SiteSettings,user=Depends(admin)):
  if data.support_email and not core.EMAIL_RE.fullmatch(data.support_email):raise HTTPException(422,'Invalid support email')
  with core.connection() as db:
   for k,v in data.model_dump().items():db.execute('INSERT INTO control_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v,ensure_ascii=False)))
   store.audit(db,user['id'],'settings.save','site',{'fields':list(type(data).model_fields)})
  return {'ok':True}

 @app.post('/api/control/jobs/retry-failed')
 def retry(user=Depends(admin)):
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');ids=[r[0] for r in db.execute("SELECT id FROM games WHERE stage='error' LIMIT 100")]
   db.executemany("UPDATE games SET stage='pending',error=NULL WHERE id=?",[(i,) for i in ids]);store.audit(db,user['id'],'jobs.retry','failed',{'count':len(ids)})
  return {'retried':len(ids)}

 @app.get('/api/control/audit')
 def audit(page:int=Query(1,ge=1),user=Depends(admin)):
  with core.connection() as db:return {'items':[dict(x) for x in db.execute('SELECT id,actor_id,action,target,details_json,created_at FROM control_audit ORDER BY id DESC LIMIT 50 OFFSET ?',((page-1)*50,))],'total':db.execute('SELECT count(*) FROM control_audit').fetchone()[0],'page':page}

 @app.get('/api/billing/catalog')
 def catalog():
  with core.connection() as db:return {'plans':[store.plan(x) for x in db.execute('SELECT * FROM control_plans WHERE enabled=1 ORDER BY price_iqd')],'gateways':billing.gateways_public(db),'features':store.FEATURES}
 @app.get('/api/site-info')
 def site_info():
  cfg=store.settings()
  return {k:cfg[k] for k in ('site_name','tagline_ar','tagline_en','support_email','maintenance','maintenance_ar','maintenance_en')}
 @app.get('/api/billing/me')
 def my_plan(user=Depends(auth)):return store.entitlement(user['id'])
 @app.post('/api/billing/checkout')
 def checkout(data:Checkout,user=Depends(auth)):return billing.checkout(user['id'],data)
 @app.get('/api/billing/orders')
 def my_orders(user=Depends(auth)):
  with core.connection() as db:return {'items':[billing.public_order(x) for x in db.execute('SELECT * FROM control_orders WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(user['id'],))]}
 @app.post('/api/billing/orders/{oid}/verify')
 def user_verify_order(oid:str,user=Depends(auth)):return billing.reconcile(oid,user['id'])
 @app.post('/api/billing/callback/{name}/{oid}/{token}')
 async def callback(name:str,oid:str,token:str,request:Request):
  await bounded_body(request,65536)
  return billing.reconcile(oid,callback=token,gateway=name)
 @app.get('/api/billing/google-play/account')
 def play_account(user=Depends(auth)):return {'obfuscated_account_id':google_play.account_id(user['id']),'note':'Use this value with setObfuscatedAccountId in your Android Play Billing flow.'}
 @app.post('/api/billing/zaincash/webhook')
 async def zaincash_webhook(request:Request):
  import jwt
  from .app import ratelimit
  ratelimit('zain-push:'+(request.client.host if request.client else ''),60,60)
  try:
   data=json.loads(await bounded_body(request,65536));signed=data['webhook_token']
   if not isinstance(signed,str) or len(signed)>16000:raise ValueError()
   hint=jwt.decode(signed,options={'verify_signature':False},algorithms=['HS256'])
   with core.connection() as db:
    row=db.execute("SELECT * FROM control_orders WHERE gateway='zaincash' AND provider_id=?",(hint.get('transactionId'),)).fetchone()
    if not row:raise ValueError()
    _,profile=billing.gateway_profile(db,'zaincash',row['gateway_version'])
   claims=jwt.decode(signed,pay.credentials(profile)['api_key'],algorithms=['HS256'],options={'verify_aud':False})
   if claims.get('transactionId')!=row['provider_id'] or claims.get('orderId',claims.get('merchantReferenceId'))!=row['id']:raise ValueError()
  except Exception:raise HTTPException(401,'Webhook signature or order reference is invalid') from None
  try:billing.reconcile(row['id'],actor=row['user_id'])
  except HTTPException as e:
   if e.status_code!=429:raise
  return {'ok':True}
 @app.post('/api/billing/google-play/verify')
 def verify_play(data:PlayPurchase,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('play-verify:'+str(user['id']),20,900)
  return google_play.verify(user['id'],data.purchase_token,data.product_id)
 @app.post('/api/billing/google-play/notifications')
 async def play_notifications(request:Request):
  from .app import ratelimit
  ratelimit('play-push:'+(request.client.host if request.client else ''),60,60)
  body=await bounded_body(request,65536)
  try:payload=json.loads(body)
  except Exception:raise HTTPException(422,'Invalid notification JSON') from None
  return google_play.notification(request.headers.get('Authorization',''),payload)

 from .promotions import install as install_promotions
 install_promotions(app,auth,admin)
