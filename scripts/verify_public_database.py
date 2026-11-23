"""Verify the published database artifact without touching any running database."""
import gzip,hashlib,json,sqlite3,tempfile
from pathlib import Path
import chess
from scripts.export_public_database import PUBLIC_TABLES

def verify(directory):
 root=Path(directory);m=json.loads((root/'manifest.json').read_text(encoding='utf8'))
 assert m['private_data_included'] is False and m['studio_data_rows_exported']==0
 compressed=(root/'public-knowledge.sqlite3.gz').read_bytes()
 assert hashlib.sha256(compressed).hexdigest()==m['gzip_sha256']
 assert 0<m['sqlite_bytes']<=512*1024*1024
 with gzip.GzipFile(fileobj=__import__('io').BytesIO(compressed)) as stream:raw=stream.read(m['sqlite_bytes']+1)
 assert len(raw)==m['sqlite_bytes'] and hashlib.sha256(raw).hexdigest()==m['sqlite_sha256']
 with tempfile.TemporaryDirectory() as temp:
  path=Path(temp)/'check.sqlite3';path.write_bytes(raw);db=sqlite3.connect(path);db.row_factory=sqlite3.Row
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert not db.execute('PRAGMA foreign_key_check').fetchall()
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  assert tables==set(m['tables']) and tables<=set(PUBLIC_TABLES)
  for name,n in m['tables'].items():assert db.execute('SELECT count(*) FROM '+name).fetchone()[0]==n
  assert not db.execute("SELECT 1 FROM kc_master_games WHERE license!='CC-BY-SA-4.0'").fetchone()
  puzzles=0
  for row in db.execute('SELECT fen,moves_json FROM kc_puzzles'):
   board=chess.Board(row['fen']);assert board.is_valid()
   for uci in json.loads(row['moves_json']):
    move=chess.Move.from_uci(uci);assert move in board.legal_moves;board.push(move)
   puzzles+=1
  for row in db.execute('SELECT * FROM kc_generated_exercises'):
   assert row['status']=='published';before=chess.Board(row['fen_before']);setup=chess.Move.from_uci(row['setup_uci']);assert setup in before.legal_moves;before.push(setup)
   assert ' '.join(before.fen().split()[:4])==' '.join(row['root_fen'].split()[:4])
   proof=json.loads(row['proof_json']);assert chess.Move.from_uci(proof['best_uci']) in before.legal_moves
   source=db.execute('SELECT uci,fen FROM kc_master_moves WHERE game_id=? AND ply=?',(row['source_game'],row['source_ply'])).fetchone()
   assert source and source['uci']==row['setup_uci'] and source['fen']==row['root_fen']
  db.close()
 for name in ('studio.schema.sql','knowledge.schema.sql'):
  db=sqlite3.connect(':memory:');db.executescript((root/name).read_text(encoding='utf8'))
  for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
   assert db.execute('SELECT count(*) FROM "'+row[0].replace('"','""')+'"').fetchone()[0]==0
  db.close()
 return {'integrity':'ok','tables':m['tables'],'legal_puzzles_verified':puzzles,'schema_rows':0,'private_tables':0}

if __name__=='__main__':
 import sys
 print(json.dumps(verify(sys.argv[1] if len(sys.argv)>1 else 'database')))
