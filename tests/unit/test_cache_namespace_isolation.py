"""Cache identity tests for the authenticated proxy request path."""

from types import SimpleNamespace

from litellm.caching.caching import Cache
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.litellm_pre_call_utils import LiteLLMProxyRequestSetup


def _request_metadata(auth: UserAPIKeyAuth, **client_metadata: object) -> dict[str, object]:
    data: dict[str, object] = {"litellm_metadata": dict(client_metadata)}
    LiteLLMProxyRequestSetup.add_user_api_key_auth_to_request_metadata(
        data=data,
        user_api_key_dict=auth,
        _metadata_variable_name="litellm_metadata",
    )
    return data["litellm_metadata"]  # type: ignore[return-value]


def test_authenticated_callers_get_distinct_cache_namespaces_and_cannot_spoof_one():
    cache = Cache(type="local")
    first = UserAPIKeyAuth(api_key="hash-a", team_id="team-a", user_id="user-a")
    second = UserAPIKeyAuth(api_key="hash-b", team_id="team-a", user_id="user-b")
    common = {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture"}]}

    first_key = cache.get_cache_key(**common, litellm_metadata=_request_metadata(first, redis_namespace="attacker"))
    second_key = cache.get_cache_key(**common, litellm_metadata=_request_metadata(second, redis_namespace="attacker"))

    assert first_key != second_key
    assert "attacker" not in first_key
    assert "attacker" not in second_key


def test_cache_key_ignores_otel_span_lifecycle_objects():
    cache = Cache(type="local")
    auth = UserAPIKeyAuth(api_key="hash-a", team_id="team-a", user_id="user-a")
    metadata = _request_metadata(auth)
    common = {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture"}]}

    first_key = cache.get_cache_key(
        **common,
        litellm_metadata=metadata,
        parent_otel_span=SimpleNamespace(name="lookup"),
    )
    second_key = cache.get_cache_key(
        **common,
        litellm_metadata=metadata,
        parent_otel_span=SimpleNamespace(name="store"),
    )

    assert first_key == second_key
