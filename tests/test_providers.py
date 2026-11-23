import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from studio.teacher_v7 import providers as p

ANSWER={'title_ar':'درس','explanation_ar':'شرح','benefits_ar':['نشاط'], 'risks_ar':['تهديد'],
        'scenario_notes':[], 'learning_question_ar':'لماذا؟'}

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key=Path(self.tmp.name)/'key'
        self.key.write_text('test-secret-at-least-15')
        self.key.chmod(0o600)
        self.cfg={'primary':'groq','fallback':[], 'providers':{
            n:{'key_file':str(self.key),'model':'chosen-model'} for n in p.ENDPOINTS}}
        self.supplied={'VERIFIED_CONTEXT':{'scenarios':[]},'QUESTION_AR':'اشرح'}
        self.calls=[]
        self.real_client=httpx.Client

    def result(self,name,answer=None):
        answer=ANSWER if answer is None else answer
        if name=='openai':
            return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}], 'usage':{'input_tokens':2,'output_tokens':3}}
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}], 'usage':{'prompt_tokens':2,'completion_tokens':3}}

    def run_fake(self,handler):
        def record(req):
            self.calls.append(req)
            return handler(req)
        with patch.object(p.httpx,'Client',side_effect=lambda **kw:self.real_client(transport=httpx.MockTransport(record),**kw)):
            return p.generate(self.cfg,'instructions',self.supplied)

    def test_all_four_endpoints_and_credentials(self):
        for name,url in p.ENDPOINTS.items():
            with self.subTest(name=name):
                self.cfg['primary']=name
                answer,ins,outs,provider,model=self.run_fake(lambda req:httpx.Response(200,json=self.result(name)))
                self.assertEqual((provider,model,ins,outs),(name,'chosen-model',2,3))
                req=self.calls[-1]
                self.assertEqual(str(req.url),url)
                self.assertEqual(req.headers['Authorization'],'Bearer test-secret-at-least-15')
                self.assertNotIn('test-secret',req.content.decode())
                body=json.loads(req.content)
                if name=='openai': self.assertFalse(body['store'])
                else:self.assertEqual(body['response_format'],{'type':'json_object'})


    def test_output_language_is_applied_to_every_provider(self):
        from studio.locale import LANGUAGE
        token=LANGUAGE.set('en')
        try:
            for name in p.ENDPOINTS:
                self.cfg['primary']=name
                self.run_fake(lambda req:httpx.Response(200,json=self.result(name)))
                body=json.loads(self.calls[-1].content)
                prompt=body['instructions'] if name=='openai' else body['messages'][0]['content']
                self.assertIn('OUTPUT LANGUAGE: English',prompt)
                self.assertIn('Keep schema keys',prompt)
        finally:LANGUAGE.reset(token)

    def test_transient_and_timeout_fallback(self):
        self.cfg['fallback']=['xai']
        for failure in [429,503,'timeout']:
            self.calls=[]
            def handler(req):
                if req.url.host=='api.groq.com':
                    if failure=='timeout':raise httpx.ReadTimeout('secret upstream detail')
                    return httpx.Response(failure,text='secret upstream detail')
                return httpx.Response(200,json=self.result('xai'))
            self.assertEqual(self.run_fake(handler)[3],'xai')
            self.assertEqual(len(self.calls),2)

    def test_permanent_errors_never_fallback_or_expose_body(self):
        self.cfg['fallback']=['xai']
        for code in [400,401,403,404,302]:
            self.calls=[]
            with self.assertRaises(p.ProviderError) as e:
                self.run_fake(lambda req:httpx.Response(code,text='test-secret-at-least-15'))
            self.assertEqual(len(self.calls),1)
            self.assertNotIn('test-secret',str(e.exception))

    def test_invalid_schema_refusal_truncation_and_invented_actions_rejected(self):
        bad=copy.deepcopy(ANSWER);bad['board_actions']=[{'from':'a1','to':'h8'}]
        wrong=copy.deepcopy(ANSWER);wrong['scenario_notes']=[{'scenario_id':'invented','explanation_ar':'x','focus_ar':'x'}]
        for answer in [{},bad,wrong,{**ANSWER,'title_ar':4}]:
            with self.assertRaises(p.ProviderError):
                self.run_fake(lambda req:httpx.Response(200,json=self.result('groq',answer)))
        result=self.result('groq');result['choices'][0]['finish_reason']='length'
        with self.assertRaises(p.ProviderError):self.run_fake(lambda req:httpx.Response(200,json=result))
        result=self.result('groq');result['choices'][0]['message']['refusal']='no'
        with self.assertRaises(p.ProviderError):self.run_fake(lambda req:httpx.Response(200,json=result))

    def test_missing_key_can_fallback_and_status_has_no_secrets(self):
        self.cfg['providers']['groq']['key_file']=str(self.key)+'missing'
        self.cfg['fallback']=['xai']
        self.assertEqual(self.run_fake(lambda req:httpx.Response(200,json=self.result('xai')))[3],'xai')
        public=json.dumps(p.status(self.cfg))
        self.assertNotIn(str(self.key),public)
        self.assertNotIn('test-secret',public)

    def test_config_and_cache_identity(self):
        file=Path(self.tmp.name)/'cfg'
        file.write_text('{"primary":"grok"}')
        with patch.object(p,'CONFIG_FILE',file):
            with self.assertRaises(p.ProviderError):p.load_config()
        first=p.identity(self.cfg)
        self.cfg['fallback']=['xai'];self.assertNotEqual(first,p.identity(self.cfg))
        first=p.identity(self.cfg)
        self.cfg['providers']['groq']['model']='different';self.assertNotEqual(first,p.identity(self.cfg))

    def test_oversize_and_malformed_responses(self):
        for body in ['no json', 'x'*262145]:
            with self.assertRaises(p.ProviderError):self.run_fake(lambda req:httpx.Response(200,text=body))

    def test_groq_reasoning_model_has_constrained_schema_and_output_budget(self):
        self.cfg['providers']['groq']['model']='openai/gpt-oss-120b'
        self.supplied['VERIFIED_CONTEXT']['scenarios']=[{'id':'line-0'}]
        self.run_fake(lambda req:httpx.Response(200,json=self.result('groq')))
        body=json.loads(self.calls[-1].content)
        self.assertNotIn('max_tokens',body)
        self.assertEqual(body['max_completion_tokens'],4096)
        self.assertEqual(body['reasoning_effort'],'low')
        fmt=body['response_format']['json_schema']
        self.assertTrue(fmt['strict'])
        self.assertEqual(fmt['schema']['properties']['scenario_notes']['items']['properties']['scenario_id']['enum'],['line-0'])
        self.assertNotIn('enum',p.SCHEMA['properties']['scenario_notes']['items']['properties']['scenario_id'])
        self.supplied['VERIFIED_CONTEXT']['scenarios']=[]
        self.run_fake(lambda req:httpx.Response(200,json=self.result('groq')))
        body=json.loads(self.calls[-1].content)
        self.assertEqual(body['response_format']['json_schema']['schema']['properties']['scenario_notes']['maxItems'],0)

    def test_safe_error_codes_distinguish_limit_and_truncation(self):
        with self.assertRaises(p.ProviderError) as error:
            self.run_fake(lambda req:httpx.Response(429,text='secret upstream'))
        self.assertEqual(error.exception.code,'rate_limited')
        result=self.result('groq');result['choices'][0]['finish_reason']='length'
        with self.assertRaises(p.ProviderError) as error:
            self.run_fake(lambda req:httpx.Response(200,json=result))
        self.assertEqual(error.exception.code,'output_truncated')

    def test_no_fallback_without_opt_in(self):
        with self.assertRaises(p.ProviderError):self.run_fake(lambda req:httpx.Response(429))
        self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()
