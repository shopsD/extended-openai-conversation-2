"""Tests for Home Assistant MCP service runtime lookup."""

from unittest.mock import MagicMock

import pytest

from custom_components.extended_openai_conversation.const import (
    CONF_SERVICE_TYPE,
    SERVICE_TYPE_AI_ENDPOINT,
    SERVICE_TYPE_MCP,
)
from custom_components.extended_openai_conversation.mcp_client import (
    MCPClient,
    MCPServerConfig,
    MCPServiceConfig,
)
from custom_components.extended_openai_conversation.mcp_service_manager import (
    MCPServiceManager,
    MCPServiceNotFoundError,
    MCPServiceUnavailableError,
)
from homeassistant.config_entries import ConfigEntryState


def _mcp_entry(
    server_id: str,
    *,
    state: ConfigEntryState = ConfigEntryState.LOADED,
    runtime_data: object | None = None,
) -> MagicMock:
    config = MCPServiceConfig(
        server=MCPServerConfig(
            server_id=server_id,
            name=f"{server_id} MCP",
            url=f"https://{server_id}.example.com/mcp",
        )
    )
    entry = MagicMock()
    entry.entry_id = f"entry-{server_id}"
    entry.title = config.server.name
    entry.data = {**config.to_dict(), CONF_SERVICE_TYPE: SERVICE_TYPE_MCP}
    entry.state = state
    entry.runtime_data = runtime_data or MCPClient(config.server)
    return entry


def test_scope_lists_only_allowed_loaded_mcp_services(hass):
    """Enumeration excludes unselected, unavailable, and non-MCP entries."""
    loaded = _mcp_entry("vault")
    unselected = _mcp_entry("weather")
    unavailable = _mcp_entry("calendar", state=ConfigEntryState.NOT_LOADED)
    ai_entry = MagicMock()
    ai_entry.data = {CONF_SERVICE_TYPE: SERVICE_TYPE_AI_ENDPOINT}
    hass.config_entries.async_entries.return_value = [
        ai_entry,
        loaded,
        unselected,
        unavailable,
    ]

    services = MCPServiceManager(hass).scope({"vault", "calendar"}).list_loaded()

    assert len(services) == 1
    assert services[0].entry_id == "entry-vault"
    assert services[0].config.server.server_id == "vault"
    assert services[0].client is loaded.runtime_data
    hass.config_entries.async_entries.assert_called_once_with(
        "extended_openai_conversation"
    )


def test_scope_get_returns_allowed_service_by_server_id(hass):
    """A stable server ID resolves its configuration and runtime client."""
    calendar = _mcp_entry("calendar")
    vault = _mcp_entry("vault")
    hass.config_entries.async_entries.return_value = [calendar, vault]

    service = MCPServiceManager(hass).scope({"vault"}).get("vault")

    assert service.entry_id == "entry-vault"
    assert service.title == "vault MCP"
    assert service.config.server.server_id == "vault"
    assert service.client is vault.runtime_data


def test_scope_get_rejects_unknown_server_id(hass):
    """Unknown server IDs are distinct from unavailable services."""
    hass.config_entries.async_entries.return_value = [_mcp_entry("vault")]

    with pytest.raises(MCPServiceNotFoundError, match="missing"):
        MCPServiceManager(hass).scope({"missing"}).get("missing")


def test_scope_hides_configured_but_unselected_server(hass):
    """An unselected service is indistinguishable from an unknown service."""
    hass.config_entries.async_entries.return_value = [_mcp_entry("vault")]
    scope = MCPServiceManager(hass).scope(set())

    with pytest.raises(MCPServiceNotFoundError) as unselected:
        scope.get("vault")
    with pytest.raises(MCPServiceNotFoundError) as unknown:
        scope.get("missing")

    assert str(unselected.value) == "MCP service 'vault' was not found"
    assert str(unknown.value) == "MCP service 'missing' was not found"
    hass.config_entries.async_entries.assert_not_called()


def test_empty_scope_lists_no_services(hass):
    """An agent with no selected server IDs cannot enumerate MCP services."""
    hass.config_entries.async_entries.return_value = [_mcp_entry("vault")]

    assert MCPServiceManager(hass).scope(set()).list_loaded() == ()
    hass.config_entries.async_entries.assert_not_called()


def test_scope_get_rejects_allowed_unloaded_service(hass):
    """Configured services without a loaded entry cannot be returned."""
    hass.config_entries.async_entries.return_value = [
        _mcp_entry("vault", state=ConfigEntryState.NOT_LOADED)
    ]

    with pytest.raises(MCPServiceUnavailableError, match="not loaded"):
        MCPServiceManager(hass).scope({"vault"}).get("vault")


def test_scope_get_rejects_allowed_service_without_runtime_client(hass):
    """A loaded entry must contain the expected MCP runtime client."""
    entry = _mcp_entry("vault")
    entry.runtime_data = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]

    with pytest.raises(MCPServiceUnavailableError, match="no runtime client"):
        MCPServiceManager(hass).scope({"vault"}).get("vault")


@pytest.mark.parametrize("server_ids", ["vault", {"vault", 1}])
def test_scope_rejects_malformed_server_id_collection(hass, server_ids):
    """Malformed agent options cannot accidentally broaden the scope."""
    with pytest.raises(TypeError, match="server_ids"):
        MCPServiceManager(hass).scope(server_ids)
