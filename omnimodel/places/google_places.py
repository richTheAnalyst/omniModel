"""Google Places API ingestion.

Wraps the Google Places API (New) to search for and retrieve place details.
Supports location-biased search by country, city, or town.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from ..config import config

logger = logging.getLogger("omnimodel")

_PLACES_BASE = "https://places.googleapis.com/v1"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_places(
    query: str,
    *,
    max_results: int = 20,
    location_bias: tuple[float, float] | None = None,
    radius_m: int = 50_000,
    location_description: str | None = None,
) -> list[dict[str, Any]]:
    """Text-search Google Places for a query string.

    Parameters
    ----------
    query:
        Search query (e.g. "coffee shop", "plumber").
    max_results:
        Max number of results (capped at 20 per request).
    location_bias:
        Optional (lat, lng) to bias results toward.
    radius_m:
        Search radius in meters when location_bias is set.
    location_description:
        Optional human-readable location (e.g. "Seattle, WA"). Used only for
        logging; geocoding happens in the CLI layer.

    Returns
    -------
    list[dict]
        List of place dicts.
    """
    if not config.google_places_api_key:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Add it to your environment or .env."
        )

    headers = {
        "X-Goog-Api-Key": config.google_places_api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.types,places.rating,"
            "places.userRatingCount,places.nationalPhoneNumber,places.websiteUri"
        ),
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "textQuery": query,
        "pageSize": min(max_results, 20),
    }
    if location_bias:
        body["locationBias"] = {
            "circle": {
                "center": {
                    "latitude": location_bias[0],
                    "longitude": location_bias[1],
                },
                "radius": radius_m,
            }
        }

    logger.debug(
        "Searching Places: query=%r location=%r radius=%d",
        query, location_description or location_bias, radius_m,
    )

    resp = requests.post(
        f"{_PLACES_BASE}/places:searchText",
        headers=headers,
        json=body,
        timeout=config.http_timeout_s,
    )
    resp.raise_for_status()
    return resp.json().get("places", [])[:max_results]


def search_by_location(
    query: str,
    location: str,
    *,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """Search Places filtered by country, city, or town.

    The location is appended to the query (e.g. "coffee shop Seattle, WA").
    Google Places text search understands natural language location filters.
    """
    full_query = f"{query} in {location}"
    return search_places(
        full_query,
        max_results=max_results,
        location_description=location,
    )


# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------
def get_place(place_id: str) -> dict[str, Any]:
    """Fetch full details for a single place by ID."""
    if not config.google_places_api_key:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Add it to your environment or .env."
        )

    headers = {
        "X-Goog-FieldMask": (
            "id,displayName,formattedAddress,location,rating,"
            "userRatingCount,nationalPhoneNumber,websiteUri,types"
        ),
    }
    resp = requests.get(
        f"{_PLACES_BASE}/places/{place_id}",
        params={"key": config.google_places_api_key},
        headers=headers,
        timeout=config.http_timeout_s,
    )
    resp.raise_for_status()
    return resp.json()


def get_place_contacts(place_id: str) -> dict[str, Any]:
    """Fetch contact details for a place.

    Returns a dict with keys: id, name, phone, website, address, types,
    rating, review_count.
    """
    place = get_place(place_id)
    return {
        "id": place.get("id"),
        "name": (place.get("displayName") or {}).get("text"),
        "phone": place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "address": place.get("formattedAddress"),
        "location": place.get("location"),
        "types": place.get("types"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
    }
