"""Package/install a public-only catalogue. Never merge into account or knowledge databases."""
import argparse,gzip,hashlib,io,json,os,re,shutil,sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library

TABLES={'library_meta','library_archives','library_games','library_provenance','library_search','library_search_data','library_search_idx','library_search_docsize','library_search_config'}
def digest(file):
 with Path(file).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def validate(file,deep=False):
 with library.connection(file) as db:
  names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if names not in (TABLES,TABLES|{'library_sources','library_merges'}):raise ValueError('Unexpected tables: public catalogue only')
  version=db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
  if not version or version[0] not in library.READABLE_SCHEMAS:raise ValueError('Unsupported library schema')
  if names!=(TABLES|{'library_sources','library_merges'} if version[0]=='2' else TABLES):raise ValueError('Unexpected tables: public catalogue only')
  if tuple(r['name'] for r in db.execute('PRAGMA table_info(library_games)'))!=library.GAME_COLUMNS:raise ValueError('Unexpected game columns')
  if db.execute("SELECT 1 FROM sqlite_master WHERE type='view' OR (type='trigger' AND name!='library_search_insert')").fetchone():raise ValueError('Unexpected view/trigger in public catalogue')
  if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Invalid catalogue')
  meta=dict(db.execute('SELECT key,value FROM library_meta'))
  if set(meta)!={'schema_version','license','source_page'} or meta.get('source_page')!=library.SOURCE:raise ValueError('Unexpected catalogue metadata')
  if meta.get('license')!=library.LICENSE:raise ValueError('Unsupported collection license')
  if version[0]=='2':
   from studio.knowledge.library_sources import SOURCES
   for row in db.execute('SELECT * FROM library_sources'):
    source=dict(row)
    if SOURCES.get(source['id'])!=source:raise ValueError('Unapproved source/license metadata')
   if db.execute('SELECT 1 FROM library_archives a LEFT JOIN library_sources s ON s.id=a.source_id WHERE s.id IS NULL LIMIT 1').fetchone():raise ValueError('Missing source policy')
   if db.execute('SELECT 1 FROM library_games g JOIN library_archives a ON a.url=g.archive_url JOIN library_sources s ON s.id=a.source_id WHERE g.license!=s.license LIMIT 1').fetchone():raise ValueError('Incorrect per-game license')
   for row in db.execute('SELECT * FROM library_merges'):
    if not re.fullmatch('[0-9a-f]{64}',row['id']) or not re.fullmatch('[0-9a-f]{64}',row['source_sha256']) or row['source_schema'] not in (1,2) or row['games_added']<0 or row['duplicates']<0 or row['games_read']!=row['games_added']+row['duplicates']:raise ValueError('Invalid public merge audit')
  elif db.execute('SELECT 1 FROM library_games WHERE license!=? LIMIT 1',(library.LICENSE,)).fetchone():raise ValueError('Invalid v1 game license')
  if db.execute('SELECT 1 FROM library_games WHERE plies<1 OR plies>600 LIMIT 1').fetchone():raise ValueError('Invalid game metadata')
  stats=dict(db.execute("SELECT count(*) games,coalesce(sum(white_title='GM' AND black_title='GM'),0) gm_vs_gm,coalesce(sum(plies),0) plies,coalesce(sum(source_eval_count),0) source_evaluations,min(year) first_year,max(year) last_year FROM library_games").fetchone())
  archives=[dict(r) for r in db.execute('SELECT * FROM library_archives ORDER BY url')]
  if deep:
   import chess.pgn
   from scripts.build_game_library import Builder
   for row in db.execute('SELECT id,plies,initial_fen,pgn_z,evals_z,source_eval_count,archive_url FROM library_games'):
    game,reason,body_result=chess.pgn.read_game(io.StringIO(library.unpack(row['pgn_z'])),Visitor=lambda:Builder('all'))
    normalized=library.pack_game(game,row['archive_url'],body_result,library.archive_source(db,row['archive_url'])['id'])
    evaluations=json.loads(library.unpack(row['evals_z']))
    if reason or normalized[0]!=row['id'] or normalized[11]!=row['plies'] or normalized[12]!=row['initial_fen'] or len(evaluations)!=row['plies']:raise ValueError('Invalid full game sequence or identity')
    for score in evaluations:
     if score is not None and (not isinstance(score,list) or len(score)!=3 or any(x is not None and type(x)!=int for x in score) or (score[0] is None)==(score[1] is None)):raise ValueError('Invalid numerical source score')
    if sum(s is not None for s in evaluations)!=row['source_eval_count']:raise ValueError('Evaluation count mismatch')
 return stats,archives

def package(source,output,deep=False):
 output.mkdir(parents=True,exist_ok=True)
 if (output/'master-library.sqlite3.gz').exists() or (output/'game-library-manifest.json').exists():raise FileExistsError('Use a new output directory')
 with tempfile.TemporaryDirectory(prefix='library-package-',dir=output) as scratch:
  snapshot=Path(scratch)/'master-library.sqlite3'
  with library.connection(source) as source_db:
   target=sqlite3.connect(snapshot)
   try:source_db.backup(target);target.execute('PRAGMA journal_mode=DELETE');target.execute('VACUUM')
   finally:target.close()
  stats,archives=validate(snapshot,deep=deep);dest=output/'master-library.sqlite3.gz'
  with library.connection(snapshot) as db:
   sources=library.sources_for(db);schema_version=int(db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()[0])
   merges=[dict(r) for r in db.execute('SELECT * FROM library_merges ORDER BY merged_at,id')] if schema_version==2 else []
  with snapshot.open('rb') as src,dest.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:shutil.copyfileobj(src,compressed,1024*1024)
  manifest={'format':1,'schema_version':library.SCHEMA,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'file':dest.name,'compressed_bytes':dest.stat().st_size,'compressed_sha256':digest(dest),'database_bytes':snapshot.stat().st_size,'database_sha256':digest(snapshot),'stats':stats,'archives':archives,'source_page':library.SOURCE,'license':library.LICENSE,'license_url':library.LICENSE_URL,'attribution':'Lichess official broadcasts and the tournaments linked in each record. Adapted game data CC BY-SA 4.0.','changes':'Selected completed standard games, validated all recorded mainline moves, normalized dates, deduplicated identical player/date/event/round/start/move identities, compressed PGN and retained numerical evaluation annotations. No human commentary or side variations. Board-fact explanations are generated locally when viewed.','analysis_notice':'Source engine settings are unknown. Missing scores remain unscored; no best-play claim or estimated player rating. A completed PGN may end by resignation/draw agreement and need not contain checkmate.','coverage_notice':'Only accepted records in the listed archives and scopes. Not all world chess games, not the Chessgames.com collection.'}
  manifest.update(schema_version=schema_version,sources=sources,merges=merges,source_page=sources[0]['page'] if len(sources)==1 else library.CATALOGUE_PAGE,attribution=' '.join(s['attribution'] for s in sources)+' Adapted combined collection CC BY-SA 4.0; individual records retain their source license.')
  manifest['verification']={'sqlite_integrity_and_foreign_keys':True,'public_tables_only':True,'all_mainlines_checked_during_import':True,'all_mainlines_rechecked_during_packaging':deep}
  (output/'game-library-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 return manifest

def install(archive,manifest_file,destination,replace=False):
 meta=json.loads(manifest_file.read_text(encoding='utf8'))
 if meta.get('format')!=1 or str(meta.get('schema_version')) not in library.READABLE_SCHEMAS or meta.get('license')!=library.LICENSE:raise ValueError('Unsupported manifest')
 if not 0<meta['database_bytes']<=32*1024**3:raise ValueError('Invalid database size')
 if archive.stat().st_size!=meta['compressed_bytes'] or digest(archive)!=meta['compressed_sha256']:raise ValueError('Archive checksum mismatch')
 if destination.name!='master-library.sqlite3':raise ValueError('Destination must be named master-library.sqlite3; never an account/knowledge database')
 if destination.is_symlink():raise ValueError('Refusing a symlink destination')
 if destination.exists() and not replace:raise FileExistsError('Catalogue already installed; use --replace after review')
 if destination.exists():validate(destination)
 if any(Path(str(destination)+suffix).exists() for suffix in ('-wal','-shm')):raise ValueError('Stop the catalogue builder before replacement')
 destination.parent.mkdir(parents=True,exist_ok=True)
 if shutil.disk_usage(destination.parent).free<meta['database_bytes']*2+256*1024**2:raise OSError('Insufficient space for staged install and backup')
 fd,name=tempfile.mkstemp(prefix='library-install-',suffix='.sqlite3',dir=destination.parent);temporary=Path(name)
 try:
  with os.fdopen(fd,'wb') as out,gzip.open(archive,'rb') as src:
   size=0
   for block in iter(lambda:src.read(1024*1024),b''):
    size+=len(block)
    if size>meta['database_bytes']:raise ValueError('Oversized database payload')
    out.write(block)
  if size!=meta['database_bytes'] or digest(temporary)!=meta['database_sha256']:raise ValueError('Database checksum mismatch')
  stats,_=validate(temporary)
  if stats!=meta['stats']:raise ValueError('Manifest record counts differ')
  if destination.exists():
   backup=destination.with_name(destination.name+'.backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
   shutil.copy2(destination,backup)
  temporary.replace(destination)
 finally:temporary.unlink(missing_ok=True)
 return stats

def main():
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
 pack=sub.add_parser('package');pack.add_argument('--database',type=Path,required=True);pack.add_argument('--output',type=Path,required=True);pack.add_argument('--deep',action='store_true')
 load=sub.add_parser('install');load.add_argument('--archive',type=Path,required=True);load.add_argument('--manifest',type=Path,required=True);load.add_argument('--destination',type=Path,required=True);load.add_argument('--replace',action='store_true')
 verify=sub.add_parser('verify');verify.add_argument('--database',type=Path,required=True);verify.add_argument('--deep',action='store_true')
 args=parser.parse_args()
 result=package(args.database,args.output,args.deep) if args.action=='package' else validate(args.database,args.deep) if args.action=='verify' else install(args.archive,args.manifest,args.destination,args.replace)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
