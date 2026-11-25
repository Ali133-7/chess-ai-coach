"""Merge a checksummed public supplement; atomically retain the complete existing catalogue."""
import argparse,json,shutil,stat,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library
from scripts.game_library_artifact import digest,install
from scripts.merge_game_libraries import merge

def apply(archive,manifest,destination,expected_sha256=None):
 if destination.name!='master-library.sqlite3' or destination.is_symlink() or not destination.is_file():raise ValueError('An existing regular master-library.sqlite3 is required; never an account database')
 if any(Path(str(destination)+suffix).exists() for suffix in ('-wal','-shm')):raise ValueError('Stop writers before updating the installed public catalogue')
 initial=digest(destination)
 if expected_sha256 and initial!=expected_sha256:raise ValueError('Installed catalogue changed; review its checksum')
 if shutil.disk_usage(destination.parent).free<destination.stat().st_size*3+archive.stat().st_size*3+256*1024**2:raise OSError('Insufficient space for staging and retained backup')
 with tempfile.TemporaryDirectory(prefix='library-supplement-',dir=destination.parent) as folder:
  root=Path(folder);incoming=root/'incoming/master-library.sqlite3';install(archive,manifest,incoming)
  staged=root/'merged/master-library.sqlite3';report=merge([destination,incoming],staged)
  if not report['merges']:return {'status':'already-applied','stats':report['stats'],'database_sha256':initial}
  with library.connection(staged,True) as db:
   db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('PRAGMA journal_mode=DELETE')
  # merge validated the complete public result; identity preservation follows its
  # snapshot + INSERT OR IGNORE construction. Refuse a concurrent base replacement.
  if digest(destination)!=initial:raise ValueError('Installed catalogue changed during staging; no replacement performed')
  backup=destination.with_name(destination.name+'.backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
  shutil.copy2(destination,backup)
  if digest(destination)!=initial:raise ValueError('Installed catalogue changed during backup; no replacement performed')
  staged.chmod(stat.S_IMODE(destination.stat().st_mode));staged.replace(destination)
 return {'status':'installed','stats':report['stats'],'games_added':sum(m['games_added'] for m in report['merges']),'database_sha256':digest(destination),'previous_database_sha256':initial,'all_existing_ids_preserved':True,'backup':str(backup)}

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--expected-current-sha256');a=p.parse_args();print(json.dumps(apply(a.archive,a.manifest,a.destination,a.expected_current_sha256)))
