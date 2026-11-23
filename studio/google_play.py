"""Android purchase verification and RTDN refresh; no web Google Play checkout is simulated."""
import base64,json,time,hashlib,hmac,secrets
from datetime import datetime,timezone
from urllib.parse import quote
from fastapi import HTTPException
from . import core,control_store as store,payment_providers as api
from .billing import gateway_profile
from .control_secrets import root,atomic,put,read

def account_id(uid):
 p=root()/'play-account-binding'
 # Publish a fully written private file atomically. Concurrent readers must never
 # derive an account ID from an empty, newly-created binding key.
 if not p.exists():
  import os,tempfile
  fd,name=tempfile.mkstemp(prefix='.binding-',dir=root())
  try:
   os.fchmod(fd,0o600) if hasattr(os,'fchmod') else os.chmod(name,0o600)
   with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32));f.flush();os.fsync(f.fileno())
   try:os.link(name,p)
   except FileExistsError:pass
  finally:os.unlink(name)
 if p.is_symlink():raise HTTPException(503,'Account binding unavailable')
 key=read('play-account-binding')
 if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise HTTPException(503,'Account binding unavailable')
 return hmac.new(key.encode(),str(uid).encode(),hashlib.sha256).hexdigest()

def expiry(value):
 try:
  d=datetime.fromisoformat(value.replace('Z','+00:00'))
  if d.tzinfo is None:raise ValueError()
  return d.timestamp()
 except Exception:raise HTTPException(502,'Google returned an invalid expiry') from None

def verify(uid,purchase_token,product_id,*,refresh=False):
 digest=hashlib.sha256(purchase_token.encode()).hexdigest();now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM control_play_purchases WHERE token_hash=?',(digest,)).fetchone()
  if old and old['user_id']!=uid:raise HTTPException(409,'Purchase is already bound to another account')
  g,profile=gateway_profile(db,'google_play',old['gateway_version'] if old else None)
  if not g['enabled'] and not old:raise HTTPException(503,'Google Play is disabled')
  cfg=json.loads(profile['public_json']);pid=cfg.get('products',{}).get(product_id)
  if not pid or not db.execute('SELECT id FROM control_plans WHERE id=?',(pid,)).fetchone():raise HTTPException(422,'Unknown Google Play product mapping')
  if old and old['last_check']>now-10:return {'state':old['state'],'expires_at':old['expires_at'],'cached':True}
  if old:db.execute('UPDATE control_play_purchases SET last_check=? WHERE token_hash=?',(now,digest))
 token=api.token(profile);base='https://androidpublisher.googleapis.com/androidpublisher/v3/applications/'+quote(cfg['package_name'],safe='')
 result=api.request('GET',base+'/purchases/subscriptionsv2/tokens/'+quote(purchase_token,safe=''),headers={'Authorization':'Bearer '+token})
 if result.get('externalAccountIdentifiers',{}).get('obfuscatedExternalAccountId')!=account_id(uid):raise HTTPException(409,'Google Play account binding mismatch')
 lines=[x for x in result.get('lineItems',[]) if x.get('productId')==product_id]
 if not lines:raise HTTPException(502,'Google Play product mismatch')
 end=max(expiry(x.get('expiryTime','')) for x in lines)
 state=result.get('subscriptionState','');test='testPurchase' in result and result['testPurchase'] is not None
 if test and not cfg.get('allow_test_purchases',False):raise HTTPException(409,'Test purchases are not accepted by this profile')
 active=state in ('SUBSCRIPTION_STATE_ACTIVE','SUBSCRIPTION_STATE_IN_GRACE_PERIOD','SUBSCRIPTION_STATE_CANCELED') and end>time.time()
 if active and result.get('acknowledgementState')=='ACKNOWLEDGEMENT_STATE_PENDING':api.request('POST',base+'/purchases/subscriptions/'+quote(product_id,safe='')+'/tokens/'+quote(purchase_token,safe='')+':acknowledge',headers={'Authorization':'Bearer '+token},body={})
 order_id=result.get('latestOrderId')
 if not isinstance(order_id,str) or not order_id or len(order_id)>200:raise HTTPException(502,'Google Play order ID is missing')
 real=profile['environment']=='live' and not test
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  existing=db.execute('SELECT user_id FROM control_play_purchases WHERE token_hash=?',(digest,)).fetchone()
  if existing and existing['user_id']!=uid:raise HTTPException(409,'Purchase is already bound to another account')
  if not existing:
   ref=put('play-purchase',purchase_token)
   db.execute('INSERT INTO control_play_purchases VALUES(?,?,?,?,?,?,?,?,?,?)',(digest,uid,profile['id'],product_id,pid,'pending-'+digest,0,'verifying',ref,now))
  same=db.execute('SELECT user_id,token_hash FROM control_play_purchases WHERE order_id=?',(order_id,)).fetchone()
  if same and (same['user_id']!=uid or same['token_hash']!=digest):raise HTTPException(409,'Google Play order is already recorded')
  db.execute('UPDATE control_play_purchases SET order_id=?,expires_at=?,state=?,last_check=? WHERE token_hash=?',(order_id,end,('test:' if not real else '')+state,time.time(),digest))
  current=db.execute('SELECT * FROM control_memberships WHERE user_id=?',(uid,)).fetchone()
  blocked=bool(current and (current['source']=='admin_block' or current['source']=='admin' and current['expires_at']>time.time()))
  applied=real and active and not blocked
  if applied:store.grant(db,uid,pid,1,'google_play',digest,expiry=end)
  elif real and not active and current and current['source']=='google_play' and current['reference']==digest:db.execute('UPDATE control_memberships SET expires_at=?,updated_at=? WHERE user_id=?',(min(time.time(),end),core.now(),uid))
  store.audit(db,uid,'google_play.verified',order_id,{'product_id':product_id,'state':state,'test':not real,'expires_at':end})
 return {'state':state,'expires_at':end,'membership_activated':applied,'managed_override':blocked,'test':not real}

def notification(authorization,payload):
 import jwt
 with core.connection() as db:_,profile=gateway_profile(db,'google_play')
 cfg=json.loads(profile['public_json']);aud=cfg.get('push_audience');email=cfg.get('push_email')
 if not aud or not email or not authorization.startswith('Bearer '):raise HTTPException(401,'Configure authenticated Google Pub/Sub push')
 try:
  signed=authorization[7:];head=jwt.get_unverified_header(signed)
  keys=api.request('GET','https://www.googleapis.com/oauth2/v3/certs')['keys'];key=next(k for k in keys if k.get('kid')==head.get('kid'))
  claims=jwt.decode(signed,jwt.PyJWK.from_dict(key).key,algorithms=['RS256'],audience=aud,issuer=['https://accounts.google.com','accounts.google.com'])
  if claims.get('email')!=email or claims.get('email_verified') is not True:raise ValueError()
 except Exception:raise HTTPException(401,'Google push identity could not be verified') from None
 try:
  encoded=payload['message']['data']
  if len(encoded)>48000:raise ValueError()
  body=json.loads(base64.b64decode(encoded,validate=True));assert body['packageName']==cfg['package_name']
  item=body.get('subscriptionNotification',{});purchase=item.get('purchaseToken')
  if not purchase:return {'ok':True}
  digest=hashlib.sha256(purchase.encode()).hexdigest()
 except Exception:raise HTTPException(422,'Invalid Google notification') from None
 with core.connection() as db:r=db.execute('SELECT * FROM control_play_purchases WHERE token_hash=?',(digest,)).fetchone()
 if r:
  try:verify(r['user_id'],read(r['token_ref']),r['product_id'],refresh=True)
  except HTTPException as e:
   if e.status_code!=429:raise
 return {'ok':True}

def refresh_due(limit=3):
 with core.connection() as db:
  rows=[dict(r) for r in db.execute('SELECT * FROM control_play_purchases WHERE last_check<? AND expires_at>? ORDER BY last_check LIMIT ?',(time.time()-300,time.time()-86400*60,limit))]
 for r in rows:
  try:verify(r['user_id'],read(r['token_ref']),r['product_id'],refresh=True)
  except Exception:
   with core.connection() as db:db.execute('UPDATE control_play_purchases SET last_check=? WHERE token_hash=?',(time.time(),r['token_hash']))
