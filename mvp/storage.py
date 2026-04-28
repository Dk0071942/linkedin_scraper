"""Per-job file storage + slim summary CSV.

Layout:
    data/
      jobs/<job_id>.json        # full record per kept job
      discarded/<job_id>.json   # filter rejects (still saved for audit + dedup)
      summary.csv               # one row per kept job, no description

Why per-file, not one big JSONL:
  - Each file is small and human-readable; you can open one job in any editor.
  - LLM-friendly — point a tool at a single JSON file to draft a motivation
    letter, update application status, etc.
  - Application state lives inside the same file as the scraped data, so
    one file = one job's complete state.
  - Re-scraping preserves your application progress.
"""

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Iterable, Optional

from .models import Application, JobRecord


SUMMARY_COLUMNS = [
    "job_id",
    "job_title",
    "company",
    "location",
    "workplace_type",
    "employment_type",
    "posted_date",
    "posted_days_ago",
    "applicant_count",
    "status",
    "applied_at",
    "search_keywords",
    "linkedin_url",
]

# Discarded rows omit application columns (always not_applied for these).
DISCARDED_COLUMNS = [
    "job_id",
    "job_title",
    "company",
    "location",
    "workplace_type",
    "employment_type",
    "posted_date",
    "posted_days_ago",
    "applicant_count",
    "search_keywords",
    "linkedin_url",
]


def url_to_id(url: str) -> Optional[str]:
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else None


class JobStore:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.jobs_dir = self.data_dir / "jobs"
        self.discarded_dir = self.data_dir / "discarded"
        self.summary_path = self.data_dir / "summary.csv"
        self.discarded_summary_path = self.data_dir / "discarded.csv"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.discarded_dir.mkdir(parents=True, exist_ok=True)

    # --- Dedup ---

    def _all_seen_ids(self) -> set[str]:
        ids: set[str] = set()
        for d in (self.jobs_dir, self.discarded_dir):
            ids.update(p.stem for p in d.glob("*.json"))
        return ids

    def filter_unseen(self, urls: Iterable[str]) -> list[str]:
        seen = self._all_seen_ids()
        out: list[str] = []
        for u in urls:
            jid = url_to_id(u)
            if jid is None:
                # No parseable id — keep, let it fail downstream rather than dedup wrongly
                out.append(u)
            elif jid not in seen:
                out.append(u)
        return out

    # --- Save ---

    def _existing_application(self, job_id: str) -> Optional[Application]:
        """Look in both dirs for a prior file; return its Application if any."""
        for d in (self.jobs_dir, self.discarded_dir):
            path = d / f"{job_id}.json"
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    app = raw.get("application")
                    if app:
                        return Application(**app)
                except Exception:
                    pass
        return None

    def save(self, job: JobRecord) -> None:
        if not job.job_id:
            raise ValueError(f"Job has no job_id, cannot save: {job.linkedin_url}")

        # Preserve application state across re-scrapes / matched-status changes.
        existing = self._existing_application(job.job_id)
        if existing is not None:
            job.application = existing

        # Choose target dir, remove file from the other dir if present.
        target_dir = self.jobs_dir if job.matched else self.discarded_dir
        other_dir = self.discarded_dir if job.matched else self.jobs_dir
        other_path = other_dir / f"{job.job_id}.json"
        if other_path.exists():
            other_path.unlink()

        path = target_dir / f"{job.job_id}.json"
        path.write_text(
            json.dumps(job.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- Summary CSVs ---

    @staticmethod
    def _row_for(record: dict, *, include_application: bool) -> dict:
        row = {
            "job_id": record.get("job_id"),
            "job_title": record.get("job_title"),
            "company": record.get("company"),
            "location": record.get("location"),
            "workplace_type": record.get("workplace_type"),
            "employment_type": record.get("employment_type"),
            "posted_date": record.get("posted_date"),
            "posted_days_ago": record.get("posted_days_ago"),
            "applicant_count": record.get("applicant_count"),
            "search_keywords": record.get("search_keywords"),
            "linkedin_url": record.get("linkedin_url"),
        }
        if include_application:
            app = record.get("application") or {}
            row["status"] = app.get("status", "not_applied")
            row["applied_at"] = app.get("applied_at")
        return row

    def _write_csv(self, source_dir: Path, out_path: Path,
                   columns: list[str], include_application: bool) -> int:
        rows = []
        for f in sorted(source_dir.glob("*.json")):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append(self._row_for(rec, include_application=include_application))
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def regenerate_summary(self) -> tuple[int, int]:
        """Regenerate both summary.csv (kept jobs) and discarded.csv (rejects).

        Returns (kept_count, discarded_count).
        """
        kept = self._write_csv(
            self.jobs_dir, self.summary_path,
            SUMMARY_COLUMNS, include_application=True,
        )
        discarded = self._write_csv(
            self.discarded_dir, self.discarded_summary_path,
            DISCARDED_COLUMNS, include_application=False,
        )
        return kept, discarded

    # --- Lifecycle ---

    def reset(self) -> None:
        """Wipe per-job files and summary CSVs."""
        for d in (self.jobs_dir, self.discarded_dir):
            if d.exists():
                shutil.rmtree(d)
        for p in (self.summary_path, self.discarded_summary_path):
            if p.exists():
                p.unlink()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.discarded_dir.mkdir(parents=True, exist_ok=True)

    def count(self, matched_only: bool = False) -> int:
        kept = sum(1 for _ in self.jobs_dir.glob("*.json"))
        if matched_only:
            return kept
        return kept + sum(1 for _ in self.discarded_dir.glob("*.json"))

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, *_) -> None:
        return None
