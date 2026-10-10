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


def test_client_auth_shaped_metadata_cannot_override_server_auth_in_other_channel():
    cache = Cache(type="local")
    server_auth = UserAPIKeyAuth(api_key="hash-server", team_id="team-a", user_id="user-a")
    other_auth = UserAPIKeyAuth(api_key="hash-other", team_id="team-a", user_id="user-b")
    server_metadata = _request_metadata(server_auth)
    other_metadata = _request_metadata(other_auth)
    common = {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture"}]}

    # The first channel imitates a client JSON object; only the stamped model
    # in the second channel is authoritative.
    client_spoof = {"user_api_key_auth": {"api_key": "hash-other"}, "redis_namespace": "attacker"}
    first_key = cache.get_cache_key(**common, metadata=client_spoof, litellm_metadata=server_metadata)
    expected_key = cache.get_cache_key(**common, litellm_metadata=server_metadata)
    other_key = cache.get_cache_key(**common, litellm_metadata=other_metadata)

    assert first_key == expected_key
    assert first_key != other_key


def test_authenticated_namespace_keeps_field_boundaries_distinct():
    cache = Cache(type="local")
    first = UserAPIKeyAuth(api_key="ab", team_id="c", user_id=None)
    second = UserAPIKeyAuth(api_key="a", team_id="bc", user_id=None)
    common = {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture"}]}

    first_key = cache.get_cache_key(**common, litellm_metadata=_request_metadata(first))
    second_key = cache.get_cache_key(**common, litellm_metadata=_request_metadata(second))

    assert first_key != second_key


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
