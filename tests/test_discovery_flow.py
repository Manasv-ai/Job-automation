from agent.graphs.discovery import build_discovery_graph
from tests.conftest import dump


def row(i, company, title, score=0.9):
    return {"id": i, "title": title, "company": company, "location": "B", "site": "linkedin",
            "job_url": "https://x/" + i, "match_score": score, "key_matches": "SQL", "missing_skills": "", "date_posted": ""}


async def test_discovery_pushes_deduped_new_jobs(board, boxes, store, settings):
    rows = [row("a", "Acme", "APM"), row("b", "Acme", "APM"), row("c", "Zeta", "Analyst"), row("known", "Old", "PM")]
    store.upsert_job("known", "p0", "Applied")
    g = build_discovery_graph(board, store, settings, run_discovery=lambda: None,
                              list_candidates=lambda t, n: rows, threshold=lambda: 0.75)
    out = await g.ainvoke({})
    assert out["pushed"] == 2                                   # cross-posted dup + known job skipped
    assert (await g.ainvoke({}))["pushed"] == 0                 # re-run adds nothing


async def test_scrape_failure_does_not_block_push(board, store, settings):
    def boom(): raise RuntimeError("linkedin 429")
    g = build_discovery_graph(board, store, settings, run_discovery=boom,
                              list_candidates=lambda t, n: [row("a", "Acme", "APM")], threshold=lambda: 0.75)
    out = await g.ainvoke({})
    assert out["pushed"] == 1 and "429" in out["discover_error"]
