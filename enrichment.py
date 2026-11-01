import re

from listings import JobListing


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<.*?>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_description_playwright(url: str, headless: bool = True, timeout_ms: int = 45_000) -> str:
    if not url or url == "#":
        return ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()
        text = _strip_html(html)
        return text[:12_000] if text else ""
    except Exception:
        return ""


def enrich_listings(
    listings: list[JobListing],
    max_enrich: int = 15,
    min_desc_len: int = 120,
    headless: bool = True,
    on_progress=None,
) -> int:
    """Fetch missing descriptions for up to max_enrich listings. Returns count enriched."""
    enriched = 0
    targets = [j for j in listings if len((j.description or "").strip()) < min_desc_len]
    targets = targets[:max_enrich]

    for idx, job in enumerate(targets, start=1):
        if on_progress:
            on_progress(idx, len(targets), job.job_url)
        text = fetch_description_playwright(job.job_url, headless=headless)
        if len(text) >= min_desc_len:
            job.description = text
            enriched += 1
    return enriched
