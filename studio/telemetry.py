"""Bounded, buffered aggregate telemetry in a separate SQLite file. No user identifiers."""
import json,logging,math,os,re,sqlite3,threading,time
from collections import defaultdict
from pathlib import Path
from . import core

BOUNDS=(10,50,100,250,500,1000,5000)
_lock=threading.Lock();_pending={};_dropped=0;_stop=threading.Event();_thread=None
log=logging.getLogger('studio.telemetry')

def path():return Path(os.getenv('STUDIO_TELEMETRY_DB',str(core.DB.parent/'telemetry.sqlite3')))
def connect(target):
 target.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(target,timeout=3);db.row_factory=sqlite3.Row
 db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=3000')
 db.execute('''CREATE TABLE IF NOT EXISTS telemetry_buckets(bucket INTEGER,kind TEXT,route TEXT,status TEXT,release TEXT,n INTEGER,total_ms REAL,b0 INTEGER,b1 INTEGER,b2 INTEGER,b3 INTEGER,b4 INTEGER,b5 INTEGER,b6 INTEGER,b7 INTEGER,input_tokens INTEGER,output_tokens INTEGER,usage_known INTEGER,PRIMARY KEY(bucket,kind,route,status,release))''')
 return db

def record(kind,route,status,duration_ms,input_tokens=0,output_tokens=0,usage_known=False):
 global _dropped
 if kind not in ('http','provider'):return
 route=route if isinstance(route,str) and re.fullmatch(r'[A-Za-z0-9_/{}/.:-]{1,140}',route) else 'unmatched'
 status=str(status)[:16];release=os.getenv('STUDIO_RELEASE_SHA','development')[:40]
 duration=max(0,min(3600000,float(duration_ms)));bucket=int(time.time()//60)*60
 key=(str(path()),bucket,kind,route,status,release)
 with _lock:
  if key not in _pending:
   if len(_pending)>=4096:_dropped+=1;return
   _pending[key]=[0,0.,*[0]*8,0,0,0]
  values=_pending[key];values[0]+=1;values[1]+=duration
  values[2+sum(duration>x for x in BOUNDS)]+=1
  values[10]+=max(0,min(10000000,input_tokens)) if isinstance(input_tokens,int) else 0
  values[11]+=max(0,min(10000000,output_tokens)) if isinstance(output_tokens,int) else 0
  values[12]+=int(usage_known)

def flush():
 global _dropped
 with _lock:pending=dict(_pending);_pending.clear()
 groups=defaultdict(list)
 for key,value in pending.items():groups[key[0]].append((*key[1:],*value))
 for filename,rows in groups.items():
  db=None
  try:
   if not Path(filename).parent.exists():
    with _lock:_dropped+=sum(r[5] for r in rows)
    continue
   db=connect(Path(filename))
   columns=['n','total_ms',*[f'b{x}' for x in range(8)],'input_tokens','output_tokens','usage_known']
   update=','.join(f'{x}={x}+excluded.{x}' for x in columns)
   db.executemany('INSERT INTO telemetry_buckets VALUES('+','.join('?'*18)+') ON CONFLICT(bucket,kind,route,status,release) DO UPDATE SET '+update,rows)
   db.execute('DELETE FROM telemetry_buckets WHERE bucket<?',(time.time()-30*86400,));db.commit()
  except (sqlite3.Error,OSError):
   with _lock:_dropped+=sum(r[5] for r in rows)
   log.warning('Telemetry aggregate batch unavailable; request processing continues')
  finally:
   if db:db.close()

def start():
 global _thread
 if _thread and _thread.is_alive():return
 try:
  db=connect(path());db.close()
 except (sqlite3.Error,OSError):log.warning('Telemetry storage unavailable; application startup continues')
 _stop.clear()
 def loop():
  while not _stop.wait(5):flush()
 _thread=threading.Thread(target=loop,name='studio-aggregate-metrics',daemon=True);_thread.start()
def stop():
 _stop.set()
 if _thread:_thread.join(timeout=4)
 flush()

def history(hours=24):
 flush();db=connect(path())
 try:
  rows=[dict(x) for x in db.execute('SELECT kind,route,status,release,sum(n) n,sum(total_ms) total_ms,'+','.join(f'sum(b{x}) b{x}' for x in range(8))+',sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,sum(usage_known) usage_known FROM telemetry_buckets WHERE bucket>=? GROUP BY kind,route,status,release ORDER BY kind,route',(time.time()-hours*3600,))]
 finally:db.close()
 for row in rows:
  target=math.ceil(row['n']*.95);cumulative=0;p95=None
  for i,bound in enumerate((*BOUNDS,None)):
   cumulative+=row.pop('b'+str(i))
   if cumulative>=target:p95=bound;break
  # Remove any unvisited histogram fields as well.
  for i in range(8):row.pop('b'+str(i),None)
  row['mean_ms']=round(row.pop('total_ms')/row['n'],2);row['p95_upper_bound_ms']=p95
 with _lock:dropped=_dropped;buffered=sum(x[0] for x in _pending.values())
 resources={'logical_cpus':os.cpu_count(),'host_load_average':list(os.getloadavg()) if hasattr(os,'getloadavg') else None}
 for name,file in [('cgroup_memory_current_bytes','/sys/fs/cgroup/memory.current'),('cgroup_memory_max_bytes','/sys/fs/cgroup/memory.max'),('cgroup_cpu_usage','/sys/fs/cgroup/cpu.stat')]:
  try:resources[name]=Path(file).read_text().strip()
  except OSError:resources[name]=None
 return {'hours':hours,'rows':rows,'resources':resources,'retention_days':30,'buffer_seconds':5,'buffered_samples':buffered,'dropped_samples_this_process':dropped,'p95_method':'Histogram upper bound; null means >5000ms. Mean and counts are exact for retained samples. Up to one unflushed batch can be lost on process failure. No raw URLs, queries, emails, user IDs, or prompts stored.'}

def alerts(hours=1):
 data=history(hours);http=[x for x in data['rows'] if x['kind']=='http'];total=sum(x['n'] for x in http);errors=sum(x['n'] for x in http if x['status'].startswith('5'));out=[]
 if total>=20 and errors/total>.05:out.append({'code':'http_error_rate','observed':round(errors/total,4),'threshold':.05,'samples':total})
 for row in http:
  if row['n']>=20 and (row['p95_upper_bound_ms'] is None or row['p95_upper_bound_ms']>float(os.getenv('STUDIO_HTTP_P95_ALERT_MS','1000'))):out.append({'code':'http_latency','route':row['route'],'p95_upper_bound_ms':row['p95_upper_bound_ms'],'samples':row['n']})
 providers=defaultdict(lambda:[0,0])
 for row in data['rows']:
  if row['kind']=='provider':providers[row['route']][0]+=row['n'];providers[row['route']][1]+=row['n'] if row['status']!='ok' else 0
 for name,(n,failed) in providers.items():
  if n>=5 and failed/n>.2:out.append({'code':'provider_failure_rate','provider':name,'attempts':n,'failed':failed})
 with core.connection() as db:
  queue=db.execute("SELECT count(*) n,min(q.requested_at) oldest FROM games g LEFT JOIN analysis_jobs q ON q.game_id=g.id WHERE g.stage IN ('pending','running')").fetchone()
  failures=db.execute("SELECT count(*) FROM games WHERE stage='error'").fetchone()[0]
 age=max(0,time.time()-queue['oldest']) if queue['oldest'] else None
 if age is not None and age>float(os.getenv('STUDIO_QUEUE_ALERT_SECONDS','900')):out.append({'code':'queue_wait','age_seconds':round(age),'pending_or_running':queue['n']})
 if failures:out.append({'code':'analysis_errors','games':failures})
 return {'alerts':out,'window_hours':hours,'sample_count':total,'queue':{'pending_or_running':queue['n'],'oldest_request_age_seconds':age},'notification':'Poll this authenticated endpoint or run scripts/check_operations.py from a monitoring timer. No external alert destination is enabled automatically.'}
