"""Google Places search that follows result pages, so one search can return more than 20 companies.
Google allows at most 60 results per search (3 pages of 20). To go beyond that you need several different searches."""
from __future__ import annotations

import logging
import os

import requests

from ..config import config

logger = logging.getLogger("omnimodel")

GOOGLE_LIMIT = 60   # Google's own ceiling for one text search
PAGE_SIZE = 20
_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELDS = (
    "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.rating,"
    "places.userRatingCount,places.nationalPhoneNumber,places.websiteUri,nextPageToken"
)


def hard_cap() -> int:
    """The most results one search may return. Lower it with PLACES_MAX_RESULTS to limit Google costs."""
    try:
        cap = int(os.getenv("PLACES_MAX_RESULTS", GOOGLE_LIMIT))
    except ValueError:
        cap = GOOGLE_LIMIT
    return max(1, min(cap, GOOGLE_LIMIT))


def search_all(query: str, location: str, max_results: int | None = None) -> list[dict]:
    """Search for `query` in `location`. max_results=None means everything Google will return (up to hard_cap())."""
    if not config.google_places_api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not set. Add it to your environment or .env.")
    wanted = hard_cap() if not max_results else min(int(max_results), hard_cap())
    headers = {"X-Goog-Api-Key": config.google_places_api_key, "X-Goog-FieldMask": _FIELDS, "Content-Type": "application/json"}
    body = {"textQuery": f"{query} in {location}", "pageSize": min(wanted, PAGE_SIZE)}  # pageSize must stay the same on every page

    places, seen = [], set()
    for _ in range(GOOGLE_LIMIT // PAGE_SIZE):
        resp = requests.post(_URL, headers=headers, json=body, timeout=config.http_timeout_s)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            if places:  # keep what we already have if a later page fails
                logger.warning("Places paging stopped early: HTTP %s", resp.status_code)
                break
            raise
        data = resp.json()
        for p in data.get("places", []):
            pid = p.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                places.append(p)
        token = data.get("nextPageToken")
        if not token or len(places) >= wanted:
            break
        body["pageToken"] = token
    return places[:wanted]