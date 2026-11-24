import base64,json,time,unittest,concurrent.futures,os
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from studio import core,account_security as accounts,control_secrets,mailer
from studio.app import app
import test_play_groq as common

PASSWORD='test-training-pass-12345'
class AccountTests(unittest.TestCase):
 setUp=common.PlayTests.setUp
 tearDown=common.PlayTests.tearDown
 post=common.PlayTests.post
 def enroll(self):
  r=self.post('/api/account/mfa/enroll',{'password':PASSWORD});self.assertEqual(r.status_code,200,r.text)
  secret=r.json()['secret'];code=accounts.totp(secret,int(time.time()//30))
  confirmed=self.post('/api/account/mfa/confirm',{'code':code});self.assertEqual(confirmed.status_code,200,confirmed.text)
  return secret,code,confirmed.json()['recovery_codes']
 def email_token(self,purpose):
  with patch.object(mailer,'configured',return_value=True),patch.object(mailer,'public_base',return_value='https://studio.example.test'):
   if purpose=='reset':response=self.clients[0].post('/api/auth/recovery/request',json={'email':'play0@example.net'})
   else:response=self.post('/api/account/email/request',{})
  self.assertEqual(response.status_code,202,response.text)
  with core.connection() as db:r=db.execute('SELECT private_ref FROM account_mail_outbox WHERE user_id=? AND purpose=? ORDER BY created_at DESC',(self.uids[0],purpose)).fetchone()
  message=json.loads(control_secrets.read(r[0]));return message['url'].split('=',1)[1]
 def test_rfc6238_vector_window_and_replay(self):
  secret=base64.b32encode(b'12345678901234567890').decode()
  self.assertEqual(accounts.totp(secret,1,8),'94287082')
  code=accounts.totp(secret,100);self.assertEqual(accounts.match_counter(secret,code,at=3000),100)
  self.assertIsNone(accounts.match_counter(secret,code,last=100,at=3000))
  self.assertIsNone(accounts.match_counter(secret,'1234567',at=3000))
 def test_mfa_challenge_does_not_issue_session_before_factor(self):
  _,code,codes=self.enroll();client=TestClient(app)
  r=client.post('/api/auth/login',json={'email':'play0@example.net','password':PASSWORD});self.assertTrue(r.json()['mfa_required']);self.assertNotIn('studio_session',client.cookies)
  challenge=r.json()['challenge'];bad=client.post('/api/auth/mfa/complete',json={'challenge':challenge,'code':code});self.assertEqual(bad.status_code,401)
  good=client.post('/api/auth/mfa/complete',json={'challenge':challenge,'code':codes[0]});self.assertEqual(good.status_code,200,good.text);self.assertEqual(client.get('/api/me').status_code,200)
  self.assertEqual(client.post('/api/auth/mfa/complete',json={'challenge':challenge,'code':codes[1]}).status_code,401)
 def test_concurrent_second_factor_consumption_accepts_once(self):
  _,_,codes=self.enroll();client=TestClient(app);challenge=client.post('/api/auth/login',json={'email':'play0@example.net','password':PASSWORD}).json()['challenge']
  def submit(_):return TestClient(app).post('/api/auth/mfa/complete',json={'challenge':challenge,'code':codes[0]}).status_code
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(submit,range(2)))
  self.assertEqual(sorted(statuses),[200,401])
 def test_recovery_code_single_use_and_attempt_limit(self):
  _,_,codes=self.enroll();client=TestClient(app)
  challenge=client.post('/api/auth/login',json={'email':'play0@example.net','password':PASSWORD}).json()['challenge']
  for _ in range(5):self.assertEqual(client.post('/api/auth/mfa/complete',json={'challenge':challenge,'code':'badbad'}).status_code,401)
  self.assertEqual(client.post('/api/auth/mfa/complete',json={'challenge':challenge,'code':codes[0]}).status_code,401)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');self.assertTrue(accounts.consume_factor(db,self.uids[0],codes[0]));self.assertFalse(accounts.consume_factor(db,self.uids[0],codes[0]))
 def test_mfa_confirmation_revokes_other_sessions_and_guards_legacy(self):
  other=TestClient(app);self.assertEqual(other.post('/api/auth/login',json={'email':'play0@example.net','password':PASSWORD}).status_code,200)
  with core.connection() as db:db.execute('DELETE FROM account_session_info WHERE token_hash=?',(accounts.digest(self.clients[0].cookies.get('studio_session')),))
  self.enroll();self.assertEqual(other.get('/api/me').status_code,401);self.assertEqual(self.clients[0].get('/api/me').status_code,200)
 def test_disable_requires_password_and_fresh_factor(self):
  _,code,codes=self.enroll()
  self.assertEqual(self.post('/api/account/mfa/disable',{'password':PASSWORD,'code':code}).status_code,403)
  self.assertEqual(self.post('/api/account/mfa/disable',{'password':PASSWORD,'code':codes[0]}).status_code,200)
  self.assertFalse(self.clients[0].get('/api/account/security').json()['mfa_enabled'])
 def test_recovery_codes_rotate_only_with_both_factors(self):
  _,_,codes=self.enroll();r=self.post('/api/account/mfa/recovery-codes',{'password':PASSWORD,'code':codes[0]});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(len(r.json()['recovery_codes']),10)
  with core.connection() as db:
   self.assertFalse(accounts.consume_factor(db,self.uids[0],codes[1]));self.assertTrue(accounts.consume_factor(db,self.uids[0],r.json()['recovery_codes'][0]))
 def test_password_recovery_single_use_revokes_sessions_keeps_mfa(self):
  self.enroll();token=self.email_token('reset');client=TestClient(app)
  body={'token':token,'password':'a-new-private-password-12345'}
  r=client.post('/api/auth/recovery/complete',json=body);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.clients[0].get('/api/me').status_code,401);self.assertEqual(client.post('/api/auth/recovery/complete',json=body).status_code,400)
  result=client.post('/api/auth/login',json={'email':'play0@example.net','password':body['password']});self.assertTrue(result.json()['mfa_required'])
 def test_verification_proves_email_only_and_no_plain_tokens_in_database(self):
  token=self.email_token('verify')
  with core.connection() as db:
   row=db.execute('SELECT * FROM account_email_tokens').fetchone();self.assertNotIn(token,str(tuple(row)))
  self.assertEqual(TestClient(app).post('/api/auth/email/confirm',json={'token':token}).status_code,200)
  state=self.clients[0].get('/api/account/security').json();self.assertTrue(state['email_verified']);self.assertFalse(state['chess_ownership_verified'])
  self.assertEqual(TestClient(app).post('/api/auth/email/confirm',json={'token':token}).status_code,400)
 def test_expired_or_password_changed_link_is_rejected(self):
  token=self.email_token('reset')
  with core.connection() as db:db.execute('UPDATE account_email_tokens SET expires_at=0')
  self.assertEqual(TestClient(app).post('/api/auth/recovery/complete',json={'token':token,'password':'another-password-123456'}).status_code,400)
 def test_generic_recovery_and_unconfigured_delivery(self):
  with patch.object(mailer,'configured',return_value=False):
   a=TestClient(app).post('/api/auth/recovery/request',json={'email':'play0@example.net'});b=TestClient(app).post('/api/auth/recovery/request',json={'email':'nobody@example.net'})
  self.assertEqual(a.status_code,202);self.assertEqual(a.json(),b.json())
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM account_mail_outbox').fetchone()[0],0)
 def test_sessions_owner_scoped_csrf_and_revocation(self):
  other=TestClient(app);other.post('/api/auth/login',json={'email':'play0@example.net','password':PASSWORD})
  rows=self.clients[0].get('/api/account/sessions').json()['items'];self.assertEqual(len(rows),2);sid=next(x['id'] for x in rows if not x['current'])
  self.assertEqual(self.clients[1].delete('/api/account/sessions/'+sid,headers=self.headers[1]).status_code,404)
  self.assertEqual(self.clients[0].delete('/api/account/sessions/'+sid).status_code,403)
  self.assertEqual(self.clients[0].delete('/api/account/sessions/'+sid,headers=self.headers[0]).status_code,200);self.assertEqual(other.get('/api/me').status_code,401)
 def test_optional_admin_mfa_policy_allows_enrollment(self):
  with core.connection() as db:db.execute("UPDATE users SET role='admin' WHERE id=?",(self.uids[0],))
  with patch.dict('os.environ',{'STUDIO_REQUIRE_ADMIN_MFA':'true'}):
   self.assertEqual(self.clients[0].get('/api/admin/overview').status_code,403);self.enroll();self.assertEqual(self.clients[0].get('/api/admin/overview').status_code,200)
 def test_outbox_delivery_failure_is_sanitized_and_retryable(self):
  self.email_token('verify')
  with patch.object(mailer,'configured',return_value=True),patch.object(mailer,'deliver',side_effect=RuntimeError('SECRET SMTP RESPONSE')):self.assertTrue(mailer.job())
  with core.connection() as db:
   row=dict(db.execute('SELECT * FROM account_mail_outbox').fetchone());self.assertEqual(row['status'],'pending');self.assertEqual(row['last_error'],'delivery_failed');self.assertNotIn('SECRET',json.dumps(row))
 def test_expired_mail_worker_cannot_delete_new_owners_payload(self):
  self.email_token('verify')
  def delayed_delivery(message):
   with core.connection() as db:db.execute("UPDATE account_mail_outbox SET token='new-owner'")
  with patch.object(mailer,'configured',return_value=True),patch.object(mailer,'deliver',side_effect=delayed_delivery):self.assertTrue(mailer.job())
  with core.connection() as db:row=db.execute('SELECT private_ref,token,status FROM account_mail_outbox').fetchone()
  self.assertEqual(row['token'],'new-owner');self.assertEqual(row['status'],'sending');self.assertTrue((control_secrets.root()/row['private_ref']).is_file())
 def test_smtp_requires_https_links_and_upgrades_tls_before_authentication(self):
  secret=Path(self.temp.name)/'smtp-password';secret.write_text('private-smtp-fixture-password');secret.chmod(0o600)
  env={'STUDIO_BASE_URL':'https://studio.example.test','STUDIO_SMTP_HOST':'mail.example.test','STUDIO_SMTP_FROM':'coach@example.test','STUDIO_SMTP_USERNAME':'smtp-user','STUDIO_SMTP_PASSWORD_FILE':str(secret),'STUDIO_SMTP_MODE':'starttls'}
  with patch.dict(os.environ,env),patch.object(mailer.smtplib,'SMTP') as smtp:
   self.assertTrue(mailer.configured());mailer.deliver({'to':'student@example.test','purpose':'verify','url':'https://studio.example.test/#account-verify=fixture'})
   smtp.return_value.starttls.assert_called_once();smtp.return_value.login.assert_called_once();smtp.return_value.send_message.assert_called_once()
  with patch.dict(os.environ,{**env,'STUDIO_BASE_URL':'http://unsafe.example.test'}):self.assertFalse(mailer.configured())

if __name__=='__main__':unittest.main()
