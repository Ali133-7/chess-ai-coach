"""Advertising uses disposable accounts and synthetic IDs, never merchant/ad calls."""
import json,sqlite3,time,unittest,io
from PIL import Image,PngImagePlugin
from contextlib import closing,contextmanager
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from studio import core,control_store
from studio import advertising
import test_control_center as fixture

class AdvertisingTests(unittest.TestCase):
 setUp=fixture.ControlTests.setUp
 tearDown=fixture.ControlTests.tearDown
 post=fixture.ControlTests.post
 put=fixture.ControlTests.put
 plan=fixture.ControlTests.plan
 def campaign(self,**changes):
  now=time.time();data={'title_ar':'حملة اختبار معزولة','title_en':'Isolated test campaign','placement':'screen_top','event':'home_visit','kind':'custom','starts_at':now-10,'ends_at':now+172800,'enabled':True,'daily_cap':3,'cooldown_minutes':1,**changes}
  r=self.put('/api/control/campaigns/new',data);self.assertEqual(r.status_code,200,r.text);return r.json()['id']
 def context(self,visit='visit-1',width=1920,view='home'):return {'visit':visit,'width':width,'view':view}
 def select(self,**kwargs):
  context=self.context(**kwargs);r=self.post('/api/promotions/banners/select',context,1);self.assertEqual(r.status_code,200,r.text);return r.json()
 def impression(self,cid,**kwargs):return self.post('/api/promotions/banners/'+cid+'/impression',self.context(**kwargs),1)
 def configure(self,**changes):
  cfg=self.clients[0].get('/api/control/advertising').json()['settings'];cfg.update(changes);r=self.put('/api/control/advertising',cfg);self.assertEqual(r.status_code,200,r.text);return r.json()['settings']
 def test_control_permissions_csrf_and_version_conflicts(self):
  self.assertEqual(self.clients[1].get('/api/control/advertising').status_code,403)
  cfg=self.clients[0].get('/api/control/advertising').json()['settings']
  self.assertEqual(self.clients[0].put('/api/control/advertising',json=cfg).status_code,403)
  self.assertEqual(self.put('/api/control/advertising',{**cfg,'side_min_width':1440}).status_code,422)
  self.configure(max_active=2)
  self.assertEqual(self.put('/api/control/advertising',cfg).status_code,409)
 def test_four_placements_wide_only_and_slot_switches(self):
  ids={p:self.campaign(placement=p) for p in ('screen_top','screen_bottom','screen_left','screen_right')}
  narrow=self.select(width=1799);self.assertEqual({c['placement'] for c in narrow['items']},{'screen_top','screen_bottom'})
  wide=self.select(width=1800);self.assertEqual({c['id'] for c in wide['items']},set(ids.values()))
  cfg=self.configure(side_min_width=1920);cfg['slots']['screen_left']=False;self.configure(slots=cfg['slots'])
  self.assertNotIn(ids['screen_left'],[c['id'] for c in self.select()['items']])
  self.assertFalse(self.impression(ids['screen_right'],width=1919).json()['show'])
 def test_schedule_visibility_view_and_global_pause(self):
  self.campaign(visible=False);self.campaign(views=['knowledge']);self.campaign(starts_at=time.time()+100)
  valid=self.campaign();self.assertEqual([c['id'] for c in self.select()['items']],[valid])
  self.configure(enabled=False);self.assertEqual(self.select()['items'],[]);self.assertFalse(self.impression(valid).json()['show'])
 def test_no_ads_membership_and_administrator_never_receive_inventory(self):
  cid=self.campaign();self.assertEqual(self.post('/api/promotions/banners/select',self.context(),0).json()['items'],[])
  p=self.plan();self.put(f'/api/control/users/{self.uids[1]}/membership',{'plan_id':p['id'],'days':2,'reason':'test no advertising'})
  self.assertEqual(self.select()['items'],[]);self.assertFalse(self.impression(cid).json()['show'])
 def test_distinct_visit_threshold_and_visible_impression_dedup(self):
  cid=self.campaign(after_n=2)
  self.assertEqual(self.select()['items'],[]);self.assertEqual(self.select()['items'],[])
  self.assertEqual([c['id'] for c in self.select(visit='visit-2')['items']],[cid])
  first=self.impression(cid,visit='visit-2').json();again=self.impression(cid,visit='visit-2').json()
  self.assertTrue(first['show']);self.assertEqual(first['delivery_id'],again['delivery_id']);self.assertTrue(again['duplicate'])
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM control_ad_deliveries').fetchone()[0],1)
 def test_parallel_impressions_are_atomic_and_count_once(self):
  cid=self.campaign();self.select()
  with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:self.impression(cid).json(),range(2)))
  self.assertTrue(all(r['show'] for r in responses));self.assertEqual(len({r['delivery_id'] for r in responses}),1)
 def test_one_campaign_per_placement_and_maximum_active_enforced(self):
  a=self.campaign();b=self.campaign();c=self.campaign(placement='screen_bottom');self.configure(max_active=1);self.select()
  self.assertTrue(self.impression(a).json()['show']);self.assertFalse(self.impression(b).json()['show']);self.assertFalse(self.impression(c).json()['show'])
 def test_shown_campaign_remains_stable_on_poll_without_new_impression(self):
  cid=self.campaign();self.select();self.impression(cid)
  response=self.clients[1].get('/api/promotions/banners',params=self.context()).json();self.assertIn(cid,[c['id'] for c in response['items']])
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM control_ad_deliveries').fetchone()[0],1)
 def test_cooldown_daily_cap_and_dismissal_are_server_enforced(self):
  cid=self.campaign(daily_cap=1);self.select();self.impression(cid)
  self.assertEqual(self.select(visit='visit-2')['items'],[]);self.assertFalse(self.impression(cid,visit='visit-2').json()['show'])
  fresh=self.campaign(placement='screen_bottom');self.select(visit='visit-3')
  self.assertEqual(self.post('/api/promotions/banners/'+fresh+'/dismiss',{},1).status_code,200)
  self.assertNotIn(fresh,[c['id'] for c in self.select(visit='visit-4')['items']]);self.assertFalse(self.impression(fresh,visit='visit-4').json()['show'])
 def test_priority_then_least_recent_and_pause_state_version(self):
  low=self.campaign(priority=1);high=self.campaign(priority=90);items=self.select()['items'];self.assertEqual(items[0]['id'],high)
  self.assertEqual(self.post('/api/control/campaigns/'+high+'/state',{'action':'hide','version':1}).status_code,200)
  self.assertNotIn(high,[c['id'] for c in self.select()['items']]);self.assertFalse(self.impression(high).json()['show'])
  self.assertEqual(self.post('/api/control/campaigns/'+high+'/state',{'action':'show','version':1}).status_code,409)
  self.assertEqual(self.post('/api/control/campaigns/'+low+'/state',{'action':'pause','version':1},1).status_code,403)
 def test_invalid_context_and_arbitrary_code_are_rejected(self):
  for changes in ({'view':'admin'},{'width':-1},{'visit':'<script>'}):self.assertEqual(self.post('/api/promotions/banners/select',{**self.context(),**changes},1).status_code,422)
  self.assertEqual(self.clients[1].get('/api/promotions/banners',params={**self.context(),'view':'admin'}).status_code,422)
  data={'title_ar':'a','title_en':'b','starts_at':time.time(),'ends_at':time.time()+100,'kind':'adsense','placement':'modal','adsense_slot':'1234567890'}
  self.assertEqual(self.put('/api/control/campaigns/new',data).status_code,422)
  data.update(placement='screen_top',script='<script>alert(1)</script>');self.assertEqual(self.put('/api/control/campaigns/new',data).status_code,422)
 def test_google_requires_valid_account_consent_and_password(self):
  cfg=self.clients[0].get('/api/control/advertising').json()['settings']
  self.assertEqual(self.put('/api/control/advertising',{**cfg,'google_enabled':True}).status_code,422)
  self.assertEqual(self.put('/api/control/advertising',{**cfg,'google_enabled':True,'google_consent_ready':True,'google_client':'ca-pub-1234567890123456','confirm_password':'wrong'}).status_code,403)
  self.configure(google_enabled=True,google_consent_ready=True,google_client='ca-pub-1234567890123456',confirm_password='test-training-pass-12345')
  self.assertIn('google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0',self.clients[1].get('/ads.txt').text)
  self.assertFalse(self.select()['config']['google_ready'],'testserver does not match the configured HTTPS hostname')
 def test_nonce_is_user_host_and_entitlement_bound(self):
  self.configure(google_enabled=True,google_consent_ready=True,google_client='ca-pub-1234567890123456',confirm_password='test-training-pass-12345');self.campaign(kind='adsense',adsense_slot='1234567890')
  def request(who,host='studio.example.net'):return SimpleNamespace(url=SimpleNamespace(hostname=host),cookies={'studio_session':self.clients[who].cookies.get('studio_session')})
  self.assertIsNone(advertising.bootstrap_nonce(request(0)));self.assertIsNone(advertising.bootstrap_nonce(request(1,'localhost')))
  one=advertising.bootstrap_nonce(request(1));two=advertising.bootstrap_nonce(request(1));self.assertTrue(one);self.assertNotEqual(one,two)
  self.assertIn("'unsafe-eval'",advertising.google_csp(one));self.assertIn("'strict-dynamic'",advertising.google_csp(one))
  self.plan();self.put(f'/api/control/users/{self.uids[1]}/membership',{'plan_id':'pro','days':1,'reason':'no ads test'});self.assertIsNone(advertising.bootstrap_nonce(request(1)))
 def test_default_csp_and_nonce_template_preserve_security(self):
  page=self.clients[1].get('/');self.assertIn("script-src 'self'",page.headers['content-security-policy']);self.assertNotIn('unsafe-inline',page.headers['content-security-policy'])
  with patch('studio.advertising.bootstrap_nonce',return_value='test-nonce-only'):
   page=self.clients[1].get('/');self.assertIn("'nonce-test-nonce-only'",page.headers['content-security-policy']);self.assertIn('<script nonce="test-nonce-only"',page.text)
 def test_media_is_decoded_reencoded_stripped_and_cacheable(self):
  image=Image.new('RGB',(64,32),'red');raw=io.BytesIO();meta=PngImagePlugin.PngInfo();meta.add_text('private-note','strip-this-metadata');image.save(raw,format='PNG',pnginfo=meta)
  r=self.clients[0].post('/api/control/media',content=raw.getvalue(),headers=self.headers[0]);self.assertEqual(r.status_code,200,r.text)
  r=self.clients[1].get(r.json()['path']);self.assertEqual(r.status_code,200);self.assertIn('immutable',r.headers['cache-control']);self.assertNotIn(b'strip-this-metadata',r.content)
  with Image.open(io.BytesIO(r.content)) as saved:self.assertEqual(saved.size,(64,32));saved.load()
 def test_media_deduplication_and_storage_budget(self):
  output=io.BytesIO();Image.new('RGB',(20,20),'blue').save(output,format='PNG');raw=output.getvalue()
  a=self.clients[0].post('/api/control/media',content=raw,headers=self.headers[0]);b=self.clients[0].post('/api/control/media',content=raw,headers=self.headers[0]);self.assertEqual(a.json()['path'],b.json()['path'])
  output=io.BytesIO();Image.new('RGB',(20,20),'green').save(output,format='PNG')
  with patch('studio.ad_media.MAX_STORED_BYTES',1):self.assertEqual(self.clients[0].post('/api/control/media',content=output.getvalue(),headers=self.headers[0]).status_code,413)
 def test_media_rejects_truncation_huge_dimensions_and_animation(self):
  from studio.ad_media import normalise
  for raw in (b'\x89PNG\r\n\x1a\n'+b'x'*80,b'\xff\xd8\xffhello\xff\xd9',b'RIFF'+b'1234WEBP'+b'x'*30):
   self.assertEqual(self.clients[0].post('/api/control/media',content=raw,headers=self.headers[0]).status_code,422)
  output=io.BytesIO();Image.new('RGB',(4097,1)).save(output,format='PNG')
  self.assertEqual(self.clients[0].post('/api/control/media',content=output.getvalue(),headers=self.headers[0]).status_code,422)
  output=io.BytesIO();Image.new('RGB',(2,2),'red').save(output,format='WEBP',save_all=True,append_images=[Image.new('RGB',(2,2),'blue')],duration=100,loop=0)
  self.assertEqual(self.clients[0].post('/api/control/media',content=output.getvalue(),headers=self.headers[0]).status_code,422)
 def test_webp_canvas_is_bounded_before_native_decoder_opens(self):
  from studio import ad_media
  from fastapi import HTTPException
  canvas=bytes(4)+(9999).to_bytes(3,'little')+(9999).to_bytes(3,'little')
  raw=b'RIFF'+(22).to_bytes(4,'little')+b'WEBPVP8X'+(10).to_bytes(4,'little')+canvas
  with patch.object(ad_media.Image,'open',side_effect=AssertionError('Decoder must not open an oversized canvas')):
   with self.assertRaises(HTTPException) as error:ad_media.normalise(raw)
  self.assertEqual(error.exception.status_code,422)
 def test_upload_authentication_precedes_body_and_ad_json_is_bounded(self):
  from fastapi.testclient import TestClient
  from studio.app import app
  consumed=[]
  def body():consumed.append(True);yield b'x'*10000
  with TestClient(app) as anonymous:
   self.assertEqual(anonymous.post('/api/control/media',content=body()).status_code,401)
  self.assertEqual(consumed,[])
  from studio.ad_payload import validate_json
  for text in ('[{'+chr(92)+chr(34)+']}' , '['*100):self.assertEqual(validate_json(json.dumps({'text':text}).encode())['text'],text)
  self.assertEqual(validate_json(b'['*32+b'0'+b']'*32),json.loads(b'['*32+b'0'+b']'*32))
  cid=self.campaign();self.assertEqual(self.clients[1].post('/api/promotions/banners/'+cid+'/dismiss',headers=self.headers[1]).status_code,200)
  self.assertEqual(validate_json(b'{"text":"\\ud83d\\ude00"}')['text'],'\U0001f600')
  for bad in (b'{"\\ud800":1}',b'{"value":NaN}',b'{"value":1e9999}'):
   self.assertEqual(self.clients[1].post('/api/promotions/banners/select',content=bad,headers={**self.headers[1],'Content-Type':'application/json'}).status_code,400)
  nested=b'['*1500+b']'*1500
  self.assertEqual(self.clients[1].post('/api/promotions/banners/select',content=nested,headers={**self.headers[1],'Content-Type':'application/json'}).status_code,400)
  self.assertEqual(self.clients[1].post('/api/promotions/banners/select',content=b'{}',headers={**self.headers[1],'Content-Length':'9'*5000}).status_code,413)
  self.assertEqual(self.clients[1].post('/api/promotions/banners/select',content=b'x'*(64*1024+1),headers=self.headers[1]).status_code,413)
 def test_media_concurrency_budget_and_content_size(self):
  from studio import ad_media
  self.assertTrue(ad_media._decoders.acquire(False));self.assertTrue(ad_media._decoders.acquire(False))
  try:self.assertEqual(self.clients[0].post('/api/control/media',content=b'x'*100,headers=self.headers[0]).status_code,429)
  finally:ad_media._decoders.release();ad_media._decoders.release()
  self.assertEqual(self.clients[0].post('/api/control/media',content=b'x'*(2*1024*1024+1),headers=self.headers[0]).status_code,413)
 def test_no_inventory_creates_no_visit_records(self):
  self.assertEqual(self.select()['items'],[])
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM control_ad_events').fetchone()[0],0)
 def test_many_campaigns_are_ranked_with_bounded_queries_and_fallback(self):
  now=time.time();template=self.campaign();self.configure(google_enabled=True,google_consent_ready=True,google_client='ca-pub-1234567890123456',confirm_password='test-training-pass-12345')
  with core.connection() as db:
   columns=[r[1] for r in db.execute('PRAGMA table_info(control_ads)')];base=dict(db.execute('SELECT * FROM control_ads WHERE id=?',(template,)).fetchone())
   for index in range(1000):
    row={**base,'id':f'{index:032x}','priority':index%100}
    db.execute('INSERT INTO control_ads('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[k] for k in columns])
  statements=[];original=core.connection
  @contextmanager
  def traced():
   with original() as db:
    db.set_trace_callback(statements.append);yield db
  with patch.object(core,'connection',traced):items=self.select()['items']
  self.assertLessEqual(sum(q.lstrip().upper().startswith(('SELECT','WITH')) for q in statements),20)
  self.assertLessEqual(len(items),4);self.assertTrue(all(x['priority']==99 for x in items));self.assertFalse(any('slot_rank' in x for x in items))
  listing=self.clients[0].get('/api/control/campaigns',params={'page':2,'limit':10}).json();self.assertEqual(listing['total'],1001);self.assertEqual(len(listing['items']),10)
  found=self.clients[0].get('/api/control/campaigns',params={'q':'Isolated test campaign','filter':'custom','limit':100}).json();self.assertEqual(found['total'],1001)
  self.assertEqual(self.clients[0].get('/api/control/campaigns',params={'limit':101}).status_code,422)
 def test_google_dismissal_click_and_invalid_timestamps_are_rejected(self):
  cid=self.campaign(kind='adsense',adsense_slot='1234567890')
  self.assertEqual(self.post('/api/promotions/banners/'+cid+'/dismiss',{},1).status_code,404)
  with core.connection() as db:db.execute("INSERT INTO control_ad_deliveries(id,user_id,campaign_id,created_at,shown_at) VALUES(?,?,?,?,?)",('google-delivery',self.uids[1],cid,time.time(),time.time()))
  self.assertEqual(self.post('/api/promotions/google-delivery/click',{},1).status_code,404)
  from studio.control_models import Campaign
  with self.assertRaises(ValueError):Campaign(title_ar='a',title_en='b',starts_at=0,ends_at=float('inf'))
  with self.assertRaises(ValueError):Campaign(title_ar='a',title_en='b',starts_at=0,ends_at=1e308)
  bad={'title_ar':'a','title_en':'b','starts_at':0,'ends_at':1e308}
  self.assertEqual(self.put('/api/control/campaigns/new',bad).status_code,422)
 def test_corrupted_ad_settings_disable_ads_without_breaking_home(self):
  with core.connection() as db:db.execute("INSERT OR REPLACE INTO control_settings VALUES('advertising','invalid-json')")
  self.assertEqual(self.clients[1].get('/').status_code,200);self.assertFalse(self.select()['config']['enabled'])
 def test_account_delete_removes_advertising_preferences(self):
  cid=self.campaign();self.select();self.impression(cid);self.post('/api/promotions/banners/'+cid+'/dismiss',{},1)
  self.assertEqual(self.clients[1].delete('/api/account',headers=self.headers[1]).status_code,200)
  with core.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM control_ad_dismissals').fetchone()[0],0)
 def test_parallel_service_startup_migrates_once_without_losing_rows(self):
  path=Path(self.temp.name)/'parallel-control.sqlite3';barrier=Barrier(2)
  with closing(sqlite3.connect(path)) as db:db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(9);')
  def migrate(_):
   with closing(sqlite3.connect(path,timeout=20)) as db:
    db.row_factory=sqlite3.Row;barrier.wait(timeout=10);control_store.setup(db);db.commit()
  with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(migrate,range(2)))
  with closing(sqlite3.connect(path)) as db:
   self.assertEqual(db.execute('SELECT id FROM users').fetchall(),[(9,)])
   self.assertEqual(db.execute('SELECT count(*) FROM control_plans').fetchone()[0],1)
   self.assertIn('banner_placement',{r[1] for r in db.execute('PRAGMA table_info(control_ad_deliveries)')})
   self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
 def test_additive_legacy_migration_keeps_campaign_and_delivery_ids(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(9); CREATE TABLE control_ads(id TEXT PRIMARY KEY,title_ar TEXT NOT NULL,title_en TEXT NOT NULL,body_ar TEXT NOT NULL,body_en TEXT NOT NULL,image_path TEXT NOT NULL,link_url TEXT NOT NULL,button_ar TEXT NOT NULL,button_en TEXT NOT NULL,placement TEXT NOT NULL,event TEXT NOT NULL,after_n INTEGER NOT NULL,daily_cap INTEGER NOT NULL,cooldown_minutes INTEGER NOT NULL,plan_id TEXT,enabled INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL,priority INTEGER NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE control_ad_deliveries(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),campaign_id TEXT NOT NULL REFERENCES control_ads(id),created_at REAL NOT NULL,clicked_at REAL);')
  values=('old','قديم','Old','','','','','','','home_top','home_visit',1,1,1440,None,1,1,9999999999,0,1,'old-date');db.execute('INSERT INTO control_ads VALUES('+','.join('?'*21)+')',values);db.execute("INSERT INTO control_ad_deliveries VALUES('delivery',9,'old',1,NULL)")
  control_store.setup(db);control_store.setup(db);row=db.execute("SELECT * FROM control_ads WHERE id='old'").fetchone()
  self.assertEqual(tuple(row)[:21],values);self.assertEqual(row['kind'],'custom');self.assertEqual(row['visible'],1);self.assertEqual(db.execute("SELECT visit_key FROM control_ad_deliveries WHERE id='delivery'").fetchone()[0],'');self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall());db.close()

if __name__=='__main__':unittest.main()
