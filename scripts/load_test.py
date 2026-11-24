"""Measure 10/25/50 simulated users against an automatically isolated local fixture."""
import argparse,asyncio,json,math,os,socket,sqlite3,statistics,subprocess,sys,tempfile,time,threading,logging
from collections import Counter
from pathlib import Path
from contextlib import closing
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

async def workload(base,users,concurrency,seconds):
 durations=[];statuses=Counter();failures=0
 clients=[httpx.AsyncClient(base_url=base,timeout=30,trust_env=False,cookies={'studio_session':u['cookie']},headers={'X-CSRF-Token':u['csrf']}) for u in users[:concurrency]]
 # Prepare clients and warm connections before timing, so every virtual user
 # participates for the complete measured interval.
 await asyncio.gather(*(client.get('/api/me') for client in clients))
 until=time.monotonic()+seconds
 async def virtual(index):
  nonlocal failures
  user=users[index];paths=['/api/me','/api/games?limit=20','/api/analysis/jobs','/api/training/plan','/api/training/diagnostics','/api/analysis/speed'];n=0
  client=clients[index]
  try:
   while time.monotonic()<until:
    started=time.perf_counter()
    try:
     if n%7==6:r=await client.put('/api/analysis/speed',json={'preset':'turbo'})
     else:r=await client.get(paths[n%7])
     statuses[str(r.status_code)]+=1
     if r.status_code>=400:failures+=1
    except httpx.HTTPError:statuses['transport_error']+=1;failures+=1
    durations.append((time.perf_counter()-started)*1000);n+=1
    await asyncio.sleep(.03)
  finally:await client.aclose()
 await asyncio.gather(*(virtual(i) for i in range(concurrency)))
 values=sorted(durations);n=len(values)
 return {'virtual_users':concurrency,'duration_seconds':seconds,'requests':n,'statuses':dict(statuses),'error_rate':failures/n if n else 1,'p50_ms':round(statistics.median(values),2) if n else None,'p95_ms':round(values[max(0,math.ceil(n*.95)-1)],2) if n else None,'max_ms':round(max(values),2) if n else None}

def main():
 logging.getLogger('httpx').setLevel(logging.WARNING)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--levels',default='10,25,50');p.add_argument('--seconds',type=int,default=10);p.add_argument('--port',type=int,default=18026);p.add_argument('--engine',action='store_true');p.add_argument('--output',type=Path,required=True);p.add_argument('--max-p95-ms',type=float);p.add_argument('--max-error-rate',type=float,default=.01);a=p.parse_args()
 levels=[int(x) for x in a.levels.split(',')]
 if not levels or any(x<1 or x>50 for x in levels) or not 1<=a.seconds<=300:p.error('levels 1..50; seconds 1..300')
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',a.port))==0:p.error('Port already in use; existing applications are never reused')
 with tempfile.TemporaryDirectory(prefix='chess-load-') as td:
  root=Path(td);command=[sys.executable,str(Path(__file__).with_name('load_server.py')),'--root',str(root),'--port',str(a.port)]+(['--engine'] if a.engine else [])
  log=(root/'server.log').open('w');server=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT);worker=None;stop_worker=threading.Event()
  try:
   base=f'http://127.0.0.1:{a.port}';config=None
   with httpx.Client(timeout=2,trust_env=False) as client:
    for _ in range(120):
     if server.poll() is not None:raise RuntimeError('Isolated load server did not start; inspect dependency setup')
     try:
      if (root/'credentials.json').is_file():
       config=json.loads((root/'credentials.json').read_text());r=client.get(base+'/health')
       if r.status_code==200 and r.headers.get('X-Chess-Load-Fixture')==config['nonce']:break
     except (httpx.HTTPError,ValueError):pass
     time.sleep(.5)
    else:raise RuntimeError('Fixture health/identity verification failed')
   if a.engine:
    os.environ.update(STUDIO_DB=str(root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(root/'knowledge.sqlite3'),STUDIO_ENGINE_THREADS='1',STUDIO_ENGINE_HASH_MB='32')
    from studio import worker as engine_worker
    if not Path(engine_worker.STOCKFISH).is_file():raise ValueError('--engine requires an installed Stockfish executable')
    def run_engine():
     while not stop_worker.is_set():
      if not engine_worker.job():stop_worker.wait(.1)
    worker=threading.Thread(target=run_engine,name='isolated-load-engine',daemon=True);worker.start()
   results=[asyncio.run(workload(base,config['users'],n,a.seconds)) for n in levels]
   with closing(sqlite3.connect(root/'studio.sqlite3')) as db:engine={'cached_positions':db.execute('SELECT count(*) FROM shared_engine_scans WHERE scan_json IS NOT NULL').fetchone()[0],'completed_fixture_games':db.execute("SELECT count(*) FROM games WHERE stage='done'").fetchone()[0]}
   report={'fixture':'Synthetic local-only workloads, 50 isolated accounts; not real users or historical games','background_stockfish':a.engine,'engine':engine,'results':results,'host_cpu_count':os.cpu_count(),'python':sys.version.split()[0],'method':'Closed-loop virtual users after client/connection warm-up, 30ms think time, six authenticated read routes and one preference write per seven requests; p95 uses nearest rank. External AI, SMTP, billing and archive sync are disabled. Results characterize this machine, not production capacity.'}
   report['passed']=all(x['error_rate']<=a.max_error_rate and (a.max_p95_ms is None or x['p95_ms']<=a.max_p95_ms) for x in results)
   fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'w',encoding='utf8') as out:json.dump(report,out,indent=2)
   print(json.dumps(report));return 0 if report['passed'] else 1
  finally:
   if worker:
    stop_worker.set();worker.join(timeout=15)
   server.terminate()
   try:server.wait(timeout=15)
   except subprocess.TimeoutExpired:server.kill();server.wait()
   log.close()
if __name__=='__main__':raise SystemExit(main())
