import json, sys
from pathlib import Path
import pytest
from agent.mcp_hub import open_toolboxes
from agent.notion import NotionBoard
from agent.settings import Settings
from agent.store import Store

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


class ScriptedLLM:
    """Duck-types LangChain's with_structured_output(...).ainvoke(messages)."""
    def __init__(self, fn): self.fn, self.calls = fn, []
    def with_structured_output(self, model):
        outer = self
        class R:
            async def ainvoke(self, messages):
                outer.calls.append(messages)
                return outer.fn(model, messages, len(outer.calls))
        return R()


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.state_db = str(tmp_path / "state.db"); s.checkpoint_db = str(tmp_path / "cp.db")
    s.resume_out_dir = str(tmp_path / "resumes"); s.master_resume = str(ROOT / "resume" / "master_resume.example.json")
    s.notion_database_id = "db-1"; s.max_revision_rounds = 3
    s.ensure_dirs()
    return s


@pytest.fixture
def store(settings):
    return Store(settings.state_db)


@pytest.fixture
def mail_file(tmp_path):
    p = tmp_path / "mail.json"; p.write_text("[]"); return p


@pytest.fixture
async def boxes(mail_file):
    """Sessions are opened/closed inside ONE background task (anyio cancel-scope requirement)."""
    import asyncio
    cfg = {
        "notion": {"transport": "stdio", "command": sys.executable, "args": [str(HERE / "fake_notion_server.py")]},
        "gmail": {"transport": "stdio", "command": sys.executable, "args": [str(HERE / "fake_gmail_server.py")],
                  "env": {"FAKE_MAIL": str(mail_file)}},
    }
    holder, ready, stop = {}, asyncio.Event(), asyncio.Event()

    async def runner():
        async with open_toolboxes(None, ("notion", "gmail"), configs=cfg) as b:
            holder["b"] = b
            ready.set()
            await stop.wait()

    task = asyncio.create_task(runner())
    await asyncio.wait_for(ready.wait(), 60)
    yield holder["b"]
    stop.set()
    await task


@pytest.fixture
def board(boxes):
    return NotionBoard(boxes["notion"], "db-1", min_interval=0)


async def dump(boxes):
    return await boxes["notion"].call("TEST-dump")
