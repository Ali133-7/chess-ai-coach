"""Server-only provider transport. Endpoints are fixed; redirects/proxy env disabled."""
import copy
import hashlib
import json
import os
import stat
import time
from pathlib import Path
import httpx
from .schema import TutorAnswer, SCHEMA

CONFIG_FILE = Path(os.getenv('TEACHER_PROVIDERS_FILE', '/studio-data/teacher-providers.json'))
ENDPOINTS = {
    'groq': 'https://api.groq.com/openai/v1/chat/completions',
    'xai': 'https://api.x.ai/v1/chat/completions',
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    'openai': 'https://api.openai.com/v1/responses',
}
RETRYABLE = {408, 429, 500, 502, 503, 504}

class ProviderError(RuntimeError):
    """Contains only safe category/provider names, never upstream text or credentials."""
    def __init__(self, message, code='provider_error'):
        super().__init__(message)
        self.code = code



def load_config():
    if not CONFIG_FILE.exists():
        return None
    try:
        if CONFIG_FILE.stat().st_size > 16384:
            raise ValueError()
        cfg = json.loads(CONFIG_FILE.read_text('utf-8'))
        if set(cfg) != {'primary', 'fallback', 'providers'}:
            raise ValueError()
        order = [cfg['primary']] + cfg['fallback']
        if not isinstance(cfg['fallback'], list) or len(order) > 4 or len(set(order)) != len(order):
            raise ValueError()
        if not isinstance(cfg['providers'], dict) or not set(cfg['providers']) <= ENDPOINTS.keys():
            raise ValueError()
        for name in order:
            p = cfg['providers'][name]
            if name not in ENDPOINTS or set(p) != {'model', 'key_file'}:
                raise ValueError()
            if not isinstance(p['model'], str) or not p['model'].strip() or len(p['model']) > 160:
                raise ValueError()
            if not isinstance(p['key_file'], str) or not Path(p['key_file']).is_absolute():
                raise ValueError()
        return cfg
    except Exception:
        raise ProviderError('Invalid teacher provider configuration') from None


def read_key(path):
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError()
        if os.name != 'nt' and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError()
        key = path.read_text('utf-8').strip()
        if len(key) < 15 or not key.isascii() or any(c.isspace() for c in key):
            raise ValueError()
        return key
    except Exception:
        raise ProviderError('Provider key unavailable') from None


def configuration(legacy_path, legacy_model):
    cfg = load_config()
    return cfg or {'primary':'openai', 'fallback':[], 'providers':{
        'openai':{'model':legacy_model, 'key_file':str(legacy_path)}}}


def identity(cfg):
    # No key content or paths enter cache keys or public status.
    public = [(n, cfg['providers'][n]['model']) for n in [cfg['primary']] + cfg['fallback']]
    return hashlib.sha256(json.dumps(public).encode()).hexdigest()


def status(cfg):
    available = []
    for name in [cfg['primary']] + cfg['fallback']:
        try:
            read_key(cfg['providers'][name]['key_file'])
            available.append(name)
        except ProviderError:
            pass
    return {'ready':bool(available), 'provider':cfg['primary'],
            'model':cfg['providers'][cfg['primary']]['model'],
            'fallback':cfg['fallback'], 'available_providers':available}


def generate(cfg, instructions, supplied, *, answer_type=TutorAnswer, schema=None, task_name='chess_teacher_v7', apply_locale=True):
    from ..control_store import global_ai_enabled
    if not global_ai_enabled():raise ProviderError('AI services paused by administrator','disabled')
    schema = copy.deepcopy(SCHEMA if schema is None else schema)
    teacher_task = answer_type is TutorAnswer
    from ..locale import instructions_for
    if apply_locale:
        instructions = instructions_for(instructions)
    # One attempt per configured provider; no hidden SDK retries or error-body logging.
    deadline = time.monotonic() + 55
    failure_code = "unavailable"
    for name in [cfg['primary']] + cfg['fallback']:
        p = cfg['providers'][name]
        try:
            secret = read_key(p['key_file'])
        except ProviderError:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        prompt = json.dumps(supplied, ensure_ascii=False)
        if name == 'openai':
            payload = {'model':p['model'], 'store':False, 'instructions':instructions,
                       'input':[{'role':'user','content':prompt}], 'max_output_tokens':1800,
                       'text':{'format':{'type':'json_schema','name':task_name,'strict':True,'schema':schema}}}
        else:
            payload = {'model':p['model'], 'messages':[
                {'role':'system','content':instructions + '\nReturn only a JSON object matching this schema: ' + json.dumps(schema)},
                {'role':'user','content':prompt}], 'max_tokens':1800,
                'response_format':{'type':'json_object'}}
            if name == 'groq' and p['model'] in ('openai/gpt-oss-20b', 'openai/gpt-oss-120b'):
                # These reasoning models support constrained JSON Schema on Groq.
                # Reserve room for both reasoning and the actual Arabic answer.
                payload.pop('max_tokens')
                payload['max_completion_tokens'] = 4096
                payload['reasoning_effort'] = 'low'
                if teacher_task:
                    ids = [s['id'] for s in supplied['VERIFIED_CONTEXT'].get('scenarios', [])]
                    if ids:
                        schema['properties']['scenario_notes']['items']['properties']['scenario_id']['enum'] = ids
                    else:
                        schema['properties']['scenario_notes']['maxItems'] = 0
                payload['response_format'] = {'type':'json_schema', 'json_schema':{
                    'name':task_name, 'strict':True, 'schema':schema}}

        try:
            with httpx.Client(timeout=httpx.Timeout(min(20, remaining), connect=min(5, remaining)),
                              follow_redirects=False, trust_env=False) as client:
                with client.stream('POST', ENDPOINTS[name], json=payload,
                                   headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'}) as response:
                    code = response.status_code
                    if code in RETRYABLE:
                        failure_code = "rate_limited" if code == 429 else "temporary_failure"
                        continue
                    if code != 200:
                        # Auth/model/configuration errors stop, rather than silently spending elsewhere.
                        raise ProviderError('Teacher provider rejected request: '+name, 'http_'+str(code))
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline or len(raw) + len(chunk) > 262144:
                            raise ProviderError('Teacher response limit exceeded', 'response_limit')
                        raw.extend(chunk)
            result = json.loads(raw)
            if name == 'openai':
                if result.get('status') != 'completed':
                    raise ValueError()
                texts = [c['text'] for m in result.get('output',[]) if m.get('type') == 'message'
                         for c in m.get('content',[]) if c.get('type') == 'output_text']
                content = '\n'.join(texts)
                usage = result.get('usage') or {}
                ins, outs = usage.get('input_tokens',0), usage.get('output_tokens',0)
            else:
                choice = result['choices'][0]
                if choice.get('finish_reason') == 'length':
                    raise ProviderError('Teacher output truncated', 'output_truncated')
                if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
                    raise ProviderError('Teacher output refused', 'unusable_output')
                content = choice['message']['content']
                usage = result.get('usage') or {}
                ins, outs = usage.get('prompt_tokens',0), usage.get('completion_tokens',0)
            answer = answer_type.model_validate_json(content, strict=True)
            if teacher_task and any(n.scenario_id not in {s['id'] for s in supplied['VERIFIED_CONTEXT'].get('scenarios',[])} for n in answer.scenario_notes):
                raise ValueError()
            return answer, max(0,int(ins)), max(0,int(outs)), name, p['model']
        except ProviderError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            failure_code = "network_timeout"
            continue
        except Exception:
            raise ProviderError('Invalid teacher response: '+name, 'invalid_output') from None
    raise ProviderError('No teacher provider available', failure_code)
