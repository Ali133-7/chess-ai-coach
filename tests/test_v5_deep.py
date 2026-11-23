"""Offline integration checks for v5. Run inside image via python -m unittest."""
import json
import tempfile
import unittest
from unittest.mock import patch
import chess.engine
from pathlib import Path
import chess
from fastapi.testclient import TestClient
import main as core
import coach_v5
import deep_worker as deep
import coach_advanced as advanced
import coach_brain

PGN='''[Event "Archived fixture"]
[Site "Chess.com"]
[Date "2026.11.18"]
[White "ali_ebrahim"]
[Black "Opponent"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
'''

class DeepJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=(core.DATABASE_PATH,core.USERNAME,core.API_KEY)
        core.DATABASE_PATH=Path(self.temp.name)/'test.sqlite3'
        core.USERNAME='ali_ebrahim'
        core.API_KEY='secret-test-key-that-is-more-than-32-characters'
        deep.init()
        self.client=TestClient(core.app)
        self.auth={'X-API-Key':core.API_KEY}

    def tearDown(self):
        core.DATABASE_PATH,core.USERNAME,core.API_KEY=self.old
        self.temp.cleanup()

    def insert_fixture(self):
        return deep.save_game({'url':'https://www.chess.com/game/live/99999999','pgn':PGN,'end_time':1795026163})

    def test_completed_import_creates_persistent_job(self):
        self.assertTrue(self.insert_fixture())
        self.assertTrue(self.insert_fixture()) # duplicate imports are idempotent
        with core.db_connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deep_jobs').fetchone()[0],1)
        response=self.client.get('/api/pro/v5/deep/status',headers=self.auth)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['waiting'],1)
        self.assertEqual(self.client.get('/api/pro/v5/deep/status').status_code,401)

    def test_requeue_and_invalidate_cached_positions(self):
        self.insert_fixture()
        gid=core.game_id('https://www.chess.com/game/live/99999999')
        with core.db_connect() as db:
            db.execute("INSERT INTO deep_scans(game_id,ply,version,fen,scan_json) VALUES(?,?,?,?,?)",
                       (gid,0,deep.VERSION,chess.STARTING_FEN,'{}'))
        response=self.client.post('/api/pro/v5/deep/requeue/'+gid,headers=self.auth)
        self.assertEqual(response.status_code,200)
        with core.db_connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deep_scans').fetchone()[0],0)

    def test_position_checkpoint_resume_after_worker_restart(self):
        self.insert_fixture()
        gid=core.game_id('https://www.chess.com/game/live/99999999')
        with core.db_connect() as db:row=dict(db.execute('SELECT * FROM deep_jobs WHERE game_id=?',(gid,)).fetchone())
        class Engine:
            options={}
            def __init__(self,fail_after=None):self.count=0;self.fail_after=fail_after
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def analyse(self,board,limit,multipv=1):
                self.count+=1
                if self.fail_after and self.count>self.fail_after:raise RuntimeError('simulated shutdown')
                move=next(iter(board.legal_moves))
                return [{'score':chess.engine.PovScore(chess.engine.Cp(0),chess.WHITE),
                    'pv':[move],'depth':12,'nodes':1000}]
        first=Engine(fail_after=2)
        with patch.object(deep.chess.engine.SimpleEngine,'popen_uci',return_value=first):
            with self.assertRaises(RuntimeError):deep.analyze_job(row)
        with core.db_connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM deep_scans').fetchone()[0],2)
        deep.init()  # simulates a container restart: running -> pending
        second=Engine()
        with patch.object(deep.chess.engine.SimpleEngine,'popen_uci',return_value=second):
            deep.analyze_job(row)
        self.assertEqual(second.count,3)  # already-saved scans weren't recomputed
        with core.db_connect() as db:
            self.assertEqual(db.execute('SELECT status FROM deep_jobs WHERE game_id=?',(gid,)).fetchone()[0],'done')
            analysis=json.loads(db.execute('SELECT analysis_json FROM games WHERE id=?',(gid,)).fetchone()[0])
        self.assertEqual(analysis['schema_version'],5)
        self.assertIn('deep_analysis',analysis)

    def test_scenario_explanations_are_legal_and_contextual(self):
        b=chess.Board()
        line=coach_brain.line_insight(b,['e2e4','e7e5','d1h5'])
        self.assertEqual(line['line'],['e4','e5','Qh5'])
        self.assertEqual(len(line['moves']),3)
        self.assertTrue(line['ideas'])
        self.assertEqual(coach_brain.line_insight(b,['e2e5'])['moves'],[])

    def test_rebuild_review_from_saved_scans_without_engine(self):
        import io,chess.pgn
        game=chess.pgn.read_game(io.StringIO(PGN));board=game.board();moves=list(game.mainline_moves());positions=[board.copy()]
        for m in moves:board.push(m);positions.append(board.copy())
        scans=[]
        for b in positions:
            legal=list(b.legal_moves)
            best=legal[0] if legal else None
            lines=[{'uci':best.uci(),'san':b.san(best),'line':[b.san(best)],'pv_uci':[best.uci()],
                    'cp_white':0,'depth':12}] if best else []
            scans.append({'cp_white':0,'mate':None,'lines':lines})
        report=advanced.analysis_from_scans(PGN,'ali_ebrahim',scans,0.01)
        self.assertEqual(report['schema_version'],5)
        self.assertEqual(len(report['all_moves']),len(moves))
        self.assertTrue(report['all_moves'][0]['scenarios'])
        self.assertTrue(report['all_moves'][0]['explanation_ar'])

if __name__=='__main__':unittest.main()
