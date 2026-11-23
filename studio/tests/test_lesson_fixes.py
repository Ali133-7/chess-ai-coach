"""Regression tests for lesson orientation, sides and alternative moves."""
import sqlite3, unittest
import chess
from studio.core import choose_lesson_position
from studio.lesson_engine import assess_move

class LessonsFixedTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY, chess_username TEXT);
        CREATE TABLE games(id INTEGER PRIMARY KEY, user_id INTEGER,white TEXT,black TEXT,url TEXT, finished_at INTEGER);
        CREATE TABLE moves(game_id INTEGER,ply INTEGER,best_uci TEXT,fen_before TEXT,
                           san TEXT,grade TEXT,loss_cp INTEGER,lines_json TEXT);
        CREATE TABLE lesson_solves(user_id INTEGER,lesson_id TEXT,game_id INTEGER,ply INTEGER,solved_at TEXT);
        INSERT INTO users VALUES(1,'ali_ebrahim'),(2,'another_player');
        INSERT INTO games VALUES(101,1,'ali_ebrahim','Rival','https://example.com',100);
        INSERT INTO games VALUES(102,1,'Rival','ali_ebrahim','https://example.com',200);
        INSERT INTO games VALUES(103,2,'another_player','Rival','https://example.com',300);
        INSERT INTO moves VALUES(101,1,'e2e4','rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
             'd4','blunder',340,'[]');
        INSERT INTO moves VALUES(102,2,'e7e5','rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1',
             'a6','blunder',300,'[]');
        INSERT INTO moves VALUES(103,1,'d2d4','rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
             'a3','blunder',900,'[]');
        """)
    def tearDown(self):self.db.close()
    def test_explicit_side(self):
        white=choose_lesson_position(self.db,1,'01','white')
        black=choose_lesson_position(self.db,1,'01','black')
        self.assertEqual(white['game_id'],101)
        self.assertEqual(black['game_id'],102)
    def test_mix_prefers_black_first_then_white(self):
        first=choose_lesson_position(self.db,1,'01')
        self.assertEqual(first['game_id'],102)
        self.db.execute("INSERT INTO lesson_solves VALUES(1,'01',102,2,'2026-01-01')")
        second=choose_lesson_position(self.db,1,'01')
        self.assertEqual(second['game_id'],101)
    def test_scope_does_not_show_other_users(self):
        row=choose_lesson_position(self.db,1,'01','white')
        self.assertEqual(row['game_id'],101)
    def test_saved_alternative_accepted_when_close(self):
        board=chess.Board()
        row={'best_uci':'e2e4','lines_json':'[{"uci":"e2e4","eval":20},{"uci":"d2d4","eval":0}]'}
        res=assess_move(row,board,chess.Move.from_uci('d2d4'))
        self.assertEqual(res['status'],'acceptable');self.assertTrue(res['accepted'])
    def test_saved_alternative_rejected_when_worse(self):
        board=chess.Board()
        row={'best_uci':'e2e4','lines_json':'[{"uci":"e2e4","eval":100},{"uci":"d2d4","eval":0}]'}
        res=assess_move(row,board,chess.Move.from_uci('d2d4'))
        self.assertEqual(res['status'],'weaker');self.assertFalse(res['accepted'])
    def test_best_still_accepted_without_engine(self):
        board=chess.Board()
        row={'best_uci':'e2e4','lines_json':None}
        res=assess_move(row,board,chess.Move.from_uci('e2e4'))
        self.assertTrue(res['accepted'])

if __name__=='__main__':unittest.main()
