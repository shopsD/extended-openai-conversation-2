"""Tests for the extractable MCP client public API."""

import pytest

from custom_components.extended_openai_conversation.mcp_client import (
    MCPClientConfigFlow,
    MCPConfigError,
    MCPServerConfig,
    MCPServerInformation,
    MCPServiceConfig,
    MCPTool,
    MCPUtils,
    estimate_permanent_context,
)


def test_server_config_normalises_and_serialises_values():
    """The public configuration model owns normalisation and serialisation."""
    config = MCPServerConfig(
        server_id=" vault ",
        name=" Vault MCP ",
        url=" https://mcp.example.com/api ",
        description=" Storage tools ",
        headers={"Authorization": "Bearer token"},
    )

    assert config.to_dict() == {
        "server_id": "vault",
        "name": "Vault MCP",
        "url": "https://mcp.example.com/api",
        "description": "Storage tools",
        "headers": {"Authorization": "Bearer token"},
    }
    assert MCPServerConfig.from_dict(config.to_dict()) == config


def test_service_config_round_trips_complete_permanent_catalogue():
    """Persisted service data retains policies and complete tool snapshots."""
    tool = MCPTool(
        name="read_secret",
        title="Read secret",
        description="Read a stored secret.",
        input_schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
        },
        output_schema={"type": "object"},
        definition={"name": "read_secret", "inputSchema": {"type": "object"}},
    )
    config = MCPServiceConfig(
        server=MCPServerConfig(
            server_id="vault",
            name="Vault MCP",
            url="https://mcp.example.com/api",
            description="Storage tools",
            headers={"Authorization": "Bearer token"},
        ),
        permanent_tool_exposure=True,
        permanent_tools=(tool,),
        include_permanent_schemas=False,
        on_demand_discovery=True,
        regex_timeout=0.2,
        server_information=MCPServerInformation(
            name="Vault Server",
            version="1.0.0",
            protocol_version="2025-06-18",
            instructions="Server instructions",
            capabilities={"tools": {"listChanged": True}},
        ),
    )

    persisted = config.to_dict()

    assert persisted["permanent_tools"] == ["read_secret"]
    assert persisted["permanent_tool_catalogue"] == [tool.to_dict()]
    assert persisted["permanent_tool_catalogue"][0]["input_schema"] == (
        tool.input_schema
    )
    assert MCPServiceConfig.from_dict(persisted) == config


@pytest.mark.parametrize(
    ("kwargs", "field", "code"),
    [
        ({"server_id": "Not Valid"}, "server_id", "invalid_server_id"),
        ({"name": " "}, "name", "invalid_name"),
        ({"url": "ftp://mcp.example.com"}, "url", "invalid_url"),
        ({"headers": {"Bad Header": "value"}}, "headers", "invalid_headers"),
        (
            {"headers": {"Authorization": "Bearer token\nInjected: value"}},
            "headers",
            "invalid_headers",
        ),
    ],
)
def test_server_config_rejects_invalid_values(kwargs, field, code):
    """Invalid host input produces stable public error fields and codes."""
    values = {
        "server_id": "vault",
        "name": "Vault MCP",
        "url": "https://mcp.example.com/api",
        "headers": {},
        **kwargs,
    }

    with pytest.raises(MCPConfigError) as err:
        MCPServerConfig(**values)

    assert err.value.field == field
    assert err.value.code == code


def test_generate_server_id_uses_first_available_suffix():
    """Generated IDs remain readable and avoid existing service IDs."""
    assert (
        MCPUtils.generate_server_id({"mcp_server", "mcp_server_2"})
        == "mcp_server_3"
    )


def test_permanent_context_estimate_uses_the_rendered_schema_content():
    """Schema inclusion changes the exact context and its estimated token cost."""
    config = MCPServerConfig(
        server_id="vault",
        name="Vault MCP",
        url="https://mcp.example.com/api",
        description="Storage tools",
    )
    tools = (
        MCPTool(
            name="read_secret",
            title="Read secret",
            description="Read a stored secret.",
            input_schema={
                "type": "object",
                "properties": {"key": {"type": "string"}},
            },
            output_schema=None,
            definition={"name": "read_secret"},
        ),
    )

    metadata_only = estimate_permanent_context(
        config, tools, include_schemas=False
    )
    with_schemas = estimate_permanent_context(
        config, tools, include_schemas=True
    )

    assert metadata_only.selected_tool_count == 1
    assert '"input_schema"' not in metadata_only.content
    assert '"input_schema"' in with_schemas.content
    assert with_schemas.character_count > metadata_only.character_count
    assert with_schemas.byte_count > metadata_only.byte_count
    assert with_schemas.estimated_tokens > metadata_only.estimated_tokens


def test_config_flow_returns_framework_independent_initial_values():
    """The MCP flow supplies defaults without importing a host UI framework."""
    result = MCPClientConfigFlow({"mcp_server"}).process()

    assert not result.is_complete
    assert result.errors == {}
    assert result.values == {
        "name": "MCP Server",
        "server_id": "mcp_server_2",
        "description": "",
        "headers": {},
    }


def test_config_flow_returns_normalised_configuration():
    """Valid host input is normalized into the public MCP configuration."""
    result = MCPClientConfigFlow().process(
        {
            "name": " Vault MCP ",
            "server_id": " vault ",
            "url": " https://mcp.example.com/api ",
            "description": " Storage tools ",
            "headers": {"Authorization": "Bearer token"},
        }
    )

    assert result.is_complete
    assert result.errors == {}
    assert result.config == MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
        description="Storage tools",
        headers={"Authorization": "Bearer token"},
    )


def test_config_flow_returns_field_error_and_preserves_values():
    """Invalid data is returned to the host with a stable field error."""
    values = {
        "name": "Vault MCP",
        "server_id": "Not Valid",
        "url": "https://mcp.example.com/api",
        "description": "Storage tools",
        "headers": {},
    }

    result = MCPClientConfigFlow().process(values)

    assert not result.is_complete
    assert result.config is None
    assert result.values == values
    assert result.errors == {"server_id": "invalid_server_id"}


def test_config_flow_rejects_missing_required_field():
    """Processing does not rely on a host framework to require form fields."""
    result = MCPClientConfigFlow().process(
        {
            "name": "Vault MCP",
            "server_id": "vault",
            "description": "Storage tools",
            "headers": {},
        }
    )

    assert not result.is_complete
    assert result.errors == {"url": "invalid_url"}


def test_config_flow_rejects_host_reserved_server_id():
    """The host can reserve IDs without exposing its entry implementation."""
    result = MCPClientConfigFlow({"vault"}).process(
        {
            "name": "Vault MCP",
            "server_id": "vault",
            "url": "https://mcp.example.com/api",
            "description": "Storage tools",
            "headers": {},
        }
    )

    assert not result.is_complete
    assert result.errors == {"server_id": "duplicate_server_id"}
