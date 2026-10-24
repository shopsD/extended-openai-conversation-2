"""Tests for the extractable MCP client public API."""

import pytest

from custom_components.extended_openai_conversation.mcp_client import (
    MCPClientConfigFlow,
    MCPConfigError,
    MCPServerConfig,
    MCPUtils,
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
