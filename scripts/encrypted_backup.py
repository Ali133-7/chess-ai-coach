"""Consistent SQLite snapshots, authenticated streaming encryption, and isolated restore drills."""
import argparse,hashlib,json,os,re,secrets,shlex,shutil,sqlite3,subprocess,tarfile,tempfile
from datetime import datetime,timezone
from pathlib import Path
from contextlib import closing
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

MAGIC=b'CHESSBK1';CHUNK=1024*1024
def private_dir(path):path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700)
def private_key(path):
 path=Path(path)
 if path.is_symlink() or (os.name!='nt' and path.stat().st_mode&0o077):raise ValueError('Backup key must be a private regular file')
 key=path.read_bytes()
 if len(key)!=32:raise ValueError('Backup key must contain exactly 32 random bytes')
 return key
def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def snapshot(source,dest):
 with closing(sqlite3.connect('file:'+str(Path(source).resolve())+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(dest)) as dst:
  src.backup(dst,pages=256)
  if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite snapshot failed integrity check')
 os.chmod(dest,0o600)
def encrypt(source,dest,key):
 nonce=secrets.token_bytes(12);header=MAGIC+nonce;enc=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor();enc.authenticate_additional_data(header)
 fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  with os.fdopen(fd,'wb') as out,open(source,'rb') as src:
   out.write(header)
   for chunk in iter(lambda:src.read(CHUNK),b''):out.write(enc.update(chunk))
   out.write(enc.finalize());out.write(enc.tag);out.flush();os.fsync(out.fileno())
 except BaseException:
  Path(dest).unlink(missing_ok=True);raise
def decrypt(source,dest,key):
 size=Path(source).stat().st_size
 if size<len(MAGIC)+28:raise ValueError('Truncated encrypted backup')
 with open(source,'rb') as src:
  header=src.read(len(MAGIC)+12)
  if not header.startswith(MAGIC):raise ValueError('Unknown backup format')
  src.seek(-16,2);tag=src.read(16);src.seek(len(header));remaining=size-len(header)-16
  dec=Cipher(algorithms.AES(key),modes.GCM(header[len(MAGIC):],tag)).decryptor();dec.authenticate_additional_data(header)
  fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  try:
   with os.fdopen(fd,'wb') as out:
    while remaining:
     chunk=src.read(min(CHUNK,remaining))
     if not chunk:raise ValueError('Truncated backup')
     out.write(dec.update(chunk));remaining-=len(chunk)
    out.write(dec.finalize())
  except BaseException:Path(dest).unlink(missing_ok=True);raise
def create(databases,includes,output,key_file):
 output=Path(output);private_dir(output.parent);key=private_key(key_file)
 if output.exists():raise FileExistsError('Refusing to overwrite an existing backup')
 if not databases:raise ValueError('At least one database is required')
 with tempfile.TemporaryDirectory(prefix='chess-snapshot-',dir=output.parent) as td:
  stage=Path(td);private_dir(stage);files={};origins={}
  for name,source in databases.items():
   if not re.fullmatch('[a-zA-Z0-9_-]{1,40}',name):raise ValueError('Invalid database label')
   target=stage/'databases'/(name+'.sqlite3');target.parent.mkdir(exist_ok=True);snapshot(source,target);origins[target.relative_to(stage).as_posix()]=str(Path(source).resolve())
  for index,source in enumerate(includes):
   if Path(source).is_symlink():raise ValueError('Private backup includes may not be symlinks')
   source=Path(source).resolve(strict=True)
   if source==Path(key_file).resolve():raise ValueError('Never include the backup encryption key in its own archive')
   target=stage/'private'/str(index)/source.name;target.parent.mkdir(parents=True,exist_ok=True)
   if source.is_dir():
    for p in source.rglob('*'):
     if p.is_symlink():raise ValueError('Private backup includes may not contain symlinks')
     if p.resolve()==Path(key_file).resolve():raise ValueError('Key directory must be excluded from backup payload')
    shutil.copytree(source,target)
   elif source.is_file():shutil.copy2(source,target)
   else:raise ValueError('Only regular private files/directories may be included')
   origins[target.relative_to(stage).as_posix()]=str(source)
  for p in stage.rglob('*'):
   if p.is_file():files[p.relative_to(stage).as_posix()]={'sha256':digest(p),'bytes':p.stat().st_size}
  manifest={'version':1,'created_at':datetime.now(timezone.utc).isoformat(),'files':files,'origins':origins,'snapshot_method':'SQLite online backup, individually consistent per database; pause writers for a cross-database/application snapshot.'}
  (stage/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
  tar_path=stage/'payload.tar.gz'
  with tarfile.open(tar_path,'w:gz') as tar:
   for name in ['manifest.json',*sorted(files)]:tar.add(stage/name,arcname=name,recursive=False)
  encrypt(tar_path,output,key)
 return {'file':str(output),'sha256':digest(output),'encrypted':True,'databases':list(databases),'private_includes':len(includes)}
def restore(source,key_file,destination=None):
 source=Path(source);destination=Path(destination) if destination else None
 if destination and destination.exists():raise FileExistsError('Restore destination must be new; live databases are never overwritten')
 parent=destination.parent if destination else source.parent;parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='chess-restore-',dir=parent) as td:
  temp=Path(td);private_dir(temp);tar_path=temp/'authenticated.tar.gz';decrypt(source,tar_path,private_key(key_file));stage=temp/'verified';stage.mkdir(mode=0o700)
  with tarfile.open(tar_path) as tar:
   members=tar.getmembers()
   if len(members)>100000 or sum(m.size for m in members)>50*1024**3:raise ValueError('Backup exceeds restore bounds')
   names=set()
   for member in members:
    p=Path(member.name)
    if member.name in names or not member.isfile() or p.is_absolute() or '..' in p.parts or '\\' in member.name or ':' in member.name:raise ValueError('Unsafe backup member')
    names.add(member.name);target=stage/p
    if not target.resolve().is_relative_to(stage.resolve()):raise ValueError('Backup path escapes destination')
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tar.extractfile(member) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst,CHUNK)
    target.chmod(0o600)
  manifest=json.loads((stage/'manifest.json').read_text(encoding='utf8'))
  if manifest['version']!=1 or names!={'manifest.json',*manifest['files']}:raise ValueError('Manifest member mismatch')
  databases=[]
  for name,info in manifest['files'].items():
   path=stage/name
   if path.stat().st_size!=info['bytes'] or digest(path)!=info['sha256']:raise ValueError('Backup payload hash mismatch')
   if name.startswith('databases/'):
    with closing(sqlite3.connect(path)) as db:
     if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Restored SQLite database failed checks')
    databases.append(name)
  if destination:stage.replace(destination)
 return {'verified':True,'databases':databases,'files':len(manifest['files']),'restored_to':str(destination) if destination else None,'live_database_modified':False}
def offsite(file,destination,identity_file=None):
 match=re.fullmatch(r'([A-Za-z0-9_][A-Za-z0-9_.-]*)@([A-Za-z0-9][A-Za-z0-9.-]*):(/[A-Za-z0-9_./-]+)',destination)
 if not match or '..' in Path(match[3]).parts:raise ValueError('Use user@host:/safe/absolute/directory; no shell expressions')
 user,host,directory=match.groups();file=Path(file);remote=directory.rstrip('/')+'/'+file.name;temporary=remote+'.part'
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',file.name):raise ValueError('Unsafe backup filename')
 opts=['-o','BatchMode=yes','-o','StrictHostKeyChecking=yes']
 if identity_file:opts+=['-i',str(identity_file)]
 subprocess.run(['scp',*opts,'--',str(file),f'{user}@{host}:{temporary}'],check=True,capture_output=True,timeout=1800)
 command='sha256sum -- '+shlex.quote(temporary)
 actual=subprocess.check_output(['ssh',*opts,f'{user}@{host}',command],text=True,timeout=60).split()[0]
 if actual!=digest(file):raise ValueError('Off-site checksum did not match')
 subprocess.run(['ssh',*opts,f'{user}@{host}','mv -n -- '+shlex.quote(temporary)+' '+shlex.quote(remote)],check=True,capture_output=True,timeout=60)
 actual=subprocess.check_output(['ssh',*opts,f'{user}@{host}','sha256sum -- '+shlex.quote(remote)],text=True,timeout=60).split()[0]
 if actual!=digest(file):raise ValueError('Final off-site object checksum mismatch')
 return {'offsite_uploaded':True,'checksum_verified':True,'remote_file':remote}
def run_config(config):
 cfg=json.loads(Path(config).read_text(encoding='utf8'));output=Path(cfg['output_directory']);private_dir(output)
 includes=list(cfg.get('private_includes',[]))
 if cfg.get('data_directory'):
  data=Path(cfg['data_directory']).resolve()
  if Path(cfg['key_file']).resolve().is_relative_to(data):raise ValueError('Store the backup encryption key outside the data volume')
  for entry in data.iterdir():
   if entry.name in ('private-backups','backups') or entry.name.endswith(('.sqlite3','.sqlite3-wal','.sqlite3-shm','.db','.db-wal','.db-shm','.log')):continue
   if output.resolve().is_relative_to(entry.resolve()):continue
   includes.append(str(entry))
 includes=list(dict.fromkeys(str(Path(x).resolve()) for x in includes))
 file=output/('chess-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.enc')
 result=create(cfg['databases'],includes,file,cfg['key_file']);result['restore_drill']=restore(file,cfg['key_file'])
 if cfg.get('ssh_destination'):result.update(offsite(file,cfg['ssh_destination'],cfg.get('identity_file')))
 else:result['offsite_uploaded']=False
 receipt=file.with_suffix('.receipt.json');receipt.write_text(json.dumps(result,indent=2));receipt.chmod(0o600)
 return result
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 gen=sub.add_parser('keygen');gen.add_argument('--key-file',type=Path,required=True)
 run=sub.add_parser('run');run.add_argument('--config',type=Path,required=True)
 verify=sub.add_parser('restore');verify.add_argument('--file',type=Path,required=True);verify.add_argument('--key-file',type=Path,required=True);verify.add_argument('--destination',type=Path)
 a=p.parse_args()
 if a.command=='keygen':
  private_dir(a.key_file.parent);fd=os.open(a.key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as out:out.write(secrets.token_bytes(32))
  result={'key_created':True,'key_contents_printed':False}
 elif a.command=='run':result=run_config(a.config)
 else:result=restore(a.file,a.key_file,a.destination)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
