"""Operator-only migration of an owner's completed games; never exposed as HTTP API."""
import argparse, hashlib, json, sqlite3
from .core import connection,setup,game_moves_from_pgn,now

def import_owner(path,email):
 setup();old=sqlite3.connect('file:'+path+'?mode=ro',uri=True)
 old.row_factory=sqlite3.Row
 with connection() as db:
  user=db.execute('SELECT id,chess_username FROM users WHERE email=?',(email.lower(),)).fetchone()
 if not user or not user['chess_username']:
  raise SystemExit('Register first, link Chess.com username, then run migration.')
 username=user['chess_username'];inserted=0;scanned=0
 try:
  entries=old.execute('SELECT * FROM games WHERE lower(username)=?',(username,))
  for g in entries:
   try:
    pg,positions=game_moves_from_pgn(g['pgn'])
    if username not in (pg.headers.get('White','').lower(),pg.headers.get('Black','').lower()):continue
   except ValueError:continue
   key=hashlib.sha256(g['url'].encode()).hexdigest()[:30]
   with connection() as db:
    db.execute('''INSERT OR IGNORE INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,
      total_positions,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
      (user['id'],key,g['url'],g['pgn'],g['finished_at'],g['white'],g['black'],g['result'],len(positions)+1,now()))
    row=db.execute('SELECT id FROM games WHERE user_id=? AND external_id=?',(user['id'],key)).fetchone()
    gid=row['id'];inserted+=1
   try:
    rows=old.execute('SELECT * FROM deep_scans WHERE game_id=? ORDER BY ply',(g['id'],)).fetchall()
   except sqlite3.OperationalError:rows=[]
   # Deep v5 scans are reused safely, but older shallow analyses are not labeled deep.
   if rows:
    with connection() as db:
     for x in rows:
      scan=json.loads(x['scan_json'])
      new={'eval':scan.get('cp_white',0),'terminal':scan.get('terminal',False),
       'lines':[{'uci':v.get('uci'),'san':v.get('san'),'pv_uci':v.get('pv_uci',[]),
                 'line':v.get('line',[]),'eval':v.get('cp_white',0),'depth':v.get('depth')}
                for v in scan.get('lines',[])]}
      db.execute('''INSERT OR IGNORE INTO position_scans(game_id,ply,fen,scan_json) VALUES(?,?,?,?)''',
         (gid,x['ply'],x['fen'],json.dumps(new,ensure_ascii=False)))
      scanned+=1
 except sqlite3.Error as exc:raise SystemExit('Cannot read legacy data: '+str(exc))
 finally:old.close()
 return inserted,scanned

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--email',required=True);ap.add_argument('--legacy',required=True)
 a=ap.parse_args()
 print('Migrated games and stored position scans:',import_owner(a.legacy,a.email))
