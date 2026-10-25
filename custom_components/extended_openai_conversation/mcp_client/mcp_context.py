"""Render and estimate the permanent MCP context supplied to a model."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

from .config import MCPServerConfig
from .mcp_datatypes import MCPTool

DEFAULT_MCP_PROMPT = (
    "Use list_servers to find available MCP servers, list_tools to discover "
    "tools, and execute_tool to run a tool. Use the server_id and tool name "
    "returned by discovery. Tools already supplied in permanent context do not "
    "need to be discovered again."
)


@dataclass(frozen=True, slots=True)
class MCPContextEstimate:
    """Size information for one rendered permanent MCP context block."""

    content: str
    selected_tool_count: int
    character_count: int
    byte_count: int
    estimated_tokens: int

    @staticmethod
    def estimate_permanent_context(
        config: MCPServerConfig,
        tools: tuple[MCPTool, ...],
        *,
        include_schemas: bool,
        include_default_prompt: bool = False,
    ) -> MCPContextEstimate:
        """Render permanent tool context and return its approximate token cost."""
        if not tools and not include_default_prompt:
            return MCPContextEstimate(
                content="",
                selected_tool_count=0,
                character_count=0,
                byte_count=0,
                estimated_tokens=0,
            )

        rendered_tools: list[dict[str, object]] = []
        for tool in sorted(tools, key=lambda item: item.name):
            rendered_tool: dict[str, object] = {
                "name": tool.name,
                "description": tool.description,
            }
            if include_schemas:
                rendered_tool["input_schema"] = tool.input_schema
            rendered_tools.append(rendered_tool)

        context: dict[str, object] = {
            "server_id": config.server_id,
            "server_name": config.name,
            "server_description": config.description,
            "tools": rendered_tools,
        }
        if include_default_prompt:
            context["instructions"] = DEFAULT_MCP_PROMPT

        content = json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        byte_count = len(content.encode("utf-8"))
        return MCPContextEstimate(
            content=content,
            selected_tool_count=len(tools),
            character_count=len(content),
            byte_count=byte_count,
            estimated_tokens=math.ceil(byte_count / 4),
        )
