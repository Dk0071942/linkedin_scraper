"""MVP entrypoint.

Usage:
    uv run python -m mvp.run                  # uses mvp/config.yaml
    uv run python -m mvp.run --rescrape       # wipe data/ and re-run all searches
    uv run python -m mvp.run path/to/cfg.yaml
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from linkedin_scraper import BrowserManager, is_logged_in, wait_for_manual_login

from .filters import FilterConfig
from .pipeline import SearchSpec, run_pipeline
from .storage import JobStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mvp")


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(
            f"Config not found: {path}\n"
            f"Copy mvp/config.example.yaml to {path} and edit."
        )
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def ensure_session(session_file: Path) -> None:
    """If session is missing or stale, open a visible browser for manual login."""
    needs_login = not session_file.exists()
    if not needs_login:
        async with BrowserManager(headless=True) as browser:
            await browser.load_session(str(session_file))
            await browser.page.goto("https://www.linkedin.com/feed/")
            if not await is_logged_in(browser.page):
                logger.warning("Existing session is stale, will re-login.")
                needs_login = True

    if not needs_login:
        return

    print("=" * 60)
    print("No valid LinkedIn session found.")
    print("A browser window will open. Log in to LinkedIn manually.")
    print("=" * 60)

    async with BrowserManager(headless=False) as browser:
        await browser.page.goto("https://www.linkedin.com/login")
        await wait_for_manual_login(browser.page, timeout=300000)
        await browser.save_session(str(session_file))
        logger.info("Session saved to %s", session_file)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "config", nargs="?", default="mvp/config.yaml",
        help="Path to config YAML (default: mvp/config.yaml)",
    )
    p.add_argument(
        "--rescrape", action="store_true",
        help="Wipe data/jobs.jsonl and data/jobs.db before running, "
             "so all jobs get re-scraped from scratch.",
    )
    return p.parse_args()


async def main(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config))
    scrape_cfg = cfg.get("scrape", {})

    session_file = Path(scrape_cfg.get("session_file", "linkedin_session.json"))
    delay_seconds = float(scrape_cfg.get("delay_seconds", 3))
    randomize_delay = bool(scrape_cfg.get("randomize_delay", False))
    data_dir = scrape_cfg.get("data_dir", "data")

    raw_searches = cfg.get("searches") or []
    if not raw_searches:
        sys.exit("No searches defined in config.")
    searches = [
        SearchSpec(
            keywords=s["keywords"],
            location=s["location"],
            limit=int(s.get("limit", 25)),
        )
        for s in raw_searches
    ]

    filter_cfg = FilterConfig.from_dict(cfg.get("filters"))
    if filter_cfg.is_active:
        logger.info("Filter active: %s", filter_cfg.describe())
    else:
        logger.info("No filter configured — every scraped job will be kept.")

    await ensure_session(session_file)

    with JobStore(data_dir) as store:
        if args.rescrape:
            logger.warning("--rescrape: wiping %s", data_dir)
            store.reset()

        async with BrowserManager(headless=True) as browser:
            await browser.load_session(str(session_file))
            summary = await run_pipeline(
                browser, searches, store, filter_cfg,
                delay_seconds, randomize_delay,
            )

        total_in_store = store.count()
        total_matched = store.count(matched_only=True)

    print("\n" + "=" * 60)
    print(f"Searches run:      {summary.searches_run}")
    print(f"URLs found:        {summary.urls_found}")
    print(f"New URLs scraped:  {summary.scraped}")
    print(f"Matched filter:    {summary.matched}")
    print(f"Failed scrapes:    {summary.failed_scrapes}")
    print(f"Lifetime kept:     {total_matched} / {total_in_store} scraped")
    print(f"Per-job records:   {data_dir}/jobs/<id>.json")
    print(f"Discarded:         {data_dir}/discarded/<id>.json")
    print(f"Summary CSV:       {data_dir}/summary.csv")
    print(f"Discarded CSV:     {data_dir}/discarded.csv")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
