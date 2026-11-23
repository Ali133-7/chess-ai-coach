"""Bounded reconciliation of existing orders/subscriptions; never creates payments."""
import argparse,logging,time
from . import core,billing,google_play
log=logging.getLogger('control-worker')
def cycle():
 with core.connection() as db:
  rows=[dict(r) for r in db.execute("SELECT id,user_id FROM control_orders WHERE status='pending' AND last_check<? ORDER BY last_check LIMIT 3",(time.time()-60,))]
 for row in rows:
  try:billing.reconcile(row['id'],actor=row['user_id'])
  except Exception:log.warning('Order verification postponed')
 google_play.refresh_due(3)
def main():
 p=argparse.ArgumentParser();p.add_argument('--loop',action='store_true');args=p.parse_args();core.setup()
 while True:
  try:cycle()
  except Exception:log.warning('Control refresh postponed')
  if not args.loop:return
  time.sleep(60)
if __name__=='__main__':main()
