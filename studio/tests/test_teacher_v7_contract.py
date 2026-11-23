"""These checks can run without python-chess or network access."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio.teacher_v7 import service
from studio.teacher_v7.schema import SCHEMA, TutorAnswer

class DummyResponse:
    def __init__(self, payload):self.payload=payload;self.status_code=200;self.headers={}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def iter_bytes(self):yield json.dumps(self.payload).encode()
    def raise_for_status(self):pass
    def json(self):return self.payload

class DummyClient:
    def __init__(self, payload):self.payload=payload;self.sent=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def stream(self,method,url,json,headers):
        self.sent=(url,json,headers)
        return DummyResponse(self.payload)

class TutorContractTests(unittest.TestCase):
    def test_schema_fields_are_all_required(self):
        self.assertFalse(SCHEMA['additionalProperties'])
        self.assertEqual(set(SCHEMA['required']),set(SCHEMA['properties']))
        example={'title_ar':'درس المركز','explanation_ar':'ابدأ بفحص المركز',
                 'benefits_ar':['الضغط على الوسط'],'risks_ar':['تعرض قطعة للهجوم'],
                 'scenario_notes':[{'scenario_id':'line-0','explanation_ar':'أفضلية متواضعة','focus_ar':'الوسط'}],
                 'learning_question_ar':'ماذا سيتغير؟'}
        parsed=TutorAnswer.model_validate(example)
        self.assertEqual(parsed.title_ar,'درس المركز')

    def test_https_response_parse_and_private_key(self):
        answer={'title_ar':'درس','explanation_ar':'شرح','benefits_ar':['نعم'],'risks_ar':['انتبه'],
                'scenario_notes':[],'learning_question_ar':'لماذا؟'}
        result={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}],
                'usage':{'input_tokens':100,'output_tokens':50}}
        fake=DummyClient(result)
        with tempfile.TemporaryDirectory() as temp:
            key=Path(temp)/'secret';key.write_text('sk-proj-test-not-a-real-secret')
            key.chmod(0o600)
            with patch.object(service,'KEY_FILE',key),patch.object(service.httpx,'Client',return_value=fake):
                value,ins,outs=service.call_openai({'fen':'start'},'اشرح')
        self.assertEqual(value.explanation_ar,'شرح')
        self.assertEqual((ins,outs),(100,50))
        uri,payload,headers=fake.sent
        self.assertEqual(uri,'https://api.openai.com/v1/responses')
        self.assertFalse(payload['store'])
        self.assertEqual(payload['text']['format']['type'],'json_schema')
        self.assertEqual(headers['Authorization'],'Bearer sk-proj-test-not-a-real-secret')
        self.assertNotIn('sk-proj-test-not-a-real-secret',json.dumps(payload))

    def test_incomplete_result_is_not_presented_as_coaching(self):
        fake=DummyClient({'status':'incomplete','output':[]})
        with tempfile.TemporaryDirectory() as temp:
            key=Path(temp)/'secret';key.write_text('sk-proj-test-not-a-real-secret')
            key.chmod(0o600)
            with patch.object(service,'KEY_FILE',key),patch.object(service.httpx,'Client',return_value=fake):
                with self.assertRaises(RuntimeError):
                    service.call_openai({'fen':'start'},'اشرح')

if __name__=='__main__':unittest.main()
