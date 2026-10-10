import faulthandler, hashlib, json, sys
faulthandler.dump_traceback_later(30, repeat=False)
print('fixture_start', flush=True)
import httpx
print('imports_done', flush=True)
import litellm
from litellm import Router
from litellm.caching.caching import Cache
print('litellm_import_done', flush=True)

calls = 0
requests = []

def body_shape(request):
    global requests
    try:
        body = json.loads(request.content.decode())
    except Exception:
        body = {}
    safe = {k: body.get(k) for k in sorted(body) if k not in {'messages', 'prompt'}}
    digest = hashlib.sha256(request.content).hexdigest()[:16]
    requests.append({'shape': safe, 'body_hash': digest})

async def async_send(self, request, *args, **kwargs):
    global calls
    body_shape(request)
    if request.url.path.endswith('/api/chat'):
        calls += 1
        payload = {
            'model': 'qwen3:4b', 'created_at': '2026-01-01T00:00:00Z',
            'message': {'role': 'assistant', 'content': 'CACHE_OK'},
            'done': True, 'done_reason': 'stop', 'total_duration': 1,
            'load_duration': 1, 'prompt_eval_count': 3, 'prompt_eval_duration': 1,
            'eval_count': 1, 'eval_duration': 1,
        }
        return httpx.Response(200, json=payload, request=request)
    raise AssertionError(f'unexpected URL path: {request.url.path}')

def sync_send(self, request, *args, **kwargs):
    import asyncio
    return asyncio.run(async_send(self, request, *args, **kwargs))

httpx.AsyncClient.send = async_send
httpx.Client.send = sync_send
litellm.cache = Cache(type='local')
router = Router(
    model_list=[{'model_name': 'ha-local', 'litellm_params': {
        'model': 'ollama_chat/qwen3:4b', 'api_base': 'http://mock.invalid',
        'api_key': 'fixture', 'num_ctx': 8192,
    }, 'model_info': {'rpm': 60}}],
    cache_responses=True, enable_pre_call_checks=True, num_retries=0,
)
kwargs = {
    'model': 'ha-local',
    'messages': [{'role': 'user', 'content': 'Return exactly CACHE_OK.'}],
    'temperature': 0, 'max_tokens': 16, 'stream': False, 'user': 'paperless-gpt',
}
results=[]
for i in range(2):
    print(f'call_{i}_start', flush=True)
    response = router.completion(**kwargs)
    results.append({'id': getattr(response, 'id', None), 'cache_hit': getattr(response, 'cache_hit', None), 'content': response.choices[0].message.content})
    print(f'call_{i}_done', flush=True)
print(json.dumps({'provider_calls': calls, 'responses': results, 'request_observations': requests}, sort_keys=True, separators=(',', ':')), flush=True)
assert calls == 1, f'expected one Ollama adapter call, got {calls}'
assert results[0]['content'] == results[1]['content'] == 'CACHE_OK'
faulthandler.cancel_dump_traceback_later()
