from litellm.proxy.management_endpoints.model_management_endpoints import _explicit_zero_pricing_overrides


def test_explicit_zero_pricing_is_preserved_without_freezing_catalog_rates():
    assert _explicit_zero_pricing_overrides(
        {
            "input_cost_per_token": 0.0,
            "output_cost_per_token": 0,
            "cache_read_input_token_cost": 0.000001,
            "mode": "responses",
        }
    ) == {
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0,
    }


def test_non_pricing_and_nonzero_rates_are_not_overridden():
    assert _explicit_zero_pricing_overrides(
        {"input_cost_per_token": 0.000001, "mode": "responses", "blocked": False}
    ) == {}
