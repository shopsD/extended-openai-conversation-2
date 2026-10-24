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
    CONF_MCP_DESCRIPTION,
    CONF_MCP_HEADERS,
    CONF_MCP_SERVER_ID,
    CONF_MCP_SERVER_URL,
    CONF_PROMPT,
    CONF_SERVICE_TYPE,
    CONF_SKILLS,
    DEFAULT_CONF_BASE_URL,
    SERVICE_TYPE_AI_ENDPOINT,
    SERVICE_TYPE_MCP,
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

    result = await flow.async_step_user(
        {CONF_SERVICE_TYPE: SERVICE_TYPE_AI_ENDPOINT}
    )

    assert result == {"step_id": "ai_endpoint"}
    flow.async_step_ai_endpoint.assert_awaited_once_with()


async def test_user_step_routes_to_mcp(hass):
    """Selecting MCP opens the MCP configuration form."""
    flow = _config_flow(hass)
    flow.async_step_mcp = AsyncMock(return_value={"step_id": "mcp"})

    result = await flow.async_step_user({CONF_SERVICE_TYPE: SERVICE_TYPE_MCP})

    assert result == {"step_id": "mcp"}
    flow.async_step_mcp.assert_awaited_once_with()


async def test_mcp_step_keeps_config_and_opens_discovery(hass):
    """A valid MCP form successfully moves to tool discovery and keeps previous flow data."""
    flow = _config_flow(hass)
    flow.async_step_mcp_discover = AsyncMock(return_value={"step_id": "mcp_discover"})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    user_input = {
        "name": "Vault MCP",
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
        CONF_MCP_DESCRIPTION: "Secure storage tools",
        CONF_MCP_HEADERS: {"Authorization": "Bearer test-token"},
    }

    await flow.async_step_mcp(user_input)
    assert flow._mcp_config is not None
    assert flow._mcp_config.server_id == "vault"
    assert flow._mcp_config.url == "https://mcp.example.com/api"
    flow.async_step_mcp_discover.assert_awaited_once_with()

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
    """Entries without a type retain the legacy AI endpoint behavior."""
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
