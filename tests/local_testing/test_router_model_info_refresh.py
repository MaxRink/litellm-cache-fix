from litellm.router import resolve_model_info_api_key


def test_model_info_refresh_resolves_environment_reference(monkeypatch):
    seen = []

    def fake_get_secret(name):
        seen.append(name)
        return "resolved-secret"

    monkeypatch.setattr("litellm.router.get_secret_str", fake_get_secret)

    assert resolve_model_info_api_key("os.environ/PROVIDER_KEY", "dynamic") == "resolved-secret"
    assert seen == ["os.environ/PROVIDER_KEY"]


def test_model_info_refresh_fails_closed_when_reference_is_unset(monkeypatch):
    monkeypatch.setattr("litellm.router.get_secret_str", lambda _name: None)

    assert resolve_model_info_api_key("os.environ/MISSING_PROVIDER_KEY", "dynamic") is None
    assert resolve_model_info_api_key(None, "dynamic") == "dynamic"
