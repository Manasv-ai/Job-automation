import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from jobspy import scrape_jobs

logging.getLogger("JobSpy").setLevel(logging.INFO)

DEFAULT_SITES = ["linkedin", "indeed", "naukri"]
ALL_SITES = ["linkedin", "indeed", "naukri", "google"]


@dataclass
class ScrapeAttempt:
    site: str
    search_term: str
    location: str
    count: int = 0
    error: str | None = None
    query_kind: str = "primary"
    is_remote: bool = False


@dataclass
class ScrapeResult:
    jobs: pd.DataFrame = field(default_factory=pd.DataFrame)
    attempts: list[ScrapeAttempt] = field(default_factory=list)


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class MultiPlatformScraper:
    def __init__(self, target_sites: list[str] | None = None):
        sites = target_sites or DEFAULT_SITES
        self.target_sites = [s for s in sites if s in ALL_SITES]

        self.strict_visa_patterns = [
            r"us citizenship required",
            r"must be authorized to work in the u\.?s\.?",
            r"no visa sponsorship",
            r"unable to sponsor",
            r"u\.?s\.? residents only",
            r"eu citizens only",
            r"must reside in (?:the )?(?:us|usa|united states|canada|uk)",
            r"green card required",
        ]

        self.global_remote_patterns = [
            r"work from anywhere",
            r"worldwide remote",
            r"global remote",
            r"anywhere in the world",
            r"hire globally",
        ]

    def _scrape_single_site_labeled(
        self,
        site: str,
        search_term: str,
        location: str,
        query_kind: str,
        is_remote: bool,
        results_wanted: int,
        hours_old: int,
        country_indeed: str,
    ) -> tuple[pd.DataFrame, ScrapeAttempt]:
        attempt = ScrapeAttempt(
            site=site,
            search_term=search_term,
            location=location,
            query_kind=query_kind,
            is_remote=is_remote,
        )
        log_capture = _LogCapture()
        site_logger = logging.getLogger(f"JobSpy:{site.capitalize()}")
        site_logger.addHandler(log_capture)
        try:
            target_loc = location
            if site == "glassdoor" and location.lower() == "remote":
                target_loc = ""

            scrape_kwargs: dict = {
                "site_name": [site],
                "search_term": search_term,
                "location": target_loc,
                "results_wanted": results_wanted,
                "country_indeed": country_indeed,
                "linkedin_fetch_description": True,
                "enforce_annual_salary": False,
                "is_remote": is_remote,
            }
            if hours_old is not None and hours_old > 0:
                scrape_kwargs["hours_old"] = hours_old

            df = scrape_jobs(**scrape_kwargs)
            if df is not None and not df.empty:
                attempt.count = len(df)
                return df, attempt

            if site == "google":
                attempt.error = (
                    "Google Jobs returned 0 parseable listings — JobSpy’s Google "
                    "scraper is often broken (Google HTML changes). Use LinkedIn/Indeed."
                )
            elif log_capture.messages:
                last = log_capture.messages[-1]
                if "initial cursor not found" in last.lower():
                    attempt.error = "Board returned no parseable results (layout/block)."
                else:
                    attempt.error = last[:160]
            return pd.DataFrame(), attempt
        except Exception as exc:
            attempt.error = str(exc)[:160]
            return pd.DataFrame(), attempt
        finally:
            site_logger.removeHandler(log_capture)

    def check_visa_eligibility(self, description: str, location_str: str) -> dict:
        text = str(description).lower()
        loc = str(location_str).lower()

        has_visa_restriction = any(re.search(p, text) for p in self.strict_visa_patterns)
        is_global_friendly = any(re.search(p, text) for p in self.global_remote_patterns) or "worldwide" in loc

        if has_visa_restriction:
            return {"is_eligible": False, "visa_status_flag": "Restricted (Visa Required)"}
        if is_global_friendly:
            return {"is_eligible": True, "visa_status_flag": "Global Remote (Visa-Free)"}
        return {"is_eligible": True, "visa_status_flag": "Standard / Verification Needed"}

    def generate_job_hash(self, company: str, title: str, location: str) -> str:
        raw_str = f"{str(company).lower().strip()}_{str(title).lower().strip()}_{str(location).lower().strip()}"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def fetch_all_jobs(
        self,
        search_term: str,
        location: str = "India",
        max_results_per_site: int = 20,
        hours_old: int = 48,
        country_indeed: str = "India",
        include_visa_restricted: bool = False,
        include_remote_variants: bool = True,
        target_sites: list[str] | None = None,
        on_scrape_progress: Callable[[int, int, ScrapeAttempt], None] | None = None,
    ) -> ScrapeResult:
        if target_sites:
            self.target_sites = [s for s in target_sites if s in ALL_SITES]

        all_dfs: list[pd.DataFrame] = []
        attempts: list[ScrapeAttempt] = []
        remote_loc = location if location else country_indeed

        search_queries: list[tuple[str, str, str, bool]] = [
            (search_term, location, "primary", False),
        ]
        if include_remote_variants:
            search_queries.extend(
                [
                    (search_term, remote_loc, "remote_same_country", True),
                    (search_term, "Remote", "remote_global", True),
                ]
            )

        tasks: list[tuple] = []
        for site in self.target_sites:
            for query, loc, kind, is_remote in search_queries:
                tasks.append(
                    (site, query, loc, kind, is_remote)
                )

        total_tasks = len(tasks)
        completed_tasks = 0

        def run_task(task_args):
            site, query, loc, kind, is_remote = task_args
            return self._scrape_single_site_labeled(
                site,
                query,
                loc,
                kind,
                is_remote,
                max_results_per_site,
                hours_old,
                country_indeed,
            )

        linkedin_tasks = [t for t in tasks if t[0] == "linkedin"]
        other_tasks = [t for t in tasks if t[0] != "linkedin"]

        for task in linkedin_tasks:
            res_df, attempt = run_task(task)
            attempts.append(attempt)
            completed_tasks += 1
            if on_scrape_progress:
                on_scrape_progress(completed_tasks, total_tasks, attempt)
            if not res_df.empty:
                all_dfs.append(res_df)

        if other_tasks:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(run_task, t) for t in other_tasks]
                for future in as_completed(futures):
                    res_df, attempt = future.result()
                    attempts.append(attempt)
                    completed_tasks += 1
                    if on_scrape_progress:
                        on_scrape_progress(completed_tasks, total_tasks, attempt)
                    if not res_df.empty:
                        all_dfs.append(res_df)

        if not all_dfs:
            return ScrapeResult(jobs=pd.DataFrame(), attempts=attempts)

        combined_df = pd.concat(all_dfs, ignore_index=True)
        combined_df["job_id"] = combined_df.apply(
            lambda r: self.generate_job_hash(
                r.get("company", ""), r.get("title", ""), r.get("location", "")
            ),
            axis=1,
        )
        combined_df = combined_df.drop_duplicates(subset=["job_id"])

        eligibility_results = combined_df.apply(
            lambda row: self.check_visa_eligibility(row.get("description", ""), row.get("location", "")),
            axis=1,
        )
        combined_df["is_visa_eligible"] = [r["is_eligible"] for r in eligibility_results]
        combined_df["visa_status_flag"] = [r["visa_status_flag"] for r in eligibility_results]

        if include_visa_restricted:
            jobs = combined_df.copy()
        else:
            jobs = combined_df[combined_df["is_visa_eligible"] == True].copy()

        return ScrapeResult(jobs=jobs, attempts=attempts)
