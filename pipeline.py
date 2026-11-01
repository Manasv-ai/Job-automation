from collections.abc import Callable
from dataclasses import dataclass, field

from config_loader import load_config, profile_from_config
from job_import import ImportedJob
from job_text import build_job_description
from db import is_job_existing, save_evaluated_jobs_batch
from excel_exporter import export_jobs_to_excel
from notifier import send_telegram_alert
from scrape_progress import format_scrape_progress
from scraper import MultiPlatformScraper


@dataclass
class ScanSummary:
    scraped: int = 0
    evaluated: int = 0
    skipped_existing: int = 0
    telegram_sent: int = 0
    attempts: list = field(default_factory=list)
    excel_path: str | None = None
    import_parsed: int = 0


def _evaluate_jobs(
    config: dict,
    to_evaluate: list[dict],
    summary: ScanSummary,
    force_refresh: bool,
    on_progress: Callable[[int, str], None] | None,
    send_telegram: bool,
    export_excel: bool,
) -> ScanSummary:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(max(0, min(100, pct)), message)

    search = config["search_criteria"]
    profile = profile_from_config(config)
    search_term = search.get("search_term", "import")

    pending = []
    for job in to_evaluate:
        if not force_refresh and is_job_existing(job["id"]):
            summary.skipped_existing += 1
            continue
        pending.append(job)

    if not pending:
        report(100, "Nothing new to evaluate (already in database)")
        return summary

    from matcher import WeightedJobMatcher, get_embedding_model

    report(20, "Loading embedding model…")
    model = get_embedding_model()
    matcher = WeightedJobMatcher(profile, model=model)

    def match_tick(done: int, total: int) -> None:
        pct = 25 + int((done / max(total, 1)) * 65)
        report(pct, f"Scoring matches ({done}/{total})…")

    eval_results = matcher.evaluate_batch(pending, on_progress=match_tick)
    payloads = []
    for job, ev in zip(pending, eval_results):
        payloads.append(
            {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "site": job["site"],
                "job_url": job["job_url"],
                "visa_status": job.get("visa_status", "Manual import"),
                "match_score": ev["match_score"],
                "req_yoe": ev["required_yoe"],
                "exp_score": ev["exp_score"],
                "semantic_score": ev["semantic_score"],
                "title_score": ev["title_score"],
                "search_query": job.get("search_query", search_term),
                "date_posted": job.get("date_posted", ""),
                "key_matches": ev["key_matches"],
                "missing_skills": ev["missing_skills"],
                "experience_eligible": ev.get("experience_eligible", True),
                "description": job.get("description", ""),
            }
        )

    report(92, f"Saving {len(payloads)} jobs…")
    save_evaluated_jobs_batch(payloads)
    summary.evaluated = len(payloads)

    threshold = float(search.get("min_match_threshold", 0.75))
    bot_token = (config.get("telegram_bot_token") or "").strip()
    chat_id = (config.get("telegram_chat_id") or "").strip()
    telegram_ok = (
        send_telegram
        and bot_token
        and chat_id
        and "YOUR_TELEGRAM" not in bot_token.upper()
    )

    export_rows = sorted(payloads, key=lambda x: x["match_score"], reverse=True)
    if export_excel:
        summary.excel_path = export_jobs_to_excel(export_rows, "job_search_results.xlsx")

    if telegram_ok:
        report(95, "Sending Telegram alerts…")
        for job in export_rows:
            if job["match_score"] >= threshold:
                if send_telegram_alert(bot_token, chat_id, job):
                    summary.telegram_sent += 1

    report(100, "Done")
    return summary


def run_link_import(
    jobs: list[ImportedJob],
    config: dict | None = None,
    force_refresh: bool = False,
    export_excel: bool = False,
    send_telegram: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> ScanSummary:
    config = config or load_config()
    search_term = config.get("search_criteria", {}).get("search_term", "import")

    summary = ScanSummary(import_parsed=len(jobs), scraped=len(jobs))
    if not jobs:
        if on_progress:
            on_progress(100, "No valid posting links found")
        return summary

    to_evaluate = [
        {
            "id": j.job_id,
            "title": j.title,
            "company": j.company,
            "location": j.location,
            "site": j.site,
            "job_url": j.job_url,
            "visa_status": "Manual import",
            "description": j.description,
            "date_posted": "",
            "search_query": f"import:{search_term}",
        }
        for j in jobs
    ]

    return _evaluate_jobs(
        config, to_evaluate, summary, force_refresh, on_progress, send_telegram, export_excel
    )


def run_job_scan(
    config: dict | None = None,
    force_refresh: bool = False,
    export_excel: bool = False,
    send_telegram: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> ScanSummary:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(max(0, min(100, pct)), message)

    config = config or load_config()
    search = config["search_criteria"]
    profile = profile_from_config(config)
    search_term = search["search_term"]
    location = search["location"]

    report(2, "Starting job board scrape…")

    enabled_sites = search.get("enabled_sites") or ["linkedin", "indeed"]
    scraper = MultiPlatformScraper(target_sites=enabled_sites)

    def scrape_tick(done: int, total: int, attempt) -> None:
        pct = 5 + int((done / max(total, 1)) * 47)
        report(pct, format_scrape_progress(done, total, attempt))

    scrape_result = scraper.fetch_all_jobs(
        search_term=search_term,
        location=location,
        max_results_per_site=int(search.get("results_wanted", 20)),
        hours_old=int(search.get("hours_old", 48)),
        country_indeed=search.get("country_indeed", "India"),
        include_visa_restricted=bool(search.get("include_visa_restricted", False)),
        include_remote_variants=bool(search.get("include_remote_variants", True)),
        target_sites=enabled_sites,
        on_scrape_progress=scrape_tick,
    )

    summary = ScanSummary(
        scraped=len(scrape_result.jobs),
        attempts=scrape_result.attempts,
    )
    report(55, f"Deduplicating & filtering — {summary.scraped} listings kept")

    if scrape_result.jobs.empty:
        report(100, "Finished — no listings to evaluate")
        return summary

    to_evaluate = []
    for _, row in scrape_result.jobs.iterrows():
        to_evaluate.append(
            {
                "id": row["job_id"],
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "location": row.get("location", ""),
                "site": row.get("site", ""),
                "job_url": row.get("job_url", "#"),
                "visa_status": row.get("visa_status_flag", "Unknown"),
                "description": build_job_description(row),
                "date_posted": row.get("date_posted", ""),
                "search_query": search_term,
            }
        )

    return _evaluate_jobs(
        config, to_evaluate, summary, force_refresh, on_progress, send_telegram, export_excel
    )
