import gzip,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from studio import core
from studio.knowledge import store
from scripts.export_public_database import export,PUBLIC_TABLES

class ExportTests(unittest.TestCase):
 def test_release_artifact_integrity_and_legal_moves(self):
  from scripts.verify_public_database import verify
  result=verify(Path(__file__).resolve().parents[1]/'database')
  self.assertEqual(result['integrity'],'ok');self.assertGreater(result['legal_puzzles_verified'],5000)
 def test_allowlist_excludes_private_rows_caches_and_unused_metadata(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);main=root/'main.sqlite3';knowledge=root/'knowledge.sqlite3'
   with patch.object(core,'DB',main),patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(knowledge)}):
    core.setup();store.setup()
    with core.connection() as db:db.execute('INSERT INTO control_settings VALUES(?,?)',('private_test',json.dumps('SECRET_MAIN_ROW_123456')))
    with store.connection() as db:
     db.execute('INSERT INTO kc_meta VALUES(?,?)',('opening_revision','test-public-revision'))
     db.execute('INSERT INTO kc_meta VALUES(?,?)',('private_meta','SECRET_METADATA_123456'))
     db.execute('INSERT INTO kc_external_cache VALUES(?,?,?,?)',('test','key','SECRET_CACHE_123456',0))
     db.execute('INSERT INTO kc_positions VALUES(?,?)',('private-position','SECRET_POSITION_123456'))
     db.execute('INSERT INTO kc_edges VALUES(?,?,?,?)',('private-position','e2e4','private-next','SECRET_EDGE_123456'))
     db.execute('INSERT INTO kc_puzzles VALUES(?,?,?,?,?,?,?,?,?)',('private-puzzle','SECRET_PUZZLE_123456','unused','[]',0,'','','','generated:private'))
    report=export(main,knowledge,root/'export');raw=gzip.decompress((root/'export/public-knowledge.sqlite3.gz').read_bytes())
    for marker in (b'SECRET_MAIN_ROW_123456',b'SECRET_METADATA_123456',b'SECRET_CACHE_123456',b'SECRET_POSITION_123456',b'SECRET_EDGE_123456',b'SECRET_PUZZLE_123456'):self.assertNotIn(marker,raw)
    for name in ('studio.schema.sql','knowledge.schema.sql'):
     ddl=(root/'export'/name).read_text(encoding='utf8');self.assertNotIn('SECRET_',ddl)
     db=sqlite3.connect(':memory:');db.executescript(ddl);self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');db.close()
    self.assertFalse(report['private_data_included']);self.assertEqual(report['tables']['kc_meta'],1)
    (root/'check.sqlite3').write_bytes(raw);db=sqlite3.connect(root/'check.sqlite3')
    self.assertTrue({x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}<=set(PUBLIC_TABLES));db.close()

if __name__=='__main__':unittest.main()
