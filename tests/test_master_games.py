import os,io,json,sqlite3,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import chess,chess.pgn
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.knowledge import store,masters
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play

FIXTURE=Path(__file__).parent/'fixtures/master-first.pgn'
if not FIXTURE.exists():FIXTURE=Path(__file__).parent/'master-data/grandmaster-games.pgn'
class MasterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DB;core.DB=Path(self.tmp.name)/'studio.sqlite3'
  self.env=patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(Path(self.tmp.name)/'knowledge.sqlite3')});self.env.start()
  core.setup();setup_teacher();setup_play();store.setup()
  with FIXTURE.open(encoding='utf8') as f:self.game=chess.pgn.read_game(f)
  self.pgn=Path(self.tmp.name)/'single.pgn';self.pgn.write_text(self.game.accept(chess.pgn.StringExporter(headers=True,variations=False,comments=True))+'\n',encoding='utf8')
  masters.import_pgn(self.pgn,hashlib.sha256(self.pgn.read_bytes()).hexdigest(),'https://database.lichess.org/#broadcasts')
  self.gid=masters.search()['items'][0]['id']
 def tearDown(self):core.DB=self.old;self.env.stop();self.tmp.cleanup()
 def test_metadata_names_year_and_source(self):
  g=masters.detail(self.gid);self.assertEqual(g['white'],self.game.headers['White']);self.assertEqual(g['black'],self.game.headers['Black']);self.assertEqual(g['year'],int(self.game.headers['Date'][:4]));self.assertEqual(g['license'],'CC-BY-SA-4.0');self.assertTrue(g['source_url'].startswith('https://lichess.org/broadcast/'))
 def test_complete_game_moves_and_bilingual_facts(self):
  g=masters.detail(self.gid);b=chess.Board(g['initial_fen']);self.assertFalse(b.chess960)
  self.assertEqual(len(g['path']),len(list(self.game.mainline_moves())))
  for s in g['path']:
   m=chess.Move.from_uci(s['uci']);self.assertIn(m,b.legal_moves);self.assertEqual(s['san'],b.san(m));b.push(m);self.assertEqual(s['fen'],b.fen());self.assertTrue(s['note']['ar']['why']);self.assertTrue(s['note']['en']['watch']);self.assertEqual(s['source'],'master');self.assertEqual(set(s['legal_moves']),{m.uci() for m in b.legal_moves})
 def test_source_evaluations_keep_provenance(self):
  g=masters.detail(self.gid);evals=[s['evaluation'] for s in g['path'] if s['evaluation']];self.assertTrue(evals)
  for e in evals:self.assertEqual(e['source'],'broadcast-eval');self.assertIsNone(e['nodes']);self.assertIn('broadcast',e['engine'])
  self.assertTrue(all(s['loss_cp_estimate'] is None for s in g['path']),'unknown source engine budgets cannot grade moves')
 def test_import_resume_and_deduplication(self):
  first=masters.search()['total'];masters.import_pgn(self.pgn,'same','https://database.lichess.org/#broadcasts');self.assertEqual(masters.search()['total'],first)
  with store.connection() as db:db.execute("UPDATE kc_master_imports SET cursor=0,status='pending'")
  masters.import_pgn(self.pgn,'same','https://database.lichess.org/#broadcasts');self.assertEqual(masters.search()['total'],first)
 def test_filters_are_literal_and_bounded(self):
  self.assertEqual(masters.search(year=int(self.game.headers['Date'][:4]))['total'],1);self.assertEqual(masters.search(year=1801)['total'],0);self.assertEqual(masters.search('%')['total'],0);self.assertEqual(masters.search("' OR 1=1 --")['total'],0);self.assertEqual(masters.search(offset=1)['items'],[])
 def test_gm_titles_and_known_year_required(self):
  for field,value in [('WhiteTitle','IM'),('BlackTitle',''),('Date','????.??.??'),('Result','*')]:
   g=chess.pgn.read_game(io.StringIO(self.pgn.read_text(encoding='utf8')));g.headers[field]=value
   with self.assertRaises(ValueError):masters.clean_game(g)
 def test_chess960_rejected_even_if_variant_header_says_standard(self):
  g=chess.pgn.read_game(io.StringIO(self.pgn.read_text(encoding='utf8')));g.headers['FEN']='rnbbnkqr/pppppppp/8/8/8/8/PPPPPPPP/RNBBNKQR w KQkq - 0 1';g.headers['Variant']='Standard'
  with self.assertRaises(ValueError):masters.clean_game(g)
 def test_auth_download_and_payload_limits(self):
  c=TestClient(app);self.assertEqual(c.get('/api/knowledge/masters').status_code,401);self.assertEqual(c.get('/api/knowledge/masters/'+self.gid).status_code,401)
  self.assertEqual(c.post('/api/auth/register',json={'email':'master-test@example.net','password':'master-test-password-123'}).status_code,201)
  self.assertEqual(c.get('/api/knowledge/masters?limit=500').status_code,422);self.assertEqual(c.get('/api/knowledge/masters?year=0').status_code,422)
  r=c.get('/api/knowledge/masters/'+self.gid);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['white'],self.game.headers['White'])
  r=c.get('/api/knowledge/masters/'+self.gid+'/pgn');self.assertEqual(r.status_code,200,r.text);self.assertIn('CC BY-SA',r.text);self.assertIn(self.game.headers['White'],r.text);self.assertEqual(r.headers['Cache-Control'],'no-store');parsed=chess.pgn.read_game(io.StringIO(r.text));self.assertEqual(parsed.headers['White'],self.game.headers['White']);self.assertEqual(len(list(parsed.mainline_moves())),len(list(self.game.mainline_moves())));self.assertIn('CC BY-SA',parsed.headers['License'])
 def test_missing_game_has_no_fabricated_payload(self):
  from fastapi import HTTPException
  with self.assertRaises(HTTPException) as exc:masters.detail('f'*64)
  self.assertEqual(exc.exception.status_code,404)
 def test_packaged_seed_is_complete_and_legal(self):
  path=store.DATA/'master-games.sqlite3';manifest=json.loads((store.DATA/'master-games-manifest.json').read_text(encoding='utf8'))
  self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),manifest['seed_sha256'])
  db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True)
  self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
  self.assertEqual(db.execute('SELECT count(*) FROM kc_master_games').fetchone()[0],1500)
  self.assertEqual(db.execute("SELECT count(*) FROM kc_master_games WHERE white_title!='GM' OR black_title!='GM' OR white='' OR black='' OR year!=CAST(substr(date,1,4) AS INTEGER)").fetchone()[0],0)
  available={r[0] for r in db.execute('SELECT fen_key FROM kc_master_evals')}
  for fen, in db.execute('SELECT initial_fen FROM kc_master_games'):
   b=chess.Board(fen);self.assertTrue(b.is_valid());self.assertFalse(b.has_chess960_castling_rights())
  count=0
  for fen,note,imported in db.execute('SELECT fen,note_json,imported_eval FROM kc_master_moves'):
   self.assertTrue(chess.Board(fen).is_valid());data=json.loads(note);self.assertTrue(data['ar']['why']);self.assertTrue(data['en']['watch']);self.assertTrue(imported or ' '.join(fen.split()[:5]) in available);count+=1
  self.assertEqual(count,manifest['stats']['moves'])
  for key,payload in db.execute('SELECT fen_key,payload FROM kc_master_evals'):
   b=chess.Board(key+' 1');p=json.loads(payload)
   for u in p['pv']:m=chess.Move.from_uci(u);self.assertIn(m,b.legal_moves);b.push(m)
  db.close()
 def test_seed_merge_is_idempotent_and_checks_hash(self):
  p=store.DATA/'master-games.sqlite3';sha=json.loads((store.DATA/'master-games-manifest.json').read_text(encoding='utf8'))['seed_sha256']
  with self.assertRaises(ValueError):masters.seed(p,'0'*64)
  a=masters.seed(p,sha);b=masters.seed(p,sha);self.assertEqual(a['present'],1500);self.assertEqual(b['present'],1500);self.assertEqual(masters.search()['all_count'],1500)
