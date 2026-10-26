"""Tests for the MCP function dispatcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.extended_openai_conversation.functions import MCPFunction
from custom_components.extended_openai_conversation.functions.mcp import (
    build_mcp_function_tool,
)
from custom_components.extended_openai_conversation.mcp_client import MCPToolManager


def test_all_tools_description_explains_implicit_bounded_preview():
    """The model is told how all_tools affects inclusion and pagination."""
    tool = build_mcp_function_tool(["weather"])

    description = tool["spec"]["parameters"]["properties"]["all_tools"][
        "description"
    ]
    assert "Implies include_tools=true" in description
    assert "per-server result limit" in description
    assert "paginate further" in description


@pytest.mark.parametrize(
    ("action", "arguments", "method_name", "expected_arguments"),
    [
        (
            "list_servers",
            {
                "action": "list_servers",
                "query": "weather",
                "include_tools": True,
                "ignored": True,
            },
            "list_servers",
            {"query": "weather", "include_tools": True},
        ),
        (
            "list_tools",
            {
                "action": "list_tools",
                "server_ids": ["weather"],
                "query": "forecast",
                "include_schema": True,
                "ignored": True,
            },
            "list_tools",
            {
                "server_ids": ["weather"],
                "query": "forecast",
                "include_schema": True,
            },
        ),
        (
            "get_schema",
            {
                "action": "get_schema",
                "server_id": "weather",
                "tool_name": "forecast",
                "ignored": True,
            },
            "get_schema",
            {"server_id": "weather", "tool_name": "forecast"},
        ),
        (
            "execute_tool",
            {
                "action": "execute_tool",
                "server_id": "weather",
                "tool_name": "forecast",
                "arguments": {"location": "London"},
                "ignored": True,
            },
            "execute_tool",
            {
                "server_id": "weather",
                "tool_name": "forecast",
                "arguments": {"location": "London"},
            },
        ),
    ],
)
async def test_execute_routes_action(
    hass,
    llm_context,
    exposed_entities,
    action,
    arguments,
    method_name,
    expected_arguments,
):
    """Test actions are scoped and forwarded to the matching operation."""
    services = [MagicMock()]
    scope = MagicMock()
    scope.list_loaded.return_value = services
    manager = MagicMock()
    manager.scope.return_value = scope
    operation = AsyncMock(return_value={"action": action})

    with (
        patch(
            "custom_components.extended_openai_conversation.functions.mcp.MCPServiceManager",
            return_value=manager,
        ),
        patch.object(MCPToolManager, method_name, operation),
    ):
        result = await MCPFunction().execute(
            hass,
            {"type": "mcp", "server_ids": ["weather", "home"]},
            arguments,
            llm_context,
            exposed_entities,
        )

    assert result == {"action": action}
    manager.scope.assert_called_once_with(["weather", "home"])
    scope.list_loaded.assert_called_once_with()
    operation.assert_awaited_once_with(services, **expected_arguments)


@pytest.mark.parametrize("arguments", [{}, {"action": "unknown"}])
async def test_execute_rejects_invalid_action(
    hass, llm_context, exposed_entities, arguments
):
    """Test missing and unsupported actions return a structured error."""
    with patch(
        "custom_components.extended_openai_conversation.functions.mcp.MCPServiceManager"
    ) as manager:
        result = await MCPFunction().execute(
            hass,
            {"type": "mcp", "server_ids": ["weather"]},
            arguments,
            llm_context,
            exposed_entities,
        )

    assert result == {
        "error": {
            "code": "invalid_action",
            "message": "Unsupported MCP action",
        }
    }
    manager.assert_not_called()
