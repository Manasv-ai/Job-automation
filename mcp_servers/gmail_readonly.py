"""Minimal READ-ONLY Gmail MCP server (scope: gmail.readonly).

Why custom? The popular community Gmail MCP server requests `gmail.modify` and exposes
send_email / delete_email / batch_delete tools. An agent that reads untrusted email text
should not hold those powers. This server can only search and read.

Run once to authorise:   python -m agent gmail-auth
The MCP client spawns this file over stdio.
"""
from __future__ import annotations

import base64
import json
import os
import re

from mcp.server.fastmcp import FastMCP

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "secrets/gmail_token.json")

mcp = FastMCP("gmail-readonly")


def _service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("Gmail token invalid/expired — re-run `python -m agent gmail-auth`")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _body_text(payload: dict) -> str:
    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime == "text/plain" and data:
            yield base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            yield from walk(sub)

    text = "\n".join(walk(payload))
    if not text:  # HTML-only email: crude strip
        def walk_html(part):
            data = part.get("body", {}).get("data")
            if part.get("mimeType") == "text/html" and data:
                yield base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            for sub in part.get("parts", []) or []:
                yield from walk_html(sub)

        html = "\n".join(walk_html(payload))
        text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


@mcp.tool()
def search_emails(query: str, max_results: int = 25) -> str:
    """Search Gmail using Gmail query syntax. Returns JSON list of {id, from, subject, date, snippet}."""
    svc = _service()
    ids = svc.users().messages().list(userId="me", q=query, maxResults=min(max_results, 50)).execute()
    out = []
    for m in ids.get("messages", []):
        msg = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        h = msg["payload"]["headers"]
        out.append({
            "id": m["id"], "thread_id": msg.get("threadId"),
            "from": _header(h, "From"), "subject": _header(h, "Subject"),
            "date": _header(h, "Date"), "snippet": msg.get("snippet", ""),
        })
    return json.dumps(out)


@mcp.tool()
def read_email(message_id: str) -> str:
    """Read one email. Returns JSON {id, from, subject, date, body} (body truncated to 6000 chars)."""
    svc = _service()
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = msg["payload"]["headers"]
    return json.dumps({
        "id": message_id, "thread_id": msg.get("threadId"),
        "from": _header(h, "From"), "subject": _header(h, "Subject"),
        "date": _header(h, "Date"), "body": _body_text(msg["payload"])[:6000],
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")
