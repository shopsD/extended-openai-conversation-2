"""Home Assistant runtime lookup for configured MCP services."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVICE_TYPE_MCP
from .helpers import get_service_type
from .mcp_client import CONF_MCP_SERVER_ID, MCPClient, MCPService, MCPServiceConfig


class MCPServiceNotFoundError(LookupError):
    """Raised when no configured MCP service has the requested server ID."""


class MCPServiceUnavailableError(RuntimeError):
    """Raised when a configured MCP service is not currently loaded."""


@dataclass(frozen=True, slots=True)
class MCPServiceScope:
    """Agent-visible view of the MCP services it is allowed to use."""

    _manager: MCPServiceManager
    _server_ids: frozenset[str]

    def list_loaded(self) -> tuple[MCPService, ...]:
        """Return allowed MCP services that are currently loaded."""
        return self._manager._list_loaded(self._server_ids)

    def get(self, server_id: str) -> MCPService:
        """Return an allowed, loaded MCP service by its stable server ID."""
        if server_id not in self._server_ids:
            raise MCPServiceNotFoundError(
                f"MCP service {server_id!r} was not found"
            )
        return self._manager._get(server_id)


class MCPServiceManager:
    """Create agent-scoped views of Home Assistant MCP config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize a manager without caching config-entry state."""
        self._hass = hass

    def scope(self, server_ids: Collection[str]) -> MCPServiceScope:
        """Restrict service lookup to the stable IDs selected by one agent."""
        if isinstance(server_ids, str):
            raise TypeError("server_ids must be a collection of strings")
        if not all(isinstance(server_id, str) for server_id in server_ids):
            raise TypeError("server_ids must contain only strings")
        return MCPServiceScope(self, frozenset(server_ids))

    def _list_loaded(
        self, allowed_server_ids: frozenset[str]
    ) -> tuple[MCPService, ...]:
        """Return loaded services whose stable IDs are in the scope."""
        if not allowed_server_ids:
            return ()
        services: list[MCPService] = []
        for entry in self._mcp_entries():
            if entry.data.get(CONF_MCP_SERVER_ID) not in allowed_server_ids:
                continue
            if entry.state is not ConfigEntryState.LOADED:
                continue
            client = entry.runtime_data
            if not isinstance(client, MCPClient):
                continue
            services.append(self._service(entry, client))
        return tuple(services)

    def _get(self, server_id: str) -> MCPService:
        """Return a loaded MCP service after its scope has been checked."""
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
