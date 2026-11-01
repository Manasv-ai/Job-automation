"""Full human-in-the-loop loop via real MCP plumbing + real LangGraph checkpointing."""
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.graphs.application import build_application_graph
from agent.resume.models import TailoredBullet, TailoredResume, TailoredSection
from agent.runner import poll_board
from tests.conftest import ScriptedLLM, dump

JOB = {"id": "job12345abc", "title": "Associate Product Manager", "company": "Acme Corp", "location": "Bengaluru",
       "site": "linkedin", "job_url": "https://x.io/1", "match_score": 0.82, "key_matches": "SQL", "missing_skills": "Figma",
       "description": "We want an APM comfortable with SQL, analytics and A/B testing. " * 6}


def good(summary):
    return TailoredResume(
        summary=summary, skills_order=["SQL", "Analytics", "A/B Testing"],
        experience=[TailoredSection(id="exp1", bullets=[TailoredBullet(
            source_id="exp1.b1", text="Analysed funnel data in SQL to find a checkout drop-off, informing a fix that lifted conversion by 4%.")])],
        gaps=["Figma"], rationale="Led with SQL/analytics.")


async def build(board, store, llm, settings):
    cm = AsyncSqliteSaver.from_conn_string(settings.checkpoint_db)
    cp = await cm.__aenter__()
    return build_application_graph(board, store, llm, settings, lambda jid: JOB, cp), cm


async def step(board, store, llm, settings):
    """One poll tick with a *freshly built* graph = simulates the worker process restarting."""
    g, cm = await build(board, store, llm, settings)
    try:
        return await poll_board(board, store, g, settings)
    finally:
        await cm.__aexit__(None, None, None)


async def status(boxes):
    return list((await dump(boxes))["pages"].values())[0]


async def test_full_loop(board, boxes, store, settings):
    page = await board.create_job(JOB); store.upsert_job(JOB["id"], page, "New")
    seen_feedback = []

    def script(model, messages, n):
        text = messages[-1][1]
        seen_feedback.append("shorter summary" in text)
        return good("Revised summary." if "shorter summary" in text else "First summary.")

    llm = ScriptedLLM(script)

    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Apply")
    assert (await step(board, store, llm, settings))["started"] == 1
    p = await status(boxes)
    assert p["Status"] == "Resume Review" and "Resume review (round 1)" in (await dump(boxes))["bodies"][page]

    # nothing happens while the human hasn't decided (idempotent polling)
    assert (await step(board, store, llm, settings))["resumed"] == 0 and len(llm.calls) == 1

    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Revise", feedback="shorter summary please")
    assert (await step(board, store, llm, settings))["resumed"] == 1
    p = await status(boxes)
    assert p["Status"] == "Resume Review" and seen_feedback[-1] is True
    assert "round 2" in (await dump(boxes))["bodies"][page]

    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Resume Approved")
    await step(board, store, llm, settings)
    p = await status(boxes)
    assert p["Status"] == "Ready to Apply"
    assert Path(p["Resume file"]).exists() and p["Resume file"].endswith(".docx")


async def test_validator_retry_then_success(board, boxes, store, settings):
    page = await board.create_job(JOB); store.upsert_job(JOB["id"], page, "New")

    def script(model, messages, n):
        r = good("ok")
        if n == 1:
            r.skills_order = ["SQL", "Kubernetes"]   # fabricated
        return r

    llm = ScriptedLLM(script)
    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Apply")
    await step(board, store, llm, settings)
    assert len(llm.calls) == 2 and "validator" in llm.calls[1][1][1]
    assert (await status(boxes))["Status"] == "Resume Review"


async def test_permanent_validation_failure_goes_manual(board, boxes, store, settings):
    page = await board.create_job(JOB); store.upsert_job(JOB["id"], page, "New")

    def script(model, messages, n):
        r = good("ok"); r.skills_order = ["Kubernetes"]; return r

    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Apply")
    await step(board, store, ScriptedLLM(script), settings)
    p = await status(boxes)
    assert p["Status"] == "Manual" and "safety validation" in p["Feedback"]


async def test_llm_crash_is_retried_then_poison_pill_stops(board, boxes, store, settings):
    page = await board.create_job(JOB); store.upsert_job(JOB["id"], page, "New")

    def boom(model, messages, n):
        raise RuntimeError("api down")

    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Apply")
    for expected in ("Apply", "Apply", "Manual"):
        await step(board, store, ScriptedLLM(boom), settings)
        assert (await status(boxes))["Status"] == expected


async def test_stuck_claim_is_recovered(board, boxes, store, settings):
    page = await board.create_job(JOB); store.upsert_job(JOB["id"], page, "New")
    await boxes["notion"].call("TEST-human-edit", page_id=page, status="Tailoring")
    store.claim(JOB["id"], "Tailoring", "Apply")
    settings.stuck_minutes = 0
    import time; time.sleep(0.05)
    stats = await step(board, store, ScriptedLLM(lambda *a: good("x")), settings)
    assert stats["recovered"] == 1
