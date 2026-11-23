import json,tempfile,time,unittest,copy
from pathlib import Path
from unittest.mock import patch
import chess,httpx
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import store,curriculum as c,placement as p,learning_plans as a
from studio.teacher_v7 import providers
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play

class PlacementPlanTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'main.sqlite3';self.env=patch.dict(__import__('os').environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'kb.sqlite3')});self.env.start();core.setup();setup_teacher();setup_play();store.setup();self.client=TestClient(app);self.client.post('/api/auth/register',json={'email':'placement@example.net','password':'placement-tests-12345'});me=self.client.get('/api/me').json();self.uid=me['id'];self.csrf={'X-CSRF-Token':me['csrf']};self.cfg={'primary':'groq','fallback':['xai'],'providers':{n:{'model':'test-model','key_file':'/private/not-read'} for n in ['groq','xai']}}
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def err(self,code,fn,*args,**kw):
  with self.assertRaises(Exception) as e:fn(*args,**kw)
  self.assertEqual(e.exception.status_code,code)
 def complete_assessment(self,correct=True):
  s=p.start(self.uid)
  while not s['complete']:
   if not correct:s=p.answer(s['id'],self.uid,s['version'],skip=True);continue
   task=p.tasks()[s['cursor']];x=c.lesson(task['lid'])
   if task['kind']=='board':s=p.answer(s['id'],self.uid,s['version'],uci=x['example']['moves'][x['practice_from']])
   else:
    with core.connection() as db:state=json.loads(db.execute('select state_json from learning_placement_sessions where id=?',(s['id'],)).fetchone()[0])
    s=p.answer(s['id'],self.uid,s['version'],answer=state['orders'][s['cursor']].index(0))
  return s
 def make_eligible(self,stage=8):
  result={'status':'assessed','start_stage':stage,'scores':[],'created_at':core.now()}
  with core.connection() as db:
   db.execute('insert into learning_placement_results values(?,?,?,?,?)',('fixture-result',self.uid,p.VERSION,json.dumps(result),core.now()))
   for x in c.data()['lessons']:
    if x['stage']>=stage:db.execute('insert into learning_progress values(?,?,?,?,?,?,?,?)',(self.uid,c.data()['revision'],x['id'],core.now(),1,0,'2099-01-01T00:00:00+00:00','fixture'))
 def fake_generate(self,cfg,instructions,supplied,**kw):
  pool=supplied['ACTIVITIES'];chosen=pool[:5]+[next(x for x in pool if x['type']=='personal')]
  result=a.Plan(title={'ar':'خطة متابعة','en':'Follow-up'},summary={'ar':'مراجعة وتطبيق','en':'Review and practice'},items=[{'activity_id':x['id'],'sessions':2,'minutes':15,'goal':{'ar':'احسب ثم قارن تفسيرك','en':'Calculate, then compare your reasoning'}} for x in chosen]);return result,100,200,'groq','test-model'
 def mocked_generate(self):return (patch.object(a.service,'provider_config',return_value=self.cfg),patch.object(providers,'status',return_value={'ready':True}),patch.object(providers,'generate',side_effect=self.fake_generate))
 def test_all_tasks_are_real_legal_and_complete_separately_from_elo(self):
  self.assertEqual(len(p.tasks()),16)
  s=self.complete_assessment();r=s['result'];self.assertEqual(r['correct'],16);self.assertEqual(r['start_stage'],8);self.assertEqual(r['readiness_percent'],100);self.assertNotIn('elo',r);self.assertEqual(c.catalog(self.uid)['completed'],0);self.assertEqual(c.catalog(self.uid)['assigned_total'],6)
 def test_all_unknown_starts_from_zero(self):self.assertEqual(self.complete_assessment(False)['result']['start_stage'],1)
 def test_initial_questions_do_not_leak_answers(self):
  s=p.start(self.uid);self.assertNotIn('answer',s['task']);self.assertNotIn('result',s['task']);self.assertEqual(len(s['task']['options']),3)
 def test_first_answer_only_and_version_guard(self):
  s=p.start(self.uid);r=p.answer(s['id'],self.uid,0,skip=True);self.err(409,p.answer,s['id'],self.uid,0,skip=True);self.assertEqual(r['cursor'],1)
 def test_resume_and_user_isolation(self):
  s=p.start(self.uid);r=p.answer(s['id'],self.uid,0,skip=True);self.assertEqual(p.start(self.uid)['cursor'],1);self.err(404,p.answer,s['id'],self.uid+1,1,skip=True)
 def test_illegal_board_move_rejected_without_score_change(self):
  s=p.start(self.uid);s=p.answer(s['id'],self.uid,0,skip=True);self.assertEqual(s['task']['kind'],'board');self.err(422,p.answer,s['id'],self.uid,s['version'],uci='a1a8');self.assertEqual(p.start(self.uid)['cursor'],1)
 def test_reliable_rating_cap_and_no_cross_format_average(self):
  answers=[{'stage':i,'correct':True} for i in range(1,9) for _ in range(2)];rating={'source':'chess.com-pubapi','ratings':{'rapid':{'reliable':True,'readiness_stage':2,'rating':700},'blitz':{'reliable':True,'readiness_stage':8,'rating':2300}}}
  self.assertEqual(p.recommend(answers,rating,'rapid')['start_stage'],3);self.assertEqual(p.recommend(answers,rating,'blitz')['start_stage'],8);rating['ratings']['rapid']['reliable']=False;self.assertEqual(p.recommend(answers,rating,'rapid')['start_stage'],8)
 def test_test_gap_is_not_overridden_by_high_rating(self):
  answers=[{'stage':i,'correct':i!=2} for i in range(1,9) for _ in range(2)];r=p.recommend(answers,{'ratings':{'rapid':{'reliable':True,'readiness_stage':8}}},'rapid');self.assertEqual(r['start_stage'],2)
 def test_missing_link_and_skip_do_not_invent_a_rating(self):
  self.assertEqual(p.snapshot(self.uid,True)['source'],'unlinked');p.skip_placement(self.uid);self.assertEqual(c.catalog(self.uid)['start_stage'],1);self.assertEqual(c.catalog(self.uid)['completed'],0)
 def test_fetch_fixed_endpoint_cache_rd_and_freshness(self):
  with core.connection() as db:db.execute("update users set chess_username='safe_player' where id=?",(self.uid,))
  real=httpx.Client;calls=[]
  def handler(req):
   calls.append(req);return httpx.Response(200,json={'chess_rapid':{'last':{'rating':1234,'rd':50,'date':int(time.time())},'record':{'win':12,'loss':10,'draw':1}},'chess_blitz':{'last':{'rating':2200,'rd':170,'date':int(time.time())},'record':{'win':500}}})
  with patch.object(p.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
   r=p.snapshot(self.uid,True);self.assertTrue(r['ratings']['rapid']['reliable']);self.assertFalse(r['ratings']['blitz']['reliable']);p.snapshot(self.uid,True)
  self.assertEqual(len(calls),1);self.assertEqual(str(calls[0].url),'https://api.chess.com/pub/player/safe_player/stats')
 def test_old_sync_rating_is_visible_but_not_reliable(self):
  with core.connection() as db:
   db.execute("update users set chess_username='safe_player' where id=?",(self.uid,));db.execute('insert into ratings values(?,?,?,?,?,?,?,?)',(self.uid,'rapid',1200,1500,10,10,0,core.now()))
  r=p.snapshot(self.uid);self.assertEqual(r['source'],'local-sync');self.assertFalse(r['ratings']['rapid']['reliable'])
 def test_stale_snapshot_does_not_become_fresh_after_network_failure(self):
  with core.connection() as db:
   db.execute("update users set chess_username='safe_player' where id=?",(self.uid,));db.execute('insert into learning_rating_snapshots values(?,?,?,?)',(self.uid,'safe_player',json.dumps({'ratings':{'rapid':{'rating':1200,'reliable':True}},'fetched_at':1,'source':'chess.com-pubapi'}),1))
  with patch.object(p.httpx,'Client',side_effect=httpx.ConnectError('hidden')):r=p.snapshot(self.uid,True)
  self.assertEqual(r['source'],'stale-cache');self.assertFalse(r['ratings']['rapid']['reliable']);self.assertEqual(r['fetched_at'],1)
 def test_assigned_route_counts_only_real_completed_lessons(self):
  self.make_eligible(8);r=c.catalog(self.uid);self.assertTrue(r['route_completed']);self.assertEqual(r['completed'],6);self.assertEqual(r['assigned_total'],6);self.assertFalse(r['lessons'][0]['completed'])
 def test_generation_is_locked_before_route_end(self):self.err(409,a.generate,self.uid)
 def test_generated_ids_resolve_to_local_pool_and_are_cached(self):
  self.make_eligible();p1,p2,p3=self.mocked_generate()
  with p1,p2,p3 as gen:
   r=a.generate(self.uid);again=a.generate(self.uid);self.assertEqual(r['id'],again['id']);self.assertEqual(gen.call_count,1)
  self.assertEqual(len(r['plan']['items']),6);self.assertEqual(r['provider'],'groq');self.assertEqual(r['plan']['activities'][-1]['type'],'personal');self.assertNotIn('placement@example',json.dumps(r))
 def test_generated_context_excludes_private_identifiers_and_raw_games(self):
  self.make_eligible();ctx,pool=a.context(self.uid);raw=json.dumps([ctx,pool]);self.assertNotIn('placement@example',raw);self.assertNotIn('pass_hash',raw);self.assertNotIn('pgn',raw);self.assertNotIn('chess_username',raw)
 def test_invalid_ids_are_rejected_not_rendered(self):
  self.make_eligible();p1,p2,p3=self.mocked_generate()
  bad=a.Plan(title={'ar':'خطة','en':'Plan'},summary={'ar':'شرح','en':'Why'},items=[{'activity_id':'invented:'+str(i),'sessions':1,'minutes':10,'goal':{'ar':'عمل','en':'Work'}} for i in range(6)])
  with p1,p2,patch.object(providers,'generate',return_value=(bad,1,1,'groq','x')):self.err(503,a.generate,self.uid)
 def test_failed_generation_preserves_progress_and_sanitizes_errors(self):
  self.make_eligible();p1,p2,p3=self.mocked_generate()
  with p1,p2,patch.object(providers,'generate',side_effect=providers.ProviderError('DO-NOT-EXPOSE-SECRET','network_timeout')):self.err(503,a.generate,self.uid)
  self.assertEqual(c.catalog(self.uid)['completed'],6);self.assertIsNone(a.status(self.uid)['latest'])
 def test_activity_progress_is_owner_scoped_and_bounded(self):
  self.make_eligible();p1,p2,p3=self.mocked_generate()
  with p1,p2,p3:r=a.generate(self.uid)
  self.assertEqual(a.mark(r['id'],self.uid,0,True)['done'],[0]);self.err(404,a.mark,r['id'],self.uid+1,0,True);self.err(422,a.mark,r['id'],self.uid,99,True)
 def test_http_csrf_auth_validation_and_cache(self):
  anon=TestClient(app);self.assertEqual(anon.get('/api/learning/placement').status_code,401);self.assertEqual(self.client.get('/api/learning/placement').headers['cache-control'],'no-store');self.assertEqual(self.client.post('/api/learning/placement/start',json={}).status_code,403);self.assertEqual(self.client.post('/api/learning/placement/start',json={'format':'elo'},headers=self.csrf).status_code,422);self.assertEqual(self.client.get('/api/learning/followup').status_code,200)
 def test_additive_setup_is_idempotent(self):
  p.setup();a.setup();p.setup();a.setup()
  with core.connection() as db:self.assertEqual(db.execute('select count(*) from users').fetchone()[0],1)
 def test_generic_plan_transport_all_four_providers_and_fallback(self):
  key=Path(self.tmp.name)/'test-key';key.write_text('fake-key-at-least-15');key.chmod(0o600);cfg={'primary':'groq','fallback':[],'providers':{n:{'model':'openai/gpt-oss-20b' if n=='groq' else 'test-model','key_file':str(key)} for n in providers.ENDPOINTS}};answer=self.fake_generate(None,'',{'ACTIVITIES':[{'id':'lesson:'+str(i),'type':'lesson'} for i in range(5)]+[{'id':'personal:review','type':'personal'}]})[0].model_dump();real=httpx.Client;calls=[]
  def handler(req):
   calls.append(req);name=next(n for n,u in providers.ENDPOINTS.items() if str(req.url)==u);body=json.loads(req.content);self.assertNotIn('scenario_notes',json.dumps(body));self.assertNotIn('fake-key',req.content.decode());result={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]} if name=='openai' else {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]};return httpx.Response(200,json=result)
  for name in providers.ENDPOINTS:
   cfg['primary']=name
   with patch.object(providers.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):r=providers.generate(cfg,'bilingual',{},answer_type=a.Plan,schema=a.Plan.model_json_schema(),task_name='test_plan',apply_locale=False)
   self.assertEqual(r[3],name)
  cfg['primary']='groq';cfg['fallback']=['xai']
  def fallback(req):return httpx.Response(429,json={}) if str(req.url)==providers.ENDPOINTS['groq'] else handler(req)
  with patch.object(providers.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(fallback),**kw)):r=providers.generate(cfg,'bilingual',{},answer_type=a.Plan,schema=a.Plan.model_json_schema(),task_name='test_plan',apply_locale=False)
  self.assertEqual(r[3],'xai')

if __name__=='__main__':unittest.main()
