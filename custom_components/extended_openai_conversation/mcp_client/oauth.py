"""Framework-independent MCP OAuth metadata discovery."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from mcp.client.auth.oauth2 import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
)
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import ValidationError

from .mcp_errors import MCPAuthenticationError


@dataclass(frozen=True, slots=True)
class MCPOAuthConfiguration:
    """OAuth endpoints and scopes advertised for an MCP resource."""

    authorization_url: str
    token_url: str
    resource: str
    scopes: tuple[str, ...] = ()


async def async_discover_mcp_oauth(
    server_url: str,
    *,
    resource_metadata_url: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> MCPOAuthConfiguration:
    """Discover OAuth metadata using the MCP authorization specification."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(follow_redirects=False)
    try:
        resource_metadata = await _async_discover_resource_metadata(
            client, server_url, resource_metadata_url
        )
        authorization_server = (
            str(resource_metadata.authorization_servers[0])
            if resource_metadata is not None
            and resource_metadata.authorization_servers
            else None
        )
        oauth_metadata = await _async_discover_authorization_metadata(
            client, server_url, authorization_server
        )
    finally:
        if owns_client:
            await client.aclose()

    scopes = (
        resource_metadata.scopes_supported
        if resource_metadata is not None
        and resource_metadata.scopes_supported is not None
        else oauth_metadata.scopes_supported or []
    )
    endpoint_base = authorization_server or server_url
    return MCPOAuthConfiguration(
        authorization_url=urljoin(
            endpoint_base, str(oauth_metadata.authorization_endpoint)
        ),
        token_url=urljoin(endpoint_base, str(oauth_metadata.token_endpoint)),
        resource=server_url,
        scopes=tuple(scopes),
    )


async def _async_discover_resource_metadata(
    client: httpx.AsyncClient,
    server_url: str,
    resource_metadata_url: str | None,
) -> ProtectedResourceMetadata | None:
    """Return the first valid protected-resource metadata response, if any."""
    urls = build_protected_resource_metadata_discovery_urls(
        resource_metadata_url, server_url
    )
    for url in urls:
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        try:
            return ProtectedResourceMetadata.model_validate_json(response.content)
        except ValidationError:
            continue
    return None


async def _async_discover_authorization_metadata(
    client: httpx.AsyncClient,
    server_url: str,
    authorization_server: str | None,
) -> OAuthMetadata:
    """Return authorization-server metadata or raise a useful public error."""
    urls = build_oauth_authorization_server_metadata_discovery_urls(
        authorization_server, server_url
    )
    for url in urls:
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        try:
            return OAuthMetadata.model_validate_json(response.content)
        except ValidationError:
            continue
    raise MCPAuthenticationError("Unable to discover the MCP authorization server")
