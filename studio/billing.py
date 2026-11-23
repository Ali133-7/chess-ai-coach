"""Server-priced orders, bounded discounts and verified, idempotent settlement."""
import json,time,uuid,secrets,hashlib,hmac,os
from urllib.parse import urlsplit
from fastapi import HTTPException
from . import core,control_store as store,payment_providers as transport

def gateway_profile(db,name,version=None):
 g=db.execute('SELECT * FROM control_gateways WHERE name=?',(name,)).fetchone()
 if not g:raise HTTPException(404,'Unknown gateway')
 r=db.execute('SELECT * FROM control_gateway_versions WHERE id=?',(version or g['version_id'],)).fetchone()
 if not r:raise HTTPException(503,'Payment gateway is not configured')
 if r['name']!=name:raise HTTPException(409,'Gateway profile mismatch')
 return dict(g),dict(r)

def gateways_public(db):
 result=[]
 for g in db.execute('SELECT * FROM control_gateways ORDER BY name'):
  r=db.execute('SELECT * FROM control_gateway_versions WHERE id=?',(g['version_id'],)).fetchone();ready=False
  if r:
   p=json.loads(r['public_json']);p['_environment']=r['environment'];ready=transport.ready(g['name'],p,json.loads(r['secrets_json']))
  result.append({'name':g['name'],'enabled':bool(g['enabled']),'environment':g['environment'],'ready':ready})
 return result

def public_order(row):
 x=dict(row);return {k:x[k] for k in ('id','plan_id','plan_title','days','original_amount','amount','currency','discount_code','gateway','status','created_at','expires_at','paid_at')}|{'checkout':json.loads(x['checkout_json'] or '{}')}

def checkout(uid,data):
 origin=os.getenv('STUDIO_BASE_URL','').rstrip('/');u=urlsplit(origin)
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.path:raise HTTPException(503,'Configure a public HTTPS STUDIO_BASE_URL before accepting payments')
 callback=secrets.token_urlsafe(32);oid=str(uuid.uuid4());now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  old=db.execute('SELECT * FROM control_orders WHERE user_id=? AND request_key=?',(uid,data.request_key)).fetchone()
  if old:return public_order(old)
  if db.execute('SELECT count(*) FROM control_orders WHERE user_id=? AND created_at>?',(uid,now-900)).fetchone()[0]>=5:raise HTTPException(429,'Too many checkout attempts; try later')
  p=db.execute('SELECT * FROM control_plans WHERE id=? AND enabled=1',(data.plan_id,)).fetchone()
  if not p or p['id']=='free' or p['price_iqd']<=0:raise HTTPException(422,'Select an enabled paid plan')
  g,profile=gateway_profile(db,data.gateway)
  if not g['enabled']:raise HTTPException(503,'Gateway is disabled')
  if db.execute("SELECT 1 FROM control_memberships WHERE user_id=? AND source='admin_block'",(uid,)).fetchone():raise HTTPException(403,'Contact administration before purchasing a new membership')
  amount=p['price_iqd'];code=data.discount_code.strip().upper() or None
  if code:
   d=db.execute('SELECT * FROM control_discounts WHERE code=?',(code,)).fetchone()
   if not d or not d['enabled'] or not d['starts_at']<=now<d['ends_at'] or d['plan_id'] and d['plan_id']!=p['id']:raise HTTPException(422,'Discount is unavailable for this plan')
   # A late merchant settlement must not make an expired reservation reusable.
   # Release a reservation only after an authoritative failed/refunded response.
   sql="SELECT count(*) FROM control_orders WHERE discount_code=? AND status IN ('paid','test_paid','creating','pending')"
   if db.execute(sql,(code,)).fetchone()[0]>=d['max_uses'] or db.execute(sql+' AND user_id=?',(code,uid)).fetchone()[0]>=d['per_user']:raise HTTPException(409,'Discount usage limit reached')
   amount=max(0,amount-(amount*d['value']//100 if d['kind']=='percent' else d['value']))
  db.execute('INSERT INTO control_orders(id,user_id,plan_id,plan_title,days,original_amount,amount,discount_code,gateway,gateway_version,status,callback_hash,request_key,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,uid,p['id'],p['title_ar'],p['days'],p['price_iqd'],amount,code,data.gateway,profile['id'],'creating',hashlib.sha256(callback.encode()).hexdigest(),data.request_key,now,now+900))
  row=dict(db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone())
 try:
  if amount==0:
   with core.connection() as db:
    db.execute('BEGIN IMMEDIATE');state='paid' if profile['environment']=='live' else 'test_paid'
    db.execute('UPDATE control_orders SET status=?,paid_at=? WHERE id=?',(state,time.time(),oid))
    if state=='paid':store.grant(db,uid,p['id'],p['days'],'discount',oid)
    store.audit(db,uid,'checkout.zero',oid,{'state':state,'discount':code})
    return public_order(db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone())
  pid,info=transport.create(profile,row,origin+'/api/billing/callback/'+data.gateway+'/'+oid+'/'+callback,origin+'/?billing_order='+oid)
  with core.connection() as db:
   db.execute("UPDATE control_orders SET status='pending',provider_id=?,checkout_json=? WHERE id=? AND status='creating'",(pid,json.dumps(info),oid))
   return public_order(db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone())
 except Exception:
  with core.connection() as db:db.execute("UPDATE control_orders SET status='failed' WHERE id=? AND status='creating'",(oid,))
  raise

def reconcile(oid,uid=None,*,callback=None,gateway=None,actor=None):
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone()
  if not r or uid is not None and r['user_id']!=uid:raise HTTPException(404,'Order not found')
  if callback is not None and (gateway!=r['gateway'] or not hmac.compare_digest(hashlib.sha256(callback.encode()).hexdigest(),r['callback_hash'])):raise HTTPException(404,'Callback not found')
  if r['status'] in ('refunded','failed') or r['status'] in ('paid','test_paid') and actor is None and callback is None:return public_order(r)
  if r['status'] not in ('pending','paid','test_paid') or not r['provider_id']:return public_order(r)
  if r['last_check']>time.time()-10:raise HTTPException(429,'Payment verification already in progress; try again shortly')
  db.execute('UPDATE control_orders SET last_check=? WHERE id=?',(time.time(),oid));row=dict(r);_,profile=gateway_profile(db,r['gateway'],r['gateway_version'])
 state=transport.inquire(profile,row)
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');current=db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone()
  if current['status'] in ('paid','test_paid'):
   if state=='refunded':
    db.execute("UPDATE control_orders SET status='refunded' WHERE id=?",(oid,))
    db.execute("UPDATE control_memberships SET expires_at=?,updated_at=? WHERE user_id=? AND reference=? AND source='payment'",(time.time(),core.now(),row['user_id'],oid))
    store.audit(db,actor or row['user_id'],'payment.refund_verified',oid)
   return public_order(db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone())
  if current['status'] not in ('pending','creating'):return public_order(current)
  if state=='paid':
   state='test_paid' if profile['environment']=='sandbox' else 'paid'
   hold=db.execute("SELECT 1 FROM control_memberships WHERE user_id=? AND source='admin_block'",(row['user_id'],)).fetchone()
   if state=='paid' and not hold:store.grant(db,row['user_id'],row['plan_id'],row['days'],'payment',oid)
   db.execute('UPDATE control_orders SET status=?,paid_at=? WHERE id=?',(state,time.time(),oid))
   store.audit(db,actor or row['user_id'],'payment.verified',oid,{'state':state,'gateway':row['gateway'],'amount':row['amount']})
  elif state in ('failed','refunded'):db.execute('UPDATE control_orders SET status=? WHERE id=?',(state,oid))
  return public_order(db.execute('SELECT * FROM control_orders WHERE id=?',(oid,)).fetchone())
