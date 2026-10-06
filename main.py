"""Legacy FastAPI worker for the Laravel integration.

Run: uvicorn main:app --port 8001

Superseded by ``omnimodel.api`` (uvicorn omnimodel.api.main:app). Kept because
the Laravel app still points at these four endpoints; everything else should use
``omnimodel.api``.
"""
import os
import re

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from extract import extract_profile, write_pitch
from omnimodel.profile_loader import list_profiles, load_profile
from omnimodel.scoring.profile_scoring import score_lead

app = FastAPI(title="Simba Gate Lead Engine")
API_KEY = os.environ.get("SERVICE_API_KEY", "")
PLACES_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")


def _default_profile() -> str:
    profiles = list_profiles()
    if not profiles:
        raise HTTPException(503, "No business profiles are installed")
    return profiles[0]

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"(?s)<(script|style).*?</\1>")
_TITLE_RE = re.compile(r"(?i)<title>(.*?)</title>")
_BRANCH_RE = re.compile(r"(?i)\bbranch(es)?\b")


def auth(key: str | None):
    if not API_KEY:
        raise HTTPException(503, "SERVICE_API_KEY is not set on the server")
    if key != API_KEY:
        raise HTTPException(401, "bad key")


class DiscoverReq(BaseModel):
    country: str = "Ghana"
    region: str
    city: str
    industry: str


class ProfileReq(BaseModel):
    url: str


@app.post("/discover")
def discover(req: DiscoverReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    if not PLACES_KEY:
        raise HTTPException(503, "GOOGLE_PLACES_API_KEY is not set on the server")
    query = f"{req.industry} companies in {req.city}, {req.region}, {req.country}"
    resp = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "X-Goog-Api-Key": PLACES_KEY,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.websiteUri,places.nationalPhoneNumber"
            ),
        },
        json={"textQuery": query, "pageSize": 20},
        timeout=30,
    )
    resp.raise_for_status()
    out = []
    for place in resp.json().get("places", []):
        location = place.get("location") or {}
        out.append(
            {
                "place_id": place.get("id"),
                "name": (place.get("displayName") or {}).get("text"),
                "address": place.get("formattedAddress"),
                "lat": location.get("latitude"),
                "lng": location.get("longitude"),
                "website": place.get("websiteUri"),
                "phone": place.get("nationalPhoneNumber"),
                "source": "google_places",
                "confidence": 70,
            }
        )
    return out


@app.post("/profile")
def profile(req: ProfileReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    html = requests.get(req.url, timeout=20, follow_redirects=True).text
    text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", html)))
    title = _TITLE_RE.search(html)
    info = extract_profile(text)
    info["title"] = title.group(1).strip() if title else None
    info["branch_mentions"] = len(_BRANCH_RE.findall(text))
    return info


class PitchReq(BaseModel):
    company: dict
    service: str
    risk_notes: list[str] = []


@app.post("/pitch")
def pitch(req: PitchReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    return write_pitch(req.company, req.service, req.risk_notes)


@app.post("/score")
def score(lead: dict, profile: str | None = None, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    stem = profile or _default_profile()
    return score_lead(lead, load_profile(stem))
