"""Datatypes used by the MCP Client API"""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MCPServerInformation:
    """Public server information returned by MCP initialization."""

    name: str
    version: str
    protocol_version: str
    instructions: str | None
    capabilities: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPTool:
    """Serializable MCP tool definition returned by catalogue discovery."""

    name: str
    title: str | None
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    definition: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """Serializable result returned by an MCP tool invocation."""

    content: tuple[dict[str, Any], ...]
    structured_content: dict[str, Any] | None
    is_error: bool


@dataclass(frozen=True, slots=True)
class MCPDiscoveryResult:
    """Server metadata and complete tool catalogue from one MCP session."""

    server: MCPServerInformation
    tools: tuple[MCPTool, ...]
