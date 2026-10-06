"""The logic behind the API, in plain Python (no web code).

main.py only turns these functions into web endpoints.
"""
from __future__ import annotations

import asyncio
import ipaddress
import textwrap
from functools import lru_cache
from urllib.parse import urlparse

from omnimodel.export import export_docx, export_pdf, export_txt
from omnimodel.extraction.factory import available_backends, get_extractor
from omnimodel.places.google_places import search_by_location
from omnimodel.profile_loader import list_profiles, load_profile
from omnimodel.scoring.profile_scoring import (
    best_offering,
    lead_from_signals,
    score_lead,
)
from omnimodel.scraping.playwright_scraper import fetch_pages
from omnimodel.templates.profile_templates import render

MAX_PLACES_RESULTS = 20


class NotFound(Exception):
    """Profile or place does not exist. Becomes HTTP 404."""


class BadInput(Exception):
    """The request was malformed. Becomes HTTP 422."""


class Upstream(Exception):
    """Google, the website, or the LLM failed. Becomes HTTP 502."""


# ---------------------------------------------------------------- profiles
def get_profile(name: str) -> dict:
    # Checking the stem against the known list also stops "../" tricks in the name.
    if name not in list_profiles():
        raise NotFound(
            f"Unknown profile '{name}'. Available: {', '.join(list_profiles())}"
        )
    try:
        return load_profile(name)
    except (ValueError, OSError) as exc:
        raise BadInput(f"Profile '{name}' is not usable: {exc}") from exc


def public_profile(name: str) -> dict:
    """What a frontend needs to build its dropdowns.

    Outreach templates stay on the server.
    """
    p = get_profile(name)
    return {
        "id": name,
        "name": p["name"],
        "country": p["country"],
        "business": p["business"],
        "offerings": {k: v["label"] for k, v in p["offerings"].items()},
        "sectors": {k: v["label"] for k, v in p["sectors"].items()},
        "geography": p["geography"],
    }


# ---------------------------------------------------------------- scoring helper
def _scored(P: dict, lead: dict, signals: dict | None, cluster_size: int) -> dict:
    scores = score_lead(
        lead_from_signals(signals, lead.get("sector"), cluster_size, lead, P), P
    )
    best = best_offering(scores)
    return {
        "scores": {
            k: {"label": P["offerings"][k]["label"], **v} for k, v in scores.items()
        },
        "best_offering": best,
    }


# ---------------------------------------------------------------- search
@lru_cache(maxsize=128)  # repeat searches are free; the cache clears on restart
def _places(query: str, location: str, n: int) -> tuple:
    return tuple(search_by_location(query, location, max_results=n))


def search_leads(
    profile: str, region: str, city: str, sector: str, max_results: int
) -> dict:
    P = get_profile(profile)
    if region not in P["geography"]:
        raise BadInput(
            f"Unknown region '{region}' for this profile. "
            f"Known: {', '.join(P['geography'])}"
        )
    if sector not in P["sectors"]:
        raise BadInput(
            f"Unknown sector '{sector}' for this profile. "
            f"Known: {', '.join(P['sectors'])}"
        )
    if not (city or "").strip():
        raise BadInput("City is required.")
    n = max(1, min(int(max_results), MAX_PLACES_RESULTS))
    location = f"{city}, {region}, {P['country']}"
    try:
        raw = _places(P["sectors"][sector]["query"], location, n)
    except RuntimeError as exc:  # e.g. GOOGLE_PLACES_API_KEY missing
        raise Upstream(str(exc)) from exc
    except Exception as exc:
        raise Upstream(f"Google Places search failed: {exc}") from exc
    leads = []
    for p in raw:
        lead = {
            "id": p.get("id"),
            "name": (p.get("displayName") or {}).get("text"),
            "address": p.get("formattedAddress"),
            "phone": p.get("nationalPhoneNumber"),
            "website": p.get("websiteUri"),
            "rating": p.get("rating"),
            "review_count": p.get("userRatingCount"),
            "region": region,
            "city": city,
            "sector": sector,
        }
        leads.append({**lead, **_scored(P, lead, None, len(raw) - 1)})
    leads.sort(
        key=lambda x: x["scores"].get(x["best_offering"], {}).get("score", 0.0),
        reverse=True,
    )
    return {"profile": profile, "count": len(leads), "leads": leads}


# ---------------------------------------------------------------- analyze a website
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".home.arpa")


def _check_url(url: str) -> None:
    """Reject anything that is not a public http(s) URL.

    Blocks literal private/loopback/link-local/reserved addresses and internal
    hostnames. This cannot see through DNS, so a public name that resolves to a
    private address is still reachable; put the API behind auth before exposing
    it.
    """
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise BadInput("URL must start with http:// or https://")
    host = u.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise BadInput("That address is not allowed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a normal domain name
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise BadInput("That address is not allowed.")


def _scrape(urls: list[str]) -> dict[str, str]:
    """Run the async scraper on a private event loop.

    Windows already defaults to the Proactor loop, which Playwright needs, so
    no policy override is required here.
    """
    with asyncio.Runner() as runner:
        return runner.run(fetch_pages(urls))


def analyze_url(
    profile: str,
    url: str,
    sector: str,
    region: str,
    city: str,
    name: str | None = None,
    review_count: int | None = None,
    backend: str | None = None,
) -> dict:
    P = get_profile(profile)
    if sector not in P["sectors"]:
        raise BadInput(
            f"Unknown sector '{sector}' for this profile. "
            f"Known: {', '.join(P['sectors'])}"
        )
    _check_url(url)
    if backend and backend not in available_backends():
        raise BadInput(
            f"Backend '{backend}' is not configured. "
            f"Available: {', '.join(available_backends())}"
        )
    text = _scrape([url]).get(url, "")
    if not text.strip():
        raise Upstream("Could not read any content from that website.")
    try:
        signals = get_extractor(backend)(text, signal_schema=P["signal_schema"]) or {}
    except Exception as exc:
        raise Upstream(f"Signal extraction failed: {exc}") from exc
    lead = {
        "name": name,
        "website": url,
        "region": region,
        "city": city,
        "sector": sector,
        "review_count": review_count,
    }
    out = {"url": url, "signals": signals, **_scored(P, lead, signals, 0)}
    if "_raw" in signals:
        out["warning"] = "The model did not return valid JSON, so no signals were used."
    return out


# ---------------------------------------------------------------- outreach and export
def make_outreach(
    profile: str,
    kind: str,
    offering: str,
    lead: dict,
    business: dict | None = None,
) -> str:
    P = get_profile(profile)
    if kind not in ("email", "proposal", "followup"):
        raise BadInput("kind must be email, proposal or followup.")
    if offering not in P["offerings"]:
        raise BadInput(
            f"Unknown offering '{offering}'. Known: {', '.join(P['offerings'])}"
        )
    lead = {"region": "", "sector": "", "city": "", **(lead or {})}
    biz = {**P["business"], **(business or {})}
    try:
        return render(P, kind, lead, offering, biz)
    except KeyError as exc:
        raise BadInput(f"Cannot render {kind}: {exc}") from exc


def make_export(text: str, fmt: str, title: str = "Proposal") -> tuple[bytes, str]:
    if fmt == "pdf":
        wrapped = "\n".join(
            textwrap.fill(line, 85) if line.strip() else "" for line in text.split("\n")
        )
        return export_pdf(wrapped), "application/pdf"
    if fmt == "docx":
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return export_docx(text, title), media
    if fmt == "txt":
        return export_txt(text), "text/plain; charset=utf-8"
    raise BadInput("format must be pdf, docx or txt.")
