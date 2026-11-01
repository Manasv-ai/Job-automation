from tests.conftest import dump

JOB = {"id": "j1", "title": "APM", "company": "Acme Corp", "location": "Bengaluru", "site": "linkedin",
       "job_url": "https://x.io/1", "match_score": 0.82, "key_matches": "SQL", "missing_skills": "Figma"}


async def test_create_is_idempotent_and_queryable(board, boxes):
    await board.ensure_schema()
    a = await board.create_job(JOB)
    b = await board.create_job(JOB)          # crash-after-create replay
    assert a == b
    rows = await board.query_by_status("New")
    assert len(rows) == 1 and rows[0]["job_id"] == "j1" and rows[0]["company"] == "Acme Corp"
    await board.set_props(a, status="Apply", feedback="hi")
    assert (await board.query_by_status("Apply"))[0]["feedback"] == "hi"
    await board.set_body(a, "# review")
    assert (await dump(boxes))["bodies"][a] == "# review"
