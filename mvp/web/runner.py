"""Background scraper runner with multi-subscriber log fanout.

One process-level RunController instance owns the running task and a list of
subscriber queues. Every log line emitted by the scraper is broadcast to all
subscribers (so two browser tabs on /run can both watch live).
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from linkedin_scraper import BrowserManager, is_logged_in, wait_for_manual_login

from ..filters import FilterConfig
from ..pipeline import RunSummary, SearchSpec, run_pipeline
from ..storage import JobStore


_DONE_SENTINEL = "__DONE__"


class _QueueLogHandler(logging.Handler):
    """Log handler that fans every record out via a callback."""

    def __init__(self, broadcast):
        super().__init__()
        self.broadcast = broadcast

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        self.broadcast(msg)


class RunController:
    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None
        self.subscribers: list[asyncio.Queue] = []
        self.log_buffer: list[str] = []
        self.last_summary: Optional[RunSummary] = None
        self.error: Optional[str] = None
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.state: str = "idle"  # idle | logging_in | running | done | error | cancelled

    @property
    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "summary": self.last_summary.__dict__ if self.last_summary else None,
            "log_lines": len(self.log_buffer),
        }

    # --- Logging fanout ---

    def _broadcast(self, line: str) -> None:
        self.log_buffer.append(line)
        if len(self.log_buffer) > 2000:
            self.log_buffer = self.log_buffer[-2000:]
        for q in list(self.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10000)
        for line in self.log_buffer[-200:]:
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                break
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    # --- Lifecycle ---

    async def start_run(self, config_path: Path, rescrape: bool = False) -> None:
        if self.is_running:
            raise RuntimeError("A run is already in progress.")
        self.last_summary = None
        self.error = None
        self.log_buffer = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None
        self.state = "running"
        self.task = asyncio.create_task(self._run_scrape(config_path, rescrape))

    async def start_login(self, session_file: Path) -> None:
        if self.is_running:
            raise RuntimeError("A run is already in progress.")
        self.error = None
        self.log_buffer = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None
        self.state = "logging_in"
        self.task = asyncio.create_task(self._run_login(session_file))

    def cancel(self) -> bool:
        if self.task and not self.task.done():
            self.task.cancel()
            return True
        return False

    # --- Internals ---

    def _attach_handler(self) -> _QueueLogHandler:
        handler = _QueueLogHandler(self._broadcast)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        handler.setLevel(logging.INFO)
        root = logging.getLogger()
        root.addHandler(handler)
        # Make sure the framework's loggers actually emit at INFO
        if root.level > logging.INFO or root.level == 0:
            root.setLevel(logging.INFO)
        return handler

    async def _run_scrape(self, config_path: Path, rescrape: bool) -> None:
        handler = self._attach_handler()
        try:
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            scrape_cfg = cfg.get("scrape") or {}
            session_file = Path(scrape_cfg.get("session_file", "linkedin_session.json"))
            data_dir = scrape_cfg.get("data_dir", "data")
            delay = float(scrape_cfg.get("delay_seconds", 3))
            randomize = bool(scrape_cfg.get("randomize_delay", False))

            raw_searches = cfg.get("searches") or []
            if not raw_searches:
                raise ValueError("No searches defined in config.")
            searches = [
                SearchSpec(
                    keywords=s["keywords"],
                    location=s["location"],
                    limit=int(s.get("limit", 25)),
                )
                for s in raw_searches
            ]
            filter_cfg = FilterConfig.from_dict(cfg.get("filters"))

            self._broadcast(f"Starting run: {len(searches)} search(es), filter={filter_cfg.describe()}")

            if not session_file.exists():
                raise RuntimeError(
                    f"No LinkedIn session at {session_file}. "
                    "Click 'Log in' first, or run `uv run python -m mvp.run` once from the CLI."
                )

            with JobStore(data_dir) as store:
                if rescrape:
                    self._broadcast(f"--rescrape: wiping {data_dir}")
                    store.reset()

                async with BrowserManager(headless=True) as browser:
                    await browser.load_session(str(session_file))
                    await browser.page.goto("https://www.linkedin.com/feed/")
                    await browser.page.wait_for_timeout(1500)
                    if not await is_logged_in(browser.page):
                        raise RuntimeError(
                            "Saved session is stale. Click 'Log in' to refresh it."
                        )
                    summary = await run_pipeline(
                        browser, searches, store, filter_cfg, delay, randomize,
                    )
                    self.last_summary = summary
                    self._broadcast(
                        f"Done. searches={summary.searches_run} "
                        f"urls_found={summary.urls_found} "
                        f"scraped={summary.scraped} "
                        f"matched={summary.matched} "
                        f"failed={summary.failed_scrapes}"
                    )

            self.state = "done"
        except asyncio.CancelledError:
            self._broadcast("Run cancelled.")
            self.state = "cancelled"
            raise
        except Exception as e:
            self.error = str(e)
            self._broadcast(f"ERROR: {e}")
            self.state = "error"
        finally:
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self._broadcast(_DONE_SENTINEL)
            logging.getLogger().removeHandler(handler)

    async def _run_login(self, session_file: Path) -> None:
        handler = self._attach_handler()
        try:
            self._broadcast(
                "Opening Chromium window for LinkedIn login. "
                "Complete the login (incl. 2FA) within 5 minutes."
            )
            async with BrowserManager(headless=False) as browser:
                await browser.page.goto("https://www.linkedin.com/login")
                await wait_for_manual_login(browser.page, timeout=300000)
                await browser.save_session(str(session_file))
                self._broadcast(f"Session saved to {session_file}")
            self.state = "done"
        except asyncio.CancelledError:
            self._broadcast("Login cancelled.")
            self.state = "cancelled"
            raise
        except Exception as e:
            self.error = str(e)
            self._broadcast(f"ERROR: {e}")
            self.state = "error"
        finally:
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self._broadcast(_DONE_SENTINEL)
            logging.getLogger().removeHandler(handler)


# Process-level singleton
controller = RunController()
DONE_SENTINEL = _DONE_SENTINEL
