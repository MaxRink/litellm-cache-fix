"""Regression tests for token counting with provider-shaped tool schemas."""

import litellm


def test_token_counter_ignores_non_mapping_tool_property() -> None:
    """A malformed property must not disable router context prechecks."""
    messages = [{"role": "user", "content": "hello"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"properties": {"query": "malformed"}},
            },
        }
    ]

    count = litellm.token_counter(messages=messages, tools=tools)

    assert count >= litellm.token_counter(messages=messages)
