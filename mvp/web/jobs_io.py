"""Per-job JSON I/O for the web UI."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from ..models import Application, ApplicationEvent, ApplicationStatus, JobRecord
from ..storage import JobStore


def _data_dir_from_config() -> Path:
    cfg_path = Path("mvp/config.yaml")
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return Path((cfg.get("scrape") or {}).get("data_dir", "data"))
    return Path("data")


def store() -> JobStore:
    return JobStore(str(_data_dir_from_config()))


def list_jobs(*, discarded: bool = False) -> list[dict[str, Any]]:
    s = store()
    src = s.discarded_dir if discarded else s.jobs_dir
    out = []
    for f in sorted(src.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    # Sort: most-recently-posted first
    out.sort(key=lambda r: (r.get("posted_days_ago") if r.get("posted_days_ago") is not None else 9999))
    return out


def get_job(job_id: str) -> tuple[Optional[dict[str, Any]], Optional[Path]]:
    s = store()
    for d in (s.jobs_dir, s.discarded_dir):
        path = d / f"{job_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")), path
            except Exception:
                return None, None
    return None, None


def update_application(
    job_id: str,
    *,
    status: Optional[str] = None,
    motivation_letter: Optional[str] = None,
    cv_version: Optional[str] = None,
    applied_at: Optional[str] = None,
    rejected_at: Optional[str] = None,
    accepted_at: Optional[str] = None,
    notes: Optional[str] = None,
    add_history_event: Optional[str] = None,
    history_notes: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    rec, path = get_job(job_id)
    if rec is None or path is None:
        return None
    app = Application(**(rec.get("application") or {}))

    if status is not None and status:
        try:
            app.status = ApplicationStatus(status)
        except ValueError:
            pass
    if motivation_letter is not None:
        app.motivation_letter = motivation_letter or None
    if cv_version is not None:
        app.cv_version = cv_version or None
    if applied_at is not None:
        app.applied_at = applied_at or None
    if rejected_at is not None:
        app.rejected_at = rejected_at or None
    if accepted_at is not None:
        app.accepted_at = accepted_at or None
    if notes is not None:
        app.notes = notes or None
    if add_history_event:
        app.history.append(ApplicationEvent(
            event=add_history_event,
            notes=history_notes or None,
        ))

    rec["application"] = json.loads(app.model_dump_json())
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    return rec


def restore_from_discarded(job_id: str) -> bool:
    """Move a job from discarded/ to jobs/, overriding the filter."""
    s = store()
    src = s.discarded_dir / f"{job_id}.json"
    if not src.exists():
        return False
    try:
        rec = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return False
    rec["matched"] = True
    job = JobRecord(**rec)
    s.save(job)
    return True


def discard(job_id: str) -> bool:
    """Move a job from jobs/ to discarded/."""
    s = store()
    src = s.jobs_dir / f"{job_id}.json"
    if not src.exists():
        return False
    try:
        rec = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return False
    rec["matched"] = False
    job = JobRecord(**rec)
    s.save(job)
    return True


def regenerate_summaries() -> tuple[int, int]:
    return store().regenerate_summary()
