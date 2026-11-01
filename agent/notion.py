"""Notion 'job board' operations, executed through the official Notion MCP server tools.

Status ownership (prevents the human and the agent fighting over one dropdown):
  USER sets : Apply, Skip, Resume Approved, Revise, Applied
  AGENT sets: New, Tailoring, Resume Review, Finalizing, Ready to Apply, Assessment,
              Interview, Offer, Rejected, Needs Info, Needs Review, Manual
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .mcp_hub import ToolBox

STATUSES = [
    "New", "Apply", "Skip", "Tailoring", "Resume Review", "Resume Approved", "Revise",
    "Finalizing", "Ready to Apply", "Applied", "Assessment", "Interview", "Offer",
    "Rejected", "Needs Info", "Needs Review", "Manual",
]

SCHEMA = {
    "Company": {"rich_text": {}},
    "Location": {"rich_text": {}},
    "Source": {"select": {}},
    "URL": {"url": {}},
    "Match %": {"number": {"format": "number"}},
    "Key matches": {"rich_text": {}},
    "Gaps": {"rich_text": {}},
    "Posted": {"rich_text": {}},
    "Status": {"select": {"options": [{"name": n} for n in STATUSES]}},
    "Job ID": {"rich_text": {}},
    "Feedback": {"rich_text": {}},
    "Resume file": {"rich_text": {}},
    "Resume URL": {"url": {}},
    "Email update": {"rich_text": {}},
    "Last email": {"date": {}},
    "Interview": {"date": {}},
}

# Real tool names of @notionhq/notion-mcp-server 2.6.x ("API-" + OpenAPI operationId)
T_QUERY = "API-query-data-source"
T_CREATE = "API-post-page"
T_PATCH = "API-patch-page"
T_MARKDOWN = "API-update-page-markdown"
T_GET_DB = "API-retrieve-a-database"
T_PATCH_DS = "API-update-a-data-source"
REQUIRED_TOOLS = [T_QUERY, T_CREATE, T_PATCH, T_MARKDOWN, T_GET_DB, T_PATCH_DS]


def _rt(text: str) -> dict:
    # Notion caps one rich_text element at 2000 chars
    return {"rich_text": [{"type": "text", "text": {"content": (text or "")[:2000]}}]}


def _title(text: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": (text or "")[:2000]}}]}


def _plain(prop: dict | None) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in prop.get(t, []))
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "url":
        return prop.get("url") or ""
    if t == "number":
        return str(prop.get("number") or "")
    if t == "date":
        return (prop.get("date") or {}).get("start", "") or ""
    return ""


def simplify_page(page: dict) -> dict:
    p = page.get("properties", {})
    return {
        "page_id": page["id"],
        "job_id": _plain(p.get("Job ID")),
        "status": _plain(p.get("Status")),
        "title": _plain(p.get("Name")),
        "company": _plain(p.get("Company")),
        "feedback": _plain(p.get("Feedback")),
        "url": _plain(p.get("URL")),
    }


class NotionBoard:
    def __init__(self, tools: ToolBox, database_id: str, data_source_id: str = "", min_interval: float = 0.4):
        self.t = tools
        self.database_id = database_id
        self.data_source_id = data_source_id
        self._interval = min_interval  # Notion averages ~3 req/s
        self._last = 0.0
        self._parent_style: str | None = None

    async def _call(self, name: str, **args) -> Any:
        for attempt in range(4):
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            try:
                return await self.t.call(name, **args)
            except RuntimeError as e:
                msg = str(e).lower()
                if ("rate" in msg or "429" in msg or "conflict" in msg or "502" in msg or "503" in msg) and attempt < 3:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                raise

    # ---- setup ----------------------------------------------------------
    async def resolve_data_source(self) -> str:
        if self.data_source_id:
            return self.data_source_id
        db = await self._call(T_GET_DB, database_id=self.database_id)
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError("Database has no data_sources; is the integration connected to it?")
        self.data_source_id = sources[0]["id"]
        return self.data_source_id

    async def ensure_schema(self) -> None:
        ds = await self.resolve_data_source()
        await self._call(T_PATCH_DS, data_source_id=ds, properties=SCHEMA)

    # ---- reads ----------------------------------------------------------
    async def query(self, filter_: dict | None = None) -> list[dict]:
        ds = await self.resolve_data_source()
        out: list[dict] = []
        cursor = None
        while True:
            res = await self._call(T_QUERY, data_source_id=ds, filter=filter_, start_cursor=cursor, page_size=100)
            out.extend(simplify_page(p) for p in res.get("results", []))
            if not res.get("has_more"):
                return out
            cursor = res.get("next_cursor")

    async def query_by_status(self, status: str) -> list[dict]:
        return await self.query({"property": "Status", "select": {"equals": status}})

    async def find_by_job_id(self, job_id: str) -> dict | None:
        rows = await self.query({"property": "Job ID", "rich_text": {"equals": job_id}})
        return rows[0] if rows else None

    # ---- writes ---------------------------------------------------------
    async def create_job(self, job: dict, status: str = "New", source: str | None = None) -> str:
        """Idempotent: checks Notion for the Job ID first (guards against crash-after-create)."""
        existing = await self.find_by_job_id(job["id"])
        if existing:
            return existing["page_id"]
        score = float(job.get("match_score") or 0)
        props = {
            "Name": _title(f"{job.get('title', '')} @ {job.get('company', '')}"),
            "Company": _rt(job.get("company", "")),
            "Location": _rt(job.get("location", "")),
            "Source": {"select": {"name": (source or str(job.get("site") or "unknown")).title()}},
            "Match %": {"number": round(score * 100)},
            "Key matches": _rt(job.get("key_matches", "")),
            "Gaps": _rt(job.get("missing_skills", "")),
            "Posted": _rt(str(job.get("date_posted") or "")),
            "Status": {"select": {"name": status}},
            "Job ID": _rt(job["id"]),
        }
        if str(job.get("job_url") or "").startswith("http"):
            props["URL"] = {"url": job["job_url"]}

        # 2025-09-03+ API prefers a data_source parent; older single-source DBs accept database_id.
        styles = [self._parent_style] if self._parent_style else ["data_source_id", "database_id"]
        last_err: Exception | None = None
        for style in styles:
            parent = (
                {"type": "data_source_id", "data_source_id": await self.resolve_data_source()}
                if style == "data_source_id"
                else {"type": "database_id", "database_id": self.database_id}
            )
            try:
                res = await self._call(T_CREATE, parent=parent, properties=props)
                self._parent_style = style
                return res["id"]
            except RuntimeError as e:
                last_err = e
        raise RuntimeError(f"Could not create Notion page: {last_err}")

    async def set_props(self, page_id: str, **props: Any) -> None:
        """Friendly property setter: status=..., feedback=..., interview='2026-11-02T10:00:00+05:30'."""
        notion_props: dict = {}
        for k, v in props.items():
            if k == "status":
                notion_props["Status"] = {"select": {"name": v}}
            elif k == "feedback":
                notion_props["Feedback"] = _rt(v)
            elif k == "resume_file":
                notion_props["Resume file"] = _rt(v)
            elif k == "resume_url":
                if v:
                    notion_props["Resume URL"] = {"url": v}
            elif k == "email_update":
                notion_props["Email update"] = _rt(v)
            elif k == "last_email":
                notion_props["Last email"] = {"date": {"start": v}}
            elif k == "interview":
                notion_props["Interview"] = {"date": {"start": v}}
            elif k == "gaps":
                notion_props["Gaps"] = _rt(v)
            else:
                raise KeyError(f"Unknown property key: {k}")
        await self._call(T_PATCH, page_id=page_id, properties=notion_props)

    async def set_body(self, page_id: str, markdown: str) -> None:
        await self._call(
            T_MARKDOWN, page_id=page_id,
            type="replace_content", replace_content={"new_str": markdown, "allow_deleting_content": False},
        )
