import pytest

from litellm.router import _resolve_model_info_api_key


@pytest.mark.parametrize(
    ("api_key", "dynamic_api_key", "expected"),
    (
        ("literal-key", "dynamic-key", "literal-key"),
        (None, "dynamic-key", "dynamic-key"),
    ),
)
def test_model_info_refresh_preserves_direct_and_dynamic_keys(api_key, dynamic_api_key, expected):
    assert _resolve_model_info_api_key(api_key, dynamic_api_key) == expected


def test_model_info_refresh_resolves_environment_pointer(monkeypatch):
    monkeypatch.setenv("LITELLM_REFRESH_TEST_KEY", "resolved-key")
    assert _resolve_model_info_api_key("os.environ/LITELLM_REFRESH_TEST_KEY", None) == "resolved-key"


def test_model_info_refresh_omits_missing_environment_pointer(monkeypatch):
    monkeypatch.delenv("LITELLM_REFRESH_TEST_KEY", raising=False)
    assert _resolve_model_info_api_key("os.environ/LITELLM_REFRESH_TEST_KEY", None) is None
