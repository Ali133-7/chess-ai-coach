import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play
from studio.knowledge.store import setup as setup_knowledge
from studio.locale import LANGUAGE,language,parse,model_instruction
from studio.teacher_v7.dialogue import kind

class LocaleTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.temp.name)/'studio.sqlite3';self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.temp.name)/'knowledge.sqlite3')});self.env.start();core.setup();setup_teacher();setup_play();setup_knowledge();self.client=TestClient(app)
  self.client.post('/api/auth/register',json={'email':'locale@example.net','password':'locale-test-password-123'})
  me=self.client.get('/api/me').json();self.headers={'X-CSRF-Token':me['csrf'],'Accept-Language':'en-US,en;q=0.9'}
  with core.connection() as db:self.gid=db.execute("INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,stage,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(me['id'],'locale','https://example.net','1. e4 e5 1-0',1234,'a','b','1-0','done',core.now())).lastrowid
 def tearDown(self):core.DB=self.old;self.env.stop();self.temp.cleanup()
 def test_language_input_is_limited_and_context_resets(self):
  self.assertEqual(parse('en-GB,en;q=0.7'),'en');self.assertEqual(parse('ar-IQ'),'ar');self.assertEqual(parse('javascript:alert(1)'),'ar')
  token=LANGUAGE.set('en')
  try:self.assertEqual(language(),'en');self.assertIn('English',model_instruction());self.assertIn('schema keys',model_instruction())
  finally:LANGUAGE.reset(token)
  self.assertEqual(language(),'ar')
 def test_english_identity_is_local_and_arabic_request_restores_language(self):
  with patch('studio.teacher_v7.router.fetch_position',side_effect=AssertionError('identity must not analyze a move')),patch('studio.teacher_v7.providers.generate',side_effect=AssertionError('identity must not call LLM')):
   a=self.client.post('/api/teacher/chat',json={'game_id':self.gid,'ply':1,'question':'Who are you?'},headers=self.headers);self.assertEqual(a.status_code,200,a.text);self.assertIn('chess learning assistant',a.json()['explanation_ar']);self.assertEqual(a.json()['answer_kind'],'general')
   b=self.client.post('/api/teacher/chat',json={'game_id':self.gid,'ply':1,'question':'من أنت؟'},headers={**self.headers,'Accept-Language':'ar'});self.assertEqual(b.status_code,200);self.assertIn('أنا المعلّم',b.json()['explanation_ar'])
 def test_english_question_routing_and_strict_csp(self):
  self.assertEqual(kind('Why this move?'),'position');self.assertEqual(kind('What is the Sicilian Defense?'),'general');self.assertEqual(kind('Hello!'),'greeting')
  csp=self.client.get('/').headers['Content-Security-Policy'];self.assertIn("style-src 'self'",csp);self.assertNotIn('unsafe-inline',csp)
 def test_all_legacy_controls_preserved_and_new_controls_unique(self):
  class Ids(HTMLParser):
   def __init__(self):super().__init__();self.ids=[];self.styles=[]
   def handle_starttag(self,tag,attrs):
    d=dict(attrs)
    if 'id' in d:self.ids.append(d['id'])
    if 'style' in d:self.styles.append(d['style'])
  static=Path(__import__('studio.app',fromlist=['static']).static);new=Ids();new.feed((static/'index.html').read_text(encoding='utf-8'));self.assertEqual(len(new.ids),len(set(new.ids)));self.assertEqual(new.styles,[])
  for name in ['kc-practice-mode','kc-study-mode','kc-start-recommended','kc-next-puzzle','auth-form','password-form','kc-board','training-teaching','lesson-reveal','admin-form']:self.assertIn(name,new.ids)


 def test_summary_dashboard_defers_only_hidden_grade_counts(self):
  with patch('studio.app.game_analysis_counts',side_effect=AssertionError('summary must not aggregate hidden grades')):
   response=self.client.get('/api/dashboard?summary_only=true');self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json()['grades_deferred']);self.assertEqual(response.json()['grades'],{})
  with patch('studio.app.game_analysis_counts',return_value={'good':7}) as counted:
   response=self.client.get('/api/dashboard');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['grades'],{'good':7});self.assertFalse(response.json()['grades_deferred']);self.assertEqual(counted.call_count,1)

 def test_static_cache_never_caches_private_responses(self):
  public=self.client.get('/assets/i18n.js?v=performance-test');self.assertEqual(public.status_code,200);self.assertIn('immutable',public.headers['Cache-Control'])
  piece=self.client.get('/assets/pieces/wK.png');self.assertEqual(piece.status_code,200);self.assertIn('public',piece.headers['Cache-Control']);self.assertNotIn('no-store',piece.headers['Cache-Control'])
  plain=self.client.get('/assets/i18n.js');self.assertIn('must-revalidate',plain.headers['Cache-Control'])
  etag=piece.headers.get('etag');self.assertTrue(etag);cached=self.client.get('/assets/pieces/wK.png',headers={'If-None-Match':etag});self.assertEqual(cached.status_code,304)
  for url in ['/','/api/me','/api/knowledge/status?v=test','/api/games']:
   self.assertEqual(self.client.get(url).headers['Cache-Control'],'no-store')

 def test_translation_catalog_has_every_static_arabic_label(self):
  import re
  static=Path(__import__('studio.app',fromlist=['static']).static);catalog=json.loads((static/'translations.en.json').read_text(encoding='utf-8'))
  class Labels(HTMLParser):
   def __init__(self):super().__init__();self.labels=[];self.ignored=0
   def handle_starttag(self,tag,attrs):
    if tag in ['style','script']:self.ignored+=1
    for k,v in attrs:
     if k in ['title','aria-label','placeholder','alt'] and v:self.labels.append(v)
   def handle_endtag(self,tag):
    if tag in ['style','script']:self.ignored=max(0,self.ignored-1)
   def handle_data(self,data):
    if not self.ignored:self.labels.append(data)
  parser=Labels();parser.feed((static/'index.html').read_text(encoding='utf-8'));missing=[]
  for label in parser.labels:
   s=' '.join(label.split())
   if re.search('[\u0600-\u06ff]',s) and s not in catalog:missing.append(s)
  self.assertEqual(missing,[])

if __name__=='__main__':unittest.main()
