"""Search → scrape → filter → save loop. One pipeline per config run."""

import asyncio
import logging
import random
from dataclasses import dataclass

from linkedin_scraper import AuthenticationError, BrowserManager, RateLimitError

from .extractor import RichJobScraper
from .filters import FilterConfig, evaluate
from .search import PaginatedJobSearch
from .storage import JobStore

logger = logging.getLogger(__name__)


@dataclass
class SearchSpec:
    keywords: str
    location: str
    limit: int = 25


@dataclass
class RunSummary:
    searches_run: int = 0
    urls_found: int = 0
    new_urls: int = 0
    scraped: int = 0
    matched: int = 0
    failed_scrapes: int = 0


async def run_pipeline(
    browser: BrowserManager,
    searches: list[SearchSpec],
    store: JobStore,
    filter_cfg: FilterConfig,
    delay_seconds: float = 3.0,
    randomize_delay: bool = False,
) -> RunSummary:
    summary = RunSummary()

    # Reuse the same delay config to space out search-page fetches too —
    # otherwise a 1000-result limit would burst LinkedIn with 40 page loads.
    search_scraper = PaginatedJobSearch(
        browser.page,
        between_page_delay=delay_seconds,
        randomize_delay=randomize_delay,
    )
    job_scraper = RichJobScraper(browser.page)

    for spec in searches:
        summary.searches_run += 1
        logger.info(
            "Searching: keywords=%r location=%r limit=%d",
            spec.keywords, spec.location, spec.limit,
        )

        try:
            # Snapshot known IDs per-search: jobs saved during earlier
            # searches in this run should count as "already in store" too.
            urls = await search_scraper.search(
                keywords=spec.keywords,
                location=spec.location,
                limit=spec.limit,
                known_ids=store.all_seen_ids(),
            )
        except (AuthenticationError, RateLimitError):
            logger.exception(
                "Search aborted for %r/%r due to authentication/rate-limit state",
                spec.keywords, spec.location,
            )
            raise
        except Exception as e:
            logger.error("Search failed for %r/%r: %s", spec.keywords, spec.location, e)
            continue

        summary.urls_found += len(urls)
        new_urls = store.filter_unseen(urls)
        summary.new_urls += len(new_urls)
        logger.info("Found %d urls, %d new", len(urls), len(new_urls))

        for url in new_urls:
            try:
                job = await job_scraper.scrape(
                    url,
                    search_keywords=spec.keywords,
                    search_location=spec.location,
                )
                summary.scraped += 1

                job.matched = evaluate(job, filter_cfg)
                store.save(job)
                if job.matched:
                    summary.matched += 1
                    logger.info(
                        "MATCH: %r at %r [%s, %s]",
                        job.job_title, job.company,
                        job.workplace_type, job.employment_type,
                    )
                else:
                    logger.debug(
                        "skip (no match): %r at %r", job.job_title, job.company,
                    )
            except Exception as e:
                summary.failed_scrapes += 1
                logger.warning("Failed to scrape %s: %s", url, e)

            if randomize_delay:
                sleep_for = random.uniform(delay_seconds, delay_seconds * 3)
            else:
                sleep_for = delay_seconds
            logger.debug("Sleeping %.2fs", sleep_for)
            await asyncio.sleep(sleep_for)

    store.regenerate_summary()
    return summary
