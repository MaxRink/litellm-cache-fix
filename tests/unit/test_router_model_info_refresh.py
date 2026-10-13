import importlib
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from litellm import Router

router_module = importlib.import_module("litellm.router")


async def _exercise_refresh(monkeypatch: pytest.MonkeyPatch, api_key: str | None) -> list[Mapping[str, str]]:
    model = "openai/refresh-test"
    raw = {
        "model_name": model,
        "litellm_params": {
            "model": model,
            "api_base": "http://fake-upstream.invalid/v1",
            **({"api_key": api_key} if api_key is not None else {}),
        },
        "model_info": {"id": "refresh-test-id"},
    }
    router = Router(model_list=[raw])
    seen: list[Mapping[str, str]] = []

    async def fake_model_info(*, headers: Mapping[str, str], **kwargs: object) -> Mapping[str, int]:
        seen.append(headers)
        return MappingProxyType({"input": 1})

    monkeypatch.setattr(router_module, "get_openai_compatible_model_info", fake_model_info)
    await router._arefresh_deployment_model_info(router.model_list[0], client=object())
    return seen


@pytest.mark.asyncio
async def test_refresh_sends_resolved_environment_key_to_fake_upstream(monkeypatch):
    monkeypatch.setenv("LITELLM_REFRESH_TEST_KEY", "resolved-key")
    seen = await _exercise_refresh(monkeypatch, "os.environ/LITELLM_REFRESH_TEST_KEY")
    assert seen == [{"authorization": "Bearer resolved-key"}]


@pytest.mark.asyncio
async def test_refresh_skips_missing_environment_key_without_upstream_call(monkeypatch):
    monkeypatch.delenv("LITELLM_REFRESH_TEST_KEY", raising=False)
    seen = await _exercise_refresh(monkeypatch, "os.environ/LITELLM_REFRESH_TEST_KEY")
    assert seen == []


@pytest.mark.asyncio
async def test_refresh_preserves_direct_key(monkeypatch):
    seen = await _exercise_refresh(monkeypatch, "literal-key")
    assert seen == [{"authorization": "Bearer literal-key"}]


@pytest.mark.asyncio
async def test_refresh_preserves_intentionally_anonymous_deployment(monkeypatch):
    seen = await _exercise_refresh(monkeypatch, None)
    assert seen == [{}]
