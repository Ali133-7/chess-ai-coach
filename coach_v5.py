"""Status and queue management for archived-game deep analysis only."""
import json
from datetime import datetime, timezone
import chess.pgn
from fastapi import Depends,HTTPException,Query
import main as core
import coach_plus as plus


def install(app):
    @app.get('/api/pro/v5/deep/status',dependencies=[Depends(core.auth)])
    def status():
        with core.db_connect() as db:
            try:
                counts={x['status']:x['n'] for x in db.execute('SELECT status,COUNT(*) n FROM deep_jobs GROUP BY status')}
                current=db.execute('''SELECT j.game_id,j.total_plies,j.completed_positions,j.status,j.last_error,
                    g.white,g.black,g.finished_at FROM deep_jobs j JOIN games g ON j.game_id=g.id
                    WHERE j.status IN ('running','error') ORDER BY CASE j.status WHEN 'running' THEN 0 ELSE 1 END,j.updated_at DESC LIMIT 8''').fetchall()
                archive={x['key']:x['value'] for x in db.execute('SELECT key,value FROM archive_state')}
            except Exception:
                return {'worker_ready':False,'notice':'العامل العميق لم يهيئ قاعدة الوظائف بعد'}
            total=sum(counts.values())
            return {'worker_ready':True,'total':total,'states':counts,
                 'completed':counts.get('done',0),'waiting':counts.get('pending',0),
                 'current':[{'game_id':r['game_id'],'white':r['white'],'black':r['black'],
                   'status':r['status'],'finished_at':r['finished_at'],
                   'positions_done':r['completed_positions'],'positions_total':r['total_plies']+1,
                   'percent':round(r['completed_positions']*100/max(1,r['total_plies']+1),1),
                   'error':r['last_error']} for r in current],
                 'archive':archive,'notice':'تحليل المباريات المنتهية يعمل على السيرفر بدون متصفح.'}

    @app.post('/api/pro/v5/deep/requeue/{gid}',dependencies=[Depends(core.auth)])
    def requeue(gid:str):
        with core.db_connect() as db:
            row=db.execute('SELECT pgn FROM games WHERE id=?',(gid,)).fetchone()
            if not row:raise HTTPException(status_code=404,detail='Unknown archived game')
            plus.completed_game(row['pgn'])
            state=db.execute('SELECT status FROM deep_jobs WHERE game_id=?',(gid,)).fetchone()
            if state and state['status']=='running':raise HTTPException(status_code=409,detail='Game is being analyzed')
            db.execute('DELETE FROM deep_scans WHERE game_id=?',(gid,))
            db.execute('''INSERT INTO deep_jobs(game_id,status,total_plies,completed_positions,updated_at,attempts)
              VALUES(?,?,?,?,?,0) ON CONFLICT(game_id) DO UPDATE SET
              status='pending',completed_positions=0,updated_at=excluded.updated_at,last_error=NULL,attempts=0''',
              (gid,'pending',0,0,datetime.now(timezone.utc).isoformat()))
        return {'queued':True,'game_id':gid}

    @app.post('/api/pro/v5/deep/requeue-all',dependencies=[Depends(core.auth)])
    def requeue_all():
        with core.db_connect() as db:
            rows=db.execute('SELECT id,pgn FROM games').fetchall();count=0
            for row in rows:
                try:plus.completed_game(row['pgn'])
                except HTTPException:continue
                state=db.execute('SELECT status FROM deep_jobs WHERE game_id=?',(row['id'],)).fetchone()
                if state and state['status']=='running':continue
                db.execute('DELETE FROM deep_scans WHERE game_id=?',(row['id'],))
                db.execute('''INSERT INTO deep_jobs(game_id,status,total_plies,completed_positions,updated_at,attempts)
                  VALUES(?,?,?,?,?,0) ON CONFLICT(game_id) DO UPDATE SET
                  status='pending',completed_positions=0,updated_at=excluded.updated_at,last_error=NULL,attempts=0''',
                  (row['id'],'pending',0,0,datetime.now(timezone.utc).isoformat()))
                count+=1
        return {'queued':count}
