from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .settings import Settings


async def doctor(s: Settings) -> int:
    from .mcp_hub import open_toolboxes
    from .notion import REQUIRED_TOOLS, NotionBoard
    from .resume.models import load_master

    ok = True

    def check(label: str, good: bool, detail: str = ""):
        nonlocal ok
        ok &= good
        print(f"[{'OK' if good else 'FAIL'}] {label} {detail}")

    check("NOTION_TOKEN set", bool(s.notion_token))
    check("NOTION_DATABASE_ID set", bool(s.notion_database_id))
    try:
        m = load_master(s.master_resume)
        check("master resume parses", True, f"({len(m.skills)} skills, {len(m.bullet_index())} bullets)")
    except Exception as e:  # noqa: BLE001
        check("master resume parses", False, str(e)[:200])
    import os
    check("LLM key present", bool(os.environ.get("ANTHROPIC_API_KEY") or not s.model.startswith("anthropic")), f"(model {s.model})")
    try:
        async with open_toolboxes(s, ("notion", "gmail")) as boxes:
            missing = [t for t in REQUIRED_TOOLS if t not in boxes["notion"].tools]
            check("Notion MCP tools present", not missing, f"missing={missing}" if missing else "")
            check("Gmail MCP tools present", {"search_emails", "read_email"} <= set(boxes["gmail"].tools))
            board = NotionBoard(boxes["notion"], s.notion_database_id, s.notion_data_source_id)
            ds = await board.resolve_data_source()
            check("Notion database reachable", True, f"(data source {ds[:8]}…)")
            try:
                await board.query()
                check("Notion query works", True)
            except Exception as e:  # noqa: BLE001
                check("Notion query works", False, str(e)[:200])
            try:
                await boxes["gmail"].call("search_emails", query="newer_than:1d", max_results=1)
                check("Gmail auth works", True)
            except Exception as e:  # noqa: BLE001
                check("Gmail auth works", False, str(e)[:200])
    except Exception as e:  # noqa: BLE001
        check("MCP servers start (node/npx installed?)", False, f"{type(e).__name__}: {e}"[:300])
    return 0 if ok else 1


def gmail_auth(s: Settings) -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from pathlib import Path

    flow = InstalledAppFlow.from_client_secrets_file(
        s.gmail_client_secret_path, ["https://www.googleapis.com/auth/gmail.readonly"])
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    Path(s.gmail_token_path).parent.mkdir(parents=True, exist_ok=True)
    Path(s.gmail_token_path).write_text(creds.to_json())
    print("Saved", s.gmail_token_path)
    return 0


async def init_notion(s: Settings) -> int:
    from .app import _ctx

    async with _ctx(s, ("notion",)) as (_, board, _store):
        await board.ensure_schema()
    print("Notion schema applied (properties + Status options).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("cmd", choices=["doctor", "init-notion", "gmail-auth", "discover", "poll", "inbox", "run"])
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings()
    from .app import task_discover, task_inbox, task_poll
    from .scheduler import run_forever

    if a.cmd == "gmail-auth":
        return gmail_auth(s)
    table = {"doctor": doctor, "init-notion": init_notion, "discover": task_discover,
             "poll": task_poll, "inbox": task_inbox, "run": run_forever}
    res = asyncio.run(table[a.cmd](s))
    if isinstance(res, int):
        return res
    print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
