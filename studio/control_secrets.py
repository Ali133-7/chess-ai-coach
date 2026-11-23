"""Write-only private-file credentials. Public responses contain readiness flags only."""
import json,os,re,secrets,tempfile
try:import fcntl
except ImportError:fcntl=None
from pathlib import Path
from fastapi import HTTPException
from . import core
from .teacher_v7 import providers,service

def root():
 p=Path(os.getenv('CONTROL_PRIVATE_DIR',str(core.DB.parent/'control-private')));p.mkdir(mode=0o700,parents=True,exist_ok=True)
 if p.is_symlink():raise HTTPException(503,'Private configuration path unavailable')
 p.chmod(0o700);return p

def atomic(path,value):
 path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 if path.is_symlink():raise HTTPException(503,'Private configuration path unavailable')
 fd,name=tempfile.mkstemp(prefix='.control-',dir=path.parent)
 try:
  os.fchmod(fd,0o600) if hasattr(os,'fchmod') else os.chmod(name,0o600)
  with os.fdopen(fd,'w',encoding='utf8') as out:out.write(value);out.flush();os.fsync(out.fileno())
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)

def put(label,value):
 if not re.fullmatch('[a-zA-Z0-9_-]{1,160}',label):raise ValueError('Invalid private label')
 if not value or len(value)>32768:raise HTTPException(422,'Invalid private value')
 ref=label+'-'+secrets.token_hex(12);atomic(root()/ref,value);return ref

def read(ref):
 if not re.fullmatch('[a-zA-Z0-9_-]{1,200}',ref or ''):raise HTTPException(503,'Private value unavailable')
 p=root()/ref
 try:
  if p.is_symlink() or (os.name!='nt' and p.stat().st_mode&0o077) or p.stat().st_size>32768:raise ValueError()
  return p.read_text(encoding='utf8')
 except Exception:raise HTTPException(503,'Private value unavailable') from None

def provider_public():
 from .control_store import settings
 enabled=settings()['ai_enabled']
 try:
  cfg=service.provider_config();ready=providers.status(cfg)
  try:catalog=json.loads((root()/'ai-catalog.json').read_text(encoding='utf8'))
  except (FileNotFoundError,ValueError):catalog={}
  catalog.update(cfg['providers']);models={n:v['model'] for n,v in catalog.items() if n in providers.ENDPOINTS}
  saved=set()
  for n,v in catalog.items():
   try:providers.read_key(v['key_file']);saved.add(n)
   except (providers.ProviderError,KeyError):pass
  return {'enabled':enabled,'primary':cfg['primary'],'fallback':cfg['fallback'],'models':models,'configured':{n:n in saved for n in providers.ENDPOINTS}}
 except providers.ProviderError:return {'enabled':enabled,'primary':'groq','fallback':[],'models':{},'configured':{n:False for n in providers.ENDPOINTS},'error':'configuration_unavailable'}

def save_providers(data):
 lock=root()/'.ai.lock'
 with lock.open('a') as f:
  lock.chmod(0o600);fcntl.flock(f,fcntl.LOCK_EX) if fcntl else None
  try:old=service.provider_config()
  except providers.ProviderError:old={'providers':{}}
  catalog_path=root()/'ai-catalog.json'
  try:catalog=json.loads(catalog_path.read_text(encoding='utf8'))
  except (FileNotFoundError,ValueError):catalog={}
  catalog.update(old.get('providers',{}));old['providers']=catalog
  if not data.enabled and not data.keys:return provider_public()
  result={}
  active=[data.primary]+data.fallback
  for name in dict.fromkeys(active+list(data.keys)):
   value=data.keys.get(name,'').strip()
   if value:
    if len(value)<15 or not value.isascii() or any(c.isspace() for c in value):raise HTTPException(422,'Invalid provider key')
    ref=put('ai-'+name,value+'\n');path=str((root()/ref).resolve())
   else:
    p=old['providers'].get(name)
    if not p:raise HTTPException(422,'Supply a key for '+name)
    try:providers.read_key(p['key_file'])
    except providers.ProviderError:raise HTTPException(422,'Supply a valid key for '+name) from None
    path=p['key_file']
   result[name]={'model':data.models[name].strip(),'key_file':path}
  catalog.update(result);atomic(catalog_path,json.dumps(catalog))
  atomic(providers.CONFIG_FILE,json.dumps({'primary':data.primary,'fallback':data.fallback,'providers':result},indent=2))
 return provider_public()
