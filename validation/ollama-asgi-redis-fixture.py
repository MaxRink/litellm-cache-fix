import asyncio, faulthandler, hashlib, json, os
faulthandler.dump_traceback_later(30, repeat=False)
print('fixture_start', flush=True)
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import litellm
from litellm import Router
from litellm.caching.caching import Cache
from litellm.proxy._types import UserAPIKeyAuth
import importlib.util
spec=importlib.util.spec_from_file_location('routing_audit','/run/routing_audit.py')
routing_audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(routing_audit)
print('imports_done', flush=True)

calls=0; request_shapes=[]

def record_request(request):
    try: body=json.loads(request.content.decode())
    except Exception: body={}
    safe={k:body.get(k) for k in sorted(body) if k not in {'messages','prompt'}}
    request_shapes.append({'hash':hashlib.sha256(request.content).hexdigest()[:16], 'shape':safe})

def fake_response(request):
    global calls
    record_request(request)
    if request.url.path.endswith('/api/chat'):
        calls += 1
        return httpx.Response(200,json={'model':'qwen3:4b','created_at':'2026-01-01T00:00:00Z','message':{'role':'assistant','content':'CACHE_OK'},'done':True,'done_reason':'stop','total_duration':1,'load_duration':1,'prompt_eval_count':3,'prompt_eval_duration':1,'eval_count':1,'eval_duration':1},request=request)
    raise AssertionError(f'unexpected path {request.url.path}')
_orig_async_send=httpx.AsyncClient.send
_orig_sync_send=httpx.Client.send
async def async_send(self,request,*args,**kwargs):
    if request.url.host == 'mock.invalid': return fake_response(request)
    return await _orig_async_send(self,request,*args,**kwargs)
def sync_send(self,request,*args,**kwargs):
    if request.url.host == 'mock.invalid': return fake_response(request)
    return _orig_sync_send(self,request,*args,**kwargs)
httpx.AsyncClient.send=async_send; httpx.Client.send=sync_send

redis_host=os.environ.get('REDIS_HOST','127.0.0.1')
litellm.cache=Cache(type='redis',host=redis_host,port=6379,namespace='litellm-ollama-asgi-fixture',default_in_redis_ttl=120,socket_timeout=2,max_connections=2)
router=Router(model_list=[{'model_name':'ha-local','litellm_params':{'model':'ollama_chat/qwen3:4b','api_base':'http://mock.invalid','api_key':'fixture','num_ctx':8192},'model_info':{'rpm':60}}],cache_responses=True,enable_pre_call_checks=False,num_retries=0)
auth=UserAPIKeyAuth.model_validate({'api_key':'fixture','key_alias':'paperless-gpt','user_role':'internal_user','team_id':'fixture-team','models':['ha-local']})
app=FastAPI()
@app.post('/v1/chat/completions')
async def completion(request:Request):
    data=await request.json()
    data=await routing_audit.route_audit.async_pre_call_hook(auth,litellm.cache,data,'chat_completion')
    response=await router.acompletion(**data)
    return JSONResponse(response.model_dump() if hasattr(response,'model_dump') else dict(response))

async def main():
    global calls
    transport=httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,base_url='http://asgi.test') as client:
        body={'model':'ha-local','messages':[{'role':'user','content':'Return exactly CACHE_OK.'}],'temperature':0,'max_tokens':16,'stream':False,'user':'paperless-gpt'}
        results=[]
        for _ in range(2):
            r=await client.post('/v1/chat/completions',json=body); j=r.json(); results.append({'status':r.status_code,'id':j.get('id'),'content':((j.get('choices') or [{}])[0].get('message') or {}).get('content')}); await asyncio.sleep(2) if len(results)==1 else asyncio.sleep(0)
        print(json.dumps({'provider_calls':calls,'responses':results,'request_observations':request_shapes,'auth_flags':{'alias':auth.key_alias,'role':str(auth.user_role),'user_id_present':auth.user_id is not None}},sort_keys=True,separators=(',',':')),flush=True)
        assert [x['status'] for x in results]==[200,200]
        assert calls==1, calls
        assert results[0]['id']==results[1]['id']
asyncio.run(main())
faulthandler.cancel_dump_traceback_later()
