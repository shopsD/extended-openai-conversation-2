"""LLM-callable MCP function dispatcher."""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..mcp_client import MCPToolManager
from ..mcp_service_manager import MCPServiceManager
from .base import Function

_LIST_SERVERS_ARGUMENTS = (
    "query",
    "search_fields",
    "search_regex",
    "search_case_sensitive",
    "include_tools",
    "all_tools",
    "include_description",
    "include_schema",
    "current_page",
    "entries_per_page",
)
_LIST_TOOLS_ARGUMENTS = (
    "server_ids",
    "query",
    "search_fields",
    "search_regex",
    "search_case_sensitive",
    "include_description",
    "include_schema",
    "current_page",
    "entries_per_page",
)


def build_mcp_function_tool(server_ids: list[str]) -> dict[str, Any]:
    """Build the model-facing MCP dispatcher definition for an agent."""
    return {
        "spec": {
            "name": "mcp",
            "description": (
                "Discover MCP servers and tools, retrieve tool schemas, or execute "
                "a tool. Use list_servers or list_tools before execution when the "
                "required server, tool, or arguments are unknown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list_servers",
                            "list_tools",
                            "get_schema",
                            "execute_tool",
                        ],
                        "description": "The MCP operation to perform.",
                    },
                    "server_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "For list_tools only, restrict results to these server "
                            "IDs. IDs outside the agent's assigned scope return no "
                            "results."
                        ),
                    },
                    "server_id": {
                        "type": "string",
                        "description": (
                            "Server ID for get_schema or execute_tool."
                        ),
                    },
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "Tool name for get_schema or execute_tool."
                        ),
                    },
                    "arguments": {
                        "type": "object",
                        "description": (
                            "Tool arguments for execute_tool, following the tool's "
                            "input schema."
                        ),
                        "additionalProperties": True,
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional server or tool search query.",
                    },
                    "search_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional fields in which to search.",
                    },
                    "search_regex": {
                        "type": "boolean",
                        "description": "Interpret query as a regular expression.",
                    },
                    "search_case_sensitive": {
                        "type": "boolean",
                        "description": "Perform a case-sensitive search.",
                    },
                    "include_tools": {
                        "type": "boolean",
                        "description": (
                            "For list_servers, include matching tool summaries."
                        ),
                    },
                    "all_tools": {
                        "type": "boolean",
                        "description": (
                            "For list_servers, include all discoverable tools from "
                            "each matching server rather than only tools matching "
                            "the query, subject to the per-server result limit. "
                            "Implies include_tools=true. Use list_tools with the "
                            "returned server ID to paginate further."
                        ),
                    },
                    "include_description": {
                        "type": "boolean",
                        "description": "Include tool descriptions in results.",
                    },
                    "include_schema": {
                        "type": "boolean",
                        "description": "Include tool input schemas in results.",
                    },
                    "current_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Result page to return.",
                    },
                    "entries_per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Results per page, up to 100.",
                    },
                },
                "required": ["action"],
            },
        },
        "function": {"type": "mcp", "server_ids": list(server_ids)},
    }


class MCPFunction(Function):
    """Dispatch MCP actions over the servers assigned to an agent."""

    def __init__(self) -> None:
        """Initialize the function configuration schema."""
        super().__init__(vol.Schema({vol.Required("server_ids"): [str]}))

    async def execute(
        self,
        hass: HomeAssistant,
        function_config: dict[str, Any],
        arguments: dict[str, Any],
        llm_context: llm.LLMContext | None,
        exposed_entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute an MCP action against the configured server scope."""
        action = arguments.get("action")
        if action not in {
            "list_servers",
            "list_tools",
            "get_schema",
            "execute_tool",
        }:
            return {
                "error": {
                    "code": "invalid_action",
                    "message": "Unsupported MCP action",
                }
            }

        services = MCPServiceManager(hass).scope(
            function_config["server_ids"]
        ).list_loaded()

        if action == "list_servers":
            return await MCPToolManager.list_servers(
                services,
                **{
                    key: arguments[key]
                    for key in _LIST_SERVERS_ARGUMENTS
                    if key in arguments
                },
            )

        if action == "list_tools":
            return await MCPToolManager.list_tools(
                services,
                **{
                    key: arguments[key]
                    for key in _LIST_TOOLS_ARGUMENTS
                    if key in arguments
                },
            )

        if action == "get_schema":
            return await MCPToolManager.get_schema(
                services,
                server_id=arguments.get("server_id", ""),
                tool_name=arguments.get("tool_name", ""),
            )

        return await MCPToolManager.execute_tool(
            services,
            server_id=arguments.get("server_id", ""),
            tool_name=arguments.get("tool_name", ""),
            arguments=arguments.get("arguments"),
        )
