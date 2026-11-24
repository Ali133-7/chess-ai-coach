"""Private outbox worker. Explicit TLS SMTP; no live sending until configured."""
import argparse,json,os,secrets,smtplib,ssl,time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
from . import core,control_secrets

def public_base():
 value=os.getenv('STUDIO_BASE_URL','').rstrip('/');u=urlsplit(value)
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path:raise ValueError('Email links require a canonical HTTPS origin')
 return value
def password():
 p=Path(os.getenv('STUDIO_SMTP_PASSWORD_FILE',''))
 if not p.is_file() or p.is_symlink() or p.stat().st_size>32768 or (os.name!='nt' and p.stat().st_mode&0o077):raise ValueError('Private SMTP password file unavailable')
 return p.read_text(encoding='utf8').strip()
def configured():
 try:
  public_base();host=os.getenv('STUDIO_SMTP_HOST','');sender=os.getenv('STUDIO_SMTP_FROM','')
  return bool(host and not any(c.isspace() for c in host) and core.EMAIL_RE.fullmatch(sender) and os.getenv('STUDIO_SMTP_USERNAME') and password() and os.getenv('STUDIO_SMTP_MODE','starttls') in ('starttls','ssl'))
 except (ValueError,OSError):return False
def deliver(message):
 if not configured():raise ValueError('Email delivery is not configured')
 host=os.environ['STUDIO_SMTP_HOST'];mode=os.getenv('STUDIO_SMTP_MODE','starttls');port=int(os.getenv('STUDIO_SMTP_PORT','465' if mode=='ssl' else '587'))
 body=EmailMessage();body['From']=os.environ['STUDIO_SMTP_FROM'];body['To']=message['to'];body['Subject']='Chess Studio — '+('Verify your email / تأكيد البريد' if message['purpose']=='verify' else 'Password recovery / استعادة كلمة المرور')
 body.set_content('Use this one-time link / استخدم هذا الرابط مرة واحدة:\n\n'+message['url']+'\n\nIf you did not request this, ignore this message.\nإذا لم تطلب ذلك، تجاهل الرسالة.\n')
 context=ssl.create_default_context()
 if mode=='ssl':client=smtplib.SMTP_SSL(host,port,timeout=20,context=context)
 else:
  client=smtplib.SMTP(host,port,timeout=20);client.ehlo();client.starttls(context=context);client.ehlo()
 with client:
  client.login(os.environ['STUDIO_SMTP_USERNAME'],password());client.send_message(body)
def remove_payload(ref):
 import re
 if re.fullmatch(r'account-mail-[0-9a-f]{24}',ref):
  p=control_secrets.root()/ref
  if not p.is_symlink():p.unlink(missing_ok=True)
def job():
 if not configured():return False
 token=secrets.token_hex(16);now=time.time()
 with core.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  row=db.execute("SELECT o.* FROM account_mail_outbox o JOIN users u ON u.id=o.user_id WHERE u.disabled=0 AND o.status IN ('pending','sending') AND o.available_at<=? AND o.lease_until<? ORDER BY o.created_at LIMIT 1",(now,now)).fetchone()
  if not row:return False
  if row['created_at']<now-1800:
   db.execute("UPDATE account_mail_outbox SET status='expired' WHERE id=?",(row['id'],));remove_payload(row['private_ref']);return True
  db.execute("UPDATE account_mail_outbox SET status='sending',token=?,lease_until=?,attempts=attempts+1 WHERE id=?",(token,now+120,row['id']))
 try:
  message=json.loads(control_secrets.read(row['private_ref']));deliver(message)
  with core.connection() as db:updated=db.execute("UPDATE account_mail_outbox SET status='sent',token=NULL,lease_until=0 WHERE id=? AND token=?",(row['id'],token)).rowcount
  if updated:remove_payload(row['private_ref'])
 except Exception:
  final=row['attempts']>=4
  with core.connection() as db:updated=db.execute("UPDATE account_mail_outbox SET status=?,last_error='delivery_failed',available_at=?,lease_until=0,token=NULL WHERE id=? AND token=?",('failed' if final else 'pending',time.time()+min(900,30*2**row['attempts']),row['id'],token)).rowcount
  if final and updated:remove_payload(row['private_ref'])
 return True
def main():
 p=argparse.ArgumentParser();p.add_argument('--loop',action='store_true');a=p.parse_args();core.setup()
 if not configured():raise SystemExit('SMTP is disabled or incomplete; no messages sent')
 while True:
  done=job()
  if not a.loop:break
  if not done:time.sleep(10)
if __name__=='__main__':main()
