"""Offline integration tests. No real OpenAI requests or Chess.com calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import chess
from fastapi.testclient import TestClient
from studio import core
from studio.app import app
from studio.teacher_v7.router import setup_teacher
from studio.teacher_v7.schema import TutorAnswer, LineNote
from studio.teacher_v7.engine import verified_scenarios


class TutorV7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_db=core.DB
        cls.temp=tempfile.TemporaryDirectory()
        core.DB=Path(cls.temp.name)/'tutor.sqlite3'
        core.setup();setup_teacher()
        cls.a=TestClient(app);cls.b=TestClient(app)
        for client,email in ((cls.a,'tutor-a@example.net'),(cls.b,'tutor-b@example.net')):
            r=client.post('/api/auth/register',json={'email':email,'password':'very-long-test-password-23456'})
            assert r.status_code==201,r.text
        cls.csrf_a=cls.a.get('/api/me').json()['csrf']
        cls.csrf_b=cls.b.get('/api/me').json()['csrf']
        with core.connection() as db:
            uid=db.execute('SELECT id FROM users WHERE email=?',('tutor-a@example.net',)).fetchone()['id']
            cls.uid=uid
            gid=db.execute('''INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,stage,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?)''',(uid,'tutor-fixture','https://www.chess.com/game/live/10',
                  '[Event "Test"]\n[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n1. e4 e5 1-0',
                  123456,'a','b','1-0','done',core.now())).lastrowid
            cls.gid=gid
            b=chess.Board();before=b.fen();b.push_uci('e2e4')
            db.execute('''INSERT INTO moves(game_id,ply,san,uci,fen_before,fen_after,grade,loss_cp,best_uci,best_san,lines_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(gid,1,'e4','e2e4',before,b.fen(),'mistake',180,
                'd2d4','d4','[{"pv_uci":["d2d4","d7d5"],"eval":45,"depth":17},'
                '{"pv_uci":["g1f3","g8f6"],"eval":12},'
                '{"pv_uci":["h1h8"],"eval":null}]'))

    @classmethod
    def tearDownClass(cls):
        core.DB=cls.old_db
        cls.temp.cleanup()

    def fake_answer(self,*args,**kwargs):
        return TutorAnswer(title_ar='شرح وضعية المركز',explanation_ar='يتغير الضغط على المركز.',
            benefits_ar=['تحسين نشاط القطع'],risks_ar=['راجع تهديدات الخصم'],
            scenario_notes=[LineNote(scenario_id='line-0', explanation_ar='خيار مركزي', focus_ar='نشاط القطع'),
                LineNote(scenario_id='invented',explanation_ar='غير صحيح',focus_ar='قصة مختلقة')],
            learning_question_ar='ما أهمية السيطرة على المركز؟'),10,20,'openai','test-model'

    def test_authentication_and_owner(self):
        req={'game_id':self.gid,'ply':1,'question':'اشرح لي'}
        self.assertEqual(TestClient(app).post('/api/teacher/explain',json=req).status_code,401)
        self.assertEqual(self.b.post('/api/teacher/explain',json=req,headers={'X-CSRF-Token':self.csrf_b}).status_code,404)
        self.assertEqual(self.a.post('/api/teacher/explain',json=req).status_code,403)

    def test_schema_and_verified_lines(self):
        with core.connection() as db:
            row=dict(db.execute('SELECT * FROM moves WHERE game_id=?',(self.gid,)).fetchone())
        scenarios=verified_scenarios(row)
        self.assertEqual(len(scenarios),2)
        self.assertEqual(scenarios[0]['moves'],['d2d4','d7d5'])
        self.assertEqual(scenarios[0]['arrow']['from'],'d2')

    def test_generation_cache_and_arrows_are_not_invented(self):
        req={'game_id':self.gid,'ply':1}
        with patch('studio.teacher_v7.router.configured',return_value=True),patch('studio.teacher_v7.router.provider_config',return_value={'primary':'openai','fallback':[],'providers':{'openai':{'model':'test-model','key_file':'/unused-mocked-key'}}}),patch('studio.teacher_v7.router.call_teacher',side_effect=self.fake_answer) as fake:
            r=self.a.post('/api/teacher/explain',json=req,headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(r.status_code,200,r.text)
            result=r.json()
            self.assertEqual([x['scenario_id'] for x in result['scenario_notes']],['line-0'])
            self.assertEqual([x['from'] for x in result['board_actions']],['d2'])
            r2=self.a.post('/api/teacher/explain',json=req,headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(r2.status_code,200,r2.text)
            self.assertTrue(r2.json()['cached'])
            self.assertEqual(fake.call_count,1)

    def test_chat_thread_permissions(self):
        with patch('studio.teacher_v7.router.configured',return_value=True),patch('studio.teacher_v7.router.provider_config',return_value={'primary':'openai','fallback':[],'providers':{'openai':{'model':'test-model','key_file':'/unused-mocked-key'}}}),patch('studio.teacher_v7.router.call_teacher',side_effect=self.fake_answer):
            req={'game_id':self.gid,'ply':1,'question':'لماذا؟'}
            first=self.a.post('/api/teacher/chat',json=req,headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(first.status_code,200,first.text)
            tid=first.json()['thread_id']
            req['thread_id']=tid;req['question']='ما البديل؟'
            second=self.a.post('/api/teacher/chat',json=req,headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(second.status_code,200,second.text)
            self.assertEqual(second.json()['thread_id'],tid)
            self.assertEqual(self.b.get(f'/api/teacher/threads/{tid}').status_code,404)
            self.assertEqual(len(self.a.get(f'/api/teacher/threads/{tid}').json()['messages']),4)

    def test_pending_finished_game_gets_bounded_fast_scan(self):
        # The importer stored a finished PGN, but the deep worker has not finished.
        import chess.engine
        from unittest.mock import MagicMock
        from studio.teacher_v7.router import fetch_position
        with core.connection() as db:
            gid=db.execute("""INSERT INTO games(user_id,external_id,url,pgn,finished_at,white,black,result,stage,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(self.uid,'pending-archived-game','https://www.chess.com/game/live/11',
                '[Event "Test"]\n[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n1. e4 e5 1-0',
                123457,'a','b','1-0','pending',core.now())).lastrowid
        mock_engine=MagicMock()
        mock_engine.__enter__.return_value.analyse.return_value=[{
            'pv':[chess.Move.from_uci('d2d4'),chess.Move.from_uci('d7d5')],
            'score':chess.engine.PovScore(chess.engine.Cp(40),chess.WHITE),'depth':10}]
        with patch('chess.engine.SimpleEngine.popen_uci',return_value=mock_engine):
            position,kind=fetch_position(self.uid,gid,1)
        self.assertEqual(kind,'quick')
        self.assertEqual(position['best_san'],'d4')
        self.assertEqual(len(verified_scenarios(position)),1)

    def test_quota_and_no_key_fail_closed(self):
        with patch('studio.teacher_v7.router.configured',return_value=False):
            resp=self.a.post('/api/teacher/explain',json={'game_id':self.gid,'ply':1,'question':'new unique request'},
                             headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(resp.status_code,503)
        with core.connection() as db:
            day=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()
            db.execute('INSERT OR REPLACE INTO teacher_usage(user_id,day,requests) VALUES(?,?,20)',(self.uid,day))
        with patch('studio.teacher_v7.router.configured',return_value=True):
            resp=self.a.post('/api/teacher/chat',json={'game_id':self.gid,'ply':1,'question':'كيف أتدرب؟'},
                             headers={'X-CSRF-Token':self.csrf_a})
            self.assertEqual(resp.status_code,429,resp.text)

if __name__=='__main__':unittest.main()
