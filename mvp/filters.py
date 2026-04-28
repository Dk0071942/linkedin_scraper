"""Per-field filter for scraped jobs.

YAML shape:

    filters:
      job_title:        { include: [...], exclude: [...] }   # text fields
      location:         { include: [...], exclude: [...] }
      job_description:  { include: [...], exclude: [...] }
      workplace_type:   { in: ["Remote", "Hybrid"] }         # categorical
      employment_type:  { in: ["Full-time"] }
      posted_date:      { within_days: 14 }                  # numeric
      case_sensitive: false

Semantics
---------
- `include`: at least one keyword must appear in that field (OR within field).
- `exclude`: none of the keywords may appear in that field.
- `in`: field value must be one of the listed strings (categorical match).
- `within_days`: the parsed days-ago of `posted_date` must be ≤ N.
- Across fields: AND. A job passes only if every constrained field passes.
- Case-insensitive substring match by default; flip with `case_sensitive: true`.

If a field has no constraint (or the constraint is empty), it always passes.
If `filters:` is missing entirely, every job passes.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .models import JobRecord


@dataclass
class TextFieldFilter:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def is_active(self) -> bool:
        return bool(self.include) or bool(self.exclude)

    def evaluate(self, value: Optional[str], case_sensitive: bool) -> bool:
        if not self.is_active():
            return True
        text = value or ""
        if not case_sensitive:
            text = text.lower()
            inc = [k.lower() for k in self.include]
            exc = [k.lower() for k in self.exclude]
        else:
            inc = list(self.include)
            exc = list(self.exclude)
        if inc and not any(k in text for k in inc):
            return False
        if any(k in text for k in exc):
            return False
        return True


@dataclass
class CategoricalFilter:
    in_: list[str] = field(default_factory=list)

    def is_active(self) -> bool:
        return bool(self.in_)

    def evaluate(self, value: Optional[str]) -> bool:
        if not self.is_active():
            return True
        if value is None:
            return False
        # Case-insensitive set membership for robustness against UI variants
        return value.lower() in {v.lower() for v in self.in_}


@dataclass
class DateFilter:
    within_days: Optional[float] = None

    def is_active(self) -> bool:
        return self.within_days is not None

    def evaluate(self, days_ago: Optional[float]) -> bool:
        if not self.is_active():
            return True
        if days_ago is None:
            return False
        return days_ago <= self.within_days


@dataclass
class FilterConfig:
    job_title: TextFieldFilter = field(default_factory=TextFieldFilter)
    location: TextFieldFilter = field(default_factory=TextFieldFilter)
    job_description: TextFieldFilter = field(default_factory=TextFieldFilter)
    workplace_type: CategoricalFilter = field(default_factory=CategoricalFilter)
    employment_type: CategoricalFilter = field(default_factory=CategoricalFilter)
    posted_date: DateFilter = field(default_factory=DateFilter)
    case_sensitive: bool = False

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "FilterConfig":
        raw = raw or {}

        def text(key: str) -> TextFieldFilter:
            d = raw.get(key) or {}
            return TextFieldFilter(
                include=list(d.get("include") or []),
                exclude=list(d.get("exclude") or []),
            )

        def cat(key: str) -> CategoricalFilter:
            d = raw.get(key) or {}
            return CategoricalFilter(in_=list(d.get("in") or []))

        date_d = raw.get("posted_date") or {}
        return cls(
            job_title=text("job_title"),
            location=text("location"),
            job_description=text("job_description"),
            workplace_type=cat("workplace_type"),
            employment_type=cat("employment_type"),
            posted_date=DateFilter(within_days=date_d.get("within_days")),
            case_sensitive=bool(raw.get("case_sensitive", False)),
        )

    @property
    def is_active(self) -> bool:
        return any(f.is_active() for f in (
            self.job_title, self.location, self.job_description,
            self.workplace_type, self.employment_type, self.posted_date,
        ))

    def describe(self) -> str:
        parts = []
        if self.job_title.is_active():
            parts.append(f"job_title(in={self.job_title.include}, ex={self.job_title.exclude})")
        if self.location.is_active():
            parts.append(f"location(in={self.location.include}, ex={self.location.exclude})")
        if self.job_description.is_active():
            parts.append(f"job_description(in={self.job_description.include}, ex={self.job_description.exclude})")
        if self.workplace_type.is_active():
            parts.append(f"workplace_type(in={self.workplace_type.in_})")
        if self.employment_type.is_active():
            parts.append(f"employment_type(in={self.employment_type.in_})")
        if self.posted_date.is_active():
            parts.append(f"posted_date(within_days={self.posted_date.within_days})")
        return "; ".join(parts) if parts else "(no filters)"


def evaluate(job: JobRecord, cfg: FilterConfig) -> bool:
    if not cfg.is_active:
        return True
    return all([
        cfg.job_title.evaluate(job.job_title, cfg.case_sensitive),
        cfg.location.evaluate(job.location, cfg.case_sensitive),
        cfg.job_description.evaluate(job.job_description, cfg.case_sensitive),
        cfg.workplace_type.evaluate(job.workplace_type),
        cfg.employment_type.evaluate(job.employment_type),
        cfg.posted_date.evaluate(job.posted_days_ago),
    ])


# --- Posted-date parsing ---

_RELATIVE_RE = re.compile(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", re.I)
_UNIT_DAYS = {
    "minute": 1 / 1440,
    "hour": 1 / 24,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "year": 365.0,
}


def parse_posted_date(s: Optional[str]) -> Optional[float]:
    """Convert LinkedIn relative-date strings to days-ago.

    Examples:
        'Reposted 1 week ago' → 7.0
        '2 days ago'          → 2.0
        '3 hours ago'         → 0.125
        'Just posted'         → 0.0
        None / unparseable    → None
    """
    if not s:
        return None
    text = s.lower()
    if "just posted" in text or "just now" in text or "today" in text:
        return 0.0
    if "yesterday" in text:
        return 1.0
    m = _RELATIVE_RE.search(text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    return n * _UNIT_DAYS[unit]
