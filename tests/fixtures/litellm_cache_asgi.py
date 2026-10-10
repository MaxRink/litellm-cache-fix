"""Offline ASGI cache acceptance fixture.

Runs with a fake provider and no network or credentials. Raw cache keys remain
in memory only; output contains status codes, counts, and one-way key hashes.
"""

import asyncio
import hashlib
import json
import sys
import types
from typing import Any

from fastapi import APIRouter

_enterprise_modules = {
    name: types.ModuleType(name)
    for name in (
        "litellm_enterprise",
        "litellm_enterprise.proxy",
        "litellm_enterprise.proxy.enterprise_routes",
        "litellm_enterprise.proxy.proxy_server",
    )
}
_enterprise_modules["litellm_enterprise.proxy.enterprise_routes"].router = APIRouter()
_enterprise_modules["litellm_enterprise.proxy.proxy_server"].EnterpriseProxyConfig = type(
    "EnterpriseProxyConfig", (), {}
)
sys.modules.update(_enterprise_modules)

import httpx
import litellm
import litellm.main as litellm_main
from litellm.caching.caching import Cache
from litellm.proxy import proxy_server
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.router import Router
from litellm.types.utils import ModelResponse

litellm.enable_caching_on_provider_specific_optional_params = True  # test-quality-ok: isolated fixture enables provider-parameter cache coverage
cache = Cache()
litellm.cache = cache  # test-quality-ok: isolated fixture installs its in-memory cache before ASGI requests
provider_calls = 0
events: list[dict[str, Any]] = []


def _hash(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()[:16]


original_get = cache.async_get_cache
original_add = cache.async_add_cache


async def _get(*args: object, **kwargs: Any) -> object:
    result = await original_get(*args, **kwargs)
    events.append({"op": "lookup", "hit": result is not None, "key_hash": _hash(kwargs.get("cache_key")), "key": kwargs.get("cache_key")})
    return result


async def _add(*args: object, **kwargs: Any) -> object:
    effective_key = kwargs.get("cache_key") or cache.get_cache_key(**kwargs)
    events.append({"op": "store", "key_hash": _hash(effective_key), "key": effective_key})
    return await original_add(*args, **kwargs)


cache.async_get_cache = _get
cache.async_add_cache = _add


async def _fake_provider(*args: object, **kwargs: Any) -> ModelResponse:
    global provider_calls
    provider_calls += 1
    return ModelResponse(
        id=f"fixture-{provider_calls}",
        model="paperless-routine",
        choices=[{"index": 0, "message": {"role": "assistant", "content": "fixture"}, "finish_reason": "stop"}],
    )


litellm_main.openai_chat_completions.acompletion = _fake_provider
router = Router(
    model_list=[
        {
            "model_name": "paperless-routine",
            "model_info": {"id": "fixture"},
            "litellm_params": {"model": "openai/fake-model", "api_key": "fixture-only"},
        }
    ],
    cache_responses=True,
    num_retries=0,
)
proxy_server.llm_router = router
proxy_server.master_key = "fixture-master"
proxy_server.general_settings = {}


def _install_auth_dependency(auth: UserAPIKeyAuth) -> None:
    for route in proxy_server.app.routes:
        if getattr(route, "path", "") == "/v1/chat/completions":
            for dependency in route.dependant.dependencies:
                proxy_server.app.dependency_overrides[dependency.call] = lambda auth=auth: auth


async def _request(
    caller: str,
    namespace: str,
    client: httpx.AsyncClient,
    *,
    cache_key: str | None = None,
    span: str | None = None,
    preset_cache_key: str | None = None,
    cache_control: dict[str, object] | None = None,
) -> int:
    auth = UserAPIKeyAuth(
        api_key=hashlib.sha256(caller.encode()).hexdigest(),
        token=f"fixture-{caller}",
        key_alias=caller,
        models=["paperless-routine"],
        team_id="fixture-team",
        team_alias="fixture-team",
        user_id=caller,
        user_role=LitellmUserRoles.PROXY_ADMIN,
    )
    _install_auth_dependency(auth)
    body: dict[str, object] = {
        "model": "paperless-routine",
        "messages": [{"role": "user", "content": "CACHE_CANARY_OK."}],
        "temperature": 0,
        "stream": False,
        "metadata": {"redis_namespace": namespace},
    }
    if span is not None:
        body["parent_otel_span"] = span
    if cache_key is not None:
        body["cache_key"] = cache_key
    if preset_cache_key is not None:
        # Exercise the public request parser. If this internal-looking field is
        # accepted, it must still be scoped by the authenticated caller.
        body["litellm_params"] = {"preset_cache_key": preset_cache_key}
    if cache_control is not None:
        body["cache"] = cache_control
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer fixture-{caller}"},
        json=body,
    )
    return response.status_code


async def main() -> None:
    global events
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy_server.app), base_url="http://fixture") as client:
        statuses: list[int] = []
        # Preserve the generated-key/span regression: two callers each repeat
        # the same deterministic request, so only two provider calls occur.
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=None, span="span-a"))
        calls_after_generated_a = provider_calls
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=None, span="span-b"))
        generated_a_reused = provider_calls == calls_after_generated_a
        statuses.append(await _request("caller-b", "tenant-b", client, cache_key=None, span="span-c"))
        calls_after_generated_b = provider_calls
        statuses.append(await _request("caller-b", "tenant-b", client, cache_key=None, span="span-d"))
        generated_b_reused = provider_calls == calls_after_generated_b

        # Explicit-key isolation and same-caller reuse.
        explicit_key = "shared-client-key"
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=explicit_key))
        await asyncio.sleep(0.05)
        first_store = next(event["key"] for event in events if event["op"] == "store")
        calls_after_a_first = provider_calls
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=explicit_key))
        same_caller_reused = provider_calls == calls_after_a_first

        calls_before_b_same_key = provider_calls
        statuses.append(await _request("caller-b", "tenant-b", client, cache_key=explicit_key))
        caller_b_same_explicit_isolated = provider_calls == calls_before_b_same_key + 1

        calls_before_b = provider_calls
        statuses.append(await _request("caller-b", "tenant-b", client, cache_key=first_store))
        caller_b_spoof_isolated = provider_calls == calls_before_b + 1

        # A distinct caller attempts the same spoof through the nested
        # litellm_params preset slot, which get_cache_key historically returns
        # before namespace construction.
        calls_before_preset_spoof = provider_calls
        statuses.append(
            await _request("caller-c", "tenant-c", client, preset_cache_key=first_store)
        )
        preset_spoof_isolated = provider_calls == calls_before_preset_spoof + 1

        # Populate first; no-cache must bypass that existing entry.
        no_cache_key = "no-cache-key"
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=no_cache_key))
        await asyncio.sleep(0.05)
        calls_before_no_cache = provider_calls
        events_before_no_cache = len(events)
        statuses.append(
            await _request("caller-a", "tenant-a", client, cache_key=no_cache_key, cache_control={"no-cache": True})
        )
        no_cache_called_provider = provider_calls == calls_before_no_cache + 1
        no_cache_events = events[events_before_no_cache:]

        # A no-store response must not be available to a subsequent normal call.
        no_store_key = "no-store-key"
        events_before_no_store = len(events)
        statuses.append(
            await _request("caller-a", "tenant-a", client, cache_key=no_store_key, cache_control={"no-store": True})
        )
        no_store_events = events[events_before_no_store:]
        await asyncio.sleep(0.05)
        calls_before_no_store_followup = provider_calls
        statuses.append(await _request("caller-a", "tenant-a", client, cache_key=no_store_key))
        no_store_called_provider = provider_calls == calls_before_no_store_followup + 1

    public_events = [{key: event[key] for key in ("op", "hit", "key_hash") if key in event} for event in events]
    success = (
        all(status == 200 for status in statuses)
        and same_caller_reused
        and caller_b_same_explicit_isolated
        and caller_b_spoof_isolated
        and preset_spoof_isolated
        and no_cache_called_provider
        and no_store_called_provider
        and generated_a_reused
        and generated_b_reused
        and not any(event["op"] == "store" for event in no_store_events)
    )
    print(
        json.dumps(
            {
                "status": "ok" if success else "failure",
                "statuses": statuses,
                "provider_calls": provider_calls,
                "generated_a_reused": generated_a_reused,
                "generated_b_reused": generated_b_reused,
                "same_caller_reused": same_caller_reused,
                "caller_b_same_explicit_isolated": caller_b_same_explicit_isolated,
                "caller_b_spoof_isolated": caller_b_spoof_isolated,
                "preset_spoof_isolated": preset_spoof_isolated,
                "no_cache_called_provider": no_cache_called_provider,
                "no_cache_events": [
                    {key: event[key] for key in ("op", "hit", "key_hash") if key in event}
                    for event in no_cache_events
                ],
                "no_store_called_provider": no_store_called_provider,
                "no_store_events": [
                    {key: event[key] for key in ("op", "hit", "key_hash") if key in event}
                    for event in no_store_events
                ],
                "events": public_events,
            },
            sort_keys=True,
        )
    )
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
