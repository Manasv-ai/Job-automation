"""In-memory stand-in for @notionhq/notion-mcp-server (same tool names / arg shapes)."""
import json, uuid
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-notion")
PAGES: dict[str, dict] = {}
BODIES: dict[str, str] = {}


def _store(props: dict) -> dict:
    out = {}
    for k, v in props.items():
        if "title" in v:
            out[k] = {"type": "title", "title": [{"plain_text": x["text"]["content"]} for x in v["title"]]}
        elif "rich_text" in v:
            out[k] = {"type": "rich_text", "rich_text": [{"plain_text": x["text"]["content"]} for x in v["rich_text"]]}
        elif "select" in v:
            out[k] = {"type": "select", "select": {"name": v["select"]["name"]}}
        elif "url" in v:
            out[k] = {"type": "url", "url": v["url"]}
        elif "number" in v:
            out[k] = {"type": "number", "number": v["number"]}
        elif "date" in v:
            out[k] = {"type": "date", "date": v["date"]}
    return out


def _plain(p):
    if not p: return ""
    t = p["type"]
    if t in ("title", "rich_text"): return "".join(x["plain_text"] for x in p[t])
    if t == "select": return p["select"]["name"]
    return ""


def _match(page, f) -> bool:
    if f is None: return True
    if "or" in f: return any(_match(page, x) for x in f["or"])
    val = _plain(page["properties"].get(f["property"]))
    if "select" in f: return val == f["select"]["equals"]
    if "rich_text" in f:
        c = f["rich_text"]
        return val == c["equals"] if "equals" in c else bool(val)
    return False


@mcp.tool(name="API-retrieve-a-database")
def get_db(database_id: str) -> str:
    return json.dumps({"object": "database", "data_sources": [{"id": "ds-1"}]})

@mcp.tool(name="API-update-a-data-source")
def upd_ds(data_source_id: str, properties: dict) -> str:
    return json.dumps({"object": "data_source"})

@mcp.tool(name="API-post-page")
def post_page(parent: dict, properties: dict) -> str:
    pid = str(uuid.uuid4())
    PAGES[pid] = {"id": pid, "properties": _store(properties)}
    return json.dumps({"object": "page", "id": pid})

@mcp.tool(name="API-patch-page")
def patch_page(page_id: str, properties: dict) -> str:
    PAGES[page_id]["properties"].update(_store(properties))
    return json.dumps({"object": "page", "id": page_id})

@mcp.tool(name="API-query-data-source")
def query(data_source_id: str, filter: dict | None = None, start_cursor: str | None = None, page_size: int = 100) -> str:
    return json.dumps({"results": [p for p in PAGES.values() if _match(p, filter)], "has_more": False})

@mcp.tool(name="API-update-page-markdown")
def md(page_id: str, type: str, replace_content: dict) -> str:
    BODIES[page_id] = replace_content["new_str"]
    return json.dumps({"object": "page_markdown"})

# ---- test-only: simulate the human editing Notion ----
@mcp.tool(name="TEST-human-edit")
def human_edit(page_id: str, status: str = "", feedback: str | None = None) -> str:
    props = {}
    if status: props["Status"] = {"select": {"name": status}}
    if feedback is not None: props["Feedback"] = {"rich_text": [{"text": {"content": feedback}}]}
    PAGES[page_id]["properties"].update(_store(props))
    return "ok"

@mcp.tool(name="TEST-boom")
def boom() -> str:
    raise RuntimeError("rate_limited 429")

@mcp.tool(name="TEST-dump")
def dump() -> str:
    return json.dumps({"pages": {i: {k: _plain(v) for k, v in p["properties"].items() if v["type"] != "date"} | {
        k: v["date"]["start"] for k, v in p["properties"].items() if v["type"] == "date"} for i, p in PAGES.items()},
        "bodies": BODIES})

if __name__ == "__main__":
    mcp.run(transport="stdio")
