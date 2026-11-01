import hashlib
import re
from dataclasses import dataclass

URL_RE = re.compile(r"https?://[^\s\|\>,\)\]\"']+", re.IGNORECASE)


@dataclass
class ImportedJob:
    title: str
    company: str
    location: str
    job_url: str
    description: str
    site: str

    @property
    def job_id(self) -> str:
        normalized = self.job_url.strip().lower().split("?")[0]
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def detect_site(url: str) -> str:
    u = url.lower()
    if "linkedin.com" in u:
        return "linkedin"
    if "indeed.com" in u or "indeed." in u:
        return "indeed"
    if "google.com" in u:
        return "google"
    if "naukri.com" in u:
        return "naukri"
    return "manual"


def _clean_url(raw: str) -> str:
    return raw.rstrip(".,;)")


def _parse_block(block: str) -> ImportedJob | None:
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if not lines:
        return None

    fields: dict[str, str] = {"title": "", "company": "", "location": "", "url": "", "description": ""}
    desc_lines: list[str] = []
    in_description = False

    for line in lines:
        lower = line.lower()
        if lower.startswith("title:"):
            fields["title"] = line.split(":", 1)[1].strip()
            in_description = False
        elif lower.startswith("company:"):
            fields["company"] = line.split(":", 1)[1].strip()
            in_description = False
        elif lower.startswith("location:"):
            fields["location"] = line.split(":", 1)[1].strip()
            in_description = False
        elif lower.startswith("url:") or lower.startswith("link:"):
            fields["url"] = _clean_url(line.split(":", 1)[1].strip())
            in_description = False
        elif lower.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            if rest:
                desc_lines.append(rest)
            in_description = True
        elif in_description:
            desc_lines.append(line)
        elif "|" in line:
            parts = [p.strip() for p in line.split("|")]
            urls = [p for p in parts if p.lower().startswith("http")]
            if urls:
                fields["url"] = _clean_url(urls[-1])
                text_parts = [p for p in parts if p not in urls]
                if len(text_parts) >= 1:
                    fields["title"] = text_parts[0]
                if len(text_parts) >= 2:
                    fields["company"] = text_parts[1]
                if len(text_parts) >= 3:
                    fields["location"] = text_parts[2]
        else:
            found = URL_RE.search(line)
            if found:
                fields["url"] = _clean_url(found.group(0))
                prefix = line.replace(found.group(0), "").strip(" |-–—")
                if prefix and not fields["title"]:
                    fields["title"] = prefix

    if not fields["url"]:
        for line in lines:
            found = URL_RE.search(line)
            if found:
                fields["url"] = _clean_url(found.group(0))
                break

    if not fields["url"]:
        return None

    if not fields["title"]:
        fields["title"] = "Role (edit in export)"

    description = "\n".join(desc_lines).strip()
    url = fields["url"]
    return ImportedJob(
        title=fields["title"],
        company=fields["company"] or "Unknown",
        location=fields["location"] or "",
        job_url=url,
        description=description,
        site=detect_site(url),
    )


def parse_application_list(text: str) -> list[ImportedJob]:
    if not text or not text.strip():
        return []

    normalized = text.replace("\r\n", "\n").strip()
    if re.search(r"\n\s*---+\s*\n", normalized):
        blocks = re.split(r"\n\s*---+\s*\n", normalized)
    else:
        blocks = [
            ln.strip()
            for ln in normalized.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    jobs: list[ImportedJob] = []
    seen_urls: set[str] = set()

    for block in blocks:
        job = _parse_block(block)
        if not job:
            continue
        key = job.job_url.lower().split("?")[0]
        if key in seen_urls:
            continue
        seen_urls.add(key)
        jobs.append(job)

    return jobs


def merge_descriptions(jobs: list[ImportedJob], descriptions_text: str) -> list[ImportedJob]:
    """Align optional description blocks (--- separated) with jobs in order."""
    if not descriptions_text or not descriptions_text.strip():
        return jobs

    blocks = [b.strip() for b in re.split(r"\n\s*---+\s*\n", descriptions_text.strip()) if b.strip()]
    merged: list[ImportedJob] = []
    for idx, job in enumerate(jobs):
        desc = blocks[idx] if idx < len(blocks) else job.description
        if desc and not job.description:
            merged.append(
                ImportedJob(
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    job_url=job.job_url,
                    description=desc,
                    site=job.site,
                )
            )
        else:
            merged.append(job)
    return merged


def parse_csv_rows(rows: list[dict]) -> list[ImportedJob]:
    jobs: list[ImportedJob] = []
    seen: set[str] = set()

    def pick(row: dict, keys: tuple[str, ...]) -> str:
        for k in keys:
            for rk, rv in row.items():
                if rk and rk.strip().lower() == k and rv is not None and str(rv).strip():
                    return str(rv).strip()
        return ""

    for row in rows:
        url = pick(row, ("job_url", "url", "link", "application link", "apply link", "posting link"))
        if not url:
            for val in row.values():
                if val and URL_RE.search(str(val)):
                    url = _clean_url(URL_RE.search(str(val)).group(0))
                    break
        if not url:
            continue
        key = url.lower().split("?")[0]
        if key in seen:
            continue
        seen.add(key)

        title = pick(row, ("title", "role", "role title", "job title", "position"))
        company = pick(row, ("company", "employer", "organization"))
        location = pick(row, ("location", "city", "place"))
        description = pick(row, ("description", "job description", "notes", "remarks"))

        jobs.append(
            ImportedJob(
                title=title or "Role (edit in export)",
                company=company or "Unknown",
                location=location,
                job_url=url,
                description=description,
                site=detect_site(url),
            )
        )
    return jobs
