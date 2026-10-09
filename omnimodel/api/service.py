"""The logic behind the API, in plain Python (no web code). main.py only turns these into web endpoints."""
from __future__ import annotations

import asyncio
import ipaddress
import sys
import textwrap
from functools import lru_cache
from urllib.parse import urlparse

from omnimodel.export import export_docx, export_pdf, export_txt
from omnimodel.extraction.factory import available_backends, get_extractor
from omnimodel.places.google_places import search_by_location
from omnimodel.profile_loader import list_profiles, load_profile, normalize_profile
from omnimodel.scraping.playwright_scraper import fetch_pages
from omnimodel.scoring.profile_scoring import best_offering, lead_from_signals, score_lead
from omnimodel.templates.profile_templates import render


class NotFound(Exception):   # becomes HTTP 404
    pass


class BadInput(Exception):   # becomes HTTP 422
    pass


class Upstream(Exception):   # becomes HTTP 502 (Google, the website, or the LLM failed)
    pass


# ---------------------------------------------------------------- profiles
def get_profile(profile) -> dict:
    """`profile` is either the id of a server profile (text) or a full profile object sent by the frontend."""
    if isinstance(profile, dict):
        try:
            return normalize_profile(profile)
        except ValueError as exc:
            raise BadInput(f"Invalid profile: {exc}")
    if profile not in list_profiles():  # also stops "../" tricks in the name
        raise NotFound(f"Unknown profile '{profile}'. Available: {', '.join(list_profiles())}")
    return load_profile(profile)


def public_profile(name: str) -> dict:
    """What a frontend needs to build its dropdowns. Outreach templates stay on the server."""
    p = get_profile(name)
    return {"id": name, "name": p["name"], "country": p["country"], "business": p["business"],
            "offerings": {k: v["label"] for k, v in p["offerings"].items()},
            "sectors": {k: v["label"] for k, v in p["sectors"].items()},
            "geography": p["geography"]}


# ---------------------------------------------------------------- scoring helper
def _scored(P: dict, lead: dict, signals: dict | None, cluster_size: int) -> dict:
    scores = score_lead(lead_from_signals(signals, lead["sector"], cluster_size, lead, P), P)
    best = best_offering(scores)
    return {"scores": {k: {"label": P["offerings"][k]["label"], **v} for k, v in scores.items()}, "best_offering": best}


# ---------------------------------------------------------------- search
@lru_cache(maxsize=128)  # repeat searches are free; the cache clears when the server restarts
def _places(query: str, location: str, n: int) -> tuple:
    return tuple(search_by_location(query, location, max_results=n))


def search_leads(profile, region: str, city: str, sector: str, max_results: int) -> dict:
    P = get_profile(profile)
    if region not in P["geography"]:
        raise BadInput(f"Unknown region '{region}' for this profile.")
    if sector not in P["sectors"]:
        raise BadInput(f"Unknown sector '{sector}' for this profile.")
    if not city.strip():
        raise BadInput("City is required.")
    try:
        raw = _places(P["sectors"][sector]["query"], f"{city}, {region}, {P['country']}", max_results)
    except RuntimeError as exc:  # e.g. GOOGLE_PLACES_API_KEY missing
        raise Upstream(str(exc))
    except Exception as exc:
        raise Upstream(f"Google Places search failed: {exc}")
    leads = []
    for p in raw:
        lead = dict(id=p.get("id"), name=(p.get("displayName") or {}).get("text"), address=p.get("formattedAddress"),
                    phone=p.get("nationalPhoneNumber"), website=p.get("websiteUri"), rating=p.get("rating"),
                    review_count=p.get("userRatingCount"), region=region, city=city, sector=sector)
        leads.append({**lead, **_scored(P, lead, None, len(raw) - 1)})
    leads.sort(key=lambda x: x["scores"][x["best_offering"]]["score"], reverse=True)
    return {"profile": profile if isinstance(profile, str) else P["name"], "count": len(leads), "leads": leads}


# ---------------------------------------------------------------- analyze a website
def _check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise BadInput("URL must start with http:// or https://")
    host = u.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise BadInput("That address is not allowed.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise BadInput("That address is not allowed.")
    except ValueError:
        pass  # a normal domain name


def _scrape(urls: list[str]) -> dict[str, str]:
    """Playwright needs its own event loop; on Windows it must be the Proactor one."""
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(fetch_pages(urls))
    finally:
        loop.close()


def analyze_url(profile, url: str, sector: str, region: str, city: str,
                name: str | None = None, review_count: int | None = None, backend: str | None = None) -> dict:
    P = get_profile(profile)
    if sector not in P["sectors"]:
        raise BadInput(f"Unknown sector '{sector}' for this profile.")
    _check_url(url)
    if backend and backend not in available_backends():
        raise BadInput(f"Backend '{backend}' is not configured. Available: {', '.join(available_backends())}")
    text = _scrape([url]).get(url, "")
    if not text:
        raise Upstream("Could not read any content from that website.")
    try:
        signals = get_extractor(backend)(text, signal_schema=P["signal_schema"]) or {}
    except Exception as exc:
        raise Upstream(f"Signal extraction failed: {exc}")
    lead = dict(name=name, website=url, region=region, city=city, sector=sector, review_count=review_count)
    out = {"url": url, "signals": signals, **_scored(P, lead, signals, 0)}
    if "_raw" in signals:
        out["warning"] = "The model did not return valid JSON, so no signals were used."
    return out


# ---------------------------------------------------------------- outreach and export
def make_outreach(profile, kind: str, offering: str, lead: dict, business: dict | None) -> str:
    P = get_profile(profile)
    if kind not in ("email", "proposal", "followup"):
        raise BadInput("kind must be email, proposal or followup.")
    if offering not in P["offerings"]:
        raise BadInput(f"Unknown offering '{offering}' for this profile.")
    lead = {"region": "", "sector": "", "city": "", **lead}
    return render(P, kind, lead, offering, {**P["business"], **(business or {})})


def make_export(text: str, fmt: str, title: str) -> tuple[bytes, str]:
    if fmt == "pdf":
        wrapped = "\n".join(textwrap.fill(line, 85) if line.strip() else "" for line in text.split("\n"))
        return export_pdf(wrapped), "application/pdf"
    if fmt == "docx":
        return export_docx(text, title), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return export_txt(text), "text/plain; charset=utf-8"
