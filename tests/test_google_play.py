"""Synthetic Google responses only; private RSA keys generated at runtime."""
import base64,json,time,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi import HTTPException
from studio import core,google_play as play,payment_providers as pay,control_store as store
from studio.control_secrets import put
import test_control_center as common_control

class GoogleTests(unittest.TestCase):
 setUp=common_control.ControlTests.setUp
 tearDown=common_control.ControlTests.tearDown
 put=common_control.ControlTests.put
 plan=common_control.ControlTests.plan
 post=common_control.ControlTests.post
 def profile(self,env='live'):
  self.plan()
  ref=put('google-test','synthetic-service-account')
  with core.connection() as db:
   p={'package_name':'net.example.chess','products':{'pro.monthly':'pro'},'allow_test_purchases':True,'push_audience':'https://studio.example.net/push','push_email':'push@example.iam.gserviceaccount.com'}
   db.execute('INSERT INTO control_gateway_versions VALUES(?,?,?,?,?,?)',('google-test','google_play',env,json.dumps(p),json.dumps({'service_account':ref}),core.now()))
   db.execute("UPDATE control_gateways SET enabled=1,version_id='google-test',environment=? WHERE name='google_play'",(env,))
 def response(self,uid=None,**changes):
  uid=uid or self.uids[1]
  return {'subscriptionState':'SUBSCRIPTION_STATE_ACTIVE','acknowledgementState':'ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED','latestOrderId':'GPA.synthetic.001','externalAccountIdentifiers':{'obfuscatedExternalAccountId':play.account_id(uid)},'lineItems':[{'productId':'pro.monthly','expiryTime':datetime.fromtimestamp(time.time()+86400,timezone.utc).isoformat()}]}|changes
 def verify(self,response,token='synthetic-purchase-token',uid=None):
  with patch.object(pay,'token',return_value='synthetic-oauth'),patch.object(pay,'request',return_value=response):
   return play.verify(uid or self.uids[1],token,'pro.monthly')
 def test_verified_binding_active_and_cross_user_replay(self):
  self.profile();r=self.verify(self.response());self.assertTrue(r['membership_activated'])
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'pro')
  with self.assertRaises(HTTPException) as e:self.verify(self.response(),uid=self.uids[0])
  self.assertEqual(e.exception.status_code,409)
  with core.connection() as db:
   row=dict(db.execute('SELECT * FROM control_play_purchases').fetchone());self.assertNotIn('synthetic-purchase-token',json.dumps(row))
 def test_concurrent_account_binding_is_stable(self):
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=8) as pool:values=list(pool.map(play.account_id,[self.uids[1]]*24))
  self.assertEqual(len(set(values)),1);self.assertEqual(len(values[0]),64)
 def test_invalid_binding_never_reserves_token(self):
  self.profile()
  with self.assertRaises(HTTPException):self.verify(self.response(uid=self.uids[0]))
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM control_play_purchases').fetchone()[0],0)
  self.assertTrue(self.verify(self.response())['membership_activated'])
 def test_test_purchase_never_grants_real_membership(self):
  self.profile();r=self.verify(self.response(testPurchase={}))
  self.assertTrue(r['test']);self.assertFalse(r['membership_activated'])
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_hold_and_expiry_remove_only_matching_google_membership(self):
  self.profile();self.verify(self.response())
  with core.connection() as db:db.execute('UPDATE control_play_purchases SET last_check=0')
  self.verify(self.response(subscriptionState='SUBSCRIPTION_STATE_ON_HOLD'))
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_manual_revocation_survives_google_refresh(self):
  self.profile();self.verify(self.response())
  with core.connection() as db:
   store.grant(db,self.uids[1],'free',1,'admin_block','manual',expiry=time.time());db.execute('UPDATE control_play_purchases SET last_check=0')
  r=self.verify(self.response());self.assertFalse(r['membership_activated']);self.assertTrue(r['managed_override'])
  self.assertEqual(store.entitlement(self.uids[1])['plan']['id'],'free')
 def test_pending_acknowledgement_is_server_side(self):
  self.profile();response=self.response(acknowledgementState='ACKNOWLEDGEMENT_STATE_PENDING');calls=[]
  def request(method,url,**kwargs):calls.append((method,url));return response if method=='GET' else {}
  with patch.object(pay,'token',return_value='test'),patch.object(pay,'request',side_effect=request):play.verify(self.uids[1],'synthetic-purchase-token','pro.monthly')
  self.assertEqual([x[0] for x in calls],['GET','POST']);self.assertTrue(calls[-1][1].endswith(':acknowledge'))
 def test_google_push_validates_signature_audience_and_requeries(self):
  import jwt
  from cryptography.hazmat.primitives.asymmetric import rsa
  self.profile();self.verify(self.response())
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));jwk['kid']='synthetic-kid'
  claims={'iss':'https://accounts.google.com','aud':'https://studio.example.net/push','email':'push@example.iam.gserviceaccount.com','email_verified':True,'exp':int(time.time())+60}
  signed=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'synthetic-kid'})
  data={'packageName':'net.example.chess','subscriptionNotification':{'purchaseToken':'synthetic-purchase-token'}}
  payload={'message':{'data':base64.b64encode(json.dumps(data).encode()).decode()}}
  with patch.object(pay,'request',return_value={'keys':[jwk]}),patch.object(play,'verify',return_value={}) as verify:
   self.assertTrue(play.notification('Bearer '+signed,payload)['ok']);verify.assert_called_once()
  bad=jwt.encode(claims|{'aud':'wrong-audience'},key,algorithm='RS256',headers={'kid':'synthetic-kid'})
  with patch.object(pay,'request',return_value={'keys':[jwk]}):
   with self.assertRaises(HTTPException) as e:play.notification('Bearer '+bad,payload)
   self.assertEqual(e.exception.status_code,401)

if __name__=='__main__':unittest.main()
