"""Graph 2 — per-job resume tailoring with a human approval loop.

One thread per job (thread_id = job_id:generation). The graph PAUSES at `wait` via
interrupt() and is checkpointed to SQLite, so it survives restarts and can wait for days.
It is resumed by the Notion poller when the user flips Status to Resume Approved / Revise.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..resume.models import MasterResume, load_master
from ..resume.render import render_docx
from ..resume.tailor import merge, review_markdown, tailor_resume


class AppState(TypedDict, total=False):
    job_id: str
    page_id: str
    feedback: str
    rounds: int
    tailored: dict
    merged: dict
    warnings: list[str]
    resume_path: str
    outcome: str  # ready | failed | manual


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "x"


def build_application_graph(
    board,
    store,
    llm,
    settings,
    get_job: Callable[[str], dict | None],
    checkpointer,
    master_loader: Callable[[], MasterResume] | None = None,
):
    master_loader = master_loader or (lambda: load_master(settings.master_resume))

    async def tailor(state: AppState) -> AppState:
        job = get_job(state["job_id"])
        if not job:
            await board.set_props(state["page_id"], status="Manual", feedback="Job missing from local DB.")
            store.set_status(state["job_id"], "Manual", last_error="job missing")
            return {"outcome": "failed"}
        master = master_loader()
        desc = job.get("description") or ""
        warnings = []
        if len(desc) < 200:
            warnings.append("Job description was very short/missing — tailoring is based mostly on the title. Review carefully.")
            desc = f"{job.get('title', '')} at {job.get('company', '')}\n{desc}"
        rounds = state.get("rounds", 0) + 1
        result, errors = await tailor_resume(llm, master, desc, state.get("feedback", ""))
        if result is None:
            await board.set_props(
                state["page_id"], status="Manual",
                feedback=("Auto-tailoring failed safety validation: " + "; ".join(errors))[:1900],
            )
            store.set_status(state["job_id"], "Manual", last_error="; ".join(errors)[:500])
            return {"outcome": "failed", "rounds": rounds}
        return {
            "tailored": result.model_dump(), "merged": merge(master, result),
            "rounds": rounds, "warnings": warnings, "outcome": "",
        }

    def after_tailor(state: AppState) -> str:
        return END if state.get("outcome") == "failed" else "post_review"

    async def post_review(state: AppState) -> AppState:
        from ..resume.models import TailoredResume

        master = master_loader()
        t = TailoredResume.model_validate(state["tailored"])
        md = review_markdown(master, t, state["merged"], state["rounds"])
        if state.get("warnings"):
            md = "> ⚠️ " + " ".join(state["warnings"]) + "\n\n" + md
        job = get_job(state["job_id"]) or {}
        fname = f"{_slug(job.get('company', ''))}_{_slug(job.get('title', ''))}_{state['job_id'][:8]}_r{state['rounds']}.docx"
        path = render_docx(state["merged"], str(Path(settings.resume_out_dir) / fname))
        url = f"{settings.resume_public_base_url.rstrip('/')}/{fname}" if settings.resume_public_base_url else None
        await board.set_body(state["page_id"], md)
        await board.set_props(state["page_id"], status="Resume Review", resume_file=path, resume_url=url, feedback="")
        store.set_status(state["job_id"], "Resume Review", resume_path=path, rounds=state["rounds"])
        return {"resume_path": path}

    async def wait(state: AppState) -> AppState:
        decision = interrupt({"job_id": state["job_id"], "round": state.get("rounds", 1), "waiting_for": "resume approval"})
        if decision.get("decision") == "approve":
            return {"feedback": "", "outcome": "approved"}
        return {"feedback": decision.get("feedback", ""), "outcome": "revise"}

    def after_wait(state: AppState) -> str:
        if state["outcome"] == "approved":
            return "finalize"
        if state.get("rounds", 0) >= settings.max_revision_rounds:
            return "give_up"
        return "tailor"

    async def give_up(state: AppState) -> AppState:
        await board.set_props(
            state["page_id"], status="Manual",
            feedback=f"Reached {settings.max_revision_rounds} revision rounds. Edit the latest DOCX by hand.",
        )
        store.set_status(state["job_id"], "Manual")
        return {"outcome": "manual"}

    async def finalize(state: AppState) -> AppState:
        # same content the user approved; the file is already rendered in post_review
        path = state["resume_path"]
        await board.set_props(state["page_id"], status="Ready to Apply", resume_file=path)
        store.set_status(state["job_id"], "Ready to Apply", resume_path=path)
        return {"outcome": "ready"}

    g = StateGraph(AppState)
    for name, fn in (("tailor", tailor), ("post_review", post_review), ("wait", wait),
                     ("give_up", give_up), ("finalize", finalize)):
        g.add_node(name, fn)
    g.add_edge(START, "tailor")
    g.add_conditional_edges("tailor", after_tailor, {END: END, "post_review": "post_review"})
    g.add_edge("post_review", "wait")
    g.add_conditional_edges("wait", after_wait, {"finalize": "finalize", "give_up": "give_up", "tailor": "tailor"})
    g.add_edge("finalize", END)
    g.add_edge("give_up", END)
    return g.compile(checkpointer=checkpointer)
