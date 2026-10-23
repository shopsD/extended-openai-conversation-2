"""Tests for integration setup and service-type routing."""

from unittest.mock import MagicMock, patch

from custom_components.extended_openai_conversation import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.extended_openai_conversation.const import (
    CONF_MCP_SERVER_ID,
    CONF_MCP_SERVER_URL,
    CONF_SERVICE_TYPE,
    SERVICE_TYPE_MCP,
)
from custom_components.extended_openai_conversation.mcp_client import MCPServerConfig


async def test_mcp_entry_does_not_create_openai_client(hass):
    """Setting up an MCP service must not run AI endpoint authentication."""
    entry = MagicMock()
    entry.data = {
        CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
    }
    entry.title = "Vault MCP"
    entry.add_update_listener.return_value = MagicMock()

    with patch(
        "custom_components.extended_openai_conversation.get_authenticated_client"
    ) as get_authenticated_client:
        assert await async_setup_entry(hass, entry)

    get_authenticated_client.assert_not_called()
    hass.config_entries.async_forward_entry_setups.assert_not_called()
    entry.async_on_unload.assert_called_once()
    assert isinstance(entry.runtime_data, MCPServerConfig)
    assert entry.runtime_data.server_id == "vault"


async def test_mcp_entry_unloads_without_ai_platforms(hass):
    """Unloading an MCP service must not unload AI endpoint platforms."""
    entry = MagicMock()
    entry.data = {CONF_SERVICE_TYPE: SERVICE_TYPE_MCP}

    assert await async_unload_entry(hass, entry)

    hass.config_entries.async_unload_platforms.assert_not_called()
