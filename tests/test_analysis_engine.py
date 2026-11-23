"""Real Stockfish smoke test; deterministic cache accounting, not timing assertions."""
import os,unittest
from studio import core,worker,analysis_runtime
import test_analysis_runtime as common

class EngineSmoke(unittest.TestCase):
 setUp=common.RuntimeTests.setUp
 tearDown=common.RuntimeTests.tearDown
 game=common.RuntimeTests.game
 @unittest.skipUnless(os.path.isfile(worker.STOCKFISH),'Stockfish binary not available')
 def test_real_engine_two_games_share_verified_scans(self):
  self.game();self.game(suffix='real-two')
  with core.connection() as db:
   db.execute("INSERT INTO analysis_preferences VALUES(?,'turbo')",(self.uids[1],))
  for _ in range(6):worker.job()
  with core.connection() as db:
   self.assertEqual(db.execute("SELECT count(*) FROM games WHERE stage='done'").fetchone()[0],2)
   self.assertEqual(db.execute('SELECT count(*) FROM shared_engine_scans WHERE scan_json IS NOT NULL').fetchone()[0],5)
   self.assertEqual(db.execute('SELECT sum(hits) FROM shared_engine_scans').fetchone()[0],5)
   self.assertEqual(db.execute('SELECT count(*) FROM moves WHERE best_uci IS NOT NULL').fetchone()[0],8)

if __name__=='__main__':unittest.main()
