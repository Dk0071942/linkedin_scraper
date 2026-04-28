"""Paginating LinkedIn job search.

The upstream `JobSearchScraper` only loads page 1 of the results (~25 URLs);
that's the cap regardless of the `limit` argument. For "run all day" volume
we walk LinkedIn's `start=N` pagination param, page by page, until either
the requested limit is reached or three consecutive pages return no unique URLs.

Polite by default: a configurable delay (with optional 100%–300% jitter)
runs between pages so the search itself doesn't burst-hit LinkedIn.
"""

import asyncio
import logging
import random
import re
from typing import Optional
from urllib.parse import urlencode

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from linkedin_scraper.core import detect_rate_limit

logger = logging.getLogger(__name__)


_PAGE_SIZE = 25  # LinkedIn paginates by 25 (the `start` param step)
_BASE_URL = "https://www.linkedin.com/jobs/search/"
_EMPTY_STREAK_BREAK = 3  # stop after this many consecutive pages with no new URLs
# LinkedIn caps search depth around 1000 results (~40 pages).
MAX_SEARCH_LIMIT = 1000
_HARD_PAGE_CAP = MAX_SEARCH_LIMIT // _PAGE_SIZE
_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")


class PaginatedJobSearch:
    """Drop-in replacement for `JobSearchScraper` that paginates.

    Args:
        page: Playwright page (must already be authenticated via session).
        between_page_delay: seconds to wait between page fetches.
        randomize_delay: if True, sleep is uniform between 100%–300% of base.
    """

    def __init__(
        self,
        page: Page,
        between_page_delay: float = 2.0,
        randomize_delay: bool = False,
    ):
        self.page = page
        self.between_page_delay = between_page_delay
        self.randomize_delay = randomize_delay

    async def search(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 25,
        known_ids: Optional[set[str]] = None,
    ) -> list[str]:
        """Walk LinkedIn search pages until `limit` *store-new* URLs are found.

        `limit` counts URLs whose job_id is not in `known_ids` — so passing
        the store's existing IDs makes the search keep paginating past
        already-scraped jobs instead of stopping when it has `limit` total.
        Already-known URLs are still returned (the caller can dedupe them
        for free); they just don't count toward the cap or reset the
        empty-streak break.
        """
        if limit <= 0:
            return []
        if limit > MAX_SEARCH_LIMIT:
            logger.warning(
                "search limit %d exceeds LinkedIn depth cap; clamping to %d",
                limit, MAX_SEARCH_LIMIT,
            )
            limit = MAX_SEARCH_LIMIT
        known = known_ids if known_ids is not None else set()

        all_urls: list[str] = []
        seen: set[str] = set()
        new_count = 0  # store-new URLs (drives limit + empty-streak)
        empty_streak = 0

        # In practice each page yields fewer than 25 unique job-view links, so
        # we don't try to compute pages-from-limit. Walk until we have enough,
        # the empty-streak guard fires, or we hit LinkedIn's depth cap.
        for page_idx in range(_HARD_PAGE_CAP):
            if new_count >= limit:
                break

            if page_idx > 0:
                await self._sleep_between_pages()

            start = page_idx * _PAGE_SIZE
            url = self._build_url(keywords, location, start)
            logger.info(
                "search page %d (start=%d, kw=%r, loc=%r, new=%d/%d)",
                page_idx + 1, start, keywords, location, new_count, limit,
            )

            page_urls = await self._fetch_page_urls(url)
            page_new_unknown = 0
            page_unique_count = 0
            for u in page_urls:
                if u in seen:
                    continue
                seen.add(u)
                page_unique_count += 1
                all_urls.append(u)
                m = _JOB_ID_RE.search(u)
                jid = m.group(1) if m else None
                # Unparseable IDs count as unknown — let downstream decide.
                if jid is None or jid not in known:
                    page_new_unknown += 1

            new_count += page_new_unknown

            if page_unique_count == 0:
                empty_streak += 1
                if empty_streak >= _EMPTY_STREAK_BREAK:
                    logger.info(
                        "no unique results for %d pages — stopping pagination",
                        empty_streak,
                    )
                    break
            else:
                empty_streak = 0
        else:
            if new_count < limit:
                logger.warning(
                    "stopped at LinkedIn search depth cap: %d store-new urls "
                    "(%d total) (limit=%d, pages=%d)",
                    new_count, len(all_urls), limit, _HARD_PAGE_CAP,
                )

        logger.info(
            "search complete: %d urls (%d store-new) (kw=%r, loc=%r)",
            len(all_urls), new_count, keywords, location,
        )
        return all_urls

    # --- helpers ---

    def _build_url(
        self,
        keywords: Optional[str],
        location: Optional[str],
        start: int,
    ) -> str:
        params: dict[str, str] = {}
        if keywords:
            params["keywords"] = keywords
        if location:
            params["location"] = location
        if start > 0:
            params["start"] = str(start)
        if not params:
            return _BASE_URL
        return f"{_BASE_URL}?{urlencode(params)}"

    async def _fetch_page_urls(self, url: str) -> list[str]:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await detect_rate_limit(self.page)

        try:
            await self.page.wait_for_selector(
                'a[href*="/jobs/view/"]', timeout=10000,
            )
        except PlaywrightTimeoutError:
            # No results on this page — could mean we paged past the end.
            return []

        # LinkedIn lazy-loads results; nudge the list so all 25 render.
        try:
            await self.page.evaluate("window.scrollTo(0, 600)")
            await self.page.wait_for_timeout(700)
            await self.page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await self.page.wait_for_timeout(900)
        except Exception:
            pass

        urls: list[str] = []
        seen_on_page: set[str] = set()
        try:
            for link in await self.page.locator('a[href*="/jobs/view/"]').all():
                try:
                    href = await link.get_attribute("href")
                except Exception:
                    continue
                if not href or "/jobs/view/" not in href:
                    continue
                clean = href.split("?")[0]
                if not clean.startswith("http"):
                    clean = f"https://www.linkedin.com{clean}"
                if clean in seen_on_page:
                    continue
                seen_on_page.add(clean)
                urls.append(clean)
        except Exception as e:
            logger.warning("URL extraction failed for %s: %s", url, e)
        return urls

    async def _sleep_between_pages(self) -> None:
        if self.randomize_delay:
            t = random.uniform(self.between_page_delay, self.between_page_delay * 3)
        else:
            t = self.between_page_delay
        if t > 0:
            await asyncio.sleep(t)
