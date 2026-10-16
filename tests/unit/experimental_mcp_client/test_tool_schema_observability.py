from types import SimpleNamespace

from litellm.experimental_mcp_client.tools import _validate_mcp_tools


def test_invalid_mcp_schema_logs_bounded_metadata_without_dropping_tool(caplog):
    tool = SimpleNamespace(
        name="tool-with-invalid-schema",
        input_schema={"type": "object", "properties": {"secret": "malformed"}},
    )

    with caplog.at_level("WARNING"):
        result = _validate_mcp_tools([tool])

    assert result == [tool]
    assert "mcp_tool_schema_invalid" in caplog.text
    assert "tool-with-invalid-schema" in caplog.text
    assert "property_schema_not_object" in caplog.text
    assert "secret" in caplog.text
    assert "malformed" not in caplog.text


def test_valid_mcp_schema_has_no_diagnostic(caplog):
    tool = SimpleNamespace(
        name="valid-tool",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )

    with caplog.at_level("WARNING"):
        result = _validate_mcp_tools([tool])

    assert result == [tool]
    assert "mcp_tool_schema_invalid" not in caplog.text


def test_boolean_json_schema_property_has_no_diagnostic(caplog):
    tool = SimpleNamespace(
        name="boolean-schema-tool",
        input_schema={"type": "object", "properties": {"enabled": False}},
    )

    with caplog.at_level("WARNING"):
        result = _validate_mcp_tools([tool])

    assert result == [tool]
    assert "mcp_tool_schema_invalid" not in caplog.text
