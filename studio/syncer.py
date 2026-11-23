"""Independently refresh linked profiles while the engine is busy for hours."""
import logging,time
from .core import connection,setup,config
from .worker import sync_user
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('studio.sync')

def run():
    setup()
    log.info('Studio archive and published-ratings synchronizer started')
    while True:
        try:
            with connection() as db:
                users=[dict(row) for row in db.execute('SELECT id,chess_username FROM users WHERE chess_username IS NOT NULL AND disabled=0')]
                refresh=int(config(db,'archive_refresh_hours','6'))*3600
            for user in users:
                key='sync_last_'+str(user['id'])
                with connection() as db:
                    item=db.execute('SELECT value FROM worker_state WHERE key=?',(key,)).fetchone()
                previous=float(item['value']) if item else 0
                if previous>time.time()-refresh:
                    continue
                try:
                    sync_user(user)
                    delay=refresh
                except Exception:
                    log.exception('Sync failed for user %s; retry in five minutes',user['id'])
                    delay=300
                # Next eligible at now+delay. Avoid repeated requests for users with empty archives.
                with connection() as db:
                    db.execute('INSERT OR REPLACE INTO worker_state(key,value) VALUES(?,?)',
                               (key,str(time.time()-(refresh-delay))))
        except Exception:
            log.exception('Studio sync cycle error')
        time.sleep(30)

if __name__=='__main__':run()
