import asyncio, importlib
p=importlib.import_module("litellm.integrations.prometheus")
P=p.PrometheusLogger; seen=[]
def cap(_self,_metric,_name,enum_values,**_kw): seen.append(enum_values)
P._inc_labeled_counter=cap
x=P.__new__(P); x.litellm_deployment_successful_fallbacks=object(); x.litellm_deployment_failed_fallbacks=object()
class E(Exception): status_code=429
def md(a): return {"user_api_key_alias":a,"user_api_key_hash":"hash","user_api_key_team_id":"team","user_api_key_team_alias":"team-alias"}
async def main():
 await x.log_success_fallback_event("requested", {"model":"fallback","litellm_params":{"metadata":md("nested")}}, E())
 await x.log_failure_fallback_event("requested", {"model":"fallback","litellm_params":{"litellm_metadata":md("nested-new")}}, E())
 await x.log_success_fallback_event("requested", {"model":"fallback","metadata":md("legacy")}, E())
 await x.log_success_fallback_event("requested", {"model":"fallback"}, E())
asyncio.run(main())
assert [getattr(v,"api_key_alias",None) for v in seen] == ["nested","nested-new","legacy",None]
print("callback smoke PASS")
