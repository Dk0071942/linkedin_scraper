"""Models for scraped jobs + application tracking.

Design goal: one per-job JSON file = one job's *complete* state. Scraped fields
and application progress live side by side, so an LLM (or you) can read or
update a single file without cross-referencing other stores.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApplicationStatus(str, Enum):
    NOT_APPLIED = "not_applied"
    DRAFTED = "drafted"          # motivation letter generated, not sent
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"


class ApplicationEvent(BaseModel):
    """Append-only history entry. Useful for audit + LLM context."""
    at: str = Field(default_factory=_now_iso)
    event: str
    notes: Optional[str] = None


class Application(BaseModel):
    status: ApplicationStatus = ApplicationStatus.NOT_APPLIED
    motivation_letter: Optional[str] = None
    cv_version: Optional[str] = None
    applied_at: Optional[str] = None
    rejected_at: Optional[str] = None
    accepted_at: Optional[str] = None
    notes: Optional[str] = None
    history: list[ApplicationEvent] = Field(default_factory=list)


class JobRecord(BaseModel):
    """Single source of truth for one job — scraped + filter status + application."""

    # --- Identity ---
    linkedin_url: str
    job_id: Optional[str] = None

    # --- Scraped fields ---
    job_title: Optional[str] = None
    company: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    location: Optional[str] = None
    posted_date: Optional[str] = None             # raw LinkedIn string
    posted_days_ago: Optional[float] = None       # parsed from posted_date
    applicant_count: Optional[str] = None
    workplace_type: Optional[str] = None          # Remote | Hybrid | On-site
    employment_type: Optional[str] = None         # Full-time | Part-time | Contract | ...
    job_description: Optional[str] = None

    # --- Search context (which query found this job) ---
    search_keywords: Optional[str] = None
    search_location: Optional[str] = None

    # --- Bookkeeping ---
    scraped_at: str = Field(default_factory=_now_iso)
    matched: bool = True

    # --- Application tracking ---
    application: Application = Field(default_factory=Application)
