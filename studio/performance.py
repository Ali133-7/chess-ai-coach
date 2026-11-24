"""Bounded process-local HTTP measurements and durable engine-cache counters."""
from collections import defaultdict,deque
from threading import Lock
from time import perf_counter
import secrets
from math import ceil
from . import core
_samples=defaultdict(lambda:deque(maxlen=128));_lock=Lock()

def install(app,admin):
 from fastapi import Depends
 @app.middleware('http')
 async def timing(request,call_next):
  from . import telemetry
  started=perf_counter();request_id=secrets.token_hex(16)
  try:response=await call_next(request)
  except Exception:
   telemetry.record('http',getattr(request.scope.get('route'),'path','unmatched'),'500',(perf_counter()-started)*1000)
   raise
  duration=(perf_counter()-started)*1000
  route=getattr(request.scope.get('route'),'path','static-or-unmatched')
  with _lock:
   if route in _samples or len(_samples)<96:_samples[route].append(duration)
  response.headers['Server-Timing']='studio;dur='+format(duration,'.2f')
  response.headers['X-Request-ID']=request_id
  telemetry.record('http',route,str(response.status_code),duration)
  return response
 @app.get('/api/analysis/metrics')
 def metrics(user=Depends(admin)):
  with _lock:routes=[{'route':k,'samples':len(v),'mean_ms':round(sum(v)/len(v),2),'p95_ms':round(sorted(v)[max(0,ceil(len(v)*.95)-1)],2)} for k,v in _samples.items() if v]
  with core.connection() as db:
   cache=dict(db.execute('SELECT count(*) entries,coalesce(sum(hits),0) hits FROM shared_engine_scans').fetchone())
   jobs=[dict(r) for r in db.execute('SELECT stage,count(*) n FROM games GROUP BY stage')]
  return {'http':routes,'engine_cache':cache,'jobs':jobs,'scope':'HTTP samples are process-local, last 128 per route; cache counters are durable. Engine and end-to-end browser times differ.'}
 from . import telemetry
 app.on_event('startup')(telemetry.start)
 app.on_event('shutdown')(telemetry.stop)
 @app.get('/api/operations/metrics')
 def durable_metrics(hours:int=24,user=Depends(admin)):
  from fastapi import HTTPException
  if not 1<=hours<=720:raise HTTPException(422,'hours must be 1..720')
  return telemetry.history(hours)
 @app.get('/api/operations/alerts')
 def operational_alerts(user=Depends(admin)):return telemetry.alerts()
