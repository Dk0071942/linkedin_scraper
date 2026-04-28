"""Focused unit tests for the MVP job-search pipeline helpers."""

from pathlib import Path

import pytest

from mvp.extractor import parse_main_text
from mvp.filters import FilterConfig, evaluate, parse_posted_date
from mvp.models import Application, ApplicationStatus, JobRecord
from mvp.storage import JobStore
from mvp.web import config_io


class MultiDictStub(dict):
    def getlist(self, key):
        value = self.get(key, [])
        return value if isinstance(value, list) else [value]


@pytest.mark.unit
def test_parse_posted_date_relative_values():
    assert parse_posted_date("Just posted") == 0.0
    assert parse_posted_date("Reposted 1 week ago") == 7.0
    assert parse_posted_date("3 hours ago") == 0.125
    assert parse_posted_date("yesterday") == 1.0
    assert parse_posted_date("Promoted") is None


@pytest.mark.unit
def test_filter_config_evaluate_text_category_and_date():
    cfg = FilterConfig.from_dict({
        "job_title": {"include": ["engineer"], "exclude": ["senior"]},
        "location": {"include": ["germany"]},
        "job_description": {"include": ["python"]},
        "workplace_type": {"in": ["Remote", "Hybrid"]},
        "employment_type": {"in": ["Full-time"]},
        "posted_date": {"within_days": 14},
        "case_sensitive": False,
    })
    matching = JobRecord(
        linkedin_url="https://www.linkedin.com/jobs/view/123/",
        job_id="123",
        job_title="Python Engineer",
        location="Berlin, Germany",
        job_description="Build Python services",
        workplace_type="remote",
        employment_type="Full-time",
        posted_days_ago=3,
    )
    excluded = matching.model_copy(update={"job_title": "Senior Python Engineer"})

    assert evaluate(matching, cfg) is True
    assert evaluate(excluded, cfg) is False


@pytest.mark.unit
def test_parse_main_text_extracts_fields_and_trims_cruft():
    main_text = "\n".join([
        "Acme GmbH",
        "Python Engineer",
        "Berlin, Germany · 2 days ago · 47 applicants",
        "Remote",
        "Full-time",
        "About the job",
        "Build reliable Python services.",
        "About the company",
        "Footer text that should be removed",
    ])

    parsed = parse_main_text(
        main_text,
        "Python Engineer | Acme GmbH | LinkedIn",
        "https://www.linkedin.com/jobs/view/4395308615/",
    )

    assert parsed["job_id"] == "4395308615"
    assert parsed["job_title"] == "Python Engineer"
    assert parsed["company"] == "Acme GmbH"
    assert parsed["location"] == "Berlin, Germany"
    assert parsed["posted_date"] == "2 days ago"
    assert parsed["applicant_count"] == "47 applicants"
    assert parsed["workplace_type"] == "Remote"
    assert parsed["employment_type"] == "Full-time"
    assert parsed["job_description"] == "Build reliable Python services."


@pytest.mark.unit
def test_job_store_persists_application_when_match_status_changes(tmp_path: Path):
    store = JobStore(str(tmp_path))
    original = JobRecord(
        linkedin_url="https://www.linkedin.com/jobs/view/123/",
        job_id="123",
        job_title="Python Engineer",
        matched=True,
        application=Application(
            status=ApplicationStatus.DRAFTED,
            motivation_letter="Draft",
        ),
    )
    store.save(original)

    rescraped = JobRecord(
        linkedin_url="https://www.linkedin.com/jobs/view/123/",
        job_id="123",
        job_title="Python Engineer",
        matched=False,
    )
    store.save(rescraped)

    assert not (tmp_path / "jobs" / "123.json").exists()
    discarded = tmp_path / "discarded" / "123.json"
    assert discarded.exists()
    saved = JobRecord.model_validate_json(discarded.read_text(encoding="utf-8"))
    assert saved.application.status == ApplicationStatus.DRAFTED
    assert saved.application.motivation_letter == "Draft"
    assert store.regenerate_summary() == (0, 1)


@pytest.mark.unit
def test_config_form_round_trip_shapes_search_filters_and_scrape_settings():
    form = MultiDictStub({
        "search_keywords": ["Python", ""],
        "search_location": ["Germany", ""],
        "search_limit": ["50", ""],
        "filter_job_title_include": "engineer\ndeveloper",
        "filter_job_title_exclude": "senior",
        "filter_workplace_type_in": "Remote\nHybrid",
        "filter_posted_within_days": "14",
        "scrape_delay_seconds": "7.5",
        "scrape_randomize_delay": "on",
        "scrape_session_file": "linkedin_session.json",
        "scrape_data_dir": "data",
    })

    cfg = config_io.from_form(form)
    view = config_io.to_form_view(cfg)

    assert cfg["searches"] == [{"keywords": "Python", "location": "Germany", "limit": 50}]
    assert cfg["filters"]["job_title"] == {
        "include": ["engineer", "developer"],
        "exclude": ["senior"],
    }
    assert cfg["filters"]["workplace_type"] == {"in": ["Remote", "Hybrid"]}
    assert cfg["filters"]["posted_date"] == {"within_days": 14.0}
    assert cfg["scrape"]["delay_seconds"] == 7.5
    assert cfg["scrape"]["randomize_delay"] is True
    assert view["filters"]["job_title"]["include"] == "engineer\ndeveloper"
