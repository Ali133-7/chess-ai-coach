"""Transparent Bayesian skill evidence and opt-in spaced puzzle reviews. Not Elo."""
import json,time
from . import core

INTERVALS=(1,3,7,14,30)

def setup(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS adaptive_attempts(session_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,score REAL NOT NULL,themes_json TEXT NOT NULL,created_at REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS adaptive_skills(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,theme TEXT NOT NULL,attempts INTEGER NOT NULL,success_weight REAL NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(user_id,theme));
 CREATE TABLE IF NOT EXISTS adaptive_reviews(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,streak INTEGER NOT NULL DEFAULT 0,due_at REAL NOT NULL,last_score REAL NOT NULL,PRIMARY KEY(user_id,puzzle_id));
 CREATE INDEX IF NOT EXISTS adaptive_due ON adaptive_reviews(user_id,due_at);
 ''')

def record(db,uid,item,session,status):
 if status not in ('solved','revealed','skipped'):return
 score=(1.0 if not session['mistakes'] else .6) if status=='solved' else 0.0
 themes=sorted(set(item['themes'].split()))[:8] or ['calculation'];now=time.time()
 inserted=db.execute('INSERT OR IGNORE INTO adaptive_attempts VALUES(?,?,?,?,?,?)',(session['id'],uid,item['id'],score,json.dumps(themes),now)).rowcount
 if not inserted:return
 old=db.execute('SELECT * FROM adaptive_reviews WHERE user_id=? AND puzzle_id=?',(uid,item['id'])).fetchone()
 if old and old['due_at']>now and score==1:return
 for theme in themes:
  db.execute('INSERT INTO adaptive_skills VALUES(?,?,1,?,?) ON CONFLICT(user_id,theme) DO UPDATE SET attempts=attempts+1,success_weight=success_weight+excluded.success_weight,updated_at=excluded.updated_at',(uid,theme,score,now))
 streak=old['streak'] if old else 0
 # Replaying early never advances a review interval. A failure brings it nearer.
 streak=min(4,streak+1) if old and score==1 else 0
 due=now+INTERVALS[streak]*86400
 db.execute('INSERT INTO adaptive_reviews VALUES(?,?,?,?,?) ON CONFLICT(user_id,puzzle_id) DO UPDATE SET streak=excluded.streak,due_at=excluded.due_at,last_score=excluded.last_score',(uid,item['id'],streak,due,score))

def evidence(uid):
 with core.connection() as db:
  rows=[dict(r) for r in db.execute('SELECT theme,attempts,success_weight FROM adaptive_skills WHERE user_id=?',(uid,))]
 for row in rows:row['mastery']=(row['success_weight']+2)/(row['attempts']+4)
 rows.sort(key=lambda r:(r['mastery'],-r['attempts'],r['theme']))
 return rows

def recommendation(uid,source='all'):
 from .knowledge import analysis,drills
 basis=analysis.recommendation_basis(uid);skills=evidence(uid);weak=skills[0] if skills else None
 target=max(0,min(5000,basis['reference_rating']+round(300*((weak['mastery'] if weak else .5)-.5))))
 theme=weak['theme'] if weak else basis['theme']
 result=drills.list_puzzles(target,theme,uid=uid,source=source,daily_priority=True)
 if not result['items']:result=drills.list_puzzles(target,uid=uid,source=source)
 if not result['items']:result=drills.list_puzzles(target,uid=uid,source=source,broaden=True)
 with core.connection() as db:
  due=[dict(r) for r in db.execute('SELECT puzzle_id,due_at,last_score,streak FROM adaptive_reviews WHERE user_id=? AND due_at<=? ORDER BY due_at LIMIT 10',(uid,time.time()))]
 return {'new':result['items'],'due_reviews':due,'weaknesses':skills[:8],'target_puzzle_rating':target,'reference_rating':basis['reference_rating'],'recommended_theme':theme,'formula':'mastery=(success_weight+2)/(attempts+4); independent solve=1, corrected solve=.6, skip/reveal=0; target=reference+round(300*(weakest_mastery-.5))','rating_notice':'Puzzle selection heuristic, not a player Elo estimate. Generated exercises remain unrated.','review_intervals_days':list(INTERVALS),'review_policy':'Solved puzzles never reappear in new recommendations. Due reviews are explicit and optional.'}

def install(app,auth):
 from fastapi import Depends
 @app.get('/api/training/plan')
 def plan(user=Depends(auth)):return recommendation(user['id'])
