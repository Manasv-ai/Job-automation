from __future__ import annotations

from .mcp_hub import ToolBox


class InboxReader:
    """Thin wrapper over the read-only Gmail MCP server tools."""

    def __init__(self, tools: ToolBox):
        self.t = tools

    async def search(self, query: str, max_results: int = 25) -> list[dict]:
        res = await self.t.call("search_emails", query=query, max_results=max_results)
        return res if isinstance(res, list) else []

    async def read(self, message_id: str) -> dict:
        res = await self.t.call("read_email", message_id=message_id)
        if not isinstance(res, dict):
            raise RuntimeError(f"unexpected read_email result for {message_id}")
        return res
