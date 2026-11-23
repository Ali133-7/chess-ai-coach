"""Control plane security and settlement tests. No merchant calls or real credentials."""
import json, os, time, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from studio import core, control_store as store, billing, payment_providers as pay, google_play
from studio.teacher_v7 import providers
import test_play_groq as common

class ControlTests(unittest.TestCase):
 def setUp(self):
  common.PlayTests.setUp(self)
  self.env=patch.dict(os.environ,{'CONTROL_PRIVATE_DIR':str(Path(self.temp.name)/'private'),'STUDIO_BASE_URL':'https://studio.example.net'})
  self.env.start();self.addCleanup(self.env.stop)
  self.config=patch.object(providers,'CONFIG_FILE',Path(self.temp.name)/'providers.json');self.config.start();self.addCleanup(self.config.stop)
  with core.connection() as db:db.execute("UPDATE users SET role='admin' WHERE id=?",(self.uids[0],))
 tearDown=common.PlayTests.tearDown
 post=common.PlayTests.post
 def put(self,path,body,who=0):return self.clients[who].put(path,json=body,headers=self.headers[who])
 def plan(self):
  body={'id':'pro','title_ar':'احتراف','title_en':'Pro','price_iqd':10000,'days':30,'enabled':True,'features':{k:True for k in store.FEATURES},'limits':dict(store.LIMITS),'version':0}
  r=self.put('/api/control/plans/pro',body);self.assertEqual(r.status_code,200,r.text);return body
 def gateway(self,environment='sandbox'):
  r=self.put('/api/control/gateways/zaincash',{'confirm_password':'test-training-pass-12345','enabled':True,'environment':environment,'public':{'client_id':'test-client','api_base':'https://pg-api-uat.zaincash.iq' if environment=='sandbox' else 'https://merchant.zaincash.iq'},'secrets':{'client_secret':'synthetic-merchant-secret','api_key':'synthetic-signing-secret'}})
  self.assertEqual(r.status_code,200,r.text)
 def order(self,key='request-key-000001',who=1,code=''):
  with patch.object(pay,'create',return_value=('transaction_12345',{'redirect_url':'https://pay.zaincash.iq/test'})):
   return self.post('/api/billing/checkout',{'plan_id':'pro','gateway':'zaincash','discount_code':code,'request_key':key},who)
 def test_auth_csrf_and_sensitive_validation_redaction(self):
  self.assertEqual(self.clients[1].get('/api/control/overview').status_code,403)
  self.assertEqual(self.clients[0].put('/api/control/providers',json={}).status_code,403)
  marker='NEVER-ECHO-THIS-SECRET'
  r=self.put('/api/control/providers',{'primary':'invalid','models':{},'keys':{'bad':marker},'confirm_password':marker})
  self.assertEqual(r.status_code,422);self.assertNotIn(marker,r.text)
  self.assertEqual(self.put('/api/control/gateways/fib',{'confirm_password':'incorrect','enabled':False,'public':{},'secrets':{}}).status_code,403)
 def test_migration_preserves_users_and_free_compatibility(self):
  core.setup();core.setup()
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],2)
  ent=self.clients[1].get('/api/billing/me').json()
  self.assertEqual(ent['plan']['id'],'free');self.assertTrue(ent['plan']['features']['knowledge'])
  self.assertTrue(all(not g['enabled'] for g in self.clients[0].get('/api/control/gateways').json()['items']))
 def test_plan_versions_feature_gates_expiry_and_manual_hold(self):
  p=self.plan();self.assertEqual(self.put('/api/control/plans/pro',p).status_code,409)
  p['version']=1;p['features']['play']=False
  self.assertEqual(self.put('/api/control/plans/pro',p).status_code,200)
  r=self.put(f'/api/control/users/{self.uids[1]}/membership',{'plan_id':'pro','days':30,'reason':'manual test'})
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.clients[1].get('/api/play/current').status_code,403)
  with core.connection() as db:db.execute('UPDATE control_memberships SET expires_at=0 WHERE user_id=?',(self.uids[1],))
  self.assertEqual(self.clients[1].get('/api/play/current').status_code,200)
  r=self.clients[0].delete(f'/api/control/users/{self.uids[1]}/membership?reason=manual-stop',headers=self.headers[0])
  self.assertEqual(r.status_code,200);self.assertTrue(self.clients[1].get('/api/billing/me').json()['manual_hold'])
 def test_last_admin_and_revoke_user_sessions(self):
  change={'confirm_password':'test-training-pass-12345','role':'user','disabled':True,'reason':'test disable'}
  self.assertEqual(self.put(f'/api/control/users/{self.uids[0]}',change).status_code,409)
  self.assertEqual(self.put(f'/api/control/users/{self.uids[1]}',change).status_code,200)
  self.assertEqual(self.clients[1].get('/api/me').status_code,401)
 def test_keys_write_only_rotation_and_domain_validation(self):
  self.gateway()
  for path in ('/api/control/gateways','/api/control/audit','/api/billing/catalog'):
   result=self.clients[0].get(path).text
   self.assertNotIn('synthetic-merchant-secret',result);self.assertNotIn('synthetic-signing-secret',result)
  r=self.put('/api/control/gateways/zaincash',{'confirm_password':'test-training-pass-12345','public':{'api_base':'https://evil.example','client_id':'x'},'secrets':{}})
  self.assertEqual(r.status_code,422)
  with core.connection() as db:
   _,profile=billing.gateway_profile(db,'zaincash');refs=json.loads(profile['secrets_json'])
  from studio.control_secrets import read
  self.assertEqual(read(refs['client_secret']),'synthetic-merchant-secret')
 def test_sandbox_idempotency_ownership_and_no_paid_access(self):
  self.plan();self.gateway();r=self.order();self.assertEqual(r.status_code,200,r.text);oid=r.json()['id']
  self.assertEqual(self.order().json()['id'],oid)
  self.assertEqual(self.post('/api/billing/orders/'+oid+'/verify',{},0).status_code,404)
  with patch.object(pay,'inquire',return_value='paid') as inquiry:
   r=self.post('/api/billing/orders/'+oid+'/verify',{},1);self.assertEqual(r.json()['status'],'test_paid')
   self.post('/api/billing/orders/'+oid+'/verify',{},1);self.assertEqual(inquiry.call_count,1)
  self.assertEqual(self.clients[1].get('/api/billing/me').json()['plan']['id'],'free')
 def test_live_settlement_exactly_once_and_verified_refund(self):
  self.plan();self.gateway('live');oid=self.order().json()['id']
  with patch.object(pay,'inquire',return_value='paid'):self.post('/api/billing/orders/'+oid+'/verify',{},1)
  first=store.entitlement(self.uids[1]);self.assertEqual(first['plan']['id'],'pro')
  self.post('/api/billing/orders/'+oid+'/verify',{},1)
  self.assertEqual(store.entitlement(self.uids[1])['expires_at'],first['expires_at'])
  with core.connection() as db:db.execute('UPDATE control_orders SET last_check=0 WHERE id=?',(oid,))
  with patch.object(pay,'inquire',return_value='refunded'):
   r=self.post('/api/control/orders/'+oid+'/verify',{});self.assertEqual(r.json()['status'],'refunded')
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_server_prices_discount_reservation_and_reject_injected_price(self):
  self.plan();self.gateway();now=time.time()
  d={'code':'SAVE50','kind':'percent','value':50,'enabled':True,'starts_at':now-10,'ends_at':now+3600,'max_uses':1,'per_user':1}
  r=self.put('/api/control/discounts/SAVE50',d);self.assertEqual(r.status_code,200,r.text)
  r=self.order(code='SAVE50');self.assertEqual(r.json()['amount'],5000)
  self.assertEqual(self.order(key='request-key-000002',code='SAVE50').status_code,409)
  self.assertEqual(self.post('/api/billing/checkout',{'plan_id':'pro','gateway':'zaincash','request_key':'request-key-000003','amount':1},1).status_code,422)
 def test_inquiry_requires_exact_amount_currency_and_reference(self):
  profile={'name':'zaincash','environment':'sandbox','public_json':json.dumps({'api_base':'https://pg-api-uat.zaincash.iq'})}
  order={'id':'order123','provider_id':'transaction_12345','amount':10000}
  good={'transactionId':order['provider_id'],'orderId':order['id'],'status':'SUCCESS','amount':{'value':'10000.00','currency':'IQD'}}
  with patch.object(pay,'token',return_value='test'),patch.object(pay,'request',return_value=good):self.assertEqual(pay.inquire(profile,order),'paid')
  for changed in ({'amount':{'value':1,'currency':'IQD'}},{'orderId':'other'},{'amount':{'value':10000,'currency':'USD'}}):
   with patch.object(pay,'token',return_value='test'),patch.object(pay,'request',return_value=good|changed):
    with self.assertRaises(HTTPException):pay.inquire(profile,order)
 def test_campaign_threshold_dedup_caps_disable_and_ownership(self):
  now=time.time();data={'title_ar':'اختبار','title_en':'Test','placement':'modal','event':'home_visit','after_n':2,'enabled':True,'starts_at':now-1,'ends_at':now+3600}
  r=self.put('/api/control/campaigns/new',data);self.assertEqual(r.status_code,200,r.text);cid=r.json()['id']
  self.assertEqual(self.post('/api/promotions/event',{'event':'home_visit','resource':'visit1'},1).json()['items'],[])
  items=self.post('/api/promotions/event',{'event':'home_visit','resource':'visit2'},1).json()['items'];self.assertEqual(len(items),1);delivery=items[0]['delivery_id']
  self.assertEqual(self.post('/api/promotions/'+delivery+'/click',{},1).status_code,404)
  self.assertTrue(self.post('/api/promotions/'+delivery+'/display',{},1).json()['show'])
  self.assertEqual(self.post('/api/promotions/'+delivery+'/click',{},0).status_code,404)
  self.assertEqual(self.post('/api/promotions/'+delivery+'/click',{},1).status_code,200)
  self.assertEqual(self.post('/api/promotions/event',{'event':'home_visit','resource':'visit3'},1).json()['items'],[])
  data.update(id=cid,version=1,enabled=False);self.assertEqual(self.put('/api/control/campaigns/'+cid,data).status_code,200)
  self.assertFalse(self.post('/api/promotions/'+delivery+'/display',{},1).json()['show'])
 def test_campaign_rejects_script_links_and_html_upload(self):
  now=time.time();body={'title_ar':'a','title_en':'b','starts_at':now,'ends_at':now+100,'link_url':'javascript:alert(1)'}
  self.assertEqual(self.put('/api/control/campaigns/new',body).status_code,422)
  self.assertEqual(self.clients[0].post('/api/control/media',content=b'<svg onload="bad"/>',headers=self.headers[0]).status_code,422)
 def test_settings_ai_pause_and_maintenance_preserve_admin_access(self):
  data=self.clients[0].get('/api/control/settings').json();data.update(ai_enabled=False,maintenance=True)
  self.assertEqual(self.put('/api/control/settings',data).status_code,200)
  self.assertFalse(store.global_ai_enabled())
  self.assertEqual(self.clients[1].get('/api/play/current').status_code,503)
  self.assertEqual(self.clients[0].get('/api/control/settings').status_code,200)
  self.assertEqual(self.clients[1].get('/api/me').status_code,200)
 def test_zain_signed_webhook_requeries_and_rejects_forgery(self):
  import jwt
  self.plan();self.gateway('live');oid=self.order().json()['id']
  claims={'transactionId':'transaction_12345','orderId':oid,'status':'SUCCESS','exp':int(time.time())+60}
  endpoint='/api/billing/zaincash/webhook'
  signed=jwt.encode(claims,'synthetic-signing-secret',algorithm='HS256')
  forged=jwt.encode(claims,'incorrect-key',algorithm='HS256')
  self.assertEqual(self.clients[1].post(endpoint,json={'webhook_token':forged}).status_code,401)
  with patch.object(pay,'inquire',return_value='pending'):
   r=self.clients[1].post(endpoint,json={'webhook_token':signed});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_pending_settlement_does_not_undo_admin_hold(self):
  self.plan();self.gateway('live');oid=self.order().json()['id']
  with core.connection() as db:store.grant(db,self.uids[1],'free',1,'admin_block','manual',expiry=time.time())
  with patch.object(pay,'inquire',return_value='paid'):self.post('/api/billing/orders/'+oid+'/verify',{},1)
  self.assertTrue(store.entitlement(self.uids[1])['manual_hold']);self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_fib_inquiry_checks_transaction_and_amount(self):
  profile={'name':'fib','environment':'sandbox','public_json':json.dumps({'api_base':'https://fib.stage.fib.iq'})}
  order={'provider_id':'transaction_12345','amount':10000}
  good={'paymentId':order['provider_id'],'status':'PAID','amount':{'amount':10000,'currency':'IQD'}}
  with patch.object(pay,'token',return_value='test'),patch.object(pay,'request',return_value=good):self.assertEqual(pay.inquire(profile,order),'paid')
  with patch.object(pay,'token',return_value='test'),patch.object(pay,'request',return_value=good|{'paymentId':'wrong'}):
   with self.assertRaises(HTTPException):pay.inquire(profile,order)
 def test_test_endpoints_cannot_be_labeled_live(self):
  for name,url in (('zaincash','https://pg-api-uat.zaincash.iq'),('fib','https://fib.stage.fib.iq')):
   with self.assertRaises(HTTPException):pay.validate(name,'live',{'api_base':url,'client_id':'test'},{})

if __name__=='__main__':unittest.main()
