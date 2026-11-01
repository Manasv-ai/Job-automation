"""Holds *persistent* MCP sessions for the duration of a run.

Why not `client.get_tools()` directly? In langchain-mcp-adapters that opens a fresh
session (= spawns a new `npx` process for stdio servers) for EVERY tool call, which is
slow and flaky. Here we open each server once per run and load tools from the session.
"""
from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .settings import ROOT, Settings


def server_configs(s: Settings, which: tuple[str, ...] = ("notion", "gmail")) -> dict[str, dict]:
    cfgs: dict[str, dict] = {}
    if "notion" in which:
        cfgs["notion"] = {
            "transport": "stdio",
            "command": "npx",
            # pin the version: the Notion server changes tool shapes between releases
            "args": ["-y", "@notionhq/notion-mcp-server@2.6.1"],
            "env": {
                "NOTION_TOKEN": s.notion_token,
                "PATH": __import__("os").environ.get("PATH", ""),
            },
        }
    if "gmail" in which:
        cfgs["gmail"] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(ROOT / "mcp_servers" / "gmail_readonly.py")],
            "env": {
                "GMAIL_TOKEN_PATH": s.gmail_token_path,
                "GMAIL_CLIENT_SECRET_PATH": s.gmail_client_secret_path,
                "PATH": __import__("os").environ.get("PATH", ""),
            },
        }
    return cfgs


def parse_tool_result(res: Any) -> Any:
    """MCP tool results arrive as str or a list of content blocks; normalise to JSON/str."""
    if isinstance(res, tuple):  # (content, artifact)
        res = res[0]
    if isinstance(res, list):
        res = "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(getattr(b, "text", b)) for b in res
        )
    if isinstance(res, str):
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            return res
    return res


class ToolBox:
    """Name -> tool lookup with a clear error if a server renamed something."""

    def __init__(self, tools: list):
        self.tools = {t.name: t for t in tools}

    def names(self) -> list[str]:
        return sorted(self.tools)

    async def call(self, name: str, **args: Any) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            raise RuntimeError(
                f"MCP tool '{name}' not found. Available: {self.names()}. "
                "The server probably changed — run `python -m agent doctor`."
            )
        # drop None args so optional params aren't sent as null
        args = {k: v for k, v in args.items() if v is not None}
        try:
            res = await tool.ainvoke(args)
        except Exception as e:  # McpError, ToolException, transport errors -> one exception type
            raise RuntimeError(f"{name} failed: {type(e).__name__}: {e}") from e
        data = parse_tool_result(res)
        # MCP servers report tool failures as *text*, not exceptions. Never let that pass as data
        # (an expired Gmail token must not look like "no new emails").
        if isinstance(data, str) and data.lstrip().lower().startswith(("error", "mcp error")):
            raise RuntimeError(f"{name} failed: {data[:300]}")
        if isinstance(data, dict) and data.get("object") == "error":
            raise RuntimeError(f"{name} failed: {data.get('code')}: {data.get('message')}")
        return data


@contextlib.asynccontextmanager
async def open_toolboxes(s: Settings, which: tuple[str, ...] = ("notion", "gmail"), configs: dict | None = None):
    """Yield {server_name: ToolBox} with live sessions; cleans up on exit."""
    client = MultiServerMCPClient(configs or server_configs(s, which))
    async with contextlib.AsyncExitStack() as stack:
        boxes: dict[str, ToolBox] = {}
        for name in which:
            session = await stack.enter_async_context(client.session(name))
            boxes[name] = ToolBox(await load_mcp_tools(session))
        yield boxes
