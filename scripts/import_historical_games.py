"""Legally validate/resume a pinned historical PGN archive; preserve author and per-game license."""
import argparse,codecs,hashlib,io,json,re,shutil,sys,time,unicodedata,zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import chess,chess.pgn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.knowledge import game_library as library
from scripts.build_game_library import Builder
from scripts.fetch_historical_archive import SHA256

SOURCE_ID='figshare-4276523-v1'
DOWNLOAD='https://ndownloader.figshare.com/files/6971717'

class CollapseBlankLines:
 """Normalize the deposit's empty lines without truncating its movetext.

 Blank lines also occur between moves. A new header block outside a brace
 comment establishes the next record; semicolon comment line endings remain.
 """
 def __init__(self,stream):self.stream=stream;self.body=False;self.comment=False;self.tags=set();self.pending=[]
 def readline(self):
  if self.pending:return self.pending.pop(0)
  while True:
   line=self.stream.readline(2*1024*1024+1)
   if len(line)>2*1024*1024:raise ValueError('Oversized PGN line')
   if not line:return ''
   line=line.lstrip('\ufeff')
   if line.isspace() and not self.comment:continue
   match=chess.pgn.TAG_REGEX.match(line.lstrip()) if not self.comment else None
   if match:
    tag=match.group(1);line=line.lstrip()
    if self.body or tag=='Event' and tag in self.tags:
     # Two blanks terminate a corrupt header-only record; one terminates body.
     self.pending=([line] if self.body else ['\n',line]);self.body=False;self.tags={tag};return '\n'
    self.tags.add(tag);return line
   if not line.startswith(('%',';')):self.body=True
   for token in re.findall(r'[{};]',line):
    if token=='{':self.comment=True
    elif token=='}':self.comment=False
    elif not self.comment:break
   return line

def verified_member(archive):
 items=archive.infolist()
 if len(items)!=1 or items[0].filename!='all.pgn':raise ValueError('Unexpected historical archive members')
 member=items[0]
 if member.flag_bits&1 or member.file_size>16*1024**3 or member.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('Unsupported/oversized PGN member')
 return member

def inspect_encoding(path,expected_sha=SHA256):
 with path.open('rb') as raw:
  if hashlib.file_digest(raw,'sha256').hexdigest()!=expected_sha:raise ValueError('Archive SHA-256 mismatch')
 decoders={name:codecs.getincrementaldecoder(name)(errors='strict') for name in ('utf-8-sig','cp1252')};valid=set(decoders)
 with zipfile.ZipFile(path) as archive:
  member=verified_member(archive)
  with archive.open(member) as stream:
   for block in iter(lambda:stream.read(1024*1024),b''):
    for name in list(valid):
     try:decoders[name].decode(block)
     except UnicodeDecodeError:valid.remove(name)
   for name in list(valid):
    try:decoders[name].decode(b'',final=True)
    except UnicodeDecodeError:valid.remove(name)
 encoding='utf-8-sig' if 'utf-8-sig' in valid else 'cp1252' if 'cp1252' in valid else 'latin-1'
 return {'sha256':expected_sha,'member':member.filename,'uncompressed_bytes':member.file_size,'encoding':encoding,'full_zip_crc_checked':True,'replacement_characters_used':False}

@contextmanager
def open_pgn(path,encoding):
 with zipfile.ZipFile(path) as archive:
  member=verified_member(archive)
  with archive.open(member) as raw,io.TextIOWrapper(raw,encoding=encoding,errors='strict') as stream:yield CollapseBlankLines(stream)

def tokens(text):
 return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c)).replace(',',' ').replace('.',' ').split()

class HistoricalBuilder(Builder):
 def __init__(self,selection,skip=False,ordinal=0):super().__init__('all',skip);self.selection=selection;self.ordinal=ordinal
 def end_headers(self):
  if super().end_headers() is chess.pgn.SKIP:return chess.pgn.SKIP
  if self.ordinal%self.selection.get('partitions',1)!=self.selection.get('partition',0):self.reason='outside_partition';return chess.pgn.SKIP
  h=self.game.headers
  date=next((h[k] for k in ('Date','UTCDate') if k in h and re.fullmatch(r'(17|18|19|20)\d{2}\.(\d{2}|\?\?)\.(\d{2}|\?\?)',h[k])),'')
  year=int(date[:4]) if date else 0
  if self.selection.get('min_year') and year<self.selection['min_year'] or self.selection.get('max_year') and year>self.selection['max_year']:
   self.reason='outside_selected_years';return chess.pgn.SKIP
  wanted=set(self.selection.get('players',[]))
  if wanted and not wanted.intersection(tokens(h.get('White',''))+tokens(h.get('Black',''))):self.reason='outside_priority_players';return chess.pgn.SKIP
  if h.get('FEN',chess.STARTING_FEN)!=chess.STARTING_FEN:self.reason='nonstandard_start_or_fragment';return chess.pgn.SKIP

def import_file(database,path,inspection,selection=None,target_games=None,max_records=None,min_free_bytes=1024**3,batch_size=200):
 # Test callers may supply a real fixture archive with its own pinned hash.
 with path.open('rb') as raw:
  if hashlib.file_digest(raw,'sha256').hexdigest()!=inspection['sha256']:raise ValueError('Archive changed after inspection')
 selection={**(selection or {}),'policy_version':1,'encoding':inspection['encoding'],'standard_start_only':True,'blank_lines':'header-aware-v2'}
 selection['players']=sorted(set(selection.get('players',[])))
 scope=json.dumps(selection,sort_keys=True,separators=(',',':'));key=hashlib.sha256(scope.encode()).hexdigest()[:24]
 url=DOWNLOAD+'#selection='+key;library.setup(database)
 with library.connection(database,True) as db:
  db.execute('INSERT OR IGNORE INTO library_archives(url,sha256,scope,source_id) VALUES(?,?,?,?)',(url,inspection['sha256'],scope,SOURCE_ID))
  job=dict(db.execute('SELECT * FROM library_archives WHERE url=?',(url,)).fetchone())
  if job['sha256']!=inspection['sha256'] or job['scope']!=scope or job['source_id']!=SOURCE_ID:raise ValueError('Historical archive revision/policy changed')
  if job['status']=='complete' or target_games and job['accepted']>=target_games:return job
 cursor=job['cursor'];accepted=job['accepted'];duplicates=job['duplicates'];rejected=job['rejected'];skipped=job['skipped'];reasons=Counter(json.loads(job['reasons_json']));batch=[];index=0;started=time.monotonic()
 def checkpoint(status='running'):
  nonlocal accepted,duplicates,batch
  if shutil.disk_usage(Path(database).resolve().parent).free<min_free_bytes:raise OSError('Reserved free space reached')
  with library.connection(database,True) as db:
   db.execute('BEGIN IMMEDIATE')
   for ordinal,row in batch:
    inserted=db.execute('INSERT OR IGNORE INTO library_games VALUES('+','.join('?'*19)+')',row).rowcount;accepted+=inserted;duplicates+=not inserted
    db.execute('INSERT OR IGNORE INTO library_provenance VALUES(?,?,?)',(row[0],url,ordinal))
   db.execute('UPDATE library_archives SET cursor=?,accepted=?,duplicates=?,rejected=?,skipped=?,status=?,reasons_json=? WHERE url=?',(index,accepted,duplicates,rejected,skipped,status,json.dumps(reasons),url))
  batch=[];print(json.dumps({'source':SOURCE_ID,'selection':key,'cursor':index,'accepted':accepted,'duplicates':duplicates,'rejected':rejected,'skipped':skipped,'status':status,'seconds':round(time.monotonic()-started,1)}),flush=True)
 with open_pgn(path,inspection['encoding']) as stream:
  while True:
   item=chess.pgn.read_game(stream,Visitor=lambda:HistoricalBuilder(selection,index<cursor,index))
   if item is None:break
   index+=1
   if index<=cursor:continue
   game,reason,result=item
   if reason:skipped+=1;reasons[reason]+=1
   else:
    try:batch.append((index,library.pack_game(game,url,result,SOURCE_ID)))
    except (ValueError,TypeError,IndexError) as exc:rejected+=1;reasons[str(exc)[:80]]+=1
   if index%batch_size==0:checkpoint()
   if target_games and accepted>=target_games or max_records and index>=max_records:checkpoint('paused');break
  if item is None:checkpoint('complete')
 with library.connection(database) as db:return dict(db.execute('SELECT * FROM library_archives WHERE url=?',(url,)).fetchone())

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--database',type=Path,required=True);p.add_argument('--inspect-only',action='store_true');p.add_argument('--players',default='');p.add_argument('--min-year',type=int);p.add_argument('--max-year',type=int);p.add_argument('--target-games',type=int);p.add_argument('--max-records',type=int);p.add_argument('--partitions',type=int,default=1);p.add_argument('--partition',type=int,default=0);a=p.parse_args()
 if a.target_games is not None and a.target_games<1:p.error('target must be positive')
 if not 1<=a.partitions<=4 or not 0<=a.partition<a.partitions:p.error('Use 1-4 partitions and a zero-based partition index')
 if a.max_records is not None and a.max_records<1:p.error('Record limit must be positive')
 if any(y is not None and not 1700<=y<=2099 for y in (a.min_year,a.max_year)) or a.min_year and a.max_year and a.min_year>a.max_year:p.error('Invalid year range')
 info_file=a.archive.with_suffix('.inspection.json')
 if info_file.exists():
  inspection=json.loads(info_file.read_text());assert inspection['sha256']==SHA256
 else:
  inspection=inspect_encoding(a.archive);info_file.write_text(json.dumps(inspection,indent=2)+'\n')
 if a.inspect_only:print(json.dumps(inspection));return
 selection={'players':sorted(set(x for name in a.players.split(',') for x in tokens(name))),'min_year':a.min_year,'max_year':a.max_year}
 if a.partitions>1:selection.update(partitions=a.partitions,partition=a.partition)
 print(json.dumps(import_file(a.database,a.archive,inspection,selection,a.target_games,a.max_records)))
if __name__=='__main__':main()
