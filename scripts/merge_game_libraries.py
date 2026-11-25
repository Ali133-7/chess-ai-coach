"""Construct a new public-only catalogue; preserve all IDs and distinguish conflicting import scans."""
import argparse,hashlib,json,shutil,sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library
from scripts.game_library_artifact import validate,digest

# Two snapshots of the same archive/policy may have different resume checkpoints.
# Keep both scan ledgers rather than attach new records to an older cursor.
SCAN_KEYS=('sha256','scope','source_id','cursor','accepted','duplicates','rejected','skipped','status','reasons_json')

def merge(inputs,output):
 if not inputs:raise ValueError('At least one source catalogue is required')
 if output.exists():raise FileExistsError('Use a new output; never merge into a live database')
 output.parent.mkdir(parents=True,exist_ok=True)
 if output.resolve() in {p.resolve() for p in inputs}:raise ValueError('Output cannot be an input')
 # Validate before copying; never snapshot an account database into an export.
 for source in inputs:validate(source)
 if shutil.disk_usage(output.parent).free<sum(p.stat().st_size for p in inputs)*2+1024**3:raise OSError('Insufficient staging space')
 try:
  with library.connection(inputs[0]) as original:
   target=sqlite3.connect(output)
   try:original.backup(target)
   finally:target.close()
  library.setup(output)
  reports=[]
  for source in inputs[1:]:
   with tempfile.TemporaryDirectory(prefix='catalogue-merge-',dir=output.parent) as td:
    snapshot=Path(td)/'source.sqlite3'
    with library.connection(source) as original:
     target=sqlite3.connect(snapshot)
     try:original.backup(target);target.execute('PRAGMA journal_mode=DELETE')
     finally:target.close()
    source_sha=digest(snapshot)
    with library.connection(output,True) as db:
     if db.execute('SELECT 1 FROM library_merges WHERE id=?',(source_sha,)).fetchone():continue
     db.execute('ATTACH DATABASE ? AS incoming',(snapshot.resolve().as_uri()+'?mode=ro',))
     schema=int(db.execute("SELECT value FROM incoming.library_meta WHERE key='schema_version'").fetchone()[0])
     db.execute('CREATE TEMP TABLE archive_map(old_url TEXT PRIMARY KEY,new_url TEXT NOT NULL)')
     db.execute('BEGIN IMMEDIATE')
     for raw in db.execute('SELECT * FROM incoming.library_archives').fetchall():
      row=dict(raw);row.setdefault('source_id','lichess-broadcasts');old_url=row['url']
      existing=db.execute('SELECT * FROM main.library_archives WHERE url=?',(old_url,)).fetchone()
      signature=tuple(row[k] for k in SCAN_KEYS)
      if existing and tuple(existing[k] for k in SCAN_KEYS)!=signature:
       suffix=hashlib.sha256(json.dumps([old_url,*signature],separators=(',',':')).encode()).hexdigest()[:24]
       row['url']=old_url+('&' if '#' in old_url else '#')+'catalogue-scan='+suffix
       existing=db.execute('SELECT * FROM main.library_archives WHERE url=?',(row['url'],)).fetchone()
       if existing and tuple(existing[k] for k in SCAN_KEYS)!=signature:raise ValueError('Import scan identifier collision')
      keys=('url','sha256','scope','cursor','accepted','duplicates','rejected','skipped','status','reasons_json','source_id')
      db.execute('INSERT OR IGNORE INTO main.library_archives('+','.join(keys)+') VALUES('+','.join('?'*len(keys))+')',tuple(row[k] for k in keys))
      db.execute('INSERT INTO archive_map VALUES(?,?)',(old_url,row['url']))
     before=db.execute('SELECT count(*) FROM main.library_games').fetchone()[0]
     columns=library.GAME_COLUMNS
     expressions=['m.new_url' if c=='archive_url' else 'g.'+c for c in columns]
     db.execute('INSERT OR IGNORE INTO main.library_games('+','.join(columns)+') SELECT '+','.join(expressions)+' FROM incoming.library_games g JOIN archive_map m ON m.old_url=g.archive_url')
     db.execute('INSERT OR IGNORE INTO main.library_provenance SELECT p.game_id,m.new_url,p.ordinal FROM incoming.library_provenance p JOIN archive_map m ON m.old_url=p.archive_url')
     read=db.execute('SELECT count(*) FROM incoming.library_games').fetchone()[0];added=db.execute('SELECT count(*) FROM main.library_games').fetchone()[0]-before
     report={'source_sha256':source_sha,'source_schema':schema,'games_read':read,'games_added':added,'duplicates':read-added,'merged_at':datetime.now(timezone.utc).isoformat()}
     db.execute('INSERT INTO library_merges VALUES(?,?,?,?,?,?,?)',(source_sha,*report.values()))
     db.commit();reports.append(report)
  stats,_=validate(output)
  return {'stats':stats,'merges':reports,'existing_ids_preserved':True}
 except BaseException:
  # Preserve the staged file for inspection. The caller's inputs remain untouched.
  raise

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(merge(a.input,a.output)))
