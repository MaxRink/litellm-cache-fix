import time
from typing import Final

import pytest

import litellm
from litellm.caching.caching import Cache
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.hooks.batch_redis_get import PROXY_BatchRedisRequests
from litellm.types.caching import LiteLLMCacheType


class _BackendSpy:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def async_get_cache(self, key: str, *args, **kwargs):
        self.keys.append(key)
        return {"timestamp": time.time(), "response": {"key": key}}


class _MemorySpy:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_cache(self, key: str, *args, **kwargs):
        return self.values.get(key)

    async def async_set_cache(self, key: str, value: object, *args, **kwargs):
        self.values[key] = value


def _caller(token: str | None) -> UserAPIKeyAuth:
    return UserAPIKeyAuth(api_key=f"raw-{token}").model_copy(update={"token": token})


@pytest.mark.asyncio
async def test_batch_redis_hook_scopes_explicit_keys_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    cache: Final = Cache(type=LiteLLMCacheType.LOCAL)
    backend = _BackendSpy()
    cache.cache = backend
    monkeypatch.setattr(litellm, "cache", cache)
    hook = PROXY_BatchRedisRequests()
    hook.in_memory_cache = _MemorySpy()

    request_a = {"metadata": {"user_api_key_auth": _caller("hashed-a")}, "cache_key": "shared"}
    request_b = {"metadata": {"user_api_key_auth": _caller("hashed-b")}, "cache_key": "shared"}

    first_a = await hook.async_get_cache(**request_a)
    second_a = await hook.async_get_cache(**request_a)
    first_b = await hook.async_get_cache(**request_b)
    missing = await hook.async_get_cache(
        metadata={"user_api_key_auth": _caller(None)},
        cache_key="shared",
    )

    assert first_a == second_a
    assert first_a != first_b
    assert missing is None
    assert len(backend.keys) == 2
    assert backend.keys[0] != backend.keys[1]
    assert all(key.startswith("caller:") for key in backend.keys)
