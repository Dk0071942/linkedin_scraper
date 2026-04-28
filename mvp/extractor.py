"""Robust extraction for LinkedIn job pages.

Strategy: read [role='main'] inner_text once, parse line-by-line. The new
LinkedIn UI uses obfuscated CSS class hashes, so semantic class selectors
are unreliable; the rendered text layout is much more stable.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Page

from .filters import parse_posted_date
from .models import JobRecord

logger = logging.getLogger(__name__)


# UI strings appear in the user's LinkedIn UI language. We assume English here;
# if the user switches LinkedIn UI language, these need updating.
_DESC_HEADER = "About the job"
_WORKPLACE_TYPES = ("Remote", "Hybrid", "On-site")
_EMPLOYMENT_TYPES = (
    "Full-time", "Part-time", "Contract", "Internship",
    "Temporary", "Volunteer", "Other",
)
# Lines whose stripped value EQUALS one of these → start of LinkedIn cruft.
_DESC_END_LINE_EQUALS = (
    "About the company",
    "Show more jobs like this",
    "Similar jobs",
    "People also viewed",
    "More jobs from",
    "More jobs you might like",
    # "Show more" / "Show less" toggle button text leaks into role_main:
    "… more",
    "...more",
    "… less",
    "...less",
    "Show more",
    "Show less",
    # Sidebar / similar-jobs widget that wraps the Premium upsell:
    "Set alert for similar jobs",
    # LinkedIn global footer noise that appears below the job content:
    "Looking for talent?",
    "Manage your account and privacy",
    "Recommendation transparency",
    "Select language",
    "Visit our Help Center.",
)

# Lines whose stripped value STARTS WITH one of these → cruft. Used for
# variants we don't want to enumerate exhaustively (currency / year / locale).
_DESC_END_LINE_PREFIXES = (
    "Job search smarter with Premium",
    "Job search faster with Premium",
    "Try Premium for",
    "LinkedIn Corporation ©",
)


def _parse_title_tag(title_tag: str) -> tuple[Optional[str], Optional[str]]:
    """Page title format: '<job_title> | <company> | LinkedIn'."""
    parts = [p.strip() for p in title_tag.split(" | ")]
    if len(parts) >= 3 and parts[-1] == "LinkedIn":
        return parts[0], parts[-2]
    if len(parts) == 2:
        return parts[0], None
    return title_tag.strip(), None


def _job_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else None


def _split_meta_line(line: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse '<location> · <posted_date> · <applicant_count>'.

    The dot is U+00B7. Some lines have only 2 parts (no applicant count yet).
    """
    parts = [p.strip() for p in line.split("·")]
    location = parts[0] if len(parts) > 0 else None
    posted = parts[1] if len(parts) > 1 else None
    applicants = parts[2] if len(parts) > 2 else None
    return location, posted, applicants


def _is_meta_line(line: str) -> bool:
    """A meta line has '·' separators and looks like location/date/applicants."""
    if "·" not in line:
        return False
    parts = [p.strip() for p in line.split("·")]
    if len(parts) < 2:
        return False
    # Heuristic: at least one part mentions time ("ago", "week", "day", "hour", "month")
    joined = " ".join(parts).lower()
    return any(tok in joined for tok in ("ago", "week", "day", "hour", "month", "minute", "year"))


def _extract_workplace_employment(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    workplace = next((l for l in lines if l.strip() in _WORKPLACE_TYPES), None)
    employment = next((l for l in lines if l.strip() in _EMPLOYMENT_TYPES), None)
    return (workplace.strip() if workplace else None,
            employment.strip() if employment else None)


def _is_cruft_line(line: str) -> bool:
    s = line.strip()
    if s in _DESC_END_LINE_EQUALS:
        return True
    return any(s.startswith(p) for p in _DESC_END_LINE_PREFIXES)


def _trim_description(desc_lines: list[str]) -> str:
    """Cut the description at the first line that matches a cruft marker."""
    cut = len(desc_lines)
    for i, line in enumerate(desc_lines):
        if _is_cruft_line(line):
            cut = i
            break
    return "\n".join(desc_lines[:cut]).strip()


def clean_description(text: str) -> str:
    """Re-trim a previously-saved description string. Idempotent.

    Used by the retroactive cleanup utility to strip LinkedIn footer cruft from
    descriptions saved before the marker list was extended.
    """
    if not text:
        return text
    return _trim_description(text.splitlines())


def parse_main_text(
    main_text: str,
    title_tag: str,
    linkedin_url: str,
) -> dict:
    """Pure parser: text in, dict of fields out. Easy to unit test."""
    title_from_tag, company_from_tag = _parse_title_tag(title_tag)
    raw_lines = main_text.splitlines()
    lines = [l for l in raw_lines if l.strip() != ""]

    company: Optional[str] = company_from_tag or (lines[0].strip() if lines else None)

    # Find the meta line (location · date · applicants)
    meta_idx = next((i for i, l in enumerate(lines) if _is_meta_line(l)), None)
    location = posted_date = applicant_count = None
    if meta_idx is not None:
        location, posted_date, applicant_count = _split_meta_line(lines[meta_idx])

    # Job title: prefer the title tag; fall back to line between company and meta line
    job_title = title_from_tag
    if not job_title and meta_idx is not None and meta_idx > 1:
        job_title = lines[meta_idx - 1].strip()

    # Workplace + employment type sit between meta line and "About the job"
    desc_idx = next(
        (i for i, l in enumerate(lines) if l.strip() == _DESC_HEADER),
        None,
    )
    pre_desc = lines[(meta_idx or 0) + 1: desc_idx if desc_idx is not None else len(lines)]
    workplace_type, employment_type = _extract_workplace_employment(pre_desc)

    # Description is everything after "About the job"
    job_description = None
    if desc_idx is not None:
        # Use raw_lines to preserve paragraph breaks within the description.
        # We need raw line index that corresponds to lines[desc_idx].
        # Easiest: find the header in raw_lines by sequential match.
        header_text = lines[desc_idx]
        raw_desc_idx = None
        seen = -1
        for i, rl in enumerate(raw_lines):
            if rl.strip() == header_text:
                seen += 1
                if seen == sum(1 for l in lines[:desc_idx] if l == header_text):
                    raw_desc_idx = i
                    break
        if raw_desc_idx is None:
            raw_desc_idx = next(
                (i for i, rl in enumerate(raw_lines) if rl.strip() == _DESC_HEADER),
                None,
            )
        if raw_desc_idx is not None:
            job_description = _trim_description(raw_lines[raw_desc_idx + 1:])

    return {
        "linkedin_url": linkedin_url,
        "job_id": _job_id_from_url(linkedin_url),
        "job_title": job_title,
        "company": company,
        "location": location,
        "posted_date": posted_date,
        "applicant_count": applicant_count,
        "workplace_type": workplace_type,
        "employment_type": employment_type,
        "job_description": job_description,
    }


class RichJobScraper:
    """Scraper that renders a LinkedIn job page and returns a JobRecord.

    Usage:
        scraper = RichJobScraper(browser.page)
        job = await scraper.scrape("https://www.linkedin.com/jobs/view/.../")
    """

    def __init__(self, page: Page):
        self.page = page

    async def scrape(
        self,
        linkedin_url: str,
        search_keywords: Optional[str] = None,
        search_location: Optional[str] = None,
    ) -> JobRecord:
        await self.page.goto(linkedin_url, wait_until="domcontentloaded", timeout=30000)

        # Wait until [role='main'] has substantive content
        try:
            await self.page.wait_for_function(
                "() => { const m = document.querySelector('[role=\"main\"]'); "
                "return m && m.innerText && m.innerText.length > 500; }",
                timeout=15000,
            )
        except Exception:
            logger.warning("role=main slow to render for %s; proceeding anyway", linkedin_url)

        # Nudge lazy content
        await self.page.evaluate("window.scrollTo(0, 800)")
        await self.page.wait_for_timeout(600)
        await self.page.evaluate("window.scrollTo(0, 1800)")
        await self.page.wait_for_timeout(600)

        title_tag = await self.page.title()
        main_loc = self.page.locator("[role='main']").first
        main_text = await main_loc.inner_text()

        fields = parse_main_text(main_text, title_tag, linkedin_url)

        # Company URL is still readable from any /company/ link
        try:
            company_link = self.page.locator('a[href*="/company/"]').first
            if await company_link.count() > 0:
                href = await company_link.get_attribute("href")
                if href:
                    href = href.split("?")[0]
                    if not href.startswith("http"):
                        href = f"https://www.linkedin.com{href}"
                    parsed = urlparse(href)
                    if parsed.netloc.endswith("linkedin.com"):
                        fields["company_linkedin_url"] = href
        except Exception:
            pass

        fields["posted_days_ago"] = parse_posted_date(fields.get("posted_date"))

        return JobRecord(
            **fields,
            search_keywords=search_keywords,
            search_location=search_location,
        )
