"""Real PGN fixture: import, resume, compact replay, provenance and legacy compatibility."""
import hashlib,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import chess,chess.pgn,zstandard
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import game_library as library,store,masters
from scripts.build_game_library import Builder,import_archive,download

FIXTURE=Path(__file__).parent/'fixtures/master-first.pgn'
URL='https://database.lichess.org/broadcast/lichess_db_broadcast_2024-01.pgn.zst'

class LibraryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.old=core.DB;core.DB=self.root/'studio.sqlite3'
  self.db=self.root/'master-library.sqlite3';self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(self.root/'knowledge.sqlite3'),'CHESS_LIBRARY_DB':str(self.db)});self.env.start()
  core.setup();store.setup();self.raw=FIXTURE.read_text(encoding='utf8');self.file=self.root/'archive.zst'
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def archive(self,raw=None):
  self.file.write_bytes(zstandard.ZstdCompressor().compress((raw or self.raw).encode()));self.item={'url':URL,'sha256':hashlib.sha256(self.file.read_bytes()).hexdigest(),'month':'2024-01'};return self.item
 def run_import(self,**kwargs):return import_archive(self.db,self.item,self.file,min_free_bytes=0,**kwargs)
 def test_compact_import_complete_legal_replay_and_source_scores(self):
  self.archive();self.run_import();result=masters.search();self.assertEqual(result['total'],1);g=masters.detail(result['items'][0]['id'])
  self.assertEqual(g['storage'],'compact-local-library');self.assertEqual(g['year'],2024);self.assertEqual(g['license'],library.LICENSE);self.assertEqual(g['provenance'][0]['sha256'],self.item['sha256'])
  board=chess.Board(g['initial_fen'])
  for step in g['path']:
   move=chess.Move.from_uci(step['uci']);self.assertIn(move,board.legal_moves);self.assertEqual(step['san'],board.san(move));board.push(move);self.assertEqual(board.fen(),step['fen']);self.assertTrue(step['note']['ar']['why']);self.assertIsNone(step['loss_cp_estimate'])
  original=chess.pgn.read_game(io.StringIO(self.raw));self.assertEqual(len(g['path']),len(list(original.mainline_moves())))
  self.assertGreater(g['analysis_coverage'],0);self.assertNotIn('%clk',g['pgn']);self.assertNotIn('%eval',g['pgn'])
 def test_resume_and_cross_archive_duplicate_provenance(self):
  self.archive(self.raw+'\n\n'+self.raw);self.run_import(max_records=1);self.assertEqual(library.status()['games'],1);self.run_import();self.assertEqual(library.status()['archives'][0]['cursor'],2);self.assertEqual(library.status()['archives'][0]['duplicates'],1)
  self.item['url']=URL.replace('2024-01','2024-02');self.run_import();self.assertEqual(library.status()['games'],1)
  with library.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM library_provenance').fetchone()[0],2)
  self.assertEqual(self.run_import()['status'],'complete')
 def test_filters_fts_escaping_and_seed_deduplication(self):
  self.archive();self.run_import();gid=masters.search()['items'][0]['id'];masters.import_pgn(FIXTURE,'seed-test',library.SOURCE)
  self.assertEqual(masters.search()['total'],1);self.assertEqual(masters.search()['all_count'],1)
  for query in ('Pragg','Giri','Rapport','D01','Pragg Giri'):self.assertEqual(masters.search(query)['total'],1)
  self.assertEqual(masters.search('%')['total'],0);self.assertEqual(masters.search('" OR *')['total'],0);self.assertEqual(masters.search(year=1801)['total'],0);self.assertEqual(masters.search(offset=1)['items'],[])
  self.assertEqual(masters.detail(gid)['id'],gid)
 def test_gm_policy_and_all_scope(self):
  self.archive(self.raw.replace('[WhiteTitle "GM"]','[WhiteTitle "IM"]'));self.run_import();self.assertEqual(library.status()['games'],0)
  other=self.root/'all.sqlite3';import_archive(other,self.item,self.file,scope='all',min_free_bytes=0)
  with patch.dict(os.environ,{'CHESS_LIBRARY_DB':str(other)}):
   self.assertEqual(masters.search()['total'],0);self.assertEqual(masters.search(scope='all')['total'],1)
 def test_date_fallback_and_truncated_game_rejection(self):
  raw=self.raw.replace('[Date "2024.01.18"]','[Date "????.??.??"]\n[UTCDate "2024.01.18"]');self.archive(raw);self.run_import();self.assertEqual(masters.search()['total'],1)
  with self.assertRaises(ValueError):
   g,reason,body=chess.pgn.read_game(io.StringIO(self.raw.rsplit('1/2-1/2',1)[0]),Visitor=lambda:Builder('gm'));library.pack_game(g,URL,body)
  g,_,body=chess.pgn.read_game(io.StringIO(self.raw.replace('2024.01.18','2024.02.31')),Visitor=lambda:Builder('gm'))
  with self.assertRaises(ValueError):library.pack_game(g,URL,body)
 def test_checksum_scope_drift_and_payload_bounds(self):
  self.archive();self.run_import()
  with self.assertRaises(ValueError):self.run_import(scope='all')
  self.file.write_bytes(b'bad')
  with self.assertRaises(ValueError):self.run_import()
  with self.assertRaises(ValueError):library.unpack(__import__('zlib').compress(b'x'*100),maximum=10)
  with self.assertRaises(ValueError):download({'url':'http://127.0.0.1/private','sha256':'0'*64},self.root)
 def test_incremental_repetition_matches_rules_and_forbids_continuation(self):
  # Synthetic legal rule fixture, never part of the historical game dataset.
  g=chess.pgn.Game();g.headers.update(White='Rule fixture',Black='Rule fixture',Date='2024.01.01',Result='1/2-1/2');node=g;board=g.board()
  for uci in ['g1f3','g8f6','f3g1','f6g8']*4:
   move=chess.Move.from_uci(uci);node=node.add_variation(move);board.push(move)
  self.assertTrue(board.is_fivefold_repetition());library.pack_game(g,URL,'1/2-1/2')
  node.add_variation(chess.Move.from_uci('e2e4'))
  with self.assertRaises(ValueError):library.pack_game(g,URL,'1/2-1/2')
 def test_api_auth_status_and_complete_export(self):
  self.archive();self.run_import();gid=masters.search()['items'][0]['id'];client=TestClient(app)
  self.assertEqual(client.get('/api/knowledge/masters/library-status').status_code,401)
  self.assertEqual(client.post('/api/auth/register',json={'email':'library@example.test','password':'library-real-test-password'}).status_code,201)
  self.assertEqual(client.get('/api/knowledge/masters/library-status').json()['games'],1)
  self.assertEqual(client.get('/api/knowledge/masters?scope=bad').status_code,422)
  response=client.get('/api/knowledge/masters/'+gid+'/pgn');self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
  parsed=chess.pgn.read_game(io.StringIO(response.text));self.assertEqual(parsed.headers['White'],'Praggnanandhaa, R');self.assertIn('CC BY-SA',parsed.headers['License']);self.assertGreater(len(list(parsed.mainline_moves())),40)
 def test_missing_catalog_does_not_create_file(self):
  self.assertFalse(library.available());self.assertEqual(library.status()['games'],0);self.assertFalse(self.db.exists());self.assertEqual(masters.search()['total'],0)
 def test_parallel_cli_uses_verified_local_archives_and_resumes(self):
  self.archive();archives=self.root/'archives';archives.mkdir();items=[]
  for month in ('2024-01','2024-02'):
   url=URL.replace('2024-01',month);(archives/url.rsplit('/',1)[1]).write_bytes(self.file.read_bytes());items.append(dict(url=url,month=month,sha256=self.item['sha256']))
  manifest=self.root/'manifest.json';manifest.write_text(json.dumps({'license':library.LICENSE,'archives':items}))
  command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/build_game_library.py'),'--database',str(self.db),'--work-directory',str(archives),'--manifest',str(manifest),'--scope','gm','--workers','2','--reserve-free-gb','0']
  first=subprocess.run(command,capture_output=True,text=True,timeout=40);self.assertEqual(first.returncode,0,first.stderr);self.assertEqual(library.status()['games'],1)
  self.assertEqual(len(library.status()['archives']),2);self.assertTrue(all(r['status']=='complete' for r in library.status()['archives']))
  second=subprocess.run(command,capture_output=True,text=True,timeout=40);self.assertEqual(second.returncode,0,second.stderr);self.assertEqual(library.status()['games'],1)
 def test_public_artifact_install_hash_and_safe_replacement(self):
  from scripts.game_library_artifact import package,install
  self.archive();self.run_import();output=self.root/'release';manifest=package(self.db,output);archive=output/manifest['file'];metadata=output/'game-library-manifest.json';dest=self.root/'installed/master-library.sqlite3'
  self.assertEqual(install(archive,metadata,dest)['games'],1)
  with self.assertRaises(FileExistsError):install(archive,metadata,dest)
  install(archive,metadata,dest,True);self.assertEqual(len(list(dest.parent.glob('*.backup-*'))),1)
  with self.assertRaises(ValueError):install(archive,metadata,self.root/'studio.sqlite3',True)
  raw=archive.read_bytes();archive.write_bytes(raw[:-1]+b'x')
  with self.assertRaises(ValueError):install(archive,metadata,dest,True)
  with library.connection(dest) as db:self.assertEqual(db.execute('SELECT count(*) FROM library_games').fetchone()[0],1)
 def test_rollback_of_failed_batch_does_not_advance_cursor(self):
  self.archive(self.raw+'\n\n'+self.raw);library.setup(self.db)
  real=library.pack_game;calls=0
  def interrupt(*args):
   nonlocal calls
   calls+=1
   if calls==2:raise RuntimeError('interrupted')
   return real(*args)
  with patch.object(library,'pack_game',side_effect=interrupt):
   with self.assertRaises(RuntimeError):self.run_import(batch_size=200)
  self.assertEqual(library.status()['games'],0);self.assertEqual(library.status()['archives'][0]['cursor'],0)
  self.run_import();self.assertEqual(library.status()['games'],1);self.assertEqual(library.status()['archives'][0]['cursor'],2)

if __name__=='__main__':unittest.main()
