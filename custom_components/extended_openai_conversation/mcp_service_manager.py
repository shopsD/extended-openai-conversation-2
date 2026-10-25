"""Home Assistant runtime lookup for configured MCP services."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVICE_TYPE_MCP
from .helpers import get_service_type
from .mcp_client import CONF_MCP_SERVER_ID, MCPClient, MCPServiceConfig


class MCPServiceNotFoundError(LookupError):
    """Raised when no configured MCP service has the requested server ID."""


class MCPServiceUnavailableError(RuntimeError):
    """Raised when a configured MCP service is not currently loaded."""


@dataclass(frozen=True, slots=True)
class MCPService:
    """One loaded MCP service and its host-independent configuration."""

    entry_id: str
    title: str
    config: MCPServiceConfig
    client: MCPClient


class MCPServiceManager:
    """Resolve loaded MCP services from Home Assistant config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize a manager without caching config-entry state."""
        self._hass = hass

    def list_loaded(self) -> tuple[MCPService, ...]:
        """Return all MCP services that are currently loaded."""
        services: list[MCPService] = []
        for entry in self._mcp_entries():
            if entry.state is not ConfigEntryState.LOADED:
                continue
            client = entry.runtime_data
            if not isinstance(client, MCPClient):
                continue
            services.append(self._service(entry, client))
        return tuple(services)

    def get(self, server_id: str) -> MCPService:
        """Return a loaded MCP service by its stable server ID."""
        for entry in self._mcp_entries():
            if entry.data.get(CONF_MCP_SERVER_ID) != server_id:
                continue
            if entry.state is not ConfigEntryState.LOADED:
                raise MCPServiceUnavailableError(
                    f"MCP service {server_id!r} is not loaded"
                )
            client = entry.runtime_data
            if not isinstance(client, MCPClient):
                raise MCPServiceUnavailableError(
                    f"MCP service {server_id!r} has no runtime client"
                )
            return self._service(entry, client)
        raise MCPServiceNotFoundError(f"MCP service {server_id!r} was not found")

    def _mcp_entries(self) -> tuple[ConfigEntry, ...]:
        """Return configured MCP entries in Home Assistant's stable order."""
        return tuple(
            entry
            for entry in self._hass.config_entries.async_entries(DOMAIN)
            if get_service_type(entry) == SERVICE_TYPE_MCP
        )

    @staticmethod
    def _service(entry: ConfigEntry, client: MCPClient) -> MCPService:
        """Build the public runtime view for one loaded entry."""
        return MCPService(
            entry_id=entry.entry_id,
            title=entry.title,
            config=MCPServiceConfig.from_dict(entry.data),
            client=client,
        )
