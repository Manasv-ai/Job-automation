from dataclasses import dataclass, field

from listings import JobListing


@dataclass
class SourceReport:
    source_id: str
    label: str
    listings: list[JobListing] = field(default_factory=list)
    error: str | None = None
    detail: str = ""

    @property
    def count(self) -> int:
        return len(self.listings)

    @property
    def status(self) -> str:
        if self.error:
            return f"error: {self.error}"
        if self.count == 0:
            return self.detail or "0 listings"
        return f"{self.count} listings"
