"""Focused unit tests for the MVP job-search pipeline helpers."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_scraper import RateLimitError
from mvp.extractor import parse_main_text
from mvp.filters import FilterConfig, evaluate, parse_posted_date
from mvp.models import Application, ApplicationStatus, JobRecord
from mvp.pipeline import SearchSpec, run_pipeline
from mvp.search import MAX_SEARCH_LIMIT, PaginatedJobSearch
from mvp.storage import JobStore
from mvp.web import config_io, geocode


class MultiDictStub(dict):
    def getlist(self, key):
        value = self.get(key, [])
        return value if isinstance(value, list) else [value]


class FakeLink:
    def __init__(self, href: str):
        self.href = href

    async def get_attribute(self, name: str):
        return self.href if name == "href" else None


class FakeJobLocator:
    def __init__(self, page: "FakeSearchPage"):
        self.page = page

    async def all(self):
        return [FakeLink(href) for href in self.page.current_urls]


class FakeSearchPage:
    def __init__(self, urls_by_start: dict[int, list[str]]):
        self.urls_by_start = urls_by_start
        self.goto_urls: list[str] = []
        self.current_urls: list[str] = []
        self.url = ""

    async def goto(self, url: str, **kwargs):
        self.url = url
        self.goto_urls.append(url)
        start = int(parse_qs(urlparse(url).query).get("start", ["0"])[0])
        self.current_urls = self.urls_by_start.get(start, [])

    async def wait_for_selector(self, selector: str, timeout: int):
        if not self.current_urls:
            raise PlaywrightTimeoutError("no job links")

    def locator(self, selector: str):
        return FakeJobLocator(self)

    async def evaluate(self, script: str):
        return None

    async def wait_for_timeout(self, timeout: int):
        return None


class FakePipelineStore:
    def all_seen_ids(self):
        return set()


class FakeBrowser:
    page = object()


async def _noop_detect_rate_limit(page):
    return None


async def _raise_detect_rate_limit(page):
    raise RuntimeError("rate limited")


class RateLimitedSearch:
    def __init__(self, *args, **kwargs):
        pass

    async def search(self, *args, **kwargs):
        raise RateLimitError("rate limited")


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


@pytest.mark.unit
def test_config_form_clamps_search_limit_to_supported_range():
    too_high = config_io.from_form(MultiDictStub({
        "search_keywords": ["Python"],
        "search_location": ["Germany"],
        "search_limit": [str(MAX_SEARCH_LIMIT + 1)],
    }))
    too_low = config_io.from_form(MultiDictStub({
        "search_keywords": ["Python"],
        "search_location": ["Germany"],
        "search_limit": ["0"],
    }))

    assert too_high["searches"][0]["limit"] == MAX_SEARCH_LIMIT
    assert too_low["searches"][0]["limit"] == 1


@pytest.mark.unit
async def test_paginated_search_paginates_dedupes_and_stops_at_limit(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _noop_detect_rate_limit)
    page = FakeSearchPage({
        0: [
            "https://www.linkedin.com/jobs/view/1/?tracking=one",
            "/jobs/view/2/?tracking=two",
        ],
        25: [
            "https://www.linkedin.com/jobs/view/2/?tracking=duplicate",
            "https://www.linkedin.com/jobs/view/3/?tracking=three",
        ],
        50: ["https://www.linkedin.com/jobs/view/4/"],
    })
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    result = await scraper.search("python engineer", "Germany", limit=3)

    assert result == [
        "https://www.linkedin.com/jobs/view/1/",
        "https://www.linkedin.com/jobs/view/2/",
        "https://www.linkedin.com/jobs/view/3/",
    ]
    assert [parse_qs(urlparse(url).query).get("start", ["0"])[0] for url in page.goto_urls] == ["0", "25"]


@pytest.mark.unit
async def test_paginated_search_counts_limit_against_store_new_ids(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _noop_detect_rate_limit)
    page = FakeSearchPage({
        0: ["https://www.linkedin.com/jobs/view/1/"],
        25: ["https://www.linkedin.com/jobs/view/2/"],
    })
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    result = await scraper.search(
        "python engineer", "Germany", limit=1, known_ids={"1"},
    )

    assert result == [
        "https://www.linkedin.com/jobs/view/1/",
        "https://www.linkedin.com/jobs/view/2/",
    ]
    assert [parse_qs(urlparse(url).query).get("start", ["0"])[0] for url in page.goto_urls] == ["0", "25"]


@pytest.mark.unit
async def test_paginated_search_continues_past_known_only_pages(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _noop_detect_rate_limit)
    page = FakeSearchPage({
        0: ["https://www.linkedin.com/jobs/view/1/"],
        25: ["https://www.linkedin.com/jobs/view/2/"],
        50: ["https://www.linkedin.com/jobs/view/3/"],
        75: ["https://www.linkedin.com/jobs/view/4/"],
    })
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    result = await scraper.search(
        "python engineer", "Germany", limit=1, known_ids={"1", "2", "3"},
    )

    assert result[-1] == "https://www.linkedin.com/jobs/view/4/"
    assert [parse_qs(urlparse(url).query).get("start", ["0"])[0] for url in page.goto_urls] == ["0", "25", "50", "75"]


@pytest.mark.unit
async def test_paginated_search_stops_after_three_empty_pages(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _noop_detect_rate_limit)
    page = FakeSearchPage({})
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    result = await scraper.search("python engineer", "Germany", limit=10)

    assert result == []
    assert [parse_qs(urlparse(url).query).get("start", ["0"])[0] for url in page.goto_urls] == ["0", "25", "50"]


@pytest.mark.unit
async def test_paginated_search_propagates_rate_limit_failures(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _raise_detect_rate_limit)
    page = FakeSearchPage({
        0: ["https://www.linkedin.com/jobs/view/1/"],
    })
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    with pytest.raises(RuntimeError, match="rate limited"):
        await scraper.search("python engineer", "Germany", limit=1)


@pytest.mark.unit
async def test_pipeline_re_raises_rate_limit_failures(monkeypatch):
    monkeypatch.setattr("mvp.pipeline.PaginatedJobSearch", RateLimitedSearch)

    with pytest.raises(RateLimitError, match="rate limited"):
        await run_pipeline(
            FakeBrowser(),
            searches=[SearchSpec("python", "Germany", 1)],
            store=FakePipelineStore(),
            filter_cfg=FilterConfig.from_dict(None),
            delay_seconds=0,
        )


@pytest.mark.unit
async def test_paginated_search_clamps_to_linkedin_depth_cap(monkeypatch):
    monkeypatch.setattr("mvp.search.detect_rate_limit", _noop_detect_rate_limit)
    page = FakeSearchPage({
        start: [
            f"https://www.linkedin.com/jobs/view/{start + offset}/"
            for offset in range(25)
        ]
        for start in range(0, MAX_SEARCH_LIMIT + 250, 25)
    })
    scraper = PaginatedJobSearch(page, between_page_delay=0)

    result = await scraper.search("python engineer", "Germany", limit=MAX_SEARCH_LIMIT + 500)

    assert len(result) == MAX_SEARCH_LIMIT
    assert len(page.goto_urls) == MAX_SEARCH_LIMIT // 25


@pytest.mark.unit
async def test_geocode_areas_uses_dedicated_disk_cache(monkeypatch, tmp_path: Path):
    calls = []

    def fake_geocode(location: str, *, include_area: bool = False):
        calls.append((location, include_area))
        return {
            "lat": 52.52,
            "lon": 13.405,
            "display_name": location,
            "geojson": {"type": "Point", "coordinates": [13.405, 52.52]},
        }

    monkeypatch.setattr("mvp.web.geocode._geocode_sync", fake_geocode)

    first = await geocode.geocode_areas(["Berlin"], tmp_path)
    second = await geocode.geocode_areas(["Berlin"], tmp_path)

    assert first == second
    assert first["Berlin"]["geojson"]["type"] == "Point"
    assert calls == [("Berlin", True)]
    assert (tmp_path / "geocode_area_cache.json").exists()
