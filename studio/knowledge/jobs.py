"""Bounded resumable maintenance; no perpetual remote crawler or hidden scheduler."""
import argparse,json
from . import store,external,analysis
from .. import core

def warm(limit=10):
 with store.connection() as db:
  rev=store.current_revision(db);key='warm_cursor:'+rev;row=db.execute('SELECT value FROM kc_meta WHERE key=?',(key,)).fetchone();cursor=row[0] if row else ''
  items=[dict(r) for r in db.execute('SELECT o.id,p.fen FROM kc_openings o JOIN kc_paths p ON p.revision=o.revision AND p.opening_id=o.id AND p.ply=o.plies WHERE o.revision=? AND o.id>? ORDER BY o.id LIMIT ?',(rev,cursor,limit))]
 done=0;failed=[]
 for row in items:
  try:
   cached=external.evaluation(row['fen'])
   if cached.get('available') is False:external.evaluation(row['fen'],True)
   done+=1
  except Exception:failed.append(row['id'])
  cursor=row['id']
  with store.connection() as db:db.execute('INSERT OR REPLACE INTO kc_meta VALUES(?,?)',(key,cursor))
 with store.connection() as db:remaining=db.execute('SELECT count(*) FROM kc_openings WHERE revision=? AND id>?',(rev,cursor)).fetchone()[0]
 return {'processed':done,'failed_ids':failed,'cursor':cursor,'remaining':remaining,'note':'Only processed openings have cached evaluations; no claim all were precomputed.'}

def warm_common():
 with store.connection() as db:rows=db.execute("SELECT key FROM kc_external_cache WHERE kind='explorer-masters'").fetchall()
 for row in rows:
  fen=row['key']+' 0 1'
  if external.evaluation(fen).get('available') is False:external.evaluation(fen,True)
 print('COMMON_POSITIONS_WARMED',len(rows),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['warm','warm-common','reports']);parser.add_argument('--user',type=int);parser.add_argument('--limit',type=int,default=25);parser.add_argument('--loop',action='store_true');args=parser.parse_args()
 store.setup()
 if args.kind=='warm-common':warm_common()
 elif args.kind=='warm':print(json.dumps(warm(max(1,min(50,args.limit)))),flush=True)
 else:
  if not args.user:raise SystemExit('--user is required')
  cursor=0
  while True:
   result=analysis.update_reports(args.user,cursor,max(1,min(50,args.limit)));print(json.dumps(result),flush=True);cursor=result['next_after_id']
   if not args.loop or not result['remaining']:break
