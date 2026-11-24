"""Additive account recovery, RFC 6238 TOTP, and individually revocable sessions."""
import base64,hashlib,hmac,json,os,re,secrets,struct,time
from urllib.parse import quote
from .reliability_locale import LocalizedError as HTTPException
from . import core,control_secrets

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS account_security(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,email_verified_at REAL,totp_ref TEXT,pending_ref TEXT,pending_until REAL,enabled_at REAL,last_counter INTEGER NOT NULL DEFAULT -1);
 CREATE TABLE IF NOT EXISTS account_session_info(token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,public_id TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,last_seen_at REAL NOT NULL,mfa_at REAL);
 CREATE TABLE IF NOT EXISTS account_challenges(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,password_version TEXT NOT NULL,totp_ref TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS account_recovery_codes(code_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE);
 CREATE TABLE IF NOT EXISTS account_email_tokens(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,purpose TEXT NOT NULL,expires_at REAL NOT NULL,password_version TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS account_email_owner ON account_email_tokens(user_id,purpose);
 CREATE TABLE IF NOT EXISTS account_mail_outbox(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,purpose TEXT NOT NULL,private_ref TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,available_at REAL NOT NULL,lease_until REAL NOT NULL DEFAULT 0,token TEXT,created_at REAL NOT NULL,last_error TEXT);
 CREATE INDEX IF NOT EXISTS account_mail_queue ON account_mail_outbox(status,available_at,lease_until);
 ''')

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def security(db,uid):
 row=db.execute('SELECT * FROM account_security WHERE user_id=?',(uid,)).fetchone()
 if row:return row
 db.execute('INSERT OR IGNORE INTO account_security(user_id) VALUES(?)',(uid,))
 return db.execute('SELECT * FROM account_security WHERE user_id=?',(uid,)).fetchone()
def record_session(db,token_hash,mfa=False):
 now=time.time();db.execute('INSERT INTO account_session_info VALUES(?,?,?,?,?)',(token_hash,secrets.token_hex(12),now,now,now if mfa else None))
def totp(secret,counter,digits=6):
 key=base64.b32decode(secret,casefold=True);mac=hmac.new(key,struct.pack('>Q',counter),hashlib.sha1).digest();offset=mac[-1]&15
 value=(struct.unpack('>I',mac[offset:offset+4])[0]&0x7fffffff)%10**digits
 return str(value).zfill(digits)
def match_counter(secret,code,last=-1,at=None):
 if not re.fullmatch(r'\d{6}',code):return None
 counter=int((time.time() if at is None else at)//30)
 for c in (counter,counter-1,counter+1):
  if c>=0 and c>last and hmac.compare_digest(totp(secret,c),code):return c
 return None
def consume_factor(db,uid,code):
 state=security(db,uid)
 if not state['totp_ref']:return False
 counter=match_counter(control_secrets.read(state['totp_ref']),code,state['last_counter'])
 if counter is not None:
  db.execute('UPDATE account_security SET last_counter=? WHERE user_id=?',(counter,uid));return True
 normalized=code.replace('-','').lower()
 if not re.fullmatch('[0-9a-f]{24}',normalized):return False
 return db.execute('DELETE FROM account_recovery_codes WHERE user_id=? AND code_hash=?',(uid,digest(normalized))).rowcount==1
def new_codes(db,uid):
 db.execute('DELETE FROM account_recovery_codes WHERE user_id=?',(uid,));codes=[secrets.token_hex(12) for _ in range(10)]
 db.executemany('INSERT INTO account_recovery_codes VALUES(?,?)',[(digest(x),uid) for x in codes])
 return ['-'.join(x[i:i+6] for i in range(0,24,6)) for x in codes]
def remove_totp(ref):
 if ref and re.fullmatch(r'totp-[0-9a-f]{24}',ref):
  p=control_secrets.root()/ref
  if not p.is_symlink():p.unlink(missing_ok=True)
def challenge(user):
 with core.connection() as db:
  state=security(db,user['id'])
  if not state['totp_ref']:return None
  raw=secrets.token_urlsafe(32);now=time.time()
  db.execute('DELETE FROM account_challenges WHERE expires_at<? OR user_id=?',(now,user['id']))
  db.execute('INSERT INTO account_challenges VALUES(?,?,?,0,?,?)',(digest(raw),user['id'],now+300,digest(user['pass_hash']),state['totp_ref']))
 return {'ok':False,'mfa_required':True,'challenge':raw,'expires_in':300}
def session_guard(db,user,token_hash):
 state=security(db,user['id'])
 meta=db.execute('SELECT mfa_at,last_seen_at FROM account_session_info WHERE token_hash=?',(token_hash,)).fetchone()
 if state['totp_ref']:
  if not meta or not meta['mfa_at']:raise HTTPException(401,'Sign in again with your second factor')
 if meta and meta['last_seen_at']<time.time()-300:db.execute('UPDATE account_session_info SET last_seen_at=? WHERE token_hash=?',(time.time(),token_hash))
def sensitive(db,user,password,code=''):
 fresh=db.execute('SELECT u.pass_hash FROM users u JOIN sessions s ON s.user_id=u.id WHERE u.id=? AND s.token_hash=? AND s.expires_at>? AND u.disabled=0',(user['id'],user['_session_hash'],time.time())).fetchone()
 if not fresh or not core.verify(password,fresh['pass_hash']):raise HTTPException(403,'Current password required')
 if security(db,user['id'])['totp_ref'] and not consume_factor(db,user['id'],code):raise HTTPException(403,'A fresh authentication code or recovery code is required')

def queue_email(uid,purpose):
 from . import mailer
 if not mailer.configured():return False
 raw=secrets.token_urlsafe(32);now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE');u=db.execute('SELECT * FROM users WHERE id=? AND disabled=0',(uid,)).fetchone()
  if not u:return False
  if purpose=='verify' and security(db,uid)['email_verified_at']:return False
  url=mailer.public_base()+'/#account-'+('verify' if purpose=='verify' else 'reset')+'='+raw
  ref=control_secrets.put('account-mail',json.dumps({'to':u['email'],'purpose':purpose,'url':url}))
  db.execute('DELETE FROM account_email_tokens WHERE expires_at<?',(now,))
  db.execute('INSERT INTO account_email_tokens VALUES(?,?,?,?,?)',(digest(raw),uid,purpose,now+(3600 if purpose=='verify' else 1800),digest(u['pass_hash'])))
  db.execute('INSERT INTO account_mail_outbox(id,user_id,purpose,private_ref,status,available_at,created_at) VALUES(?,?,?,?,\'pending\',?,?)',(secrets.token_hex(16),uid,purpose,ref,now,now))
 return True

def install(app,auth):
 from fastapi import Depends,Request,Response
 from pydantic import BaseModel,Field,ConfigDict
 class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
 class Email(Strict):email:str=Field(min_length=5,max_length=255)
 class Token(Strict):token:str=Field(min_length=32,max_length=128)
 class Reset(Token):password:str=Field(min_length=12,max_length=128)
 class Password(Strict):password:str=Field(min_length=1,max_length=128)
 class Sensitive(Password):code:str=Field(default='',max_length=32)
 class MFAComplete(Strict):
  challenge:str=Field(min_length=32,max_length=128)
  code:str=Field(min_length=6,max_length=32)
 class Confirm(Strict):code:str=Field(min_length=6,max_length=6)

 @app.post('/api/auth/recovery/request',status_code=202)
 def request_recovery(data:Email,request:Request):
  from .app import ratelimit
  email=data.email.strip().lower();ip=request.client.host if request.client else 'unknown'
  ratelimit('recovery-ip:'+ip,10,3600);ratelimit('recovery-email:'+digest(email),3,3600)
  with core.connection() as db:r=db.execute('SELECT id FROM users WHERE email=? AND disabled=0',(email,)).fetchone()
  if r:queue_email(r[0],'reset')
  return {'accepted':True,'message':'If the account exists and email delivery is configured, a recovery link will be sent.'}
 @app.post('/api/auth/recovery/complete')
 def reset_password(data:Reset,request:Request):
  from .app import ratelimit
  ratelimit('reset-complete:'+(request.client.host if request.client else 'unknown'),10,900)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE')
   row=db.execute("SELECT t.*,u.pass_hash,u.disabled FROM account_email_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.purpose='reset' AND t.expires_at>?",(digest(data.token),time.time())).fetchone()
   if not row or row['disabled'] or row['password_version']!=digest(row['pass_hash']):raise HTTPException(400,'Invalid or expired link')
   uid=row['user_id'];db.execute('UPDATE users SET pass_hash=? WHERE id=?',(core.passhash(data.password),uid))
   previous=security(db,uid);pending_ref=previous['pending_ref']
   db.execute('UPDATE account_security SET email_verified_at=coalesce(email_verified_at,?),pending_ref=NULL,pending_until=NULL WHERE user_id=?',(time.time(),uid))
   db.execute('DELETE FROM sessions WHERE user_id=?',(uid,));db.execute('DELETE FROM account_challenges WHERE user_id=?',(uid,));db.execute('DELETE FROM account_email_tokens WHERE user_id=?',(uid,))
  remove_totp(pending_ref)
  return {'ok':True,'sessions_revoked':True,'mfa_unchanged':True}
 @app.post('/api/auth/email/confirm')
 def confirm_email(data:Token,request:Request):
  from .app import ratelimit
  ratelimit('verify-complete:'+(request.client.host if request.client else 'unknown'),20,900)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE')
   r=db.execute("SELECT t.*,u.pass_hash,u.disabled FROM account_email_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.purpose='verify' AND t.expires_at>?",(digest(data.token),time.time())).fetchone()
   if not r or r['disabled'] or r['password_version']!=digest(r['pass_hash']):raise HTTPException(400,'Invalid or expired link')
   security(db,r['user_id']);db.execute('UPDATE account_security SET email_verified_at=? WHERE user_id=?',(time.time(),r['user_id']));db.execute("DELETE FROM account_email_tokens WHERE user_id=? AND purpose='verify'",(r['user_id'],))
  return {'ok':True,'email_verified':True,'chess_ownership_verified':False}
 @app.get('/api/account/security')
 def state(user=Depends(auth)):
  from . import mailer
  with core.connection() as db:
   s=security(db,user['id']);remaining=db.execute('SELECT count(*) FROM account_recovery_codes WHERE user_id=?',(user['id'],)).fetchone()[0]
  return {'email_verified':bool(s['email_verified_at']),'mfa_enabled':bool(s['totp_ref']),'recovery_codes_remaining':remaining,'email_delivery_ready':mailer.configured(),'admin_mfa_policy':os.getenv('STUDIO_REQUIRE_ADMIN_MFA','false').lower()=='true','chess_ownership_verified':False}
 @app.post('/api/account/email/request',status_code=202)
 def verification(user=Depends(auth)):
  from .app import ratelimit
  ratelimit('email-verify:'+str(user['id']),3,3600);queue_email(user['id'],'verify');return {'accepted':True}
 @app.post('/api/account/mfa/enroll')
 def enroll(data:Password,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('mfa-enroll:'+str(user['id']),5,3600)
  if not core.verify(data.password,user['pass_hash']):raise HTTPException(403,'Current password required')
  secret=base64.b32encode(secrets.token_bytes(20)).decode()
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');s=security(db,user['id'])
   fresh=db.execute('SELECT pass_hash FROM users WHERE id=? AND disabled=0',(user['id'],)).fetchone()
   if not fresh or fresh['pass_hash']!=user['pass_hash'] or not db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>?',(user['_session_hash'],time.time())).fetchone():raise HTTPException(403,'Current password required')
   if s['totp_ref']:raise HTTPException(409,'MFA is already enabled')
   ref=control_secrets.put('totp',secret);old_pending=s['pending_ref']
   db.execute('UPDATE account_security SET pending_ref=?,pending_until=? WHERE user_id=?',(ref,time.time()+600,user['id']))
  remove_totp(old_pending)
  return {'secret':secret,'otpauth_uri':'otpauth://totp/'+quote('Chess Studio:'+user['email'],safe='')+'?secret='+secret+'&issuer=Chess%20Studio&algorithm=SHA1&digits=6&period=30','expires_in':600}
 @app.post('/api/account/mfa/confirm')
 def confirm(data:Confirm,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('mfa-confirm:'+str(user['id']),10,900)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');s=security(db,user['id'])
   if not db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND user_id=? AND expires_at>?',(user['_session_hash'],user['id'],time.time())).fetchone():raise HTTPException(401,'Sign in again with your second factor')
   if s['totp_ref'] or not s['pending_ref'] or s['pending_until']<time.time():raise HTTPException(400,'Enrollment expired')
   counter=match_counter(control_secrets.read(s['pending_ref']),data.code)
   if counter is None:raise HTTPException(403,'Invalid code')
   db.execute('UPDATE account_security SET totp_ref=pending_ref,pending_ref=NULL,pending_until=NULL,enabled_at=?,last_counter=? WHERE user_id=?',(time.time(),counter,user['id']))
   db.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],user['_session_hash']))
   if not db.execute('SELECT 1 FROM account_session_info WHERE token_hash=?',(user['_session_hash'],)).fetchone():record_session(db,user['_session_hash'],mfa=True)
   db.execute('UPDATE account_session_info SET mfa_at=? WHERE token_hash=?',(time.time(),user['_session_hash']))
   codes=new_codes(db,user['id'])
  return {'ok':True,'recovery_codes':codes,'notice':'Save these codes privately now. They are returned once.'}
 @app.post('/api/auth/mfa/complete')
 def finish_login(data:MFAComplete,request:Request,response:Response):
  from .app import ratelimit,issue_session
  ratelimit('mfa-login-ip:'+(request.client.host if request.client else 'unknown'),20,900)
  accepted=None;csrf=None
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT c.*,u.pass_hash,u.disabled FROM account_challenges c JOIN users u ON u.id=c.user_id WHERE c.token_hash=?',(digest(data.challenge),)).fetchone()
   if r and r['expires_at']>time.time() and r['attempts']<5 and not r['disabled'] and r['password_version']==digest(r['pass_hash']) and r['totp_ref']==security(db,r['user_id'])['totp_ref']:
    db.execute('UPDATE account_challenges SET attempts=attempts+1 WHERE token_hash=?',(digest(data.challenge),))
    if consume_factor(db,r['user_id'],data.code):
     accepted=r['user_id'];db.execute('DELETE FROM account_challenges WHERE token_hash=?',(digest(data.challenge),));csrf=issue_session(response,accepted,db=db,mfa=True)
  if accepted is None:raise HTTPException(401,'Invalid or expired authentication challenge')
  return {'ok':True,'csrf':csrf}
 @app.post('/api/account/mfa/disable')
 def disable(data:Sensitive,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('mfa-disable:'+str(user['id']),5,900)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE');sensitive(db,user,data.password,data.code)
   previous=security(db,user['id']);old_refs=[previous['totp_ref'],previous['pending_ref']]
   db.execute('UPDATE account_security SET totp_ref=NULL,pending_ref=NULL,pending_until=NULL,enabled_at=NULL,last_counter=-1 WHERE user_id=?',(user['id'],));db.execute('DELETE FROM account_recovery_codes WHERE user_id=?',(user['id'],));db.execute('DELETE FROM account_challenges WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],user['_session_hash']))
  for ref in old_refs:remove_totp(ref)
  return {'ok':True}
 @app.get('/api/account/sessions')
 def sessions(user=Depends(auth)):
  with core.connection() as db:rows=db.execute('SELECT s.token_hash,s.expires_at,i.public_id,i.created_at,i.last_seen_at,i.mfa_at FROM sessions s LEFT JOIN account_session_info i ON s.token_hash=i.token_hash WHERE s.user_id=? AND s.expires_at>? ORDER BY i.created_at DESC',(user['id'],time.time())).fetchall()
  return {'items':[{'id':r['public_id'] or r['token_hash'][:24],'current':r['token_hash']==user['_session_hash'],'expires_at':r['expires_at'],'created_at':r['created_at'],'last_seen_at':r['last_seen_at'],'mfa_authenticated':bool(r['mfa_at'])} for r in rows]}
 @app.post('/api/account/mfa/recovery-codes')
 def rotate_codes(data:Sensitive,user=Depends(auth)):
  from .app import ratelimit
  ratelimit('mfa-codes:'+str(user['id']),5,900)
  with core.connection() as db:
   db.execute('BEGIN IMMEDIATE')
   if not security(db,user['id'])['totp_ref']:raise HTTPException(409,'MFA is not enabled')
   sensitive(db,user,data.password,data.code);codes=new_codes(db,user['id'])
  return {'ok':True,'recovery_codes':codes,'previous_codes_invalidated':True}
 @app.delete('/api/account/sessions/{sid}')
 def revoke(sid:str,user=Depends(auth)):
  with core.connection() as db:
   r=db.execute('SELECT s.token_hash FROM sessions s LEFT JOIN account_session_info i ON s.token_hash=i.token_hash WHERE s.user_id=? AND coalesce(i.public_id,substr(s.token_hash,1,24))=?',(user['id'],sid)).fetchone()
   if not r:raise HTTPException(404,'Session not found')
   db.execute('DELETE FROM sessions WHERE token_hash=?',(r[0],))
  return {'ok':True,'current_session_revoked':r[0]==user['_session_hash']}
