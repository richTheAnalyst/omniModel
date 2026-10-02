"""FastAPI worker. Laravel calls it with X-API-Key. Run: uvicorn main:app --port 8001"""
import os, re
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from scoring import score_lead
from extract import extract_profile, write_pitch

app = FastAPI(title="Simba Gate Lead Engine")
API_KEY = os.environ["SERVICE_API_KEY"]
PLACES_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")

def auth(key: str | None):
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
async def discover(req: DiscoverReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    q = f"{req.industry} companies in {req.city}, {req.region}, {req.country}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={"X-Goog-Api-Key": PLACES_KEY,
                     "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,"
                                         "places.location,places.websiteUri,places.nationalPhoneNumber"},
            json={"textQuery": q, "pageSize": 20})
        r.raise_for_status()
    return [{"place_id": p["id"], "name": p["displayName"]["text"],
             "address": p.get("formattedAddress"), "lat": p["location"]["latitude"],
             "lng": p["location"]["longitude"], "website": p.get("websiteUri"),
             "phone": p.get("nationalPhoneNumber"), "source": "google_places", "confidence": 70}
            for p in r.json().get("places", [])]

@app.post("/profile")
async def profile(req: ProfileReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        html = (await c.get(req.url)).text
    text = re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html))
    text = re.sub(r"\s+", " ", text)
    title = re.search(r"(?i)<title>(.*?)</title>", html)
    info = extract_profile(text)
    info["title"] = title.group(1).strip() if title else None
    info["branch_mentions"] = len(re.findall(r"(?i)\bbranch(es)?\b", text))
    return info

class PitchReq(BaseModel):
    company: dict
    service: str
    risk_notes: list[str] = []

@app.post("/pitch")
async def pitch(req: PitchReq, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    return write_pitch(req.company, req.service, req.risk_notes)

@app.post("/score")
async def score(lead: dict, x_api_key: str | None = Header(None)):
    auth(x_api_key)
    return score_lead(lead)