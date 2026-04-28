"""Geocode job-location strings via OpenStreetMap Nominatim.

Point cache lives at ``<data_dir>/geocode_cache.json``; search-area cache lives
at ``<data_dir>/geocode_area_cache.json``. Each maps raw location strings to
either geocode metadata or ``null`` (for misses). Once cached we never re-query;
Nominatim's usage policy caps fresh lookups at 1 req/sec, so this keeps map
loads fast after the first lookup.
"""

import asyncio
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "linkedin-scraper-mvp/1.0 (job-location-map)"


def _cache_path(data_dir: Path, *, area: bool = False) -> Path:
    return data_dir / ("geocode_area_cache.json" if area else "geocode_cache.json")


def load_cache(data_dir: Path, *, area: bool = False) -> dict[str, Optional[dict]]:
    p = _cache_path(data_dir, area=area)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(data_dir: Path, cache: dict, *, area: bool = False) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(data_dir, area=area).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _geocode_sync(location: str, *, include_area: bool = False) -> Optional[dict]:
    params = {"q": location, "format": "json", "limit": 1}
    if include_area:
        params["polygon_geojson"] = 1
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{qs}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not data:
        return None
    item = data[0]
    try:
        return {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "display_name": item.get("display_name") or location,
            **({"geojson": item.get("geojson")} if include_area and item.get("geojson") else {}),
        }
    except (KeyError, ValueError):
        return None


async def geocode_locations(
    locations: list[str], data_dir: Path
) -> dict[str, Optional[dict]]:
    """Resolve every location to a cache entry, fetching uncached ones serially.

    Returns a mapping of input location → cache entry (``None`` for misses).
    Honors Nominatim's 1 req/sec policy by sleeping between fresh lookups.
    """
    cache = load_cache(data_dir)
    fresh = sorted({loc for loc in locations if loc and loc not in cache})
    if fresh:
        for i, loc in enumerate(fresh):
            if i > 0:
                await asyncio.sleep(1.1)
            cache[loc] = await asyncio.to_thread(_geocode_sync, loc)
        save_cache(data_dir, cache)
    return {loc: cache.get(loc) for loc in locations}


async def geocode_areas(
    locations: list[str], data_dir: Path
) -> dict[str, Optional[dict]]:
    """Resolve locations with optional GeoJSON geometry for search-area previews."""
    cache = load_cache(data_dir, area=True)
    fresh = sorted({loc for loc in locations if loc and loc not in cache})
    if fresh:
        for i, loc in enumerate(fresh):
            if i > 0:
                await asyncio.sleep(1.1)
            cache[loc] = await asyncio.to_thread(_geocode_sync, loc, include_area=True)
        save_cache(data_dir, cache, area=True)
    return {loc: cache.get(loc) for loc in locations}
