"""Validated, idempotent, checkpointed imports of locally staged, licensed data."""
import argparse,csv,hashlib,io,json,time
from pathlib import Path
from datetime import datetime,timezone
import chess
from fastapi import HTTPException
from . import store
from .recognition import parse_pgn,position_key,valid_board

def stamp():return datetime.now(timezone.utc).isoformat()
def source(db,key,url,license,revision,scope):
 db.execute('INSERT INTO kc_sources(key,url,license,revision,scope,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET revision=excluded.revision,scope=excluded.scope,updated_at=excluded.updated_at',(key,url,license,revision,scope,stamp()))

def opening_record(db,row,revision):
 eco=row['eco'];name=row['name'];pgn=row['pgn']
 if len(eco)!=3 or eco[0] not in 'ABCDE' or not eco[1:].isdigit() or not name or len(name)>300:raise ValueError('Invalid ECO/name')
 game,moves,boards,sans=parse_pgn(pgn,200)
 if boards[0].fen()!=chess.STARTING_FEN or not moves:raise ValueError('Not a standard opening line')
 uci=[m.uci() for m in moves];oid=hashlib.sha256((eco+'\0'+name+'\0'+' '.join(uci)).encode()).hexdigest()[:24]
 db.execute('INSERT OR REPLACE INTO kc_openings VALUES(?,?,?,?,?,?,?,?,?)',(revision,oid,eco,name,name.split(':')[0],pgn,json.dumps(uci),position_key(boards[-1]),len(moves)))
 # REPLACE opening does not cascade path rows; every validated immutable path is upserted.
 for i,move in enumerate(moves):
  before,after=position_key(boards[i]),position_key(boards[i+1]);fen=boards[i+1].fen()
  db.execute('INSERT OR REPLACE INTO kc_paths VALUES(?,?,?,?,?,?,?,?)',(revision,oid,i+1,before,after,fen,move.uci(),sans[i]))
  db.execute('INSERT OR IGNORE INTO kc_positions VALUES(?,?)',(before,boards[i].fen()));db.execute('INSERT OR IGNORE INTO kc_positions VALUES(?,?)',(after,fen))
  db.execute('INSERT OR IGNORE INTO kc_edges VALUES(?,?,?,?)',(before,move.uci(),after,sans[i]))

def puzzle_record(db,row,sha):
 board=valid_board(row['FEN']);moves=row['Moves'].split()
 if len(moves)<2 or len(moves)>60:raise ValueError('Invalid solution length')
 original=board.fen();normalized=[];setup=None
 for i,token in enumerate(moves):
  move=board.parse_uci(token)
  if move not in board.legal_moves:raise ValueError('Illegal puzzle move')
  normalized.append(move.uci());board.push(move)
  if i==0:setup=board.fen()
 rating=int(row['Rating']);pid=row['PuzzleId']
 if not 0<=rating<=5000 or not pid.isalnum() or len(pid)>20:raise ValueError('Invalid puzzle metadata')
 db.execute('INSERT OR REPLACE INTO kc_puzzles VALUES(?,?,?,?,?,?,?,?,?)',(pid,original,setup,json.dumps(normalized),rating,row.get('Themes',''),row.get('OpeningTags',''),row.get('GameUrl',''),sha))

def eval_record(db,row,sha):
 board=valid_board(row['fen']);key=position_key(board);choices=sorted(row['evals'],key=lambda x:x.get('depth',0),reverse=True)
 for ev in choices:
  try:
   depth=int(ev['depth']);pvs=[]
   if not 1<=depth<=255:raise ValueError()
   for pv in ev['pvs']:
    if not ('cp' in pv or 'mate' in pv):raise ValueError()
    b=board.copy();moves=[];sans=[]
    for token in pv['line'].split()[:16]:
     move=b.parse_uci(token)
     if move not in b.legal_moves:raise ValueError()
     sans.append(b.san(move));moves.append(move.uci());b.push(move)
    if not moves:raise ValueError()
    pvs.append({'moves':moves,'san':sans,'cp_white':pv.get('cp'),'mate_white':pv.get('mate')})
   if not pvs:raise ValueError()
   first=pvs[0]
   db.execute('INSERT INTO kc_evaluations VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(position_key,source) DO UPDATE SET depth=excluded.depth,cp_white=excluded.cp_white,mate_white=excluded.mate_white,pv_json=excluded.pv_json,updated_at=excluded.updated_at WHERE excluded.depth>kc_evaluations.depth',
     (key,'lichess-eval',depth,first['cp_white'],first['mate_white'],json.dumps(pvs),board.fen(),'Stockfish: Lichess export, version not supplied',stamp()))
   db.execute('INSERT OR IGNORE INTO kc_positions VALUES(?,?)',(key,board.fen()));return
  except (ValueError,KeyError,TypeError):continue
 raise ValueError('No fully valid evaluation/PV')

def json_records(file):
 for line in file:
  if not line.strip():continue
  try:yield json.loads(line)
  except ValueError:yield {'invalid_json':True}

def verify_assets():
 manifest=json.loads((store.DATA/'manifest.json').read_text('utf-8'))
 for item in manifest['sources']:
  path=(store.DATA/item['file']).resolve()
  if store.DATA.resolve() not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
   raise ValueError('Asset path/checksum mismatch')
 return manifest

def import_file(filename,batch=500):
 manifest=json.loads((store.DATA/'manifest.json').read_text('utf-8'))
 item=next((s for s in manifest['sources'] if s['file']==filename),None)
 if not item or filename not in ['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv','puzzles-sample.csv','evaluations-sample.jsonl']:raise ValueError('Unknown staged dataset')
 path=store.DATA/filename;sha=hashlib.sha256(path.read_bytes()).hexdigest()
 if sha!=item['sha256']:raise ValueError('Dataset checksum mismatch')
 kind='openings' if filename.endswith('.tsv') else 'puzzles' if filename.endswith('.csv') else 'evals';revision=manifest['openings_revision'];job=filename+':'+sha
 with store.connection() as db:
  db.execute('INSERT OR IGNORE INTO kc_imports(key,kind,filename,sha256,updated_at) VALUES(?,?,?,?,?)',(job,kind,filename,sha,stamp()))
  state=dict(db.execute('SELECT * FROM kc_imports WHERE key=?',(job,)).fetchone())
  if state['status']=='complete':return state
 # Read staged plaintext from the start, skipping committed records. Constant memory, safe restart.
 with path.open(encoding='utf-8',newline='') as f:
  records=csv.DictReader(f,delimiter='\t' if kind=='openings' else ',') if kind!='evals' else json_records(f)
  for _ in range(state['cursor']):next(records)
  rows=[]
  for _ in range(batch):
   try:rows.append(next(records))
   except StopIteration:break
  complete=len(rows)<batch
  with store.connection() as db:
   db.execute('BEGIN IMMEDIATE')
   latest=db.execute('SELECT cursor FROM kc_imports WHERE key=?',(job,)).fetchone()[0]
   if latest!=state['cursor']:return dict(db.execute('SELECT * FROM kc_imports WHERE key=?',(job,)).fetchone())
   accepted=rejected=0;last=None
   for row in rows:
    db.execute('SAVEPOINT record')
    try:
     if kind=='openings':opening_record(db,row,revision)
     elif kind=='puzzles':puzzle_record(db,row,sha)
     else:eval_record(db,row,sha)
     db.execute('RELEASE record');accepted+=1
    except (ValueError,TypeError,KeyError,HTTPException):
     db.execute('ROLLBACK TO record');db.execute('RELEASE record');rejected+=1;last='Rejected invalid record at index '+str(state['cursor']+accepted+rejected)
   db.execute('UPDATE kc_imports SET cursor=cursor+?,accepted=accepted+?,rejected=rejected+?,status=?,last_error=?,updated_at=? WHERE key=?',(len(rows),accepted,rejected,'complete' if complete else 'running',last,stamp(),job))
   if kind=='openings':
    all_parts=[s for s in manifest['sources'] if s['file'] in ['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv']]
    done=all(db.execute("SELECT 1 FROM kc_imports WHERE key=? AND status='complete'",(s['file']+':'+s['sha256'],)).fetchone() for s in all_parts)
    if done and len(all_parts)==5:
     db.execute("INSERT OR REPLACE INTO kc_meta VALUES('opening_revision',?)",(revision,));source(db,'openings','https://github.com/lichess-org/chess-openings','CC0-1.0',revision,'All five ECO TSV files at pinned revision')
   else:source(db,kind,item['url'],item['license'],sha,item.get('scope','Bounded sample')+'; records='+str(item.get('records','unknown')))
   return dict(db.execute('SELECT * FROM kc_imports WHERE key=?',(job,)).fetchone())

def seed():
 store.setup();manifest=verify_assets()
 for filename in ['a.tsv','b.tsv','c.tsv','d.tsv','e.tsv','puzzles-sample.csv','evaluations-sample.jsonl']:
  while True:
   state=import_file(filename,300)
   if state['status']=='complete':print(filename,state['accepted'],state['rejected'],flush=True);break
 from .external import import_explorer_payload
 for seed_file in ['explorer-seed.json','masters-seed.json']:
  if (store.DATA/seed_file).exists():
   for row in json.loads((store.DATA/seed_file).read_text()):import_explorer_payload(row['fen'],row['data'],row.get('filters'),row.get('dataset','lichess'))
 with store.connection() as db:
  source(db,'syzygy','https://github.com/syzygy1/tb#terms-of-use','Redistribution permitted for generated tables',None,'Local 3-piece KQ/KR/KB/KN/KP versus K; files from Lichess tablebase mirror')
  source(db,'explorer','https://explorer.lichess.org/lichess','API factual statistics; underlying Lichess games CC0',None,'Optional authenticated, serialized, cached calls; no anonymous statistics fabricated')
 print('SEED_COMPLETE',flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--file');parser.add_argument('--batch',type=int,default=500);args=parser.parse_args()
 store.setup();print(import_file(args.file,max(1,min(2000,args.batch)))) if args.file else seed()
