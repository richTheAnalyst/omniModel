"""Web endpoints. Run:  uvicorn omnimodel.api.main:app --reload --port 8000
Then open http://127.0.0.1:8000/docs to try every endpoint in the browser."""
from __future__ import annotations

import hmac
import os
import re
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from omnimodel.extraction.factory import available_backends
from omnimodel.profile_loader import list_profiles

from . import service

app = FastAPI(title="omniModel Lead API", version="0.1.0")

# Which frontend addresses may call this API. Add yours in .env as CORS_ORIGINS=http://localhost:3000,https://myapp.com
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


def require_key(x_api_key: str | None = Header(default=None)):
    """Every endpoint except /health needs the header  X-API-Key: <your API_KEY>.
    Set API_KEY on the host (and in your local .env). If it is not set, the API refuses to work."""
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "API_KEY is not configured on the server.")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid X-API-Key header.")


def _run(fn, *args, **kwargs):
    """Call a service function and turn its errors into proper HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except service.NotFound as e:
        raise HTTPException(404, str(e))
    except service.BadInput as e:
        raise HTTPException(422, str(e))
    except service.Upstream as e:
        raise HTTPException(502, str(e))


# ------------------------------------------------------------------ request shapes
class SearchRequest(BaseModel):
    profile: str
    region: str
    city: str
    sector: str
    max_results: int = Field(10, ge=1, le=20)


class AnalyzeRequest(BaseModel):
    profile: str
    url: str
    sector: str
    region: str
    city: str
    name: str | None = None
    review_count: int | None = None
    backend: str | None = None  # "openrouter", "ollama" or "claude"; blank = server default


class LeadIn(BaseModel):
    name: str
    city: str = ""
    region: str = ""
    sector: str = ""


class OutreachRequest(BaseModel):
    profile: str
    kind: Literal["email", "proposal", "followup"]
    offering: str
    lead: LeadIn
    business: dict[str, str] | None = None  # optional overrides: our_name, our_title, our_email, our_phone


class ExportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    format: Literal["pdf", "docx", "txt"] = "pdf"
    title: str = "Proposal"
    filename: str = "document"


# ------------------------------------------------------------------ endpoints
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/backends", dependencies=[Depends(require_key)])
def backends():
    return {"backends": available_backends()}


@app.get("/profiles", dependencies=[Depends(require_key)])
def profiles():
    return {"profiles": list_profiles()}


@app.get("/profiles/{name}", dependencies=[Depends(require_key)])
def profile_detail(name: str):
    return _run(service.public_profile, name)


@app.post("/search", dependencies=[Depends(require_key)])
def search(req: SearchRequest):
    return _run(service.search_leads, req.profile, req.region, req.city, req.sector, req.max_results)


@app.post("/analyze", dependencies=[Depends(require_key)])
def analyze(req: AnalyzeRequest):
    return _run(service.analyze_url, req.profile, req.url, req.sector, req.region, req.city,
                req.name, req.review_count, req.backend)


@app.post("/outreach", dependencies=[Depends(require_key)])
def outreach(req: OutreachRequest):
    text = _run(service.make_outreach, req.profile, req.kind, req.offering, req.lead.model_dump(), req.business)
    return {"kind": req.kind, "text": text}


@app.post("/export", dependencies=[Depends(require_key)])
def export(req: ExportRequest):
    data, media = _run(service.make_export, req.text, req.format, req.title)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", req.filename).strip("_") or "document"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}.{req.format}"'})