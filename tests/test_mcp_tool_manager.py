"""Tests for host-independent MCP server listing."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.extended_openai_conversation.mcp_client import (
    MCPClient,
    MCPServerConfig,
    MCPServiceConfig,
    MCPTool,
    MCPToolManager,
)


def _tool(name: str, description: str) -> MCPTool:
    return MCPTool(
        name=name,
        title=None,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
        },
        output_schema=None,
        definition={"name": name},
    )


def _service(
    server_id: str,
    *,
    description: str = "",
    permanent_tools: tuple[MCPTool, ...] = (),
    on_demand_discovery: bool = True,
    tools: tuple[MCPTool, ...] = (),
) -> tuple[MCPServiceConfig, MCPClient]:
    config = MCPServiceConfig(
        server=MCPServerConfig(
            server_id=server_id,
            name=f"{server_id.title()} Server",
            url=f"https://{server_id}.example.com/mcp",
            description=description,
        ),
        permanent_tools=permanent_tools,
        on_demand_discovery=on_demand_discovery,
    )
    client = MagicMock(spec=MCPClient)
    client.list_tools = AsyncMock(return_value=tools)
    return config, client


async def test_list_servers_without_tool_fields_avoids_server_calls():
    """A metadata-only listing uses saved configuration without discovery."""
    storage = _service("storage", description="File storage")
    calendar = _service("calendar", description="Appointments")

    result = await MCPToolManager.list_servers(
        [storage, calendar],
        query="storage",
        search_fields=["server_id", "server_name"],
    )

    assert result == {
        "servers": [
            {
                "id": "storage",
                "name": "Storage Server",
                "description": "File storage",
            }
        ],
        "max_matches": 1,
        "current_page": 1,
        "max_pages": 1,
        "entries_per_page": 20,
    }
    storage[1].list_tools.assert_not_awaited()
    calendar[1].list_tools.assert_not_awaited()


async def test_list_servers_searches_only_discoverable_non_permanent_tools():
    """Tool matching applies service policy and omits permanent tools."""
    upload = _tool("upload_file", "Upload a file")
    permanent = _tool("download_file", "Download a file")
    storage = _service(
        "storage",
        permanent_tools=(permanent,),
        tools=(upload, permanent),
    )

    result = await MCPToolManager.list_servers(
        [storage],
        query="file",
        search_fields=["tool_name"],
        include_tools=True,
    )

    assert result["servers"][0]["tools"] == [
        {"tool_name": "upload_file", "description": "Upload a file"}
    ]
    storage[1].list_tools.assert_awaited_once_with()


async def test_list_servers_reports_metadata_match_without_tool_match():
    """A server metadata match remains visible with an explanatory empty list."""
    storage = _service("storage", tools=(_tool("upload_file", "Upload a file"),))

    result = await MCPToolManager.list_servers(
        [storage], query="storage", include_tools=True
    )

    server = result["servers"][0]
    assert server["tools"] == []
    assert "no discoverable tools matched" in server["tool_match_message"]


async def test_list_servers_paginates_with_a_hard_page_size_limit():
    """Pagination reports totals and rejects more than 100 entries per page."""
    services = [_service(f"server-{index}") for index in range(3)]

    result = await MCPToolManager.list_servers(
        services, current_page=2, entries_per_page=2
    )
    invalid = await MCPToolManager.list_servers(services, entries_per_page=101)

    assert [server["id"] for server in result["servers"]] == ["server-2"]
    assert result["max_matches"] == 3
    assert result["max_pages"] == 2
    assert invalid["error"]["code"] == "invalid_entries_per_page"


async def test_list_servers_regex_searches_schema_values():
    """Regex search inspects meaningful schema fields using search semantics."""
    storage = _service(
        "storage", tools=(_tool("upload_file", "Upload a file"),)
    )

    result = await MCPToolManager.list_servers(
        [storage],
        query="file_pa.*",
        search_fields=["schema"],
        search_regex=True,
        include_tools=True,
    )

    assert result["servers"][0]["id"] == "storage"
    assert result["servers"][0]["tools"][0]["tool_name"] == "upload_file"
