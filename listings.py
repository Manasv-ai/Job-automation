import hashlib
from dataclasses import dataclass, field

import pandas as pd

from job_text import cell_str


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    job_url: str
    description: str
    site: str
    date_posted: str = ""
    visa_status: str = "Standard / Verification Needed"
    query_kind: str = "primary"
    extra: dict = field(default_factory=dict)

    @property
    def job_id(self) -> str:
        raw = f"{self.company.lower()}_{self.title.lower()}_{self.location.lower()}"
        if self.job_url:
            raw = self.job_url.strip().lower().split("?")[0]
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @classmethod
    def from_scraper_row(cls, row, site: str, visa_status: str = "Standard / Verification Needed") -> "JobListing":
        return cls(
            title=cell_str(row.get("title")) or "Unknown role",
            company=cell_str(row.get("company")) or "Unknown",
            location=cell_str(row.get("location")),
            job_url=cell_str(row.get("job_url")) or "#",
            description=cell_str(row.get("description")),
            site=site or cell_str(row.get("site")) or "unknown",
            date_posted=cell_str(row.get("date_posted")),
            visa_status=visa_status,
        )

    @classmethod
    def from_jobspy_post(cls, post, source: str = "google") -> "JobListing | None":
        if not post or not post.job_url:
            return None
        loc = post.location.display_location() if post.location else ""
        return cls(
            title=post.title or "Unknown role",
            company=post.company_name or "Unknown",
            location=loc,
            job_url=post.job_url,
            description=post.description or "",
            site=source,
            date_posted=str(post.date_posted or ""),
        )

    def to_evaluate_dict(self, search_query: str) -> dict:
        return {
            "id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "site": self.site,
            "job_url": self.job_url,
            "visa_status": self.visa_status,
            "description": self.description,
            "date_posted": self.date_posted,
            "search_query": search_query,
        }


def dedupe_listings(items: list[JobListing]) -> list[JobListing]:
    seen: set[str] = set()
    out: list[JobListing] = []
    for job in items:
        key = job.job_id
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def listings_to_dataframe(items: list[JobListing]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame()
    return pd.DataFrame([job.__dict__ for job in items])
