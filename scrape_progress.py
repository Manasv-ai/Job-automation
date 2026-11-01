"""Human-readable labels for multi-query scrape progress."""

from scraper import ScrapeAttempt

_KIND_LABEL = {
    "primary": "main search",
    "remote_same_country": "remote · same region",
    "remote_global": "remote · global",
    "remote_worldwide": "remote · worldwide",
    "remote_anywhere": "remote · work from anywhere",
}


def format_scrape_progress(done: int, total: int, attempt: ScrapeAttempt) -> str:
    kind = _KIND_LABEL.get(attempt.query_kind, attempt.query_kind)
    remote_note = " · remote filter" if attempt.is_remote else ""
    if attempt.error:
        detail = attempt.error
    elif attempt.count > 0:
        detail = f"{attempt.count} jobs"
    else:
        detail = "0 jobs returned"

    loc = attempt.location or "any"
    return (
        f"Board {done}/{total}: {attempt.site.title()} · {kind}{remote_note} @ {loc} — {detail}"
    )


def format_breakdown_status(attempt: ScrapeAttempt) -> str:
    if attempt.error:
        return attempt.error[:80]
    if attempt.count > 0:
        return "OK"
    return "0 jobs"
