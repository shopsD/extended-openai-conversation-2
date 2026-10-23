"""Utilities used by the MCP Client side of the integration"""
from collections.abc import Collection


class MCPUtils:
    @staticmethod
    def generate_server_id(existing_ids: Collection[str], base_id: str = "mcp_server") -> str:
        """Generate a readable server ID that does not collide with existing IDs."""
        candidate = base_id
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{base_id}_{suffix}"
            suffix += 1
        return candidate
