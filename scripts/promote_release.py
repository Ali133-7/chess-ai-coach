"""Promote a pinned image after isolated migration checks and a verified encrypted backup."""
import argparse,json,os,re,shutil,sqlite3,subprocess,tempfile,time,urllib.request,sys
from pathlib import Path
from contextlib import closing
try:import fcntl
except ImportError:fcntl=None
sys.path.insert(0,str(Path(__file__).resolve().parent))
try:from . import encrypted_backup as backup
except ImportError:import encrypted_backup as backup

SERVICES={'studio','studio-worker','studio-sync','control-sync','mail-worker','daily-exercises'}
def run(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()
def validate_image(image,commit,repository):
 if not re.fullmatch(r'ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}',image) or image.split('@')[0]!=repository:raise ValueError('Use a digest from the configured GHCR repository')
 if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('A full source commit is required')
def render_compose(text,services,image):
 text=text.replace('\r\n','\n')
 for service in services:
  if service not in SERVICES:raise ValueError('Unknown release service')
  match=re.search(r'(?ms)^  '+re.escape(service)+r':\n.*?(?=^  [A-Za-z0-9_-]+:|^[A-Za-z0-9_-]+:|\Z)',text)
  if not match:raise ValueError('Service not in Compose: '+service)
  block=match.group()
  if re.search(r'(?m)^    image:',block):block=re.sub(r'(?m)^    image:.*$',f'    image: {image}',block)
  else:block=block.replace('  '+service+':\n','  '+service+':\n    image: '+image+'\n',1)
  text=text[:match.start()]+block+text[match.end():]
 return text
def atomic(path,text):
 temp=path.with_name(path.name+'.release-tmp');temp.write_text(text);temp.chmod(path.stat().st_mode&0o777);os.replace(temp,path)
def active(unit):return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0
def safe_unit(unit):
 if not re.fullmatch(r'chess-[a-z0-9-]+\.service',unit):raise ValueError('Only explicitly configured chess systemd units are allowed')
 return unit
def stage(image,databases,folder):
 data=folder/'candidate-data';data.mkdir(mode=0o700)
 for label,name in [('studio','studio.sqlite3'),('knowledge','knowledge.sqlite3')]:backup.snapshot(databases[label],data/name)
 probe="""import json,sqlite3
from studio.app import start
from studio import core
names=('users','games','moves','position_scans','sessions','ratings','lesson_solves')
def counts():
 with core.connection() as db:return {n:db.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in names}
before=counts();start();assert counts()==before
with core.connection() as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('PRAGMA foreign_key_check').fetchall()
from fastapi.testclient import TestClient
from studio.app import app
with TestClient(app) as client:
 assert client.get('/health').status_code==200
 assert client.get('/assets/account_security.js').status_code==200
 assert client.get('/api/account/security').status_code==401
print(json.dumps({'stage':'passed','existing_rows_unchanged':before}))
"""
 output=run('docker','run','--rm','--network','none','--cpus','1','--memory','768m','--security-opt','no-new-privileges','--mount',f'type=bind,src={data},dst=/studio-data','-e','STUDIO_DB=/studio-data/studio.sqlite3','-e','CHESS_KNOWLEDGE_DB=/studio-data/knowledge.sqlite3',image,'python','-c',probe)
 (folder/'stage-result.json').write_text(output);return json.loads(output.splitlines()[-1])
def safe_rollback(old_image,studio_db,require_mfa=False):
 info=json.loads(run('docker','image','inspect',old_image))[0]
 if info['Config'].get('Labels',{}).get('org.chessstudio.account-security')=='1':return True
 with closing(sqlite3.connect(studio_db)) as db:
  exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='account_security'").fetchone()
  enabled=exists and db.execute('SELECT 1 FROM account_security WHERE totp_ref IS NOT NULL LIMIT 1').fetchone()
 return not enabled and not require_mfa
def promote(cfg,image,commit,stage_only=False):
 if fcntl is None:raise RuntimeError('Production promotion requires a Linux host')
 validate_image(image,commit,cfg['repository']);compose=Path(cfg['compose']).resolve();services=cfg['services']
 if not {'studio','studio-worker','studio-sync'}<=set(services):raise ValueError('Web, worker and archive sync must upgrade together')
 root=Path(cfg['release_directory']).resolve();backup.private_dir(root)
 lock=(root/'promotion.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 folder=root/(commit[:12]+'-'+str(int(time.time())));folder.mkdir(mode=0o700)
 def dc(*args):return run('docker','compose','-f',str(compose),*args)
 # Never print expanded Compose/environment configuration.
 dc('config','--quiet');run('docker','pull',image)
 info=json.loads(run('docker','image','inspect',image))[0]
 if info['Config']['Labels'].get('org.opencontainers.image.revision')!=commit:raise ValueError('Image source revision mismatch')
 current_ids=dc('ps','-q','studio').splitlines()
 if len(current_ids)!=1:raise ValueError('Exactly one existing Studio instance is required')
 old=json.loads(run('docker','inspect',current_ids[0]))[0];old_image=old['Config']['Image']
 volume=next(x['Source'] for x in old['Mounts'] if x['Destination']=='/studio-data')
 databases={'studio':str(Path(volume)/'studio.sqlite3'),'knowledge':str(Path(volume)/'knowledge.sqlite3')}
 for key in ('key_file','output_directory'):
  if not cfg.get('backup',{}).get(key):raise ValueError('Encrypted backup configuration is required before promotion')
 backup.private_key(cfg['backup']['key_file'])
 before=compose.read_text();after=render_compose(before,services,image)
 candidate=folder/'compose.candidate.yaml';candidate.write_text(after);candidate.chmod(0o600)
 run('docker','compose','--project-directory',str(compose.parent),'-f',str(candidate),'config','--quiet')
 result=stage(image,databases,folder)
 if stage_only:return {'status':'stage_passed','commit':commit,'image':image,'result':result,'production_changed':False}
 units=[safe_unit(x) for x in cfg.get('systemd_units',[])];timers={x.replace('.service','.timer'):active(x.replace('.service','.timer')) for x in units}
 for unit in units:
  body=Path('/etc/systemd/system',unit).read_text()
  if body.count(old_image)!=1:raise ValueError('One-shot service image differs from Studio; reconcile before promotion')
  shutil.copy2(Path('/etc/systemd/system',unit),folder/unit)
 # Refuse to leave an old Compose writer alive against the new schema.
 configured=json.loads(dc('config','--format','json'))
 for service in SERVICES-set(services):
  if service in configured['services'] and dc('ps','-q',service):raise ValueError('Running writer omitted from coordinated upgrade: '+service)
 old_env=dict(x.split('=',1) for x in old['Config']['Env'] if '=' in x)
 shutil.copy2(compose,folder/'compose.before.yaml');(folder/'compose.before.yaml').chmod(0o600)
 record={'commit':commit,'image':image,'old_image':old_image,'timers':timers,'compose':str(compose),'services':services,'units':units,'database':databases['studio'],'require_admin_mfa':old_env.get('STUDIO_REQUIRE_ADMIN_MFA','false').lower()=='true'}
 (folder/'rollback-state.json').write_text(json.dumps(record));changed=False
 try:
  for timer in timers:run('systemctl','stop',timer)
  for unit in units:run('systemctl','stop',unit)
  for name in cfg.get('one_shot_containers',[]):
   if not re.fullmatch(r'chess-[a-z0-9-]+',name):raise ValueError('Invalid one-shot container')
   if subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:run('docker','stop','-t','30',name)
  dc('stop','-t','35',*services)
  backup_cfg={**cfg['backup'],'data_directory':volume,'databases':databases,'ssh_destination':None,'private_includes':[str(compose),str(compose.parent/'.env'),*cfg['backup'].get('private_includes',[])]}
  backup_file=folder/'backup-config.json';backup_file.write_text(json.dumps(backup_cfg));backup_file.chmod(0o600)
  receipt=backup.run_config(backup_file);(folder/'backup-receipt.json').write_text(json.dumps(receipt))
  with closing(sqlite3.connect(databases['studio'])) as db:
   db.execute('UPDATE analysis_jobs SET generation=generation+1,token=NULL,lease_until=0')
   db.execute('UPDATE shared_engine_scans SET token=NULL,lease_until=0 WHERE scan_json IS NULL');db.commit()
  atomic(compose,after);changed=True
  for unit in units:
   p=Path('/etc/systemd/system',unit);atomic(p,p.read_text().replace(old_image,image))
  if units:run('systemctl','daemon-reload')
  dc('up','-d','--no-deps','--no-build',*services)
  for _ in range(45):
   try:
    with urllib.request.urlopen(cfg.get('health_url','http://127.0.0.1:8001/health'),timeout=3) as response:
     if response.status==200:break
   except OSError:pass
   time.sleep(2)
  else:raise RuntimeError('Release health check failed')
  for service in services:
   ids=dc('ps','-q',service).splitlines()
   if len(ids)!=1:raise RuntimeError('Missing release service')
   state=json.loads(run('docker','inspect',ids[0]))[0]
   if state['Config']['Image']!=image or not state['State']['Running'] or state['RestartCount']:raise RuntimeError('Release service is unstable')
  # Network transfer happens after service recovery, so an unavailable backup
  # host cannot lengthen the maintenance window or roll back healthy code.
  if cfg['backup'].get('ssh_destination'):
   try:receipt.update(backup.offsite(receipt['file'],cfg['backup']['ssh_destination'],cfg['backup'].get('identity_file')))
   except Exception:receipt.update(offsite_uploaded=False,offsite_error='upload_failed_retry_required')
  result={'status':'deployed','commit':commit,'image':image,'stage':result,'backup':receipt,'rollback_state':str(folder/'rollback-state.json')}
  (folder/'verification.json').write_text(json.dumps(result,indent=2));return result
 except Exception:
  dc('stop','-t','35',*services)
  if changed:
   if not safe_rollback(old_image,databases['studio'],record['require_admin_mfa']):raise RuntimeError('Automatic rollback blocked: previous image would bypass MFA. Web remains stopped; deploy an MFA-compatible image.') from None
   shutil.copy2(folder/'compose.before.yaml',compose)
   for unit in units:shutil.copy2(folder/unit,Path('/etc/systemd/system',unit))
   if units:run('systemctl','daemon-reload')
  dc('up','-d','--no-deps','--no-build',*services)
  raise
 finally:
  for timer,was_active in timers.items():
   if was_active:run('systemctl','start',timer)
def rollback(state_file):
 state_file=Path(state_file);record=json.loads(state_file.read_text());folder=state_file.parent
 if not safe_rollback(record['old_image'],record['database'],record.get('require_admin_mfa',False)):raise ValueError('Previous image cannot safely enforce current MFA')
 compose=Path(record['compose'])
 if record['image'] not in compose.read_text():raise ValueError('Current Compose no longer matches this release')
 configured=json.loads(run('docker','compose','-f',str(compose),'config','--format','json'))
 if any(configured['services'][s].get('image')!=record['image'] for s in record['services']):raise ValueError('A service image changed after this release')
 for timer in record['timers']:run('systemctl','stop',timer)
 for unit in record['units']:run('systemctl','stop',unit)
 run('docker','compose','-f',str(compose),'stop','-t','35',*record['services'])
 if not safe_rollback(record['old_image'],record['database'],record.get('require_admin_mfa',False)):raise ValueError('MFA changed during shutdown; previous image is unsafe and web remains stopped')
 shutil.copy2(folder/'compose.before.yaml',compose)
 for unit in record['units']:shutil.copy2(folder/unit,Path('/etc/systemd/system',unit))
 if record['units']:run('systemctl','daemon-reload')
 run('docker','compose','-f',str(compose),'up','-d','--no-deps','--no-build',*record['services'])
 for timer,was_active in record['timers'].items():
  if was_active:run('systemctl','start',timer)
 return {'status':'code_rolled_back','database_restored':False}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path);p.add_argument('--image');p.add_argument('--commit');p.add_argument('--execute',action='store_true');p.add_argument('--stage-only',action='store_true');p.add_argument('--rollback',type=Path);a=p.parse_args()
 if a.rollback:
  if not a.execute:p.error('--rollback requires --execute')
  result=rollback(a.rollback)
 else:
  if not a.config or not a.image or not a.commit:p.error('--config, --image, --commit are required')
  cfg=json.loads(a.config.read_text());validate_image(a.image,a.commit,cfg['repository'])
  result=promote(cfg,a.image,a.commit,a.stage_only) if a.execute or a.stage_only else {'plan':'stage, stop configured writers, verify encrypted backup, promote all services, health-check and guarded rollback','production_changed':False,'image':a.image,'commit':a.commit}
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
