"""Wires settings + MCP sessions + graphs together; one function per scheduled task."""
from __future__ import annotations

import contextlib
import logging
import time

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .gmail import InboxReader
from .graphs.application import build_application_graph
from .graphs.discovery import build_discovery_graph
from .graphs.inbox import build_inbox_graph
from .llm import get_llm
from .mcp_hub import open_toolboxes
from .notify import send_text
from .notion import NotionBoard
from .runner import poll_board
from .settings import Settings
from .store import Store

log = logging.getLogger("agent")


@contextlib.asynccontextmanager
async def _ctx(s: Settings, which: tuple[str, ...]):
    s.ensure_dirs()
    async with open_toolboxes(s, which) as boxes:
        board = NotionBoard(boxes["notion"], s.notion_database_id, s.notion_data_source_id)
        yield boxes, board, Store(s.state_db)


async def _timed(store: Store, kind: str, coro):
    t0 = time.time()
    try:
        res = await coro
        store.log_run(kind, t0, True, str(res))
        return res
    except Exception as e:  # noqa: BLE001
        store.log_run(kind, t0, False, f"{type(e).__name__}: {e}")
        raise


async def task_discover(s: Settings | None = None):
    s = s or Settings()
    async with _ctx(s, ("notion",)) as (_, board, store):
        g = build_discovery_graph(board, store, s, notify=send_text)
        return await _timed(store, "discover", g.ainvoke({}))


async def task_poll(s: Settings | None = None):
    s = s or Settings()
    from db import get_job, init_db

    init_db()
    async with _ctx(s, ("notion",)) as (_, board, store):
        async with AsyncSqliteSaver.from_conn_string(s.checkpoint_db) as cp:
            g = build_application_graph(board, store, get_llm(s), s, get_job, cp)
            return await _timed(store, "poll", poll_board(board, store, g, s, send_text))


async def task_inbox(s: Settings | None = None):
    s = s or Settings()
    async with _ctx(s, ("notion", "gmail")) as (boxes, board, store):
        g = build_inbox_graph(InboxReader(boxes["gmail"]), board, store, get_llm(s), notify=send_text)
        return await _timed(store, "inbox", g.ainvoke({}))
