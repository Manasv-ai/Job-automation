"""Graph 1 — discover -> select new high-match jobs -> push to Notion.

Deterministic on purpose: no LLM here. Each node tolerates partial failure so one bad
scraper or one Notion hiccup doesn't lose the whole run.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

log = logging.getLogger("agent.discovery")


class DiscoveryState(TypedDict, total=False):
    discover_error: str
    candidates: list[dict]
    pushed: int
    push_errors: list[str]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _default_run_discovery() -> None:
    from config_loader import load_config
    from discovery import run_discovery

    run_discovery(load_config())


def _default_candidates(min_score: float, limit: int) -> list[dict]:
    from db import init_db, list_candidate_jobs

    init_db()
    return list_candidate_jobs(min_score, limit)


def _default_threshold() -> float:
    from config_loader import load_config

    return float(load_config()["search_criteria"].get("min_match_threshold", 0.75))


def build_discovery_graph(
    board,
    store,
    settings,
    run_discovery: Callable[[], None] = _default_run_discovery,
    list_candidates: Callable[[float, int], list[dict]] = _default_candidates,
    threshold: Callable[[], float] = _default_threshold,
    notify: Callable[[str], bool] | None = None,
):
    async def discover(state: DiscoveryState) -> DiscoveryState:
        try:
            await asyncio.to_thread(run_discovery)
            return {}
        except Exception as e:  # noqa: BLE001 - keep going with what's already in the DB
            log.exception("discovery failed")
            return {"discover_error": f"{type(e).__name__}: {e}"}

    async def select(state: DiscoveryState) -> DiscoveryState:
        known = store.known_job_ids()
        rows = list_candidates(threshold(), settings.max_new_jobs_per_run * 4)
        seen_keys: set[str] = store.known_dedupe_keys()  # same role cross-posted on other boards / earlier days
        out = []
        for r in rows:
            if r["id"] in known:
                continue
            key = _norm(r.get("company", "")) + "|" + _norm(r.get("title", ""))
            if key in seen_keys:
                continue
            r["_dedupe_key"] = key
            seen_keys.add(key)
            out.append(r)
            if len(out) >= settings.max_new_jobs_per_run:
                break
        return {"candidates": out}

    async def push(state: DiscoveryState) -> DiscoveryState:
        pushed, errors = 0, []
        for job in state.get("candidates", []):
            try:
                page_id = await board.create_job(job, status="New")
                store.upsert_job(job["id"], page_id, "New", job.get("_dedupe_key"))
                pushed += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{job.get('title')}: {e}")
        return {"pushed": pushed, "push_errors": errors}

    async def report(state: DiscoveryState) -> DiscoveryState:
        msg = f"Job discovery: {state.get('pushed', 0)} new jobs added to Notion."
        if state.get("discover_error"):
            msg += f"\nScrape problem: {state['discover_error']}"
        if state.get("push_errors"):
            msg += f"\n{len(state['push_errors'])} Notion errors, first: {state['push_errors'][0]}"
        if notify and (state.get("pushed") or state.get("discover_error") or state.get("push_errors")):
            notify(msg)
        return {}

    g = StateGraph(DiscoveryState)
    for name, fn in (("discover", discover), ("select", select), ("push", push), ("report", report)):
        g.add_node(name, fn)
    g.add_edge(START, "discover")
    g.add_edge("discover", "select")
    g.add_edge("select", "push")
    g.add_edge("push", "report")
    g.add_edge("report", END)
    return g.compile()
