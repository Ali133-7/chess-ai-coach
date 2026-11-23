"""Run inside the Docker image: python -m unittest discover -s tests -v.

No external Chess.com requests. Uses temporary SQLite and a sample completed PGN.
"""
import json
from pathlib import Path
import tempfile
import unittest

import chess
import chess.engine
from fastapi.testclient import TestClient

import main as core
import coach_plus as pro
import coach_advanced as advanced
import move_quality as grades

SAMPLE_PGN = '''[Event "Test"]
[Site "Local"]
[Date "2026.11.18"]
[White "ali_ebrahim"]
[Black "TestOpponent"]
[Result "1-0"]
[ECO "C20"]

1. e4 e5 2. Nf3 Nc6 1-0
'''


class CoachProTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.old_db = core.DATABASE_PATH
        cls.old_username = core.USERNAME
        cls.old_key = core.API_KEY
        core.DATABASE_PATH = Path(cls.tmp.name) / "test.sqlite3"
        core.USERNAME = "ali_ebrahim"
        core.API_KEY = "temporary-test-key-1234567890-abcdef"
        core.init_db()
        pro.init_plus_db()
        advanced.init_issue_db()
        cls.gid = core.game_id("https://www.chess.com/game/live/123")
        analysis = {"player": "ali_ebrahim", "white": "ali_ebrahim", "black": "TestOpponent", "result": "1-0",
                    "moves_reviewed": 2, "errors": 1,
                    "all_player_moves": [{"move_number": 1, "color": "white", "played": "e4", "best": "d4",
                                          "loss_cp": 150, "quality": "خطأ", "best_line": ["d4", "d5"],
                                          "fen_before": chess.STARTING_FEN, "explanation_ar": "جرّب d4 في هذا التمرين."},
                                         {"move_number": 2, "color": "white", "played": "Nf3", "best": "Nf3",
                                          "loss_cp": 0, "quality": "جيدة", "best_line": ["Nf3"],
                                          "fen_before": chess.Board().fen(), "explanation_ar": "نقلة جيدة."}]}
        with core.db_connect() as db:
            db.execute('''INSERT INTO games(id,url,username,pgn,finished_at,white,black,result,analysis_json,inserted_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (cls.gid, "https://www.chess.com/game/live/123", core.USERNAME, SAMPLE_PGN,
                 1795026163, "ali_ebrahim", "TestOpponent", "win / resigned", json.dumps(analysis),
                 "2026-11-18T19:32:28+00:00"))
        cls.client = TestClient(core.app)
        cls.headers = {"X-API-Key": core.API_KEY}

    @classmethod
    def tearDownClass(cls):
        core.DATABASE_PATH = cls.old_db
        core.USERNAME = cls.old_username
        core.API_KEY = cls.old_key
        cls.tmp.cleanup()

    def test_authentication_protected(self):
        self.assertEqual(self.client.get('/api/pro/dashboard').status_code, 401)
        self.assertEqual(self.client.get('/api/pro/games').status_code, 401)
        self.assertEqual(self.client.get('/api/pro/puzzles').status_code, 401)

    def test_frontend_is_served(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Chess AI Coach', response.text)
        self.assertIn("default-src 'self'", response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/assets/app.js').status_code, 200)
        self.assertEqual(self.client.get('/assets/style.css').status_code, 200)

    def test_game_review_includes_legal_positions(self):
        r = self.client.get('/api/pro/review/'+self.gid, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['total_plies'], 4)
        self.assertEqual(data['plies'][0]['fen'], chess.STARTING_FEN)
        self.assertEqual(data['plies'][1]['san'], 'e4')
        self.assertEqual(data['plies'][1]['lesson']['best'], 'd4')
        self.assertEqual(data['result'], 'win')

    def test_puzzle_attempt_and_progress(self):
        data = self.client.get('/api/pro/puzzles',headers=self.headers).json()
        self.assertGreaterEqual(data['total'], 1)
        puzzle=data['puzzles'][0]
        self.assertNotIn('best_uci', puzzle)
        self.assertIn('d2d4', puzzle['legal_moves'])
        result=self.client.post('/api/pro/puzzles/'+self.gid+'/1/attempt',
                                headers=self.headers,json={'uci':'d2d4'})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['correct'])
        self.assertEqual(result.json()['streak'], 1)
        data2=self.client.get('/api/pro/puzzles',headers=self.headers).json()['puzzles'][0]
        self.assertEqual(data2['solves'], 1)
        self.assertEqual(data2['attempts'], 1)

    def test_illegal_puzzle_move_rejected(self):
        r=self.client.post('/api/pro/puzzles/'+self.gid+'/1/attempt',headers=self.headers,
                           json={'uci':'a1a8'})
        self.assertEqual(r.status_code, 422)

    def test_study_plan_and_dashboard(self):
        d=self.client.get('/api/pro/dashboard',headers=self.headers).json()
        self.assertEqual(d['games'],1)
        self.assertEqual(d['wins'],1)
        self.assertEqual(d['puzzles_available'],1)
        p=self.client.get('/api/pro/plan',headers=self.headers).json()
        self.assertEqual(len(p['days']),7)

    def test_white_training_session_is_independent(self):
        d=self.client.post('/api/pro/training', headers=self.headers,
                           json={'color':'white','strength':7}).json()
        self.assertEqual(d['color'],'white')
        self.assertIn('e2e4',d['legal_moves'])
        self.assertEqual(d['fen'],chess.STARTING_FEN)

    def test_mate_score_is_bounded(self):
        info={'score':chess.engine.PovScore(chess.engine.Mate(1),chess.WHITE)}
        score=core.score_from_perspective(info,chess.WHITE)
        self.assertGreater(score,0)
        self.assertLess(score,2000)
        self.assertLess(core.score_from_perspective(info,chess.BLACK),0)

    def test_3d_piece_assets_and_browser_board_logic(self):
        for name in ('wK','wQ','wR','wB','wN','wP','bK','bQ','bR','bB','bN','bP'):
            response=self.client.get('/assets/pieces/'+name+'.png')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content[:8],b'\x89PNG\r\n\x1a\n')
        self.assertIn('pointerdown',self.client.get('/assets/board-pro.js').text)
        self.assertIn('promotion',self.client.get('/assets/board-pro.js').text)

    def test_legal_study_variation_from_archived_game_only(self):
        r=self.client.post('/api/pro/v3/game/'+self.gid+'/variation/0',headers=self.headers,
                           json={'moves':['e2e4','e7e5','g1f3']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['san'],['e4','e5','Nf3'])
        self.assertIn('b8c6',r.json()['legal_moves'])
        bad=self.client.post('/api/pro/v3/game/'+self.gid+'/variation/0',headers=self.headers,
                             json={'moves':['e2e5']})
        self.assertEqual(bad.status_code,422)
        unknown=self.client.post('/api/pro/v3/game/'+self.gid+'/variation/15',headers=self.headers,
                                 json={'moves':[]})
        self.assertEqual(unknown.status_code,404)

    def test_issues_can_be_saved_and_tracked(self):
        r=self.client.get('/api/pro/v3/issues',headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['issues'][0]['played'],'e4')
        save=self.client.post('/api/pro/v3/issues/'+self.gid+'/1',headers=self.headers,
                              json={'status':'practicing','notes':'افحص تهديد الملك أولاً'})
        self.assertEqual(save.status_code,200)
        r2=self.client.get('/api/pro/v3/issues?status=practicing',headers=self.headers)
        self.assertEqual(r2.json()['issues'][0]['notes'],'افحص تهديد الملك أولاً')
        p=self.client.get('/api/pro/v3/progress',headers=self.headers)
        self.assertEqual(p.status_code,200)
        self.assertEqual(p.json()['legacy_games'],1)
        self.assertEqual(self.client.get('/api/pro/v3/issues').status_code,401)

    def test_move_accuracy_heuristic_is_bounded(self):
        self.assertAlmostEqual(advanced.probability(0),50.0)
        self.assertGreater(advanced.probability(400),advanced.probability(0))
        self.assertEqual(advanced.classify(350,False,30)[1],'blunder')

    def test_seven_move_quality_categories(self):
        self.assertEqual(len(grades.CATEGORIES),7)
        self.assertEqual(grades.classify(0,True,0), 'excellent')
        self.assertEqual(grades.classify(0,True,0,brilliant=True), 'brilliant')
        self.assertEqual(grades.classify(39,False,2), 'good')
        self.assertEqual(grades.classify(90,False,4), 'weak')
        self.assertEqual(grades.classify(210,False,18,missed=True), 'missed')
        self.assertEqual(grades.classify(200,False,12), 'mistake')
        self.assertEqual(grades.classify(400,False,35), 'blunder')
        self.assertEqual(grades.normalize('هفوة كبيرة'), 'blunder')
        self.assertIsNone(grades.normalize('undefined'))

    def test_puzzle_hint_arrow_and_continue_private_game(self):
        hint=self.client.get('/api/pro/puzzles/'+self.gid+'/1/hint',headers=self.headers)
        self.assertEqual(hint.status_code,200)
        self.assertEqual(hint.json()['best_uci'],'d2d4')
        unauthorized=self.client.get('/api/pro/puzzles/'+self.gid+'/1/hint')
        self.assertEqual(unauthorized.status_code,401)
        res=self.client.post('/api/pro/puzzles/'+self.gid+'/1/continue',headers=self.headers,json={'uci':'d2d4'})
        self.assertEqual(res.status_code,200)
        self.assertEqual(res.json()['color'],'white')
        self.assertGreaterEqual(len(res.json()['history']),1)

    def test_puzzle_feedback_not_contradictory(self):
        response=self.client.post('/api/pro/puzzles/'+self.gid+'/1/attempt',headers=self.headers,json={'uci':'d2d4'})
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertTrue(data['correct'])
        self.assertIn('طابق الحل الأقوى المحفوظ',data['success_explanation_ar'])
        self.assertNotIn('أضعفت موقفك',data['success_explanation_ar'])
        self.assertEqual(data['quality_code'],'excellent')

    def test_active_game_is_rejected(self):
        with self.assertRaises(Exception):
            pro.completed_game(SAMPLE_PGN.replace('[Result "1-0"]','[Result "*"]').replace('1-0\n','*\n'))


if __name__ == '__main__':
    unittest.main()
