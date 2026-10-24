"""Serializable configuration for one host-managed MCP service."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from .config import MCPServerConfig
from .mcp_const import (
    CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
    CONF_MCP_ON_DEMAND_DISCOVERY,
    CONF_MCP_PERMANENT_TOOL_CATALOGUE,
    CONF_MCP_PERMANENT_TOOL_EXPOSURE,
    CONF_MCP_PERMANENT_TOOLS,
    CONF_MCP_REGEX_TIMEOUT,
    CONF_MCP_SERVER_INFORMATION,
    DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
    DEFAULT_MCP_ON_DEMAND_DISCOVERY,
    DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE,
    DEFAULT_MCP_REGEX_TIMEOUT,
)
from .mcp_datatypes import MCPDiscoveryResult, MCPServerInformation, MCPTool
from .mcp_errors import MCPConfigError


@dataclass(frozen=True, slots=True)
class MCPServiceConfig:
    """Connection, discovery snapshot and policies persisted by a host."""

    server: MCPServerConfig
    permanent_tool_exposure: bool = DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE
    permanent_tools: tuple[MCPTool, ...] = ()
    include_permanent_schemas: bool = DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS
    on_demand_discovery: bool = DEFAULT_MCP_ON_DEMAND_DISCOVERY
    regex_timeout: float = DEFAULT_MCP_REGEX_TIMEOUT
    server_information: MCPServerInformation | None = None

    def __post_init__(self) -> None:
        """Validate policy values that are independent of a host framework."""
        if (
            isinstance(self.regex_timeout, bool)
            or not isinstance(self.regex_timeout, (int, float))
            or self.regex_timeout <= 0
        ):
            raise MCPConfigError("regex_timeout", "invalid_regex_timeout")

        tool_names = [tool.name for tool in self.permanent_tools]
        if len(tool_names) != len(set(tool_names)):
            raise MCPConfigError("permanent_tools", "invalid_permanent_tools")

    @classmethod
    def from_selection(
        cls,
        server: MCPServerConfig,
        discovery: MCPDiscoveryResult | None,
        *,
        permanent_tool_exposure: bool,
        selected_tool_names: Collection[str],
        include_permanent_schemas: bool,
        on_demand_discovery: bool,
        regex_timeout: float,
    ) -> MCPServiceConfig:
        """Validate and normalize a service configuration selection."""
        if (isinstance(selected_tool_names, str) or
            not all(isinstance(name, str) for name in selected_tool_names)
        ):
            raise MCPConfigError("permanent_tools", "invalid_permanent_tools")

        selected_names: set[str] = set(selected_tool_names)
        if not permanent_tool_exposure:
            selected_names.clear()
            include_permanent_schemas = False
        elif discovery is None:
            raise MCPConfigError("permanent_tools", "mcp_discovery_required")

        available_tools: tuple[MCPTool, ...] = discovery.tools if discovery is not None else ()
        available_names: set[str] = {tool.name for tool in available_tools}
        if selected_names - available_names:
            raise MCPConfigError("permanent_tools", "invalid_permanent_tools")

        return cls(
            server=server,
            permanent_tool_exposure=permanent_tool_exposure,
            permanent_tools=tuple(
                tool for tool in available_tools if tool.name in selected_names
            ),
            include_permanent_schemas=include_permanent_schemas,
            on_demand_discovery=on_demand_discovery,
            regex_timeout=regex_timeout,
            server_information=discovery.server if discovery is not None else None,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MCPServiceConfig:
        """Build a service configuration from its persisted mapping."""
        server_information = data.get(CONF_MCP_SERVER_INFORMATION)
        catalogue = data.get(CONF_MCP_PERMANENT_TOOL_CATALOGUE, ())
        return cls(
            server=MCPServerConfig.from_dict(data),
            permanent_tool_exposure=data.get(
                CONF_MCP_PERMANENT_TOOL_EXPOSURE,
                DEFAULT_MCP_PERMANENT_TOOL_EXPOSURE,
            ),
            permanent_tools=tuple(MCPTool.from_dict(tool) for tool in catalogue),
            include_permanent_schemas=data.get(
                CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
                DEFAULT_MCP_INCLUDE_PERMANENT_SCHEMAS,
            ),
            on_demand_discovery=data.get(
                CONF_MCP_ON_DEMAND_DISCOVERY,
                DEFAULT_MCP_ON_DEMAND_DISCOVERY,
            ),
            regex_timeout=data.get(CONF_MCP_REGEX_TIMEOUT, DEFAULT_MCP_REGEX_TIMEOUT),
            server_information=(
                MCPServerInformation.from_dict(server_information)
                if isinstance(server_information, Mapping)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a flat mapping suitable for host configuration storage."""
        data = {
            **self.server.to_dict(),
            CONF_MCP_PERMANENT_TOOL_EXPOSURE: self.permanent_tool_exposure,
            CONF_MCP_PERMANENT_TOOLS: [tool.name for tool in self.permanent_tools],
            CONF_MCP_PERMANENT_TOOL_CATALOGUE: [
                tool.to_dict() for tool in self.permanent_tools
            ],
            CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: self.include_permanent_schemas,
            CONF_MCP_ON_DEMAND_DISCOVERY: self.on_demand_discovery,
            CONF_MCP_REGEX_TIMEOUT: self.regex_timeout,
        }
        if self.server_information is not None:
            data[CONF_MCP_SERVER_INFORMATION] = self.server_information.to_dict()
        return data
