"""Build a resumable compact library from the explicitly licensed Lichess broadcast archives."""
import argparse,hashlib,io,json,logging,os,re,shutil,sys,time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import chess,chess.pgn,httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library

URL=re.compile(r'https://database\.lichess\.org/broadcast/lichess_db_broadcast_(\d{4}-\d{2})\.pgn\.zst')

def manifest():
 with httpx.Client(timeout=60,follow_redirects=False,trust_env=False) as client:
  lists=client.get('https://database.lichess.org/broadcast/list.txt');lists.raise_for_status()
  checks=client.get('https://database.lichess.org/broadcast/sha256sums.txt');checks.raise_for_status()
 hashes={parts[1].lstrip('*'):parts[0] for line in checks.text.splitlines() if len(parts:=line.split())==2 and re.fullmatch('[0-9a-f]{64}',parts[0])}
 rows=[]
 for url in lists.text.splitlines():
  match=URL.fullmatch(url.strip())
  if not match or url.rsplit('/',1)[1] not in hashes:raise ValueError('Invalid upstream archive index/checksum')
  rows.append({'url':url,'month':match[1],'sha256':hashes[url.rsplit('/',1)[1]]})
 return {'format':1,'source_page':library.SOURCE,'license':library.LICENSE,'license_url':library.LICENSE_URL,'fetched_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'archives':sorted(rows,key=lambda x:x['month'],reverse=True)}

def download(item,directory):
 url=item['url'];sha=item['sha256']
 if not URL.fullmatch(url) or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Unapproved archive URL')
 dest=directory/url.rsplit('/',1)[1]
 if dest.exists():
  with dest.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
  if actual==sha:return dest
  raise ValueError('Existing archive checksum mismatch; preserve for inspection')
 partial=dest.with_suffix(dest.suffix+'.part');offset=partial.stat().st_size if partial.exists() else 0
 if offset:
  with partial.open('rb') as f:complete=hashlib.file_digest(f,'sha256').hexdigest()==sha
  if complete:partial.replace(dest);return dest
 headers={'Range':f'bytes={offset}-'} if offset else {}
 with httpx.Client(timeout=httpx.Timeout(60,read=120),follow_redirects=False,trust_env=False) as client:
  with client.stream('GET',url,headers=headers) as response:
   response.raise_for_status()
   if response.status_code not in (200,206):raise ValueError('Unexpected archive response')
   if response.status_code==206 and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid partial response')
   if response.status_code==200:offset=0
   if offset+int(response.headers.get('Content-Length','0'))>128*1024*1024:raise ValueError('Archive exceeds download bound')
   with partial.open('ab' if offset else 'wb') as out:
    size=offset
    for chunk in response.iter_bytes(1024*1024):
     size+=len(chunk)
     if size>128*1024*1024:raise ValueError('Archive exceeds download bound')
     out.write(chunk)
 with partial.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 if actual!=sha:raise ValueError('Downloaded archive checksum mismatch')
 partial.replace(dest);return dest

class Builder(chess.pgn.GameBuilder):
 def __init__(self,scope,skip=False):super().__init__();self.scope=scope;self.skip=skip;self.reason=None;self.body_result=None
 def end_headers(self):
  if self.skip:self.reason='already_processed';return chess.pgn.SKIP
  h=self.game.headers
  if self.scope=='gm' and (h.get('WhiteTitle')!='GM' or h.get('BlackTitle')!='GM'):self.reason='not_gm_vs_gm';return chess.pgn.SKIP
  if h.get('Result') not in ('1-0','0-1','1/2-1/2'):self.reason='unfinished';return chess.pgn.SKIP
  if h.get('Variant','Standard') not in ('Standard','Chess'):self.reason='nonstandard';return chess.pgn.SKIP
  dates=[h.get('Date',''),h.get('UTCDate','')]
  if not any(re.fullmatch(r'(17|18|19|20)\d{2}\.(\d{2}|\?\?)\.(\d{2}|\?\?)',d) for d in dates):self.reason='unknown_year';return chess.pgn.SKIP
 def begin_variation(self):return chess.pgn.SKIP
 def visit_comment(self,comment):
  # Retain numerical source evaluations only. Do not copy human prose/side lines.
  markers=re.findall(r'\[%eval\s+(?:#[+-]?\d+|[+-]?\d+(?:\.\d+)?)(?:,\d+)?\]',comment[:8192])
  if markers:super().visit_comment(' '.join(markers))
 def visit_nag(self,nag):pass
 def visit_result(self,result):self.body_result=result;super().visit_result(result)
 def handle_error(self,error):self.game.errors.append(error)
 def result(self):return self.game,self.reason,self.body_result

def import_archive(dbfile,item,file,scope='gm',batch_size=200,max_records=None,min_free_bytes=1024**3):
 import zstandard
 with file.open('rb') as verified:
  if hashlib.file_digest(verified,'sha256').hexdigest()!=item['sha256']:raise ValueError('Archive input checksum mismatch')
 library.setup(dbfile);url=item['url'];sha=item['sha256']
 with library.connection(dbfile,True) as db:
  db.execute('INSERT OR IGNORE INTO library_archives(url,sha256,scope) VALUES(?,?,?)',(url,sha,scope));job=dict(db.execute('SELECT * FROM library_archives WHERE url=?',(url,)).fetchone())
  if job['sha256']!=sha or job['scope']!=scope:raise ValueError('Archive revision/scope changed; use a separate library')
  if job['status']=='complete':return job
 cursor=job['cursor'];accepted=job['accepted'];duplicates=job['duplicates'];rejected=job['rejected'];skipped=job['skipped'];reasons=Counter(json.loads(job['reasons_json']));batch=[];index=0;started=time.monotonic()
 def checkpoint(complete=False):
  nonlocal accepted,duplicates,batch
  if shutil.disk_usage(Path(dbfile).resolve().parent).free<min_free_bytes:raise OSError('Reserved free disk space reached; resume after providing capacity')
  with library.connection(dbfile,True) as db:
   db.execute('BEGIN IMMEDIATE')
   for ordinal,row in batch:
    inserted=db.execute('INSERT OR IGNORE INTO library_games VALUES('+','.join('?'*19)+')',row).rowcount
    accepted+=inserted;duplicates+=not inserted
    db.execute('INSERT OR IGNORE INTO library_provenance VALUES(?,?,?)',(row[0],url,ordinal))
   db.execute('UPDATE library_archives SET cursor=?,accepted=?,duplicates=?,rejected=?,skipped=?,status=?,reasons_json=? WHERE url=?',(index,accepted,duplicates,rejected,skipped,'complete' if complete else 'running',json.dumps(reasons),url))
  batch=[]
  print(json.dumps({'month':item.get('month'),'cursor':index,'accepted':accepted,'duplicates':duplicates,'rejected':rejected,'skipped':skipped,'seconds':round(time.monotonic()-started,1)}),flush=True)
 with file.open('rb') as compressed,zstandard.ZstdDecompressor().stream_reader(compressed) as reader,io.TextIOWrapper(reader,encoding='utf-8-sig',errors='strict') as stream:
  while True:
   result=chess.pgn.read_game(stream,Visitor=lambda:Builder(scope,index<cursor))
   if result is None:break
   index+=1
   if index<=cursor:continue
   game,reason,body_result=result
   if reason:skipped+=1;reasons[reason]+=1
   else:
    try:batch.append((index,library.pack_game(game,url,body_result)))
    except (ValueError,TypeError,IndexError) as exc:rejected+=1;reasons[str(exc)[:80]]+=1
   if index%batch_size==0:checkpoint()
   if max_records and index>=max_records:checkpoint();return {'status':'paused','cursor':index,'accepted':accepted}
 checkpoint(True)
 with library.connection(dbfile) as db:return dict(db.execute('SELECT * FROM library_archives WHERE url=?',(url,)).fetchone())

def build_one(arguments):
 dbfile,directory,item,scope,keep,max_records,reserve=arguments
 for attempt in range(6):
  try:file=download(item,directory);break
  except (httpx.TransportError,httpx.HTTPStatusError) as exc:
   if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (408,429,500,502,503,504):raise
   if attempt==5:raise
   delay=min(2**attempt,16);print(json.dumps({'retry_download':item['month'],'attempt':attempt+1,'wait_seconds':delay}),flush=True);time.sleep(delay)
 result=import_archive(dbfile,item,file,scope,max_records=max_records,min_free_bytes=reserve)
 if result['status']=='complete' and not keep:file.unlink()
 return {'month':item['month'],'status':result['status']}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',type=Path,required=True);p.add_argument('--work-directory',type=Path,required=True);p.add_argument('--manifest',type=Path);p.add_argument('--scope',choices=['gm','all'],default='gm');p.add_argument('--months',type=int);p.add_argument('--keep-archives',action='store_true');p.add_argument('--reserve-free-gb',type=float,default=1);p.add_argument('--max-records-per-archive',type=int)
 p.add_argument('--workers',type=int,default=1,help='Archive workers (1-4); bound CPU/memory externally')
 p.add_argument('--refresh-index',action='store_true',help='Explicitly refresh the saved upstream archive list')
 a=p.parse_args()
 if not 1<=a.workers<=4:p.error('--workers must be 1-4')
 if a.workers>1 and a.max_records_per_archive:p.error('Record-limited smoke tests require --workers 1')
 if a.months is not None and a.months<1:p.error('--months must be positive')
 a.work_directory.mkdir(parents=True,exist_ok=True);a.database.parent.mkdir(parents=True,exist_ok=True)
 manifest_file=a.manifest or a.work_directory/'upstream-manifest.json'
 metadata=json.loads(manifest_file.read_text(encoding='utf8')) if manifest_file.exists() and not a.refresh_index else manifest()
 if metadata['license']!=library.LICENSE:raise ValueError('Unsupported archive license')
 if not manifest_file.exists() or a.refresh_index:
  temporary=manifest_file.with_name(manifest_file.name+'.tmp');temporary.write_text(json.dumps(metadata,indent=2),encoding='utf8');temporary.replace(manifest_file)
 selected=metadata['archives'][:a.months] if a.months else metadata['archives']
 library.setup(a.database);pending=[]
 for item in selected:
  if not URL.fullmatch(item.get('url','')) or not re.fullmatch('[0-9a-f]{64}',item.get('sha256','')):raise ValueError('Invalid manifest archive')
  with library.connection(a.database,True) as db:
   # A missing schema is normal on the first invocation.
   exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='library_archives'").fetchone()
   done=db.execute("SELECT status,sha256,scope FROM library_archives WHERE url=?",(item['url'],)).fetchone() if exists else None
  if done and done['status']=='complete' and done['sha256']==item['sha256'] and done['scope']==a.scope:continue
  if done and (done['sha256']!=item['sha256'] or done['scope']!=a.scope):raise ValueError('Archive revision/scope changed; use a separate library')
  pending.append((a.database,a.work_directory,item,a.scope,a.keep_archives,a.max_records_per_archive,int(a.reserve_free_gb*1024**3)))
 if a.workers==1:
  for arguments in pending:
   if build_one(arguments)['status']!='complete':break
 else:
  with ProcessPoolExecutor(max_workers=a.workers) as workers:
   for result in workers.map(build_one,pending):print(json.dumps({'archive_finished':result}),flush=True)
 print(json.dumps({'database':str(a.database),'manifest':str(manifest_file),'scope':a.scope,'selected_archives':len(selected)}))
if __name__=='__main__':main()
