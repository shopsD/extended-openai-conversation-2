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
                "Use list_servers to discover servers, list_tools to search "
                "discoverable tools, get_schema to retrieve a specific authorised "
                "tool's complete schema, or execute_tool to invoke it. Use discovery "
                "before execution when the required server, tool, or arguments are "
                "unknown."
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
                        "description": (
                            "The MCP operation to perform. get_schema and "
                            "execute_tool require server_id and tool_name."
                        ),
                    },
                    "server_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "For list_tools only, exactly filter discovery to these "
                            "server IDs. This cannot expand the agent's assigned "
                            "server scope; inaccessible IDs return no results."
                        ),
                    },
                    "server_id": {
                        "type": "string",
                        "description": (
                            "The single target server ID required by get_schema and "
                            "execute_tool. Unlike server_ids, this identifies the "
                            "target of a specific operation."
                        ),
                    },
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "The tool name required by get_schema and execute_tool. "
                            "get_schema works for any authorised tool, including a "
                            "tool omitted from discovery results."
                        ),
                    },
                    "arguments": {
                        "type": "object",
                        "description": (
                            "Tool arguments for execute_tool, following the tool's "
                            "input schema. May be omitted for a tool that accepts no "
                            "arguments."
                        ),
                        "additionalProperties": True,
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional server or tool search query. When omitted, all "
                            "eligible discovery results match."
                        ),
                    },
                    "search_fields": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "server_id",
                                "server_name",
                                "tool_name",
                                "description",
                                "schema",
                            ],
                        },
                        "description": (
                            "Optional fields in which to search. list_servers accepts "
                            "server_id, server_name, tool_name, description, and "
                            "schema. list_tools accepts only tool_name, description, "
                            "and schema. Defaults to every field supported by the "
                            "selected action."
                        ),
                    },
                    "search_regex": {
                        "type": "boolean",
                        "description": (
                            "Interpret query as a regular expression. Defaults to "
                            "false."
                        ),
                    },
                    "search_case_sensitive": {
                        "type": "boolean",
                        "description": (
                            "Perform a case-sensitive search. Defaults to false."
                        ),
                    },
                    "include_tools": {
                        "type": "boolean",
                        "description": (
                            "For list_servers, include matching tool summaries as a "
                            "bounded preview. Defaults to false."
                        ),
                    },
                    "all_tools": {
                        "type": "boolean",
                        "description": (
                            "For list_servers, include all discoverable tools from "
                            "each matching server rather than only tools matching "
                            "the query, subject to the per-server result limit. "
                            "Implies include_tools=true. Use list_tools with the "
                            "returned server ID to paginate further. Defaults to "
                            "false."
                        ),
                    },
                    "include_description": {
                        "type": "boolean",
                        "description": (
                            "Include tool descriptions in results. Server descriptions "
                            "are always included by list_servers. Defaults to true."
                        ),
                    },
                    "include_schema": {
                        "type": "boolean",
                        "description": (
                            "Include tool input schemas and advertised output schemas "
                            "in results. For list_servers, this applies only to tool "
                            "summaries included in the bounded preview. For list_tools, "
                            "this applies to each returned tool. Defaults to false."
                        ),
                    },
                    "current_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Result page to return. Defaults to 1.",
                    },
                    "entries_per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": (
                            "Results per page, from 1 through the hard maximum of 100. "
                            "Defaults to 20. For list_servers, this also bounds each "
                            "server's included tool preview."
                        ),
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
