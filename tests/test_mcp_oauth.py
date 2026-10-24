"""Tests for the Home Assistant MCP OAuth adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.extended_openai_conversation.mcp_oauth import (
    MCPOAuthCallbackView,
    async_load_mcp_oauth_storage,
    create_mcp_oauth_attempt,
    register_mcp_oauth_attempt,
)
from homeassistant.helpers import http


async def test_oauth_callback_resumes_sdk_and_config_flow(hass):
    """A valid state delivers the code and resumes the external flow step."""
    attempt = create_mcp_oauth_attempt("flow-id")
    register_mcp_oauth_attempt(hass, "oauth-state", attempt)
    attempt.completion.set_result(None)
    hass.config_entries.flow.async_configure = AsyncMock()
    request = MagicMock()
    request.query = {"state": "oauth-state", "code": "authorization-code"}
    request.app = {http.KEY_HASS: hass}

    response = await MCPOAuthCallbackView().get(request)

    assert response.status == 200
    assert await attempt.callback == ("authorization-code", "oauth-state")
    hass.config_entries.flow.async_configure.assert_awaited_once_with(
        flow_id="flow-id",
        user_input={"authenticated": True},
    )


async def test_oauth_callback_rejects_unknown_state(hass):
    """Callbacks cannot resume a flow without its unguessable SDK state."""
    request = MagicMock()
    request.query = {"state": "unknown", "code": "authorization-code"}
    request.app = {http.KEY_HASS: hass}

    response = await MCPOAuthCallbackView().get(request)

    assert response.status == 400


async def test_oauth_storage_can_replace_stale_credentials(hass):
    """A changed server connection must not restore its previous tokens."""
    store = MagicMock()
    store.async_load = AsyncMock(
        return_value={"oauth_tokens": {"access_token": "old", "token_type": "bearer"}}
    )
    store.async_save = AsyncMock()

    class FakeStore:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __new__(cls, *args, **kwargs):
            return store

    with patch(
        "custom_components.extended_openai_conversation.mcp_oauth.Store",
        FakeStore,
    ):
        replacement = await async_load_mcp_oauth_storage(
            hass,
            "server",
            {},
            prefer_seed=True,
        )

    assert not replacement.is_authenticated
    store.async_load.assert_not_awaited()
    store.async_save.assert_awaited_once_with({})
