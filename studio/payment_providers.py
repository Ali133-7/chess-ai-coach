"""Bounded, fixed-domain merchant transports. Never trust a browser's payment status."""
import json,logging,re,time,base64
from urllib.parse import urlsplit,quote
from decimal import Decimal,InvalidOperation
import httpx
from fastapi import HTTPException
from .control_secrets import read

logging.getLogger('httpx').setLevel(logging.WARNING)

def request(method,url,*,headers=None,data=None,body=None):
 try:
  with httpx.Client(timeout=httpx.Timeout(20,connect=5),follow_redirects=False,trust_env=False) as c:
   with c.stream(method,url,headers=headers,data=data,json=body) as r:
    if not 200<=r.status_code<300:raise HTTPException(502,{'code':'gateway_rejected','status':r.status_code})
    raw=bytearray()
    for chunk in r.iter_bytes():
     if len(raw)+len(chunk)>524288:raise HTTPException(502,'Gateway response too large')
     raw.extend(chunk)
  return json.loads(raw) if raw else {}
 except HTTPException:raise
 except Exception:raise HTTPException(502,'Payment service unavailable; no payment was assumed') from None

def validate(name,env,public,secrets_map):
 if name=='zaincash':
  allowed={'api_base','client_id'}
  base=public.get('api_base','https://pg-api-uat.zaincash.iq' if env=='sandbox' else '')
  if env=='live' and not base:raise HTTPException(422,'Enter the production API URL supplied during ZainCash onboarding')
  u=urlsplit(base)
  if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.path not in ('','/') or u.query or u.fragment or not u.hostname or not (u.hostname=='zaincash.iq' or u.hostname.endswith('.zaincash.iq')):raise HTTPException(422,'Use the merchant API HTTPS domain supplied by ZainCash')
  if env=='sandbox' and u.hostname!='pg-api-uat.zaincash.iq':raise HTTPException(422,'Use ZainCash UAT for sandbox')
  if env=='live' and u.hostname=='pg-api-uat.zaincash.iq':raise HTTPException(422,'UAT cannot be used for live settlement')
  public['api_base']=base.rstrip('/')
  required={'client_secret','api_key'}
 elif name=='fib':
  allowed={'client_id','api_base'};required={'client_secret'}
  base=public.get('api_base','https://fib.stage.fib.iq' if env=='sandbox' else '')
  u=urlsplit(base)
  if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.path not in ('','/') or u.query or u.fragment or not u.hostname or not u.hostname.endswith('.fib.iq'):raise HTTPException(422,'Enter the official HTTPS API domain supplied by FIB')
  if env=='sandbox' and u.hostname!='fib.stage.fib.iq':raise HTTPException(422,'Use the FIB staging domain for sandbox')
  if env=='live' and u.hostname=='fib.stage.fib.iq':raise HTTPException(422,'Staging cannot be used for live settlement')
  public['api_base']=base.rstrip('/')
 elif name=='google_play':
  allowed={'package_name','products','allow_test_purchases','push_audience','push_email'};required={'service_account'}
  package=public.get('package_name','')
  if package and not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+',package):raise HTTPException(422,'Invalid Android package name')
  products=public.get('products',{})
  if not isinstance(products,dict) or len(products)>100 or any(not re.fullmatch(r'[a-zA-Z0-9_.-]{1,150}',k) or not isinstance(v,str) or not re.fullmatch('[a-z][a-z0-9_-]{1,40}',v) for k,v in products.items()):raise HTTPException(422,'Map each Play product to a plan ID')
  if type(public.get('allow_test_purchases',False)) is not bool:raise HTTPException(422,'Invalid test purchase option')
  if 'service_account' in secrets_map and secrets_map['service_account']:
   try:
    v=json.loads(secrets_map['service_account'])
    if v['type']!='service_account' or not v['client_email'].endswith('.gserviceaccount.com'):raise ValueError('Invalid service account')
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    key=load_pem_private_key(v['private_key'].encode(),password=None)
    if not isinstance(key,RSAPrivateKey) or key.key_size<2048:raise ValueError('Invalid RSA key')
   except Exception:raise HTTPException(422,'Supply a valid RSA Google service-account JSON file') from None
 else:raise HTTPException(404,'Unknown payment gateway')
 if not set(public)<=allowed or not set(secrets_map)<=required:raise HTTPException(422,'Unknown gateway setting')
 if name!='google_play' and (not isinstance(public.get('client_id',''),str) or len(public.get('client_id',''))>300):raise HTTPException(422,'Invalid client ID')
 return public,required

def ready(name,p,refs):
 try:
  _,required=validate(name,'live' if p.get('_environment')=='live' else 'sandbox',{k:v for k,v in p.items() if k!='_environment'}, {})
  for k in required:read(refs[k])
  return bool(p.get('package_name') and p.get('products')) if name=='google_play' else bool(p.get('client_id'))
 except Exception:return False

def credentials(profile):return {k:read(v) for k,v in json.loads(profile['secrets_json']).items()}

def token(profile):
 p=json.loads(profile['public_json']);s=credentials(profile);name=profile['name']
 if name=='google_play':
  import jwt
  account=json.loads(s['service_account']);now=int(time.time())
  assertion=jwt.encode({'iss':account['client_email'],'scope':'https://www.googleapis.com/auth/androidpublisher','aud':'https://oauth2.googleapis.com/token','iat':now,'exp':now+3600},account['private_key'],algorithm='RS256')
  v=request('POST','https://oauth2.googleapis.com/token',data={'grant_type':'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion':assertion})
 else:
  base=p['api_base']
  endpoint='/oauth2/token' if name=='zaincash' else '/auth/realms/fib-online-shop/protocol/openid-connect/token'
  data={'grant_type':'client_credentials','client_id':p['client_id'],'client_secret':s['client_secret']}
  if name=='zaincash':data['scope']='payment:read payment:write'
  v=request('POST',base+endpoint,data=data)
 value=v.get('access_token')
 if not isinstance(value,str) or not value or len(value)>16000:raise HTTPException(502,'Invalid merchant token response')
 return value

def unwrap(v):return v.get('data',v) if isinstance(v,dict) else {}
def provider_id(v):
 if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,200}',v):raise HTTPException(502,'Invalid provider transaction identifier')
 return v

def safe_link(value,domain):
 if not isinstance(value,str) or len(value)>4096:raise HTTPException(502,'Invalid checkout address')
 u=urlsplit(value)
 if u.scheme!='https' or u.username or u.password or not u.hostname or not(u.hostname==domain or u.hostname.endswith('.'+domain)):raise HTTPException(502,'Invalid checkout domain')
 return value

def create(profile,order,callback,return_url):
 p=json.loads(profile['public_json']);auth={'Authorization':'Bearer '+token(profile)}
 if profile['name']=='zaincash':
  v=unwrap(request('POST',p['api_base']+'/api/v2/payment-gateway/transaction/init',headers=auth,body={'language':'ar','externalReferenceId':order['id'],'orderId':order['id'],'serviceType':'Chess Studio subscription','amount':{'value':order['amount'],'currency':'IQD'},'redirectUrls':{'successUrl':return_url,'failureUrl':return_url}}))
  return provider_id(v.get('transactionId')),{'redirect_url':safe_link(v.get('redirectUrl'),'zaincash.iq')}
 base=p['api_base']
 v=request('POST',base+'/protected/v1/payments',headers=auth,body={'monetaryValue':{'amount':str(order['amount']),'currency':'IQD'},'statusCallbackUrl':callback,'description':'Chess Studio '+order['id']})
 result={'payment_code':str(v.get('readableCode',''))[:200]}
 qr=v.get('qrCode','')
 if isinstance(qr,str):
  raw=qr.split(',',1)[-1]
  try:
   b=base64.b64decode(raw,validate=True)
   if len(b)<=200000 and b.startswith(b'\x89PNG\r\n\x1a\n'):result['qr_code']='data:image/png;base64,'+raw
  except Exception:pass
 if not result.get('payment_code') and not result.get('qr_code'):raise HTTPException(502,'No usable FIB checkout information')
 return provider_id(v.get('paymentId')),result

def inquire(profile,order):
 p=json.loads(profile['public_json']);auth={'Authorization':'Bearer '+token(profile)};pid=provider_id(order['provider_id'])
 if profile['name']=='zaincash':
  v=unwrap(request('GET',p['api_base']+'/api/v2/payment-gateway/transaction/inquiry/'+pid,headers=auth))
  state=v.get('status');amount=v.get('amount',{});identifier=v.get('transactionId');reference=v.get('orderId')
  if identifier!=pid or reference!=order['id']:raise HTTPException(502,'Merchant order reference mismatch')
  terminal='paid' if state=='SUCCESS' else 'failed' if state in ('FAILED','EXPIRED') else 'refunded' if state=='REFUNDED' else 'pending'
  value=amount.get('value');currency=amount.get('currency')
 else:
  base=p['api_base']
  v=request('GET',base+'/protected/v1/payments/'+pid+'/status',headers=auth)
  if v.get('paymentId')!=pid:raise HTTPException(502,'Merchant payment ID mismatch')
  terminal={'PAID':'paid','DECLINED':'failed','UNPAID':'pending'}.get(v.get('status'),'pending');amount=v.get('amount',{});value=amount.get('amount');currency=amount.get('currency')
 try:match=Decimal(str(value))==Decimal(order['amount']) and currency=='IQD'
 except InvalidOperation:match=False
 if not match:raise HTTPException(502,'Merchant amount or currency mismatch')
 return terminal
