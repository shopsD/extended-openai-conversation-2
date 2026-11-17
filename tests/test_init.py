"""Tests for integration setup and service-type routing."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.extended_openai_conversation import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.extended_openai_conversation.const import (
    CONF_RERANKER,
    CONF_RERANKER_MODEL,
    CONF_RERANKER_URL,
    CONF_SERVICE_TYPE,
    SERVICE_TYPE_MCP,
)
from custom_components.extended_openai_conversation.context_management import (
    RerankerClient,
)
from custom_components.extended_openai_conversation.mcp_client import (
    CONF_MCP_AUTHORIZATION_URL,
    CONF_MCP_SERVER_ID,
    CONF_MCP_SERVER_URL,
    CONF_MCP_TOKEN_URL,
    CONF_MCP_USE_OAUTH,
    MCPClient,
)
from homeassistant.const import CONF_API_KEY, CONF_TOKEN


async def test_mcp_entry_does_not_create_openai_client(hass):
    """Setting up an MCP service must not run AI endpoint authentication."""
    entry = MagicMock()
    entry.data = {
        CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
    }
    entry.title = "Vault MCP"
    entry.add_update_listener.return_value = MagicMock()

    with patch(
        "custom_components.extended_openai_conversation.get_authenticated_client"
    ) as get_authenticated_client:
        assert await async_setup_entry(hass, entry)

    get_authenticated_client.assert_not_called()
    hass.config_entries.async_forward_entry_setups.assert_not_called()
    entry.async_on_unload.assert_called_once()
    assert isinstance(entry.runtime_data, MCPClient)
    assert entry.runtime_data.config.server_id == "vault"


async def test_mcp_oauth_entry_injects_persisted_auth_provider(hass):
    """OAuth MCP entries restore SDK auth without starting a browser flow."""
    entry = MagicMock()
    entry.data = {
        CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
        CONF_MCP_USE_OAUTH: True,
        CONF_MCP_AUTHORIZATION_URL: "https://auth.example.com/authorize",
        CONF_MCP_TOKEN_URL: "https://auth.example.com/token",
        CONF_TOKEN: {"access_token": "access-token"},
    }
    entry.title = "Vault MCP"
    entry.add_update_listener.return_value = MagicMock()
    auth = MagicMock()

    with patch(
        "custom_components.extended_openai_conversation.async_get_mcp_oauth_auth",
        new=AsyncMock(return_value=auth),
    ) as get_auth:
        assert await async_setup_entry(hass, entry)

    get_auth.assert_awaited_once_with(hass, entry)
    assert entry.runtime_data._auth is auth


async def test_mcp_oauth_entry_without_token_still_loads(hass):
    """A deliberately saved incomplete OAuth entry does not crash setup."""
    entry = MagicMock()
    entry.data = {
        CONF_SERVICE_TYPE: SERVICE_TYPE_MCP,
        CONF_MCP_SERVER_ID: "vault",
        CONF_MCP_SERVER_URL: "https://mcp.example.com/api",
        CONF_MCP_USE_OAUTH: True,
    }
    entry.title = "Vault MCP"
    entry.add_update_listener.return_value = MagicMock()

    with patch(
        "custom_components.extended_openai_conversation.async_get_mcp_oauth_auth",
        new=AsyncMock(),
    ) as get_auth:
        assert await async_setup_entry(hass, entry)

    get_auth.assert_not_awaited()
    assert entry.runtime_data._auth is None


async def test_mcp_entry_unloads_without_ai_platforms(hass):
    """Unloading an MCP service must not unload AI endpoint platforms."""
    entry = MagicMock()
    entry.data = {CONF_SERVICE_TYPE: SERVICE_TYPE_MCP}
    entry.runtime_data = MagicMock(aclose=AsyncMock())

    assert await async_unload_entry(hass, entry)

    entry.runtime_data.aclose.assert_awaited_once_with()
    hass.config_entries.async_unload_platforms.assert_not_called()


async def test_ai_entry_creates_configured_reranker_client(hass):
    """AI endpoint setup retains an isolated reranker runtime client."""
    entry = MagicMock()
    entry.data = {
        CONF_API_KEY: "chat-key",
        CONF_RERANKER: {
            CONF_API_KEY: "reranker-key",
            CONF_RERANKER_URL: "https://reranker.example.com/v1/rerank",
            CONF_RERANKER_MODEL: "reranker-model",
        },
    }
    entry.add_update_listener.return_value = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    session = MagicMock()

    with (
        patch(
            "custom_components.extended_openai_conversation."
            "get_authenticated_client",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "custom_components.extended_openai_conversation."
            "async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.extended_openai_conversation."
            "async_setup_templates",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry)

    assert isinstance(entry.runtime_data.reranker_client, RerankerClient)
    assert entry.runtime_data.reranker_client.endpoint_url == (
        "https://reranker.example.com/v1/rerank"
    )
    assert entry.runtime_data.reranker_client.model == "reranker-model"
