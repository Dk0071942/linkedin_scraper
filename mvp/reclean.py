"""Retroactively re-trim job_description on every saved per-job file.

Useful when the cruft-marker list in extractor.py grows: instead of re-scraping
every page (slow, hits LinkedIn rate limits), this rewalks data/jobs/ and
data/discarded/, applies clean_description() to each saved description, and
saves any change back. Application state and other fields are untouched.

Run via:
    uv run python -m mvp.reclean
"""

import json
import sys
from pathlib import Path

import yaml

from .extractor import clean_description


def _data_dir() -> Path:
    cfg_path = Path("mvp/config.yaml")
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return Path((cfg.get("scrape") or {}).get("data_dir", "data"))
    return Path("data")


def main() -> int:
    data_dir = _data_dir()
    files = list((data_dir / "jobs").glob("*.json")) + \
            list((data_dir / "discarded").glob("*.json"))
    if not files:
        print(f"No per-job files under {data_dir}.")
        return 0

    changed = 0
    bytes_removed = 0
    for fp in files:
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {fp.name}: {e}")
            continue

        before = rec.get("job_description") or ""
        after = clean_description(before)
        if after != before:
            rec["job_description"] = after
            fp.write_text(
                json.dumps(rec, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            changed += 1
            bytes_removed += len(before) - len(after)
            print(f"  trimmed {fp.relative_to(data_dir)}: -{len(before) - len(after)} chars")

    print(f"\nDone. {changed}/{len(files)} files changed, {bytes_removed:,} chars removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
