# Autonomous job agent (LangGraph + Notion MCP + Gmail MCP)

```
            ┌────────────── 07:00 daily ──────────────┐
 config.json│ Graph 1: discover → select → push       │──► Notion rows (Status = New)
 (profile)  └──────────────────────────────────────────┘          │ you set Status = Apply / Skip
            ┌────────── every 10 min (poller) ─────────┐          ▼
            │ Graph 2 (one thread per job, checkpointed)│◄── Notion Status changes
            │ tailor → validate → post_review → ⏸ wait │──► Status = Resume Review (+ diff in page body)
            │      ▲ revise (feedback)   │ approve      │ you set Resume Approved / Revise
            │      └─────────────────────┴► finalize    │──► Status = Ready to Apply (+ DOCX path)
            └──────────────────────────────────────────┘          │ you apply, set Status = Applied
            ┌────────────── 08:00 daily ──────────────┐          ▼
            │ Graph 3: Gmail(read-only) → classify →   │──► Interview / Assessment / Offer /
            │          match job → update Notion       │    Rejected / Needs Info (+ date, note, Telegram)
            └──────────────────────────────────────────┘
```

## Status lifecycle (who owns which value)
You set: `Apply`, `Skip`, `Resume Approved`, `Revise`, `Applied`.  
Agent sets: `New`, `Tailoring`, `Resume Review`, `Finalizing`, `Ready to Apply`, `Assessment`, `Interview`, `Offer`, `Rejected`, `Needs Info`, `Needs Review`, `Manual`.

## Setup
1. `pip install -r requirements.txt -r requirements-agent.txt && playwright install chromium`; Node 18+ must be installed (Notion MCP runs via `npx`).
2. **Notion:** create an internal integration → copy token to `NOTION_TOKEN`. Create an empty database (any title column named **Name**), share it with the integration (••• → Connections), put its ID in `NOTION_DATABASE_ID`. Run `python -m agent init-notion` (adds all properties + Status options).
3. **Gmail:** Google Cloud project → enable Gmail API → OAuth client (Desktop) → save as `secrets/gmail_client_secret.json`. **Set the OAuth consent screen to "In production"** (in "Testing", refresh tokens die after 7 days). Run `python -m agent gmail-auth` once.
4. **Resume:** copy `resume/master_resume.example.json` → `resume/master_resume.json` and fill in your real, truthful content. This is the only source the agent may draw from.
5. `python -m agent doctor` — must be all `[OK]`.
6. Try each piece by hand: `python -m agent discover`, `poll`, `inbox`. Then `python -m agent run` (or `docker compose up -d`).

## Tests
`pytest` (19 tests: real MCP stdio plumbing against fake Notion/Gmail servers, real LangGraph checkpointing, restart simulation, crash recovery, prompt-injection email, idempotency).
**Not covered by tests:** live Notion/Gmail/LLM calls and real scrapers — those need your credentials. Run `doctor` first.

## What can break (and what's already done about it)
| Risk | Mitigation in code | Still on you |
|---|---|---|
| LinkedIn/Indeed/Naukri block scrapers (429, CAPTCHA), esp. from cloud IPs | Discovery failure doesn't stop the run; Telegram alert; dedupe | Prefer a home machine/residential IP; keep `results_wanted` small; accept some days returning nothing |
| Notion MCP changes tool names/params (v2.x moved to "data sources"; `children` param is oddly typed) | Server version pinned (`2.6.1`); `doctor` verifies tool names; create-page tries both parent styles; body written via markdown tool | Bump the pin deliberately, re-run `doctor` + tests |
| Gmail OAuth token expiry | Read-only scope; tool errors raise (no silent "0 new emails"); Telegram alert | Publish the OAuth app to production |
| LLM invents experience in resumes | Master-resume-only design; validator (skills, numbers, borrowed JD terms, structure); retries; human approval | Read the diff. The validator is a heuristic, not proof |
| Prompt injection via emails/JDs | LLM returns structured data only; Gmail server is read-only; Notion writes are deterministic code | — |
| Crash mid-run / duplicate rows / double processing | Idempotent create (checks Job ID), claim-then-work status, stuck-claim recovery, poison-pill limit (3 fails → `Manual`), email marked seen only after success | — |
| Human & agent both editing Status | Ownership split above | Don't hand-edit agent-owned statuses while `Tailoring/Finalizing` |
| Machine sleeps / process dies | Docker `restart: unless-stopped`; heartbeat message at 21:00; `HEALTHCHECK_URL` ping each poll | Run on an always-on box; create the healthchecks.io check |
| Ambiguous email → wrong job updated | Fuzzy company+role match with thresholds; ambiguous/low-confidence → new `Needs Review` row, never guesses | Review those rows |
| DOCX lives on the server | Path + optional `RESUME_PUBLIC_BASE_URL` | Sync `data/resumes` to Drive/Dropbox or serve it; Notion MCP can't upload files |

## Deliberately NOT built: auto-submitting applications
"Ready to Apply" is the end of the automated path. Auto-submitting to LinkedIn/Indeed/Naukri violates their ToS and gets accounts restricted, and custom application forms (screening questions, CAPTCHAs) are the most fragile thing in this domain. If you want it later, start with Greenhouse/Lever/Ashby-hosted forms only.
