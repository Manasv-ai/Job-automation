import json, os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-gmail")
def _data():
    return json.load(open(os.environ["FAKE_MAIL"]))

@mcp.tool()
def search_emails(query: str, max_results: int = 25) -> str:
    return json.dumps([{k: m[k] for k in ("id", "from", "subject", "date")} for m in _data()])

@mcp.tool()
def read_email(message_id: str) -> str:
    return json.dumps(next(m for m in _data() if m["id"] == message_id))

if __name__ == "__main__":
    mcp.run(transport="stdio")
