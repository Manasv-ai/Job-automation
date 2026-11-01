import re
from pathlib import Path
from urllib.parse import quote_plus

from jobspy.google import Google
from jobspy.google.util import find_job_info_initial_page

from listings import JobListing
from sources.reports import SourceReport

USER_DATA_DIR = Path(__file__).resolve().parent.parent / ".playwright_google_profile"


def _is_hard_captcha_page(html: str) -> bool:
    h = html.lower()
    if "our systems have detected unusual traffic" in h:
        return True
    if "unusual traffic from your computer network" in h:
        return True
    if 'id="captcha-form"' in h:
        return True
    return False


class GooglePlaywrightSource:
    """Google Jobs via local Chromium (no paid API)."""

    def __init__(self, headless: bool = True, timeout_ms: int = 60_000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    def _build_query(self, search_term: str, location: str, hours_old: int) -> str:
        query = f"{search_term} jobs near {location}"
        if hours_old <= 24:
            query += " since yesterday"
        elif hours_old <= 72:
            query += " in the last 3 days"
        elif hours_old <= 168:
            query += " in the last week"
        else:
            query += " in the last month"
        return query

    def _launch_browser(self, playwright):
        args = ["--disable-blink-features=AutomationControlled"]
        for channel in ("chrome", "msedge", None):
            try:
                if channel:
                    return playwright.chromium.launch(
                        channel=channel, headless=self.headless, args=args
                    )
                return playwright.chromium.launch(headless=self.headless, args=args)
            except Exception:
                continue
        return playwright.chromium.launch(headless=self.headless, args=args)

    def search(
        self,
        search_term: str,
        location: str,
        results_wanted: int = 20,
        hours_old: int = 168,
    ) -> SourceReport:
        report = SourceReport(source_id="google", label="Google Jobs (Playwright)")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            report.error = "Playwright not installed. Run: pip install playwright && playwright install chromium"
            return report

        query = self._build_query(search_term, location, hours_old)
        url = f"https://www.google.com/search?q={quote_plus(query)}&udm=8"

        try:
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    viewport={"width": 1366, "height": 900},
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(4000)
                try:
                    consent = page.get_by_role("button", name=re.compile("Accept all|I agree", re.I))
                    if consent.count() > 0:
                        consent.first.click(timeout=3000)
                        page.wait_for_timeout(1500)
                except Exception:
                    pass
                html = page.content()
                browser.close()
        except Exception as exc:
            report.error = str(exc)[:200]
            return report

        listings = self._parse_html(html)

        if not listings and _is_hard_captcha_page(html):
            report.error = (
                "Google CAPTCHA/block — in Settings turn off Headless browser, run Discover again, "
                "or complete CAPTCHA once in the window that opens"
            )
            return report

        report.listings = listings[:results_wanted]
        if not report.listings:
            if _is_hard_captcha_page(html):
                report.error = "Google CAPTCHA — disable headless and retry"
            else:
                report.detail = "0 parseable listings (layout changed or no matches for query)"
        return report

    def _parse_html(self, html: str) -> list[JobListing]:
        parser = Google()
        parser.seen_urls = set()
        jobs_raw = find_job_info_initial_page(html)
        listings: list[JobListing] = []

        for raw in jobs_raw:
            if isinstance(raw, dict) and raw.get("error"):
                continue
            try:
                post = parser._parse_job(raw)
            except Exception:
                continue
            if not post:
                continue
            listing = JobListing.from_jobspy_post(post, source="google")
            if listing:
                listings.append(listing)

        if not listings:
            listings = self._fallback_link_parse(html)
        return listings

    def _fallback_link_parse(self, html: str) -> list[JobListing]:
        listings: list[JobListing] = []
        pattern = re.compile(
            r'href="(https?://[^"]+(?:linkedin\.com/jobs|indeed\.com|naukri\.com)[^"]*)"',
            re.I,
        )
        seen: set[str] = set()
        for match in pattern.finditer(html):
            url = match.group(1).split("&")[0]
            if url in seen:
                continue
            seen.add(url)
            site = "manual"
            if "linkedin" in url.lower():
                site = "linkedin"
            elif "indeed" in url.lower():
                site = "indeed"
            elif "naukri" in url.lower():
                site = "naukri"
            listings.append(
                JobListing(
                    title="Role (from Google link)",
                    company="Unknown",
                    location="",
                    job_url=url,
                    description="",
                    site=site,
                )
            )
        return listings[:30]
