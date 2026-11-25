"""Export a verified player selection from a public catalogue into a fresh public file."""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library,player_names
from scripts.game_library_artifact import TABLES,validate

def export(source,output,query):
 profile=player_names.resolve(query)
 if not profile:raise ValueError('A known full player name is required')
 if output.exists() or output.is_symlink() or output.resolve()==source.resolve():raise FileExistsError('Use a new public selection file')
 with library.connection(source) as src:
  tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if tables not in (TABLES,TABLES|{'library_sources','library_merges'}):raise ValueError('Public catalogue inputs only')
  if tuple(r['name'] for r in src.execute('PRAGMA table_info(library_games)'))!=library.GAME_COLUMNS:raise ValueError('Unexpected game columns')
  src.execute('BEGIN')
  games=src.execute('SELECT * FROM library_games WHERE rowid IN (SELECT rowid FROM library_search WHERE library_search MATCH ?)',(player_names.fts_query(profile),)).fetchall()
  if not games:raise ValueError('No matching player records are available in this source snapshot')
  provenance=[]
  for index in range(0,len(games),200):
   ids=[g['id'] for g in games[index:index+200]]
   provenance.extend(src.execute('SELECT * FROM library_provenance WHERE game_id IN ('+','.join('?'*len(ids))+')',ids).fetchall())
  urls={g['archive_url'] for g in games}|{p['archive_url'] for p in provenance}
  archives=[]
  for url in sorted(urls):
   row=dict(src.execute('SELECT * FROM library_archives WHERE url=?',(url,)).fetchone());row.setdefault('source_id','lichess-broadcasts');archives.append(row)
  cursors={r['url']:r['cursor'] for r in archives}
  if any(not 0<p['ordinal']<=cursors[p['archive_url']] for p in provenance):raise ValueError('Provenance exceeds its committed source checkpoint')
  library.setup(output)
  with library.connection(output,True) as dst:
   dst.execute('BEGIN IMMEDIATE')
   keys=('url','sha256','scope','cursor','accepted','duplicates','rejected','skipped','status','reasons_json','source_id')
   for row in archives:dst.execute('INSERT INTO library_archives('+','.join(keys)+') VALUES('+','.join('?'*len(keys))+')',tuple(row[k] for k in keys))
   dst.executemany('INSERT INTO library_games VALUES('+','.join('?'*len(library.GAME_COLUMNS))+')',[tuple(g[k] for k in library.GAME_COLUMNS) for g in games])
   dst.executemany('INSERT INTO library_provenance VALUES(?,?,?)',[(p['game_id'],p['archive_url'],p['ordinal']) for p in provenance])
 stats,_=validate(output,deep=True)
 result={'format':1,'player':player_names.public(profile),'selected_games':stats['games'],'source_read_at_utc':datetime.now(timezone.utc).isoformat(),'stats':stats,'selection':'Exact known full-name spellings in one player field; no opponent/opening cross-match.','provenance_notice':'Archive counters describe the original committed source scans, not this subset size. Original game IDs, headers, PGN, license and source ordinals are retained. The live historical source may remain incomplete.','all_selected_mainlines_rechecked':True}
 output.with_suffix('.selection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--player',required=True);a=p.parse_args();print(json.dumps(export(a.source,a.output,a.player),ensure_ascii=False))
