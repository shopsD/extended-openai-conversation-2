"""Home Assistant adapter for MCP OAuth callbacks and persistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import http
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .mcp_client import MCPOAuthStorage

MCP_OAUTH_CALLBACK_PATH = f"/api/{DOMAIN}/mcp_oauth/callback"

_DATA_MCP_OAUTH_ATTEMPTS = f"{DOMAIN}.mcp_oauth_attempts"
_DATA_MCP_OAUTH_CALLBACK_REGISTERED = f"{DOMAIN}.mcp_oauth_callback_registered"
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MCPOAuthAttempt:
    """Coordinate one SDK OAuth exchange with a config-flow external step."""

    flow_id: str
    authorization_url: asyncio.Future[str]
    callback: asyncio.Future[tuple[str, str | None]]
    completion: asyncio.Future[str | None]
    state: str | None = None


def create_mcp_oauth_attempt(flow_id: str) -> MCPOAuthAttempt:
    """Create futures for one interactive OAuth exchange."""
    loop = asyncio.get_running_loop()
    return MCPOAuthAttempt(
        flow_id=flow_id,
        authorization_url=loop.create_future(),
        callback=loop.create_future(),
        completion=loop.create_future(),
    )


def register_mcp_oauth_attempt(
    hass: HomeAssistant, state: str, attempt: MCPOAuthAttempt
) -> None:
    """Register the SDK-generated state so the HTTP callback can find its flow."""
    attempts: dict[str, MCPOAuthAttempt] = hass.data.setdefault(
        _DATA_MCP_OAUTH_ATTEMPTS, {}
    )
    attempt.state = state
    attempts[state] = attempt


def remove_mcp_oauth_attempt(hass: HomeAssistant, attempt: MCPOAuthAttempt) -> None:
    """Remove a completed or failed interactive OAuth exchange."""
    if attempt.state is None:
        return
    attempts: dict[str, MCPOAuthAttempt] = hass.data.get(_DATA_MCP_OAUTH_ATTEMPTS, {})
    attempts.pop(attempt.state, None)


def async_setup_mcp_oauth_callback(hass: HomeAssistant) -> None:
    """Register the unauthenticated OAuth redirect endpoint once."""
    if hass.data.get(_DATA_MCP_OAUTH_CALLBACK_REGISTERED):
        return
    hass.http.register_view(MCPOAuthCallbackView)
    hass.data[_DATA_MCP_OAUTH_CALLBACK_REGISTERED] = True


class MCPOAuthCallbackView(HomeAssistantView):
    """Receive an authorization-server callback for an MCP config flow."""

    requires_auth = False
    url = MCP_OAUTH_CALLBACK_PATH
    name = f"api:{DOMAIN}:mcp_oauth_callback"

    async def get(self, request: web.Request) -> web.Response:
        """Resume the matching OAuth provider and config flow."""
        state = request.query.get("state")
        if state is None:
            return web.Response(text="Missing state parameter", status=400)

        hass: HomeAssistant = request.app[http.KEY_HASS]
        attempts: dict[str, MCPOAuthAttempt] = hass.data.get(
            _DATA_MCP_OAUTH_ATTEMPTS, {}
        )
        attempt = attempts.get(state)
        if attempt is None:
            return web.Response(text="Invalid or expired OAuth state", status=400)

        error = request.query.get("error")
        code = request.query.get("code")
        if error is not None:
            if not attempt.callback.done():
                attempt.callback.set_exception(RuntimeError(error))
        elif code is not None:
            if not attempt.callback.done():
                attempt.callback.set_result((code, state))
        else:
            return web.Response(text="Missing code or error parameter", status=400)

        try:
            oauth_error = await asyncio.wait_for(
                asyncio.shield(attempt.completion), timeout=300
            )
        except TimeoutError:
            oauth_error = "OAuth token exchange timed out."

        await hass.config_entries.flow.async_configure(
            flow_id=attempt.flow_id,
            user_input={"error": oauth_error}
            if oauth_error
            else {"authenticated": True},
        )
        return web.Response(
            headers={"content-type": "text/html"},
            text="<script>window.close()</script>",
        )


async def async_load_mcp_oauth_storage(
    hass: HomeAssistant,
    server_id: str,
    seed: dict[str, Any] | None = None,
    *,
    prefer_seed: bool = False,
) -> MCPOAuthStorage:
    """Load durable OAuth state and persist future SDK updates."""
    store = Store[dict[str, Any]](hass, 1, f"{DOMAIN}.mcp_oauth.{server_id}")
    stored = None if prefer_seed and seed is not None else await store.async_load()
    data = seed if prefer_seed and seed is not None else stored
    if data is None:
        data = seed or {}

    async def async_save(updated: dict[str, Any]) -> None:
        await store.async_save(updated)

    storage = MCPOAuthStorage.from_dict(data, update_callback=async_save)
    if (stored is None and data) or (prefer_seed and seed is not None):
        await store.async_save(storage.to_dict())
    return storage
