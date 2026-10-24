"""Serializable configuration for one host-managed MCP service."""

from __future__ import annotations

from collections.abc import Mapping
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
from .mcp_datatypes import MCPServerInformation, MCPTool


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
            raise ValueError("regex_timeout must be greater than zero")

        tool_names = [tool.name for tool in self.permanent_tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("permanent tool names must be unique")

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
