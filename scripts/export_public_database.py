"""Export a fresh allowlisted reference database, never a redacted copy of user pages.

Schema files contain no rows. Private tables, caches, sessions and credentials are
excluded by construction. Run against consistent SQLite backup files.
"""
import argparse,gzip,hashlib,json,sqlite3,tempfile
from datetime import datetime,timezone
from pathlib import Path

PUBLIC_TABLES=('kc_sources','kc_meta','kc_openings','kc_paths','kc_positions','kc_edges','kc_puzzles','kc_master_games','kc_master_moves','kc_generated_exercises')

def schema(db):
 return '\n\n'.join(row[0]+';' for row in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,name"))+'\n'

def export(studio,knowledge,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 main=sqlite3.connect(Path(studio).resolve().as_uri()+'?mode=ro',uri=True)
 src=sqlite3.connect(Path(knowledge).resolve().as_uri()+'?mode=ro',uri=True)
 (output/'studio.schema.sql').write_text(schema(main),encoding='utf8')
 (output/'knowledge.schema.sql').write_text(schema(src),encoding='utf8')
 main.close();counts={}
 with tempfile.TemporaryDirectory() as temp:
  path=Path(temp)/'public.sqlite3';dst=sqlite3.connect(path)
  for table in PUBLIC_TABLES:
   ddl=src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
   if not ddl:continue
   dst.execute(ddl[0])
   # Derive graph positions exclusively from published opening paths, never caches.
   where={
    'kc_meta':" WHERE key='opening_revision'",
    'kc_positions':' WHERE key IN (SELECT position_key FROM kc_paths UNION SELECT before_key FROM kc_paths)',
    'kc_edges':' WHERE (position_key,uci) IN (SELECT before_key,uci FROM kc_paths)',
    'kc_generated_exercises':" WHERE status='published' AND source_game IN (SELECT id FROM kc_master_games WHERE license='CC-BY-SA-4.0')",
    'kc_master_games':" WHERE license='CC-BY-SA-4.0'",
    'kc_master_moves':" WHERE game_id IN (SELECT id FROM kc_master_games WHERE license='CC-BY-SA-4.0')",
    'kc_puzzles':" WHERE source_sha NOT LIKE 'generated:%' OR id IN (SELECT puzzle_id FROM kc_generated_exercises WHERE status='published' AND source_game IN (SELECT id FROM kc_master_games WHERE license='CC-BY-SA-4.0'))",
   }.get(table,'')
   rows=src.execute('SELECT * FROM '+table+where)
   columns=len(rows.description);n=0
   while batch:=rows.fetchmany(500):dst.executemany('INSERT INTO '+table+' VALUES('+','.join('?'*columns)+')',batch);n+=len(batch)
   counts[table]=n
  # Indexes are recreated only for selected tables. No triggers or private views.
  for table in PUBLIC_TABLES:
   for row in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",(table,)):dst.execute(row[0])
  dst.commit();assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert not dst.execute('PRAGMA foreign_key_check').fetchall()
  assert {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}<=set(PUBLIC_TABLES)
  dst.close();raw=path.read_bytes();compressed=gzip.compress(raw,compresslevel=9,mtime=0)
  (output/'public-knowledge.sqlite3.gz').write_bytes(compressed)
 src.close()
 manifest={'exported_at_utc':datetime.now(timezone.utc).isoformat(),'format':1,'tables':counts,'sqlite_sha256':hashlib.sha256(raw).hexdigest(),'gzip_sha256':hashlib.sha256(compressed).hexdigest(),'sqlite_bytes':len(raw),'gzip_bytes':len(compressed),'private_data_included':False,'studio_data_rows_exported':0,'scope':'Public opening graph, licensed master games and published derived exercises only; no users, sessions, billing, credentials, caches or player history.','licenses':{'openings':'CC0-1.0','lichess_puzzles':'CC0-1.0','master_games_and_derived_exercises':'CC-BY-SA-4.0'},'notices':'../THIRD_PARTY_NOTICES.md'}
 (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--studio',required=True);p.add_argument('--knowledge',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(export(a.studio,a.knowledge,a.output)))
