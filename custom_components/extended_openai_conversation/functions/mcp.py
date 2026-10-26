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
