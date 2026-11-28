"""Isolated 10/25/50-user advertising concurrency smoke, never production data."""
import argparse,json,os,secrets,sqlite3,statistics,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def run(campaigns=1000,history=20000):
 with tempfile.TemporaryDirectory(prefix='chess-ad-load-') as temporary:
  root=Path(temporary)
  os.environ.update(STUDIO_DB=str(root/'studio.sqlite3'),CHESS_KNOWLEDGE_DB=str(root/'knowledge.sqlite3'),CONTROL_PRIVATE_DIR=str(root/'private'),DATABASE_PATH=str(root/'legacy.sqlite3'),CHESS_LIBRARY_DB=str(root/'no-catalogue.sqlite3'),TEACHER_PROVIDERS_FILE=str(root/'no-providers.json'),TEACHER_KEY_FILE=str(root/'no-key'),STUDIO_BASE_URL='http://testserver')
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
  from studio.app import app,start
  from studio import core
  from studio.control_models import Campaign
  from fastapi.testclient import TestClient
  import hashlib,random
  start();clients=[];tokens=[];now=time.time()
  with core.connection() as db:
   for i in range(50):
    uid=db.execute('INSERT INTO users(email,pass_hash,role,created_at,chess_username) VALUES(?,?,?,?,?)',(f'load-{i}@example.test','unusable-load-fixture-hash','user',core.now(),'load_fixture'+str(i))).lastrowid
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,now+3600));tokens.append((uid,token,csrf))
   for i in range(campaigns):
    value=Campaign(id=f'{i:032x}',title_ar='اختبار ضغط معزول',title_en='Isolated load fixture',kind='custom',placement=('screen_top','screen_bottom','screen_left','screen_right')[i%4],enabled=True,starts_at=now-86400,ends_at=now+86400,daily_cap=10,cooldown_minutes=1,priority=i%100).model_dump()
    value['views_json']=json.dumps(value.pop('views'));value['updated_at']=core.now()
    db.execute('INSERT INTO control_ads('+','.join(value)+') VALUES('+','.join('?' for _ in value)+')',tuple(value.values()))
   rng=random.Random(0)
   db.executemany('INSERT INTO control_ad_deliveries(id,user_id,campaign_id,created_at,shown_at) VALUES(?,?,?,?,?)',[(f'history-{i}',tokens[i%50][0],f'{rng.randrange(campaigns):032x}',now-172800,now-172800) for i in range(history)])
  for uid,token,csrf in tokens:
   client=TestClient(app);client.cookies.set('studio_session',token);clients.append((client,csrf))
  reports=[]
  try:
   for level in (10,25,50):
    def action(index):
     client,csrf=clients[index];ctx={'visit':f'load-{level}:{index}','view':'home','width':1920};headers={'X-CSRF-Token':csrf};started=time.perf_counter()
     selected=client.post('/api/promotions/banners/select',json=ctx,headers=headers);assert selected.status_code==200,selected.text
     items=selected.json()['items'];assert 0<len(items)<=20
     poll=client.get('/api/promotions/banners',params=ctx);assert poll.status_code==200
     impression=client.post('/api/promotions/banners/'+items[0]['id']+'/impression',json=ctx,headers=headers);assert impression.status_code==200 and impression.json()['show']
     return (time.perf_counter()-started)*1000
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=level) as pool:latencies=list(pool.map(action,range(level)))
    reports.append({'users':level,'transactions':level,'requests':level*3,'errors':0,'median_transaction_ms':round(statistics.median(latencies),2),'p95_transaction_ms':round(statistics.quantiles(latencies,n=20)[18],2),'elapsed_seconds':round(time.perf_counter()-started,3)})
   with core.connection() as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
  finally:
   for client,_ in clients:client.close()
  return {'status':'passed','isolated':True,'google_requests':0,'campaigns':campaigns,'historical_delivery_fixtures':history,'levels':reports,'scope':'Synthetic local ASGI transactions (select, poll, impression), not a public-network capacity guarantee.'}

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();result=run()
 if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
 print(json.dumps(result))
