import concurrent.futures,logging,unittest
from fastapi import HTTPException
from studio import core
from studio.app import ratelimit
from studio.security import SafeAccessLog
import test_control_center as common

class SecurityTests(unittest.TestCase):
 setUp=common.ControlTests.setUp
 tearDown=common.ControlTests.tearDown
 put=common.ControlTests.put
 post=common.ControlTests.post
 def test_auth_validation_never_echoes_password(self):
  secret='SECRET-INVALID-PASSWORD-'*10
  r=self.clients[0].post('/api/auth/login',json={'email':'x@example.net','password':secret})
  self.assertEqual(r.status_code,422);self.assertNotIn(secret,r.text)
 def test_oversized_stream_and_content_length_rejected(self):
  r=self.clients[0].post('/api/auth/login',content=b'x'*(2*1024*1024+20000));self.assertEqual(r.status_code,413)
  def stream():yield b'x'*(2*1024*1024+20000)
  self.assertEqual(self.clients[0].post('/api/auth/login',content=stream()).status_code,413)
 def test_admin_cannot_delete_own_administration(self):
  self.assertEqual(self.clients[0].delete('/api/account',headers=self.headers[0]).status_code,409)
  self.assertEqual(self.clients[0].get('/api/me').status_code,200)
 def test_free_membership_deletion_is_atomic_and_complete(self):
  with core.connection() as db:db.execute("INSERT INTO control_memberships VALUES(?,'free',0,99999999999,'admin','test','now')",(self.uids[1],))
  self.assertEqual(self.clients[1].delete('/api/account',headers=self.headers[1]).status_code,200)
  self.assertEqual(self.clients[1].get('/api/me').status_code,401)
 def test_atomic_limit_under_concurrency(self):
  def attempt(i):
   try:ratelimit('concurrent-review',3,60);return True
   except HTTPException:return False
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:accepted=list(pool.map(attempt,range(12)))
  self.assertEqual(sum(accepted),3)
 def test_old_course_endpoint_respects_curriculum_feature(self):
  free=self.clients[0].get('/api/control/plans').json()['items'][0];free.pop('updated_at');free['features']['curriculum']=False
  self.assertEqual(self.put('/api/control/plans/free',free).status_code,200)
  self.assertEqual(self.clients[1].get('/api/course').status_code,403)
 def test_access_logs_redact_capabilities_and_query(self):
  for path in ('/?token=SECRET','/api/billing/callback/fib/order/SECRET'):
   record=logging.LogRecord('uvicorn.access',20,'',1,'%s - "%s %s HTTP/%s" %d',('client','GET',path,'1.1',200),None)
   SafeAccessLog().filter(record);self.assertNotIn('SECRET',record.getMessage())
 def test_cross_origin_write_is_blocked(self):
  r=self.clients[1].post('/api/auth/logout',headers=self.headers[1]|{'Origin':'https://evil.example'})
  self.assertEqual(r.status_code,403)
 def test_untrusted_host_header_is_rejected(self):
  self.assertEqual(self.clients[0].get('/health',headers={'Host':'attacker.example'}).status_code,400)

if __name__=='__main__':unittest.main()
