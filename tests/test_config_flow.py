"""Tests for config_flow.py.

Note: these test validate_input() and the schema-building logic directly,
rather than driving the full flow through Home Assistant's flow manager
(hass.config_entries.flow.async_init(...)) - that needs the real
pytest-homeassistant-custom-component `hass` fixture, which this project's
conftest.py currently shadows project-wide with a lightweight mock for fast
unit testing. Actually exercising the flow steps end-to-end is tracked as a
follow-up (see issue #7) rather than attempted here with a mocked hass that
doesn't behave like the real flow manager.
"""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.extended_openai_conversation.config_flow import (
    ExtendedOpenAIConversationConfigFlow,
    ExtendedOpenAISubentryFlowHandler,
    validate_input,
)
from custom_components.extended_openai_conversation.const import (
    CONF_API_PROVIDER,
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_FUNCTION_TOOLS,
    CONF_PROMPT,
    CONF_SERVICE_TYPE,
    CONF_SKILLS,
    DEFAULT_CONF_BASE_URL,
    SERVICE_TYPE_AI_ENDPOINT,
    SERVICE_TYPE_MCP,
)
from custom_components.extended_openai_conversation.mcp_client import (
    MCPDiscoveryResult,
    MCPServerConfig,
    MCPServerInformation,
    MCPTool,
)
from custom_components.extended_openai_conversation.mcp_client.mcp_const import (
    CONF_MCP_DESCRIPTION,
    CONF_MCP_HEADERS,
    CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
    CONF_MCP_ON_DEMAND_DISCOVERY,
    CONF_MCP_PERMANENT_TOOL_EXPOSURE,
    CONF_MCP_PERMANENT_TOOLS,
    CONF_MCP_REGEX_TIMEOUT,
    CONF_MCP_SERVER_ID,
    CONF_MCP_SERVER_URL,
    CONF_MCP_USE_OAUTH,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.exceptions import HomeAssistantError


def _schema_keys(schema: dict) -> set[str]:
    """Extract the plain string keys from a dict of voluptuous Marker -> Selector."""
    return {getattr(key, "schema", key) for key in schema}


def _config_flow(hass) -> ExtendedOpenAIConversationConfigFlow:
    """Create a config flow with the lightweight test Home Assistant mock."""
    flow = ExtendedOpenAIConversationConfigFlow()
    flow.hass = hass
    hass.config_entries.async_entries.return_value = []
    return flow


async def test_user_step_asks_for_service_type(hass):
    """The initial Add Service step asks which service type to configure."""
    flow = _config_flow(hass)
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    await flow.async_step_user()

    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    assert flow.async_show_form.call_args.kwargs["step_id"] == "user"
    assert _schema_keys(schema.schema) == {CONF_SERVICE_TYPE}


async def test_user_step_routes_to_ai_endpoint(hass):
    """Selecting AI endpoint opens the existing AI endpoint form."""
    flow = _config_flow(hass)
    flow.async_step_ai_endpoint = AsyncMock(return_value={"step_id": "ai_endpoint"})

    result = await flow.async_step_user({CONF_SERVICE_TYPE: SERVICE_TYPE_AI_ENDPOINT})

    assert result == {"step_id": "ai_endpoint"}
    flow.async_step_ai_endpoint.assert_awaited_once_with()


async def test_user_step_routes_to_mcp(hass):
    """Selecting MCP opens the MCP configuration form."""
    flow = _config_flow(hass)
    flow.async_step_mcp = AsyncMock(return_value={"step_id": "mcp"})

    result = await flow.async_step_user({CONF_SERVICE_TYPE: SERVICE_TYPE_MCP})

    assert result == {"step_id": "mcp"}
    flow.async_step_mcp.assert_awaited_once_with()


async def test_ai_endpoint_is_reviewed_before_it_is_saved(hass):
    """A valid AI endpoint returns to the menu and only saves after review."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_AI_ENDPOINT
    flow.async_step_service_menu = AsyncMock(return_value={"type": "menu"})
    user_input = {
        "name": "Local AI",
        CONF_API_KEY: "test-key",
        CONF_BASE_URL: "https://ai.example.com/v1",
    }

    with patch(
        "custom_components.extended_openai_conversation.config_flow.validate_input",
        new=AsyncMock(),
    ):
        result = await flow.async_step_ai_endpoint(user_input)

    assert result == {"type": "menu"}
    assert flow._ai_endpoint_data == {
        **user_input,
        CONF_SERVICE_TYPE: SERVICE_TYPE_AI_ENDPOINT,
    }

    await flow.async_step_service_review({})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    result = await flow.async_step_service_save()

    assert result == {"type": "create_entry"}
    assert flow.async_create_entry.call_args.kwargs["data"] == flow._ai_endpoint_data
    assert len(flow.async_create_entry.call_args.kwargs["subentries"]) == 2


async def test_mcp_step_keeps_config_and_returns_to_service_menu(hass):
    """A valid MCP form returns to the central menu and keeps its data."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow.async_step_service_menu = AsyncMock(return_value={"step_id": "service_menu"})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    user_input = {
        "name": "Vault MCP",
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
        CONF_MCP_DESCRIPTION: "Secure storage tools",
        CONF_MCP_HEADERS: {"Authorization": "Bearer test-token"},
        CONF_MCP_USE_OAUTH: False,
    }

    result = await flow.async_step_mcp(user_input)

    assert result == {"step_id": "service_menu"}
    assert flow._mcp_config is not None
    assert flow._mcp_config.server_id == "vault"
    assert flow._mcp_config.url == "https://mcp.example.com/api"
    flow.async_step_service_menu.assert_awaited_once_with()
    flow.async_create_entry.assert_not_called()


async def test_mcp_form_includes_oauth_choice(hass):
    """The server form lets the user opt into managed OAuth."""
    flow = _config_flow(hass)
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await flow.async_step_mcp()

    assert result == {"type": "form"}
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    assert CONF_MCP_USE_OAUTH in _schema_keys(schema.schema)


async def test_service_menu_unlocks_discovery_without_connecting(hass):
    """A valid MCP server unlocks discovery without contacting it."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow.async_show_menu = MagicMock(return_value={"type": "menu"})

    with patch(
        "custom_components.extended_openai_conversation.config_flow."
        "MCPClientConfigFlow.discover",
        new=AsyncMock(),
    ) as mock_discover:
        result = await flow.async_step_service_menu()

    assert result == {"type": "menu"}
    mock_discover.assert_not_awaited()
    assert flow.async_show_menu.call_args.kwargs == {
        "step_id": "service_menu",
        "menu_options": [
            "switch_to_ai_endpoint",
            "mcp",
            "mcp_perform_discovery",
            "mcp_skip_discovery",
        ],
        "description_placeholders": {"status": ""},
    }


async def test_oauth_server_requires_authentication_before_discovery(hass):
    """OAuth MCP servers expose Authenticate before discovery actions."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
        use_oauth=True,
    )
    flow.async_show_menu = MagicMock(return_value={"type": "menu"})

    await flow.async_step_service_menu()

    assert flow.async_show_menu.call_args.kwargs["menu_options"] == [
        "switch_to_ai_endpoint",
        "mcp",
        "mcp_authenticate",
    ]

    flow._mcp_oauth_authenticated = True
    await flow.async_step_service_menu()

    assert flow.async_show_menu.call_args.kwargs["menu_options"] == [
        "switch_to_ai_endpoint",
        "mcp",
        "mcp_authenticate",
        "mcp_perform_discovery",
        "mcp_skip_discovery",
    ]


async def test_oauth_callback_completion_returns_to_service_menu(hass):
    """A successful external OAuth callback marks the draft authenticated."""
    flow = _config_flow(hass)
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
        use_oauth=True,
    )
    flow.async_external_step_done = MagicMock(return_value={"type": "external_done"})

    result = await flow.async_step_mcp_authenticate({"authenticated": True})

    assert result == {"type": "external_done"}
    assert flow._mcp_oauth_authenticated
    assert flow._workflow_status == "MCP OAuth authentication succeeded."
    flow.async_external_step_done.assert_called_once_with(next_step_id="service_menu")


async def test_oauth_authentication_opens_sdk_authorization_url(hass):
    """The explicit Authenticate action opens the SDK-generated OAuth URL."""
    flow = _config_flow(hass)
    flow.flow_id = "flow-id"
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
        use_oauth=True,
    )
    flow.async_external_step = MagicMock(return_value={"type": "external"})
    hass.async_create_task.side_effect = asyncio.create_task
    handlers = {}

    def create_provider(*args, **kwargs):
        handlers.update(kwargs)
        return MagicMock()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def check_connection(self):
            await handlers["redirect_handler"](
                "https://auth.example.com/authorize?state=oauth-state"
            )
            await handlers["callback_handler"]()

    with (
        patch(
            "custom_components.extended_openai_conversation.config_flow.get_url",
            return_value="https://ha.example.com",
        ),
        patch(
            "custom_components.extended_openai_conversation.config_flow."
            "create_mcp_oauth_provider",
            side_effect=create_provider,
        ),
        patch(
            "custom_components.extended_openai_conversation.config_flow.MCPClient",
            return_value=FakeClient(),
        ),
    ):
        result = await flow.async_step_mcp_authenticate()

    assert result == {"type": "external"}
    flow.async_external_step.assert_called_once_with(
        step_id="mcp_authenticate",
        url="https://auth.example.com/authorize?state=oauth-state",
    )
    assert flow._mcp_oauth_attempt is not None
    assert flow._mcp_oauth_attempt.state == "oauth-state"

    assert flow._mcp_oauth_task is not None
    flow._mcp_oauth_task.cancel()
    with suppress(asyncio.CancelledError):
        await flow._mcp_oauth_task


async def test_service_menu_gates_review_and_save_by_draft_state(hass):
    """Review requires valid policies, and Save requires the current review."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    assert not flow._set_mcp_service_config(
        {
            CONF_MCP_PERMANENT_TOOL_EXPOSURE: False,
            CONF_MCP_PERMANENT_TOOLS: [],
            CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: False,
            CONF_MCP_ON_DEMAND_DISCOVERY: True,
            CONF_MCP_REGEX_TIMEOUT: 0.1,
        }
    )
    flow._mark_draft_changed()
    flow.async_show_menu = MagicMock(return_value={"type": "menu"})

    await flow.async_step_service_menu()

    options = flow.async_show_menu.call_args.kwargs["menu_options"]
    assert "service_review" in options
    assert "service_save" not in options

    flow._reviewed_revision = flow._draft_revision
    await flow.async_step_service_menu()

    assert "service_save" in flow.async_show_menu.call_args.kwargs["menu_options"]

    flow._mark_draft_changed()
    await flow.async_step_service_menu()

    assert "service_save" not in flow.async_show_menu.call_args.kwargs["menu_options"]


async def test_reconfigure_menu_keeps_existing_service_type(hass):
    """Reconfiguration does not offer an unsupported entry-type conversion."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._reconfigure_entry = MagicMock()
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow.async_show_menu = MagicMock(return_value={"type": "menu"})

    await flow.async_step_service_menu()

    options = flow.async_show_menu.call_args.kwargs["menu_options"]
    assert "switch_to_ai_endpoint" not in options
    assert options == ["mcp", "mcp_perform_discovery", "mcp_skip_discovery"]


async def test_mcp_discover_step_keeps_catalogue_and_opens_tools(hass):
    """Submitting discovery retrieves the catalogue once and opens tool setup."""
    flow = _config_flow(hass)
    config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    discovery = MCPDiscoveryResult(
        server=MCPServerInformation(
            name="Vault Server",
            version="1.0.0",
            protocol_version="2025-06-18",
            instructions=None,
            capabilities={},
        ),
        tools=(
            MCPTool(
                name="read_secret",
                title="Read secret",
                description="Read a stored secret.",
                input_schema={"type": "object"},
                output_schema=None,
                definition={"name": "read_secret"},
            ),
        ),
    )
    flow._mcp_config = config
    flow._mcp_options = {
        CONF_MCP_PERMANENT_TOOL_EXPOSURE: True,
        CONF_MCP_PERMANENT_TOOLS: ["read_secret", "removed_tool"],
        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: True,
        CONF_MCP_ON_DEMAND_DISCOVERY: True,
        CONF_MCP_REGEX_TIMEOUT: 0.1,
    }
    flow.async_step_mcp_tools = AsyncMock(return_value={"step_id": "mcp_tools"})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    with patch(
        "custom_components.extended_openai_conversation.config_flow."
        "MCPClientConfigFlow.discover",
        new=AsyncMock(return_value=discovery),
    ) as mock_discover:
        result = await flow.async_step_mcp_perform_discovery()

    assert result == {"step_id": "mcp_tools"}
    mock_discover.assert_awaited_once_with(config)
    assert flow._mcp_discovery is discovery
    assert flow._mcp_options[CONF_MCP_PERMANENT_TOOLS] == ["read_secret"]
    flow.async_step_mcp_tools.assert_awaited_once_with()
    flow.async_create_entry.assert_not_called()


async def test_mcp_tools_step_displays_catalogue_and_policy_options(hass):
    """The post-discovery page exposes every tool and service-level policy."""
    flow = _config_flow(hass)
    flow._mcp_discovery = MCPDiscoveryResult(
        server=MCPServerInformation(
            name="Vault Server",
            version="1.0.0",
            protocol_version="2025-06-18",
            instructions=None,
            capabilities={},
        ),
        tools=(
            MCPTool(
                name="read_secret",
                title="Read secret",
                description="Read a stored secret.",
                input_schema={"type": "object"},
                output_schema=None,
                definition={"name": "read_secret"},
            ),
            MCPTool(
                name="write_secret",
                title=None,
                description="Write a stored secret.",
                input_schema={"type": "object"},
                output_schema=None,
                definition={"name": "write_secret"},
            ),
        ),
    )
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await flow.async_step_mcp_tools()

    assert result == {"type": "form"}
    call = flow.async_show_form.call_args.kwargs
    assert call["step_id"] == "mcp_tools"
    assert call["description_placeholders"] == {
        "server_name": "Vault Server",
        "tool_count": "2",
    }
    schema = call["data_schema"].schema
    assert _schema_keys(schema) == {
        CONF_MCP_PERMANENT_TOOL_EXPOSURE,
        CONF_MCP_PERMANENT_TOOLS,
        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS,
        CONF_MCP_ON_DEMAND_DISCOVERY,
        CONF_MCP_REGEX_TIMEOUT,
    }
    permanent_tools = next(
        selector
        for marker, selector in schema.items()
        if getattr(marker, "schema", marker) == CONF_MCP_PERMANENT_TOOLS
    )
    assert permanent_tools.config["multiple"] is True
    assert permanent_tools.config["options"] == [
        {"value": "read_secret", "label": "Read secret"},
        {"value": "write_secret", "label": "write_secret"},
    ]


async def test_mcp_tools_submission_returns_to_menu_and_review_unlocks_save(hass):
    """Tool settings return to the menu, then review unlocks Save."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
        description="Storage tools",
    )
    flow._mcp_discovery = MCPDiscoveryResult(
        server=MCPServerInformation(
            name="Vault Server",
            version="1.0.0",
            protocol_version="2025-06-18",
            instructions=None,
            capabilities={},
        ),
        tools=(
            MCPTool(
                name="read_secret",
                title="Read secret",
                description="Read a stored secret.",
                input_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                },
                output_schema=None,
                definition={"name": "read_secret"},
            ),
        ),
    )
    flow.async_step_service_menu = AsyncMock(return_value={"type": "menu"})
    selection = {
        CONF_MCP_PERMANENT_TOOL_EXPOSURE: True,
        CONF_MCP_PERMANENT_TOOLS: ["read_secret"],
        CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: True,
        CONF_MCP_ON_DEMAND_DISCOVERY: True,
        CONF_MCP_REGEX_TIMEOUT: 0.1,
    }

    result = await flow.async_step_mcp_tools(selection)

    assert result == {"type": "menu"}
    assert flow._mcp_options == selection
    flow.async_step_service_menu.assert_awaited_once_with()

    flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await flow.async_step_mcp_review()

    assert result == {"type": "form"}
    call = flow.async_show_form.call_args.kwargs
    assert call["step_id"] == "mcp_review"
    placeholders = call["description_placeholders"]
    assert placeholders["permanent_exposure"] == "Yes"
    assert placeholders["selected_tool_count"] == "1"
    assert placeholders["schemas_included"] == "Yes"
    assert placeholders["on_demand_discovery"] == "Yes"
    assert placeholders["regex_timeout"] == "0.1"
    assert int(placeholders["character_count"].replace(",", "")) > 0
    assert int(placeholders["byte_count"].replace(",", "")) > 0
    assert int(placeholders["estimated_tokens"].replace(",", "")) > 0
    flow.async_step_service_menu.reset_mock()

    result = await flow.async_step_mcp_review({})

    assert result == {"type": "menu"}
    assert flow._reviewed_revision == flow._draft_revision
    flow.async_step_service_menu.assert_awaited_once_with()

    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    result = await flow.async_step_service_save()

    assert result == {"type": "create_entry"}
    flow.async_create_entry.assert_called_once_with(
        title="Vault MCP",
        data={
            **flow._mcp_service_config.to_dict(),
            CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        },
    )


async def test_mcp_skip_configuration_can_be_reviewed_and_saved(hass):
    """Skipped discovery can be reviewed and saved without permanent tools."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow._mcp_discovery = None
    flow.async_step_service_menu = AsyncMock(return_value={"type": "menu"})

    await flow.async_step_mcp_options(
        {
            CONF_MCP_ON_DEMAND_DISCOVERY: True,
            CONF_MCP_REGEX_TIMEOUT: 0.1,
        }
    )

    await flow.async_step_mcp_review({})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    result = await flow.async_step_service_save()

    assert result == {"type": "create_entry"}
    entry_data = flow.async_create_entry.call_args.kwargs["data"]
    assert entry_data[CONF_SERVICE_TYPE] == SERVICE_TYPE_MCP
    assert entry_data[CONF_MCP_PERMANENT_TOOLS] == []
    assert entry_data["permanent_tool_catalogue"] == []


async def test_mcp_tools_rejects_tool_outside_discovered_catalogue(hass):
    """Crafted tool selections cannot escape the discovered catalogue."""
    flow = _config_flow(hass)
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow._mcp_discovery = MCPDiscoveryResult(
        server=MCPServerInformation(
            name="Vault Server",
            version="1.0.0",
            protocol_version="2025-06-18",
            instructions=None,
            capabilities={},
        ),
        tools=(),
    )
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await flow.async_step_mcp_tools(
        {
            CONF_MCP_PERMANENT_TOOL_EXPOSURE: True,
            CONF_MCP_PERMANENT_TOOLS: ["not_advertised"],
            CONF_MCP_INCLUDE_PERMANENT_SCHEMAS: True,
            CONF_MCP_ON_DEMAND_DISCOVERY: True,
            CONF_MCP_REGEX_TIMEOUT: 0.1,
        }
    )

    assert result == {"type": "form"}
    assert flow._mcp_service_config is None
    assert flow.async_show_form.call_args.kwargs["step_id"] == "mcp_tools"
    assert flow.async_show_form.call_args.kwargs["errors"] == {
        CONF_MCP_PERMANENT_TOOLS: "invalid_permanent_tools"
    }


async def test_mcp_discover_failure_returns_to_menu_for_retry_or_skip(hass):
    """Failed discovery returns to the menu without losing server data."""
    flow = _config_flow(hass)
    flow._selected_service_type = SERVICE_TYPE_MCP
    config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow._mcp_config = config
    flow.async_step_service_menu = AsyncMock(return_value={"type": "menu"})

    with patch(
        "custom_components.extended_openai_conversation.config_flow."
        "MCPClientConfigFlow.discover",
        new=AsyncMock(side_effect=Exception("Discovery failed")),
    ) as mock_discover:
        result = await flow.async_step_mcp_perform_discovery()

    assert result == {"type": "menu"}
    mock_discover.assert_awaited_once_with(config)
    assert flow._mcp_config is config
    assert flow._mcp_discovery is None
    assert flow._workflow_status == "Unable to retrieve tools from the MCP server."
    flow.async_step_service_menu.assert_awaited_once_with()


async def test_mcp_skip_discovery_does_not_connect_and_opens_options(hass):
    """Skipping discovery makes no request and continues to MCP options."""
    flow = _config_flow(hass)
    flow._mcp_config = MCPServerConfig(
        name="Vault MCP",
        server_id="vault",
        url="https://mcp.example.com/api",
    )
    flow.async_step_mcp_options = AsyncMock(return_value={"step_id": "mcp_options"})

    with patch(
        "custom_components.extended_openai_conversation.config_flow."
        "MCPClientConfigFlow.discover",
        new=AsyncMock(),
    ) as mock_discover:
        result = await flow.async_step_mcp_skip_discovery()

    assert result == {"step_id": "mcp_options"}
    mock_discover.assert_not_awaited()
    assert flow._mcp_discovery is None
    flow.async_step_mcp_options.assert_awaited_once_with()


async def test_mcp_step_rejects_duplicate_server_id(hass):
    """MCP server IDs must be unique across centrally configured services."""
    flow = _config_flow(hass)
    existing_entry = MagicMock()
    existing_entry.data = {
        CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        CONF_MCP_SERVER_ID: "vault",
    }
    hass.config_entries.async_entries.return_value = [existing_entry]
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    await flow.async_step_mcp(
        {
            "name": "Another Vault",
            CONF_MCP_SERVER_ID: "vault",
            CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
            CONF_MCP_HEADERS: {},
        }
    )

    assert flow.async_show_form.call_args.kwargs["errors"] == {
        CONF_MCP_SERVER_ID: "duplicate_server_id"
    }


def test_mcp_services_do_not_support_agent_subentries():
    """MCP services are shared connections, not agent containers."""
    entry = MagicMock()
    entry.data = {CONF_SERVICE_TYPE: SERVICE_TYPE_MCP}

    assert (
        ExtendedOpenAIConversationConfigFlow.async_get_supported_subentry_types(entry)
        == {}
    )


def test_legacy_services_still_support_agent_subentries():
    """Entries without a type maintain the legacy AI endpoint behavior."""
    entry = MagicMock()
    entry.data = {}

    subentry_types = (
        ExtendedOpenAIConversationConfigFlow.async_get_supported_subentry_types(entry)
    )

    assert set(subentry_types) == {"conversation", "ai_task_data"}


async def test_validate_input_calls_get_authenticated_client(hass):
    """A valid config is passed through to get_authenticated_client as-is."""
    with patch(
        "custom_components.extended_openai_conversation.config_flow.get_authenticated_client",
        new=AsyncMock(),
    ) as mock_get_client:
        data = {
            CONF_API_KEY: "sk-test",
            CONF_BASE_URL: "https://my-proxy.example.com",
        }
        await validate_input(hass, data)

    mock_get_client.assert_called_once()
    assert mock_get_client.call_args.kwargs["api_key"] == "sk-test"
    assert (
        mock_get_client.call_args.kwargs["base_url"] == "https://my-proxy.example.com"
    )


async def test_validate_input_clears_default_base_url(hass):
    """The default (OpenAI's own) base_url is popped rather than sent through,
    so future changes to OpenAI's own default URL don't require reconfiguring
    existing entries."""
    with patch(
        "custom_components.extended_openai_conversation.config_flow.get_authenticated_client",
        new=AsyncMock(),
    ) as mock_get_client:
        data = {CONF_API_KEY: "sk-test", CONF_BASE_URL: DEFAULT_CONF_BASE_URL}
        await validate_input(hass, data)

    assert CONF_BASE_URL not in data
    assert mock_get_client.call_args.kwargs["base_url"] is None


async def test_validate_input_azure_without_base_url_raises(hass):
    """Azure OpenAI requires a custom base URL - a missing one is a clear error,
    not a confusing failure from the OpenAI client itself."""
    data = {CONF_API_KEY: "sk-test", CONF_API_PROVIDER: "azure"}

    with pytest.raises(HomeAssistantError, match="Azure OpenAI requires"):
        await validate_input(hass, data)


def test_openai_config_option_schema_includes_core_options():
    """The shared subentry schema includes the expected core option keys,
    given at least one skill is available (see the dedicated test below for
    what happens when none are)."""
    handler = ExtendedOpenAISubentryFlowHandler()
    handler.context = {"source": "user"}

    schema = handler.openai_config_option_schema({}, skills=[{"name": "skill_a"}])

    keys = _schema_keys(schema)
    assert CONF_PROMPT in keys
    assert CONF_CHAT_MODEL in keys
    assert CONF_FUNCTION_TOOLS in keys
    assert CONF_SKILLS in keys


def test_openai_config_option_schema_omits_skills_field_when_none_available():
    """With no skills loaded, the skills selector is dropped from the schema
    entirely (rather than shown as an always-empty dropdown)."""
    handler = ExtendedOpenAISubentryFlowHandler()
    handler.context = {"source": "user"}

    schema = handler.openai_config_option_schema({}, skills=[])

    assert CONF_SKILLS not in _schema_keys(schema)
    # everything else is still there
    assert CONF_PROMPT in _schema_keys(schema)


def test_openai_config_option_schema_defaults_skills_for_new_subentry():
    """A brand-new subentry with no skills option defaults to all loaded skills."""
    handler = ExtendedOpenAISubentryFlowHandler()
    handler.context = {"source": "user"}  # _is_new == True
    skills = [{"name": "skill_a"}, {"name": "skill_b"}]

    schema = handler.openai_config_option_schema({}, skills=skills)

    skills_key = next(k for k in schema if getattr(k, "schema", k) == CONF_SKILLS)
    assert skills_key.default() == ["skill_a", "skill_b"]


def test_openai_config_option_schema_preserves_existing_skills_on_reconfigure():
    """An existing subentry's already-chosen skills aren't silently reset to
    "all skills" on reconfigure."""
    handler = ExtendedOpenAISubentryFlowHandler()
    handler.context = {"source": "reconfigure"}  # _is_new == False
    skills = [{"name": "skill_a"}, {"name": "skill_b"}]

    schema = handler.openai_config_option_schema(
        {CONF_SKILLS: ["skill_a"]}, skills=skills
    )

    skills_key = next(k for k in schema if getattr(k, "schema", k) == CONF_SKILLS)
    assert skills_key.default() == ["skill_a"]
