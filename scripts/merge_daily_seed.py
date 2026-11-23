"""Operator-only import of the reviewed public initial batch. No user data."""
import json,sys,hashlib
from pathlib import Path
import chess
from studio.knowledge import store,daily_exercises as d

def merge(path):
 payload=json.loads(Path(path).read_text(encoding='utf8'));rows=payload['records'];items={x['id']:x for x in payload['puzzles']};assert len(rows)==24 and len({r['position_key'] for r in rows})==24
 d.setup()
 with store.connection() as db:
  # Validate the whole batch before writing a single exercise.
  for row in rows:
   assert set(row)==set('puzzle_id position_key day source_game source_ply fen_before setup_uci root_fen proof_json notes_json provider model status created_at published_at'.split())
   assert set(items[row['puzzle_id']])==set('id fen setup_fen moves_json rating themes opening_tags game_url source_sha'.split())
   root=chess.Board(row['root_fen']);before=chess.Board(row['fen_before']);before.push_uci(row['setup_uci']);assert root.is_valid() and root.fen()==before.fen() and d.key(root)==row['position_key']
   origin=db.execute('SELECT fen,uci FROM kc_master_moves WHERE game_id=? AND ply=?',(row['source_game'],row['source_ply'])).fetchone();prev=db.execute('SELECT fen FROM kc_master_moves WHERE game_id=? AND ply=?',(row['source_game'],row['source_ply']-1)).fetchone()
   assert origin and prev and origin['fen']==row['root_fen'] and origin['uci']==row['setup_uci'] and prev[0]==row['fen_before']
   proof=json.loads(row['proof_json']);assert proof['nodes']==500000 and proof['gap_cp_reference']>=80 and proof['engine'].startswith('Stockfish')
   d.replay(root,[chess.Move.from_uci(u) for u in proof['pv']]);assert proof['pv'][0]==proof['best_uci'];assert root.san(chess.Move.from_uci(proof['best_uci']))==proof['best_san']
   note=d.Note.model_validate_json(row['notes_json'],strict=True);assert note.id==row['puzzle_id'] and row['provider'] in ['groq','xai','openrouter','openai']
   p=items[row['puzzle_id']];assert p['setup_fen']==row['root_fen'] and p['fen']==row['fen_before'] and json.loads(p['moves_json'])==[row['setup_uci'],proof['best_uci']] and p['rating']==0
  db.execute('BEGIN IMMEDIATE')
  for row in rows:
   keys=list(row);db.execute('INSERT OR IGNORE INTO kc_generated_exercises('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[row[k] for k in keys]);p=items[row['puzzle_id']];keys=list(p);db.execute('INSERT OR IGNORE INTO kc_puzzles('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[p[k] for k in keys])
  r=payload['run'];db.execute("INSERT INTO kc_daily_runs(day,target,status,cursor,scanned,rejected,lease_until,updated_at) VALUES(?,24,'complete',?,?,?,0,?) ON CONFLICT(day) DO UPDATE SET status='complete',cursor=excluded.cursor,updated_at=excluded.updated_at",(r['day'],r['cursor'],r['scanned'],r['rejected'],r['updated_at']))
  assert db.execute("SELECT count(*) FROM kc_generated_exercises WHERE day=? AND status='published'",(r['day'],)).fetchone()[0]>=24
 print('INITIAL_GENERATED_BATCH_MERGED',24,flush=True)
if __name__=='__main__':merge(sys.argv[1])
