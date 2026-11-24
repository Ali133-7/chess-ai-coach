"""Real Figshare PGN, old schema compatibility, source attribution and safe catalogue merge."""
import hashlib,io,json,os,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
import chess,chess.pgn,httpx,zstandard
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import game_library as lib,store,masters
from scripts.import_historical_games import inspect_encoding,import_file,verified_member,CollapseBlankLines
from scripts.build_game_library import import_archive,Builder
from scripts.game_library_artifact import validate,package,install,digest
from scripts.merge_game_libraries import merge
from scripts import fetch_historical_archive as fetcher

FIXTURES=Path(__file__).parent/'fixtures'
class HistoricalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.old=core.DB;core.DB=self.root/'studio.sqlite3'
  self.db=self.root/'master-library.sqlite3';self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(self.root/'knowledge.sqlite3'),'CHESS_LIBRARY_DB':str(self.db)});self.env.start();core.setup();store.setup()
  self.raw=(FIXTURES/'historical-first.pgn').read_text(encoding='utf8');self.zip=self.root/'fixture.zip'
 def tearDown(self):core.DB=self.old;self.env.stop();self.temp.cleanup()
 def archive(self,text=None,encoding='utf8'):
  with zipfile.ZipFile(self.zip,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('all.pgn',(text or self.raw).encode(encoding))
  self.info=inspect_encoding(self.zip,expected_sha=digest(self.zip));return self.info
 def run_import(self,db=None,**kwargs):return import_file(db or self.db,self.zip,self.info,min_free_bytes=0,**kwargs)
 def broadcast(self,path,scope='gm'):
  raw=(FIXTURES/'master-first.pgn').read_bytes();z=self.root/(path.stem+'.zst');z.write_bytes(zstandard.ZstdCompressor().compress(raw))
  item={'url':'https://database.lichess.org/broadcast/lichess_db_broadcast_2024-01.pgn.zst','sha256':digest(z),'month':'2024-01'};import_archive(path,item,z,scope=scope,min_free_bytes=0)
 def test_real_historical_game_complete_source_license_and_unknown_title(self):
  self.archive();self.run_import();r=masters.search(scope='all',source_id='figshare-4276523-v1');self.assertEqual(r['total'],1);self.assertEqual(masters.search()['total'],0)
  g=masters.detail(r['items'][0]['id']);self.assertEqual(g['white'],'Kasparov, Garry');self.assertEqual(g['black'],'Stoffers, Jeffrey');self.assertEqual(g['date'],'2000.03.14');self.assertEqual(g['license'],'CC-BY-4.0');self.assertIn('Ana Schaigorodsky',g['attribution']);self.assertIn('figshare',g['source_url']);self.assertEqual(g['plies'],67)
  b=chess.Board(g['initial_fen'])
  for step in g['path']:
   move=chess.Move.from_uci(step['uci']);self.assertIn(move,b.legal_moves);self.assertEqual(step['san'],b.san(move));b.push(move);self.assertEqual(step['fen'],b.fen());self.assertIsNone(step['evaluation'])
 def test_deposit_extra_blank_lines_do_not_drop_movetext(self):
  expanded=self.raw.replace('\n\n','\n\n\n\n').replace('10. Rb1','\n\n10. Rb1');g=chess.pgn.read_game(CollapseBlankLines(io.StringIO(expanded)));self.assertEqual(len(list(g.mainline_moves())),67)
  self.archive(expanded+'\n\n\n'+expanded);self.run_import();self.assertEqual(lib.status()['games'],1);self.assertEqual(lib.status()['archives'][0]['duplicates'],1)
 def test_header_like_comment_does_not_split_game(self):
  text=self.raw.replace('1. d4','1. d4 {comment\n\n[Event "inside comment"]\n}')
  stream=CollapseBlankLines(io.StringIO(text+'\n\n'+self.raw));first=chess.pgn.read_game(stream);second=chess.pgn.read_game(stream)
  self.assertEqual(len(list(first.mainline_moves())),67);self.assertEqual(len(list(second.mainline_moves())),67);self.assertIsNone(chess.pgn.read_game(stream))
 def test_resume_priority_selection_and_source_provenance(self):
  self.archive(self.raw+'\n\n'+self.raw);self.run_import(max_records=1);self.assertEqual(lib.status()['archives'][0]['cursor'],1);self.run_import();self.assertEqual(lib.status()['archives'][0]['status'],'complete')
  self.run_import(selection={'players':['kasparov']});self.assertEqual(lib.status()['games'],1)
  with lib.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM library_provenance').fetchone()[0],2)
  self.run_import(selection={'players':['morphy']});self.assertEqual(lib.status()['games'],1)
 def test_parallel_partition_policies_cover_source_ordinals_without_gaps(self):
  self.archive('\n\n'.join([self.raw]*5))
  for part in range(3):self.run_import(selection={'partitions':3,'partition':part})
  with lib.connection() as db:
   jobs=[dict(r) for r in db.execute('SELECT * FROM library_archives')];self.assertEqual(len(jobs),3);self.assertTrue(all(r['status']=='complete' and r['cursor']==5 for r in jobs))
   # All five source records are visited exactly once by the selected partitions;
   # identical fixture copies collapse to one game in the public catalogue.
   self.assertEqual(sum(r['accepted']+r['duplicates'] for r in jobs),5);self.assertEqual(db.execute('SELECT count(*) FROM library_games').fetchone()[0],1)
 def test_strict_encoding_crc_and_zip_member_bounds(self):
  # Codec fixture retains the real moves but uses an explicitly synthetic name.
  text=self.raw.replace('Stoffers, Jeffrey','Codec fixture, Jürgen');self.archive(text,encoding='cp1252');self.assertEqual(self.info['encoding'],'cp1252');self.run_import()
  self.assertEqual(masters.search(scope='all')['items'][0]['black'],'Codec fixture, Jürgen')
  with self.assertRaises(ValueError):inspect_encoding(self.zip,expected_sha='0'*64)
  with zipfile.ZipFile(self.zip,'w') as z:z.writestr('../../all.pgn',self.raw)
  with self.assertRaises(ValueError):inspect_encoding(self.zip,expected_sha=digest(self.zip))
  fake=zipfile.ZipInfo('all.pgn');fake.file_size=17*1024**3
  with self.assertRaises(ValueError):verified_member(Mock(infolist=lambda:[fake]))
 def test_invalid_truncated_and_unknown_date_records_are_not_invented(self):
  bad=self.raw.replace('1. d4','1. e5');unknown=self.raw.replace('2000.03.14','????.??.??');truncated=self.raw.rsplit('1-0',1)[0]
  self.archive('\n\n'.join([self.raw,bad,unknown,truncated]));self.run_import();self.assertEqual(lib.status()['games'],1)
  job=lib.status()['archives'][0];self.assertGreater(job['rejected'],0);self.assertGreater(job['skipped'],0)
 def make_v1(self,path):
  g,result,body=chess.pgn.read_game(io.StringIO((FIXTURES/'master-first.pgn').read_text()),Visitor=lambda:Builder('gm'));row=lib.pack_game(g,'fixture:legacy',body)
  with sqlite3.connect(path) as db:
   db.executescript((FIXTURES/'library-v1.schema.sql').read_text());db.executemany('INSERT INTO library_meta VALUES(?,?)',[('schema_version','1'),('license',lib.LICENSE),('source_page',lib.SOURCE)])
   db.execute("INSERT INTO library_archives(url,sha256,scope,status) VALUES('fixture:legacy',?,'gm','complete')",('0'*64,));db.execute('INSERT INTO library_games VALUES('+','.join('?'*19)+')',row);db.execute("INSERT INTO library_provenance VALUES(?,'fixture:legacy',1)",(row[0],))
  return row[0]
 def test_v1_read_package_install_and_additive_migration(self):
  gid=self.make_v1(self.db);original=digest(self.db);self.assertTrue(lib.available());self.assertEqual(masters.detail(gid)['id'],gid)
  meta=package(self.db,self.root/'v1-release',deep=True);self.assertEqual(meta['schema_version'],1);self.assertEqual(digest(self.db),original)
  dest=self.root/'installed/master-library.sqlite3';install(self.root/'v1-release'/meta['file'],self.root/'v1-release/game-library-manifest.json',dest)
  lib.setup(dest)
  with lib.connection(dest) as db:self.assertEqual(db.execute('SELECT id FROM library_games').fetchone()[0],gid);self.assertEqual(db.execute('SELECT source_id FROM library_archives').fetchone()[0],'lichess-broadcasts')
 def test_merge_preserves_ids_licenses_and_distinct_scan_policies(self):
  a=self.root/'a.sqlite3';b=self.root/'b.sqlite3';self.broadcast(a,'gm');self.broadcast(b,'all');self.archive();self.run_import(db=b);hashes=[digest(a),digest(b)]
  result=merge([a,b],self.db);self.assertEqual(result['stats']['games'],2);self.assertEqual(result['merges'][0]['duplicates'],1);self.assertEqual(hashes,[digest(a),digest(b)])
  self.assertEqual(masters.search(scope='all',source_id='figshare-4276523-v1')['total'],1);self.assertEqual(masters.search(source_id='lichess-broadcasts')['total'],1)
  with lib.connection() as db:
   self.assertEqual(db.execute('SELECT count(*) FROM library_provenance').fetchone()[0],3);self.assertEqual(db.execute('SELECT count(*) FROM library_archives').fetchone()[0],3)
  validate(self.db,deep=True)
  again=self.root/'again.sqlite3';merge([self.db,b],again)
  with lib.connection(again) as db:self.assertEqual(db.execute('SELECT count(*) FROM library_games').fetchone()[0],2)
 def test_wrong_source_license_and_private_input_are_rejected(self):
  self.archive();self.run_import()
  with lib.connection(self.db,True) as db:db.execute("UPDATE library_games SET license='CC-BY-SA-4.0'")
  with self.assertRaises(ValueError):validate(self.db)
  with self.assertRaises(ValueError):merge([core.DB],self.root/'unsafe.sqlite3')
  self.assertFalse((self.root/'unsafe.sqlite3').exists())
 def test_api_export_preserves_figshare_credit_and_source_filter(self):
  self.archive();self.run_import();gid=masters.search(scope='all')['items'][0]['id'];c=TestClient(app)
  c.post('/api/auth/register',json={'email':'historical@example.test','password':'historical-fixture-password'})
  self.assertEqual(c.get('/api/knowledge/masters?source_id=unknown').status_code,422)
  self.assertEqual(c.get('/api/knowledge/masters?scope=all&source_id=figshare-4276523-v1').json()['total'],1)
  r=c.get('/api/knowledge/masters/'+gid+'/pgn');self.assertEqual(r.status_code,200);g=chess.pgn.read_game(io.StringIO(r.text));self.assertIn('CC BY 4.0',g.headers['License']);self.assertIn('Ana Schaigorodsky',g.headers['Attribution']);self.assertEqual(len(list(g.mainline_moves())),67)
 def test_fetcher_checks_published_metadata_hashes_and_redirect_hosts(self):
  data=b'synthetic-download-test-only';md5=hashlib.md5(data,usedforsecurity=False).hexdigest();sha=hashlib.sha256(data).hexdigest();real=httpx.Client
  meta={'doi':'10.6084/m9.figshare.4276523.v1','license':{'url':'https://creativecommons.org/licenses/by/4.0/'},'files':[{'id':6971717,'name':'all.pgn.zip','size':len(data),'computed_md5':md5,'download_url':'https://ndownloader.figshare.com/files/6971717'}]}
  def handle(request):return httpx.Response(200,json=meta) if str(request.url)==fetcher.API else httpx.Response(200,content=data)
  with patch.object(fetcher,'SIZE',len(data)),patch.object(fetcher,'MD5',md5),patch.object(fetcher,'SHA256',sha),patch.object(fetcher.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(handle),**kw)):
   proof=fetcher.fetch(self.root/'download');self.assertEqual(proof['sha256'],sha);self.assertEqual(fetcher.fetch(self.root/'download')['sha256'],sha)
  for url in ('http://ndownloader.figshare.com/file','https://127.0.0.1/file','https://evil.amazonaws.com.attacker.test/file'):self.assertFalse(fetcher.allowed(url))

if __name__=='__main__':unittest.main()
