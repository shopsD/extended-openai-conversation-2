"""Framework-independent MCP OAuth helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from .config import MCPServerConfig
from .mcp_const import (
    CONF_MCP_OAUTH_CLIENT_INFO,
    CONF_MCP_OAUTH_REDIRECT_URI,
    CONF_MCP_OAUTH_TOKENS,
)

type OAuthStorageUpdateCallback = Callable[[dict[str, Any]], Awaitable[None]]


class MCPOAuthStorage(TokenStorage):
    """Store serializable OAuth tokens and dynamic client registration data."""

    def __init__(
        self,
        *,
        tokens: OAuthToken | None = None,
        client_info: OAuthClientInformationFull | None = None,
        redirect_uri: str | None = None,
        update_callback: OAuthStorageUpdateCallback | None = None,
    ) -> None:
        """Initialize OAuth storage."""
        self.tokens = tokens
        self.client_info = client_info
        self.redirect_uri = redirect_uri
        self._update_callback = update_callback

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        update_callback: OAuthStorageUpdateCallback | None = None,
    ) -> MCPOAuthStorage:
        """Restore OAuth state from a host-owned mapping."""
        tokens = data.get(CONF_MCP_OAUTH_TOKENS)
        client_info = data.get(CONF_MCP_OAUTH_CLIENT_INFO)
        redirect_uri = data.get(CONF_MCP_OAUTH_REDIRECT_URI)
        return cls(
            tokens=(
                OAuthToken.model_validate(tokens)
                if isinstance(tokens, Mapping)
                else None
            ),
            client_info=(
                OAuthClientInformationFull.model_validate(client_info)
                if isinstance(client_info, Mapping)
                else None
            ),
            redirect_uri=redirect_uri if isinstance(redirect_uri, str) else None,
            update_callback=update_callback,
        )

    @property
    def is_authenticated(self) -> bool:
        """Return whether an access token is available."""
        return self.tokens is not None and bool(self.tokens.access_token)

    async def get_tokens(self) -> OAuthToken | None:
        """Return stored OAuth tokens."""
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Persist updated OAuth tokens."""
        self.tokens = tokens
        await self._async_updated()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Return stored dynamic client registration information."""
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Persist dynamic client registration information."""
        self.client_info = client_info
        await self._async_updated()

    def to_dict(self) -> dict[str, Any]:
        """Return serializable OAuth state."""
        data: dict[str, Any] = {}
        if self.tokens is not None:
            data[CONF_MCP_OAUTH_TOKENS] = self.tokens.model_dump(
                mode="json", exclude_none=True
            )
        if self.client_info is not None:
            data[CONF_MCP_OAUTH_CLIENT_INFO] = self.client_info.model_dump(
                mode="json", exclude_none=True
            )
        if self.redirect_uri is not None:
            data[CONF_MCP_OAUTH_REDIRECT_URI] = self.redirect_uri
        return data

    async def _async_updated(self) -> None:
        if self._update_callback is not None:
            await self._update_callback(self.to_dict())


def create_mcp_oauth_provider(
    config: MCPServerConfig,
    storage: MCPOAuthStorage,
    *,
    redirect_uri: str,
    redirect_handler: Callable[[str], Awaitable[None]] | None = None,
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
) -> OAuthClientProvider:
    """Create the SDK OAuth provider for one MCP server."""
    storage.redirect_uri = redirect_uri
    return OAuthClientProvider(
        server_url=config.url,
        client_metadata=OAuthClientMetadata(
            client_name=config.name,
            redirect_uris=[AnyUrl(redirect_uri)],
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
