from collections.abc import Callable

from config_loader import load_config
from enrichment import enrich_listings
from job_text import build_job_description
from listings import JobListing, dedupe_listings
from pipeline import ScanSummary, _evaluate_jobs
from scraper import MultiPlatformScraper
from sources.google_playwright import GooglePlaywrightSource
from sources.reports import SourceReport


def _scraper_result_to_listings(scrape_result) -> list[JobListing]:
    items: list[JobListing] = []
    if scrape_result.jobs.empty:
        return items
    for _, row in scrape_result.jobs.iterrows():
        visa = row.get("visa_status_flag", "Standard / Verification Needed")
        listing = JobListing.from_scraper_row(
            row, site=str(row.get("site", "")), visa_status=str(visa)
        )
        listing.description = build_job_description(row.to_dict()) or listing.description
        items.append(listing)
    return items


def run_discovery(
    config: dict | None = None,
    force_refresh: bool = False,
    export_excel: bool = False,
    send_telegram: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> tuple[ScanSummary, list[SourceReport]]:
    config = config or load_config()
    search = config.get("search_criteria", {})
    discovery_cfg = config.get("discovery", {})

    def report(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(max(0, min(100, pct)), msg)

    search_term = search.get("search_term", "")
    location = search.get("location", "India")
    results_wanted = int(search.get("results_wanted", 20))
    hours_old = int(search.get("hours_old", 48))

    source_reports: list[SourceReport] = []
    all_listings: list[JobListing] = []

    report(2, "Starting multi-platform discovery…")

    if discovery_cfg.get("use_jobspy_boards", True):
        enabled = search.get("enabled_sites") or ["linkedin", "indeed", "naukri"]
        jobspy_sites = [s for s in enabled if s in ("linkedin", "indeed", "naukri", "google")]
        jobspy_sites = [s for s in jobspy_sites if s != "google"]

        scraper = MultiPlatformScraper(target_sites=jobspy_sites or ["linkedin", "indeed"])

        def scrape_tick(done: int, total: int, attempt) -> None:
            pct = 5 + int((done / max(total, 1)) * 35)
            report(pct, f"JobSpy {attempt.site} ({done}/{total})…")

        scrape_result = scraper.fetch_all_jobs(
            search_term=search_term,
            location=location,
            max_results_per_site=results_wanted,
            hours_old=hours_old,
            country_indeed=search.get("country_indeed", "India"),
            include_visa_restricted=bool(search.get("include_visa_restricted", False)),
            include_remote_variants=bool(search.get("include_remote_variants", True)),
            target_sites=jobspy_sites,
            on_scrape_progress=scrape_tick,
        )
        jobspy_listings = _scraper_result_to_listings(scrape_result)
        all_listings.extend(jobspy_listings)
        source_reports.append(
            SourceReport(
                source_id="jobspy",
                label=f"JobSpy ({', '.join(jobspy_sites)})",
                listings=jobspy_listings,
                detail=f"{len(jobspy_listings)} after visa filter",
            )
        )
        for attempt in scrape_result.attempts:
            source_reports.append(
                SourceReport(
                    source_id=f"jobspy-{attempt.site}",
                    label=f"{attempt.site} · {attempt.query_kind}",
                    listings=[],
                    detail=f"{attempt.count} raw" if attempt.count else (attempt.error or "empty"),
                )
            )

    if discovery_cfg.get("use_google_playwright", True):
        report(42, "Google Jobs via Playwright…")
        google = GooglePlaywrightSource(
            headless=bool(discovery_cfg.get("playwright_headless", True)),
        )
        g_report = google.search(
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=hours_old,
        )
        source_reports.append(g_report)
        all_listings.extend(g_report.listings)

    all_listings = dedupe_listings(all_listings)
    summary = ScanSummary(scraped=len(all_listings))

    if not all_listings:
        report(100, "No listings found from any source")
        return summary, source_reports

    report(50, f"Deduped to {len(all_listings)} listings")

    if discovery_cfg.get("enrich_missing_descriptions", True):
        max_enrich = int(discovery_cfg.get("enrich_max_per_run", 15))

        def enrich_tick(done: int, total: int, url: str) -> None:
            pct = 52 + int((done / max(total, 1)) * 18)
            report(pct, f"Enriching JD {done}/{total}…")

        enriched = enrich_listings(
            all_listings,
            max_enrich=max_enrich,
            headless=bool(discovery_cfg.get("playwright_headless", True)),
            on_progress=enrich_tick,
        )
        report(72, f"Enriched {enriched} descriptions from posting pages")

    to_evaluate = [job.to_evaluate_dict(search_term) for job in all_listings]
    summary = _evaluate_jobs(
        config,
        to_evaluate,
        summary,
        force_refresh,
        on_progress,
        send_telegram,
        export_excel,
    )
    return summary, source_reports
