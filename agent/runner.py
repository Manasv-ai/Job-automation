"""Bridges Notion status changes -> LangGraph runs. Safe to call repeatedly (idempotent)."""
from __future__ import annotations

import logging
from typing import Callable

from langgraph.types import Command

log = logging.getLogger("agent.runner")
MAX_FAILS = 3


def _gen(store, job_id: str) -> int:
    return int(store.kv_get(f"gen:{job_id}", "0") or 0)


def _cfg(store, job_id: str) -> dict:
    return {"configurable": {"thread_id": f"{job_id}:{_gen(store, job_id)}"}}


async def _resume_or_continue(graph, cfg: dict, decision: dict) -> bool:
    """Resume a paused graph; if it crashed mid-step (not paused) continue from its checkpoint."""
    state = await graph.aget_state(cfg)
    if not state or not state.next:
        return False  # nothing to do (finished or never started)
    paused = any(t.interrupts for t in state.tasks)
    await graph.ainvoke(Command(resume=decision) if paused else None, cfg)
    return True


async def _fail(board, store, row: dict, err: Exception, restore_to: str, notify) -> None:
    n = int(store.kv_get(f"fails:{row['job_id']}", "0") or 0) + 1
    store.kv_set(f"fails:{row['job_id']}", str(n))
    log.exception("job %s failed (%d/%d)", row["job_id"], n, MAX_FAILS)
    if n >= MAX_FAILS:  # poison-pill guard: stop retrying forever
        await board.set_props(row["page_id"], status="Manual", feedback=f"Agent failed {n}x: {err}"[:1900])
        store.set_status(row["job_id"], "Manual", last_error=str(err)[:500])
        if notify:
            notify(f"⚠️ Gave up on {row.get('title')}: {err}")
    else:
        await board.set_props(row["page_id"], status=restore_to)
        store.set_status(row["job_id"], restore_to, last_error=str(err)[:500])


async def poll_board(board, store, app_graph, settings, notify: Callable[[str], bool] | None = None) -> dict:
    stats = {"started": 0, "resumed": 0, "skipped": 0, "recovered": 0}

    # 0. crash recovery: claimed rows that nobody is working on any more
    for r in store.stuck_claims(["Tailoring", "Finalizing"], settings.stuck_minutes * 60):
        back = r.get("claimed_from") or "Apply"
        await board.set_props(r["page_id"], status=back)
        store.set_status(r["job_id"], back)
        stats["recovered"] += 1

    # 1. user chose "Apply" -> start a fresh tailoring run
    for row in await board.query_by_status("Apply"):
        if not row["job_id"] or not store.get_job(row["job_id"]):
            continue
        jid = row["job_id"]
        await board.set_props(row["page_id"], status="Tailoring")      # claim in Notion first
        store.claim(jid, "Tailoring", "Apply")
        store.kv_set(f"gen:{jid}", str(_gen(store, jid) + 1))           # fresh thread
        try:
            await app_graph.ainvoke({"job_id": jid, "page_id": row["page_id"], "rounds": 0}, _cfg(store, jid))
            store.kv_set(f"fails:{jid}", "0")
            stats["started"] += 1
        except Exception as e:  # noqa: BLE001
            await _fail(board, store, row, e, "Apply", notify)

    # 2. user decided on a resume
    for status, claim_as in (("Resume Approved", "Finalizing"), ("Revise", "Tailoring")):
        for row in await board.query_by_status(status):
            jid = row["job_id"]
            if not jid or not store.get_job(jid):
                continue
            decision = {"decision": "approve"} if status == "Resume Approved" else {
                "decision": "revise", "feedback": row["feedback"]}
            await board.set_props(row["page_id"], status=claim_as)
            store.claim(jid, claim_as, status)
            try:
                if await _resume_or_continue(app_graph, _cfg(store, jid), decision):
                    stats["resumed"] += 1
                else:  # no live graph (e.g. data loss) -> don't leave the row hanging
                    await board.set_props(row["page_id"], status="Manual", feedback="No saved agent state for this job; handle manually.")
                    store.set_status(jid, "Manual")
            except Exception as e:  # noqa: BLE001
                await _fail(board, store, row, e, status, notify)

    # 3. skips: just remember (job stays in job_sync so it is never re-suggested)
    for row in await board.query_by_status("Skip"):
        if row["job_id"] and store.get_job(row["job_id"]) and store.get_job(row["job_id"])["status"] != "Skip":
            store.set_status(row["job_id"], "Skip")
            stats["skipped"] += 1
    return stats
