"""Load + save mvp/config.yaml from the web form.

Form encoding strategy:
- Searches use repeated names: `search_keywords`, `search_location`, `search_limit`.
  Browsers submit them in DOM order; we zip them. Empty rows are skipped.
- Filter list fields use textareas with one keyword per line.
- Booleans use checkboxes; absent = false.
- Numeric fields are blank-tolerant (empty string = unset).
"""

from pathlib import Path
from typing import Any, Optional

import yaml

from ..search import MAX_SEARCH_LIMIT


CONFIG_PATH = Path("mvp/config.yaml")


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _join_lines(items: Optional[list[str]]) -> str:
    return "\n".join(items or [])


def _parse_search_limit(value: Any) -> int:
    try:
        limit = int(value) if value else 25
    except (TypeError, ValueError):
        limit = 25
    return max(1, min(limit, MAX_SEARCH_LIMIT))


def load_raw() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def to_form_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """Shape a config dict into per-field strings/bools the template renders."""
    searches = [
        {**s, "limit": _parse_search_limit(s.get("limit", 25))}
        for s in (cfg.get("searches") or [])
    ]
    filters = cfg.get("filters") or {}
    scrape = cfg.get("scrape") or {}

    def text_filter(key: str) -> dict[str, str]:
        d = filters.get(key) or {}
        return {
            "include": _join_lines(d.get("include")),
            "exclude": _join_lines(d.get("exclude")),
        }

    def cat_filter(key: str) -> str:
        d = filters.get(key) or {}
        return _join_lines(d.get("in"))

    pd = filters.get("posted_date") or {}

    return {
        "searches": searches,
        "filters": {
            "job_title": text_filter("job_title"),
            "location": text_filter("location"),
            "job_description": text_filter("job_description"),
            "workplace_type_in": cat_filter("workplace_type"),
            "employment_type_in": cat_filter("employment_type"),
            "posted_within_days": pd.get("within_days") if pd.get("within_days") is not None else "",
            "case_sensitive": bool(filters.get("case_sensitive", False)),
        },
        "scrape": {
            "delay_seconds": scrape.get("delay_seconds", 10),
            "randomize_delay": bool(scrape.get("randomize_delay", True)),
            "session_file": scrape.get("session_file", "linkedin_session.json"),
            "data_dir": scrape.get("data_dir", "data"),
        },
    }


def from_form(form: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a config dict from form fields."""
    keywords = form.getlist("search_keywords") if hasattr(form, "getlist") else form.get("search_keywords", [])
    locations = form.getlist("search_location") if hasattr(form, "getlist") else form.get("search_location", [])
    limits = form.getlist("search_limit") if hasattr(form, "getlist") else form.get("search_limit", [])

    searches: list[dict[str, Any]] = []
    for kw, loc, lim in zip(keywords, locations, limits):
        kw = (kw or "").strip()
        loc = (loc or "").strip()
        if not kw and not loc:
            continue  # skip empty rows
        lim_int = _parse_search_limit(lim)
        searches.append({"keywords": kw, "location": loc, "limit": lim_int})

    def text_block(prefix: str) -> dict[str, list[str]]:
        return {
            "include": _split_lines(form.get(f"{prefix}_include", "")),
            "exclude": _split_lines(form.get(f"{prefix}_exclude", "")),
        }

    filters: dict[str, Any] = {}
    for key in ("job_title", "location", "job_description"):
        block = text_block(f"filter_{key}")
        if block["include"] or block["exclude"]:
            # Drop empty lists for tidier YAML
            f = {}
            if block["include"]: f["include"] = block["include"]
            if block["exclude"]: f["exclude"] = block["exclude"]
            filters[key] = f

    for cat_key, form_key in [("workplace_type", "filter_workplace_type_in"),
                              ("employment_type", "filter_employment_type_in")]:
        items = _split_lines(form.get(form_key, ""))
        if items:
            filters[cat_key] = {"in": items}

    within = (form.get("filter_posted_within_days") or "").strip()
    if within:
        try:
            filters["posted_date"] = {"within_days": float(within)}
        except ValueError:
            pass

    if form.get("filter_case_sensitive"):
        filters["case_sensitive"] = True

    scrape: dict[str, Any] = {
        "delay_seconds": float(form.get("scrape_delay_seconds") or 10),
        "randomize_delay": bool(form.get("scrape_randomize_delay")),
        "session_file": (form.get("scrape_session_file") or "linkedin_session.json").strip(),
        "data_dir": (form.get("scrape_data_dir") or "data").strip(),
    }

    out: dict[str, Any] = {"searches": searches}
    if filters:
        out["filters"] = filters
    out["scrape"] = scrape
    return out


def save(cfg: dict[str, Any]) -> None:
    """Atomic write: temp file + rename, with a .bak backup of the previous version."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    yaml_text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    tmp.write_text(yaml_text, encoding="utf-8")
    if CONFIG_PATH.exists():
        bak = CONFIG_PATH.with_suffix(".yaml.bak")
        CONFIG_PATH.replace(bak)
    tmp.replace(CONFIG_PATH)
