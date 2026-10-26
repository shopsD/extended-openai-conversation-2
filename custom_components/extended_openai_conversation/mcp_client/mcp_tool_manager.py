"""Search MCP servers without host-framework dependencies."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any

import regex

from .mcp_datatypes import MCPTool
from .mcp_service import MCPService
from .service_config import MCPServiceConfig

_DEFAULT_ENTRIES_PER_PAGE = 20
_MAX_ENTRIES_PER_PAGE = 100
_SERVER_SEARCH_FIELDS = frozenset(
    {"server_id", "server_name", "tool_name", "description", "schema"}
)
_TOOL_SEARCH_FIELDS = frozenset({"tool_name", "description", "schema"})
_SCHEMA_BOILERPLATE_KEYS = frozenset(
    {
        "$defs",
        "$schema",
        "additionalProperties",
        "allOf",
        "anyOf",
        "definitions",
        "items",
        "oneOf",
        "properties",
        "required",
        "type",
    }
)


class MCPToolManager:
    """Implement model-facing MCP operations over authorized service inputs."""

    @staticmethod
    async def list_servers(
        services: Collection[MCPService],
        *,
        query: str | None = None,
        search_fields: Collection[str] | None = None,
        search_regex: bool = False,
        search_case_sensitive: bool = False,
        include_tools: bool = False,
        all_tools: bool = False,
        current_page: int = 1,
        entries_per_page: int = _DEFAULT_ENTRIES_PER_PAGE,
    ) -> dict[str, Any]:
        """Return authorized MCP servers matching the requested criteria."""

        validation_error: dict[str, Any] | None = MCPToolManager._validate_list_request(
            query=query,
            search_fields=search_fields,
            current_page=current_page,
            entries_per_page=entries_per_page,
        )
        if validation_error is not None:
            return validation_error

        try:
            fields, pattern = MCPToolManager._prepare_search(
                search_fields=search_fields,
                query=query,
                search_regex=search_regex,
                search_case_sensitive=search_case_sensitive,
            )
        except regex.error as err:
            return MCPToolManager._error("invalid_regex", str(err))

        matches: list[dict[str, Any]] = []
        try:
            for service in services:
                server_matches, tools, matching_tools = (
                    await MCPToolManager._match_server(
                        service,
                        query=query,
                        fields=fields,
                        pattern=pattern,
                        search_case_sensitive=search_case_sensitive,
                        include_tools=include_tools,
                    )
                )
                if not server_matches and not matching_tools:
                    continue
                matches.append(
                    MCPToolManager._build_server_result(
                        service.config,
                        query=query,
                        server_matches=server_matches,
                        tools=tools,
                        matching_tools=matching_tools,
                        include_tools=include_tools,
                        all_tools=all_tools,
                    )
                )
        except TimeoutError:
            return MCPToolManager._error("regex_timeout", "The MCP catalogue search timed out")

        return MCPToolManager._paginate(
            matches,
            result_key="servers",
            current_page=current_page,
            entries_per_page=entries_per_page,
        )

    @staticmethod
    def _prepare_search(
        *,
        search_fields: Collection[str] | None,
        query: str | None,
        search_regex: bool,
        search_case_sensitive: bool,
    ) -> tuple[frozenset[str], regex.Pattern[str] | None]:
        """Resolve default fields and compile an optional search expression."""
        fields = (
            frozenset(search_fields) if search_fields is not None else _SERVER_SEARCH_FIELDS
        )
        if query is None or not search_regex:
            return fields, None
        flags = 0 if search_case_sensitive else regex.IGNORECASE
        return fields, regex.compile(query, flags)

    @staticmethod
    async def _match_server(
        service: MCPService,
        *,
        query: str | None,
        fields: Collection[str],
        pattern: regex.Pattern[str] | None,
        search_case_sensitive: bool,
        include_tools: bool,
    ) -> tuple[bool, tuple[MCPTool, ...], tuple[MCPTool, ...]]:
        """Evaluate server metadata and eligible tools against one search."""

        server_matches = query is None or MCPToolManager._matches(
            MCPToolManager._server_search_values(service.config, fields),
            query,
            pattern=pattern,
            case_sensitive=search_case_sensitive,
            timeout=service.config.regex_timeout,
        )
        requires_tools = include_tools or (
            query is not None and bool(set(fields) & _TOOL_SEARCH_FIELDS)
        )
        tools: tuple[MCPTool, ...] = (
            await MCPToolManager._discoverable_tools(service) if requires_tools else ()
        )
        matching_tools = (
            tools
            if query is None else tuple(
                tool
                for tool in tools
                if MCPToolManager._matches(
                    MCPToolManager._tool_search_values(tool, fields),
                    query,
                    pattern=pattern,
                    case_sensitive=search_case_sensitive,
                    timeout=service.config.regex_timeout,
                )
            )
        )
        return server_matches, tools, matching_tools

    @staticmethod
    def _build_server_result(
        config: MCPServiceConfig,
        *,
        query: str | None,
        server_matches: bool,
        tools: tuple[MCPTool, ...],
        matching_tools: tuple[MCPTool, ...],
        include_tools: bool,
        all_tools: bool,
    ) -> dict[str, Any]:
        """Build one model-facing server result after matching is complete."""
        server = config.server
        result: dict[str, Any] = {
            "id": server.server_id,
            "name": server.name,
            "description": server.description,
        }
        if not include_tools:
            return result

        returned_tools = tools if query is None or all_tools else matching_tools
        result["tools"] = [
            MCPToolManager._tool_summary(tool) for tool in returned_tools
        ]
        if query is not None and server_matches and not matching_tools:
            result["tool_match_message"] = (
                "Server metadata matched, but no discoverable tools matched the "
                "criteria. Try searching without tool fields or list all tools."
            )
        return result

    @staticmethod
    def _paginate(
        items: Sequence[dict[str, Any]],
        *,
        result_key: str,
        current_page: int,
        entries_per_page: int,
    ) -> dict[str, Any]:
        """Return one result page with consistent pagination metadata."""
        max_matches = len(items)
        max_pages = (
            (max_matches + entries_per_page - 1) // entries_per_page
            if max_matches
            else 0
        )
        start = (current_page - 1) * entries_per_page
        return {
            result_key: list(items[start : start + entries_per_page]),
            "max_matches": max_matches,
            "current_page": current_page,
            "max_pages": max_pages,
            "entries_per_page": entries_per_page,
        }

    @staticmethod
    async def _discoverable_tools(service: MCPService) -> tuple[MCPTool, ...]:
        """Return live, policy-filtered tools that are not exposed permanently."""
        if not service.config.on_demand_discovery:
            return ()
        return service.config.filter_on_demand_tools(await service.client.list_tools())

    @staticmethod
    def _server_search_values(config: MCPServiceConfig, fields: Collection[str]) -> tuple[str, ...]:
        """Return selected searchable values from server metadata."""
        server = config.server
        values: list[str] = []
        if "server_id" in fields:
            values.append(server.server_id)
        if "server_name" in fields:
            values.append(server.name)
        if "description" in fields:
            values.append(server.description)
        return tuple(values)

    @staticmethod
    def _tool_search_values(tool: MCPTool, fields: Collection[str]) -> tuple[str, ...]:
        """Return selected searchable values from one tool definition."""
        values: list[str] = []
        if "tool_name" in fields:
            values.append(tool.name)
        if "description" in fields and tool.description is not None:
            values.append(tool.description)
        if "schema" in fields:
            values.extend(MCPToolManager._schema_search_values(tool.input_schema))
        return tuple(values)

    @staticmethod
    def _schema_search_values(value: Any) -> tuple[str, ...]:
        """Extract meaningful searchable values from a JSON schema."""
        values: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in _SCHEMA_BOILERPLATE_KEYS:
                    values.append(str(key))
                if key != "type":
                    values.extend(MCPToolManager._schema_search_values(child))
        elif isinstance(value, list):
            for child in value:
                values.extend(MCPToolManager._schema_search_values(child))
        elif isinstance(value, (str, int, float, bool)):
            values.append(str(value))
        return tuple(values)

    @staticmethod
    def _matches(
        values: Iterable[str],
        query: str,
        *,
        pattern: regex.Pattern[str] | None,
        case_sensitive: bool,
        timeout: float,
    ) -> bool:
        """Return whether any independently searched field matches the query."""
        if pattern is not None:
            return any(pattern.search(value, timeout=timeout) is not None for value in values)
        if not case_sensitive:
            query = query.casefold()
            return any(query in value.casefold() for value in values)
        return any(query in value for value in values)

    @staticmethod
    def _tool_summary(tool: MCPTool) -> dict[str, Any]:
        """Return the compact tool representation used by list_servers."""
        return {"tool_name": tool.name, "description": tool.description}

    @staticmethod
    def _validate_list_request(
        *,
        query: str | None,
        search_fields: Collection[str] | None,
        current_page: int,
        entries_per_page: int,
    ) -> dict[str, Any] | None:
        """Validate list_servers arguments and return a structured error."""
        if query is not None and not isinstance(query, str):
            return MCPToolManager._error("invalid_query", "query must be a string")
        if search_fields is not None:
            if (
                isinstance(search_fields, str)
                or not search_fields
                or not all(isinstance(field, str) for field in search_fields)
            ):
                return MCPToolManager._error("invalid_search_fields", "search_fields must be a non-empty list")
            invalid_fields = set(search_fields) - _SERVER_SEARCH_FIELDS
            if invalid_fields:
                return MCPToolManager._error(
                    "invalid_search_fields",
                    f"Unsupported search fields: {', '.join(sorted(invalid_fields))}",
                )
        if (
            isinstance(current_page, bool)
            or not isinstance(current_page, int)
            or current_page < 1
        ):
            return MCPToolManager._error("invalid_current_page", "current_page must be at least 1" )
        if (
            isinstance(entries_per_page, bool)
            or not isinstance(entries_per_page, int)
            or entries_per_page < 1
            or entries_per_page > _MAX_ENTRIES_PER_PAGE
        ):
            return MCPToolManager._error(
                "invalid_entries_per_page",
                f"entries_per_page must be between 1 and {_MAX_ENTRIES_PER_PAGE}",
            )
        return None

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        """Return a serializable model-facing error."""
        return {"error": {"code": code, "message": message}}
