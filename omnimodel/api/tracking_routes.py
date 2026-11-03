"""Endpoints for saving leads and tracking what happens to them. All of them need a signed-in account:
a guest (shared API key, no token) gets 401, because a guest has no workspace to save into.

  GET    /leads                 list saved leads   (?status= &sector= &q= &due=true &limit= &offset=)
  POST   /leads                 save a lead (saving the same company again refreshes it)
  GET    /leads/{id}            one lead with its history and outcome
  PATCH  /leads/{id}            change status, follow-up reminder, do-not-contact
  DELETE /leads/{id}            remove a saved lead (owner or admin)
  POST   /leads/{id}/events     log a call, message, visit, meeting, proposal or note
  PUT    /leads/{id}/outcome    close a lead as won or lost, with details
  GET    /pipeline              counts per status, follow-ups due, this week's activity

The business to work in is the user's first one. Send `X-Workspace-Id` to pick another one they belong to."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from omnimodel import accounts, tracking
from omnimodel.tracking import EventIn, OutcomeIn, PatchLead, SaveLead

router = APIRouter(tags=["tracking"])

_DB_DOWN = {"OperationalError", "PoolTimeout", "InterfaceError"}   # the database cannot be reached (Neon may be waking up)


def _run(fn, *args, **kwargs):
    """Calls a tracking function and turns its errors into proper HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except accounts.SessionExpired as exc:            # signed out everywhere, or the user no longer exists
        raise HTTPException(401, str(exc))
    except tracking.NotFound as exc:
        raise HTTPException(404, str(exc))
    except tracking.BadInput as exc:
        raise HTTPException(422, str(exc))
    except tracking.Conflict as exc:
        raise HTTPException(409, str(exc))
    except tracking.Forbidden as exc:
        raise HTTPException(403, str(exc))
    except RuntimeError as exc:                       # DATABASE_URL is not set
        raise HTTPException(503, str(exc))
    except Exception as exc:
        if type(exc).__name__ in _DB_DOWN:
            raise HTTPException(503, f"The database is not available right now: {type(exc).__name__}")
        raise


def current_member(
    authorization: str | None = Header(default=None),
    x_workspace_id: str | None = Header(default=None),
) -> tracking.Ctx:
    """Who is asking, and which business they are working in. Rejects guests and bad tokens."""
    if not accounts.enabled():
        raise HTTPException(503, "Accounts are not enabled on this server.")
    token = accounts.bearer_token(authorization)
    if not token:
        raise HTTPException(401, "Sign in to save and track leads.")
    try:
        claims = accounts.verify_token(token)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    return _run(tracking.resolve_member, claims, x_workspace_id)


@router.get("/leads")
def list_leads(
    ctx: tracking.Ctx = Depends(current_member),
    status: str | None = None,
    sector: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    due: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return _run(tracking.list_leads, ctx, status, sector, q, due, limit, offset)


@router.post("/leads")
def save_lead(body: SaveLead, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.save_lead, ctx, body)


@router.get("/leads/{lead_id}")
def get_lead(lead_id: UUID, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.get_lead, ctx, str(lead_id))


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: UUID, body: PatchLead, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.update_lead, ctx, str(lead_id), body)


@router.delete("/leads/{lead_id}")
def delete_lead(lead_id: UUID, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.delete_lead, ctx, str(lead_id))


@router.post("/leads/{lead_id}/events", status_code=201)
def log_event(lead_id: UUID, body: EventIn, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.log_event, ctx, str(lead_id), body)


@router.put("/leads/{lead_id}/outcome")
def set_outcome(lead_id: UUID, body: OutcomeIn, ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.set_outcome, ctx, str(lead_id), body)


@router.get("/pipeline")
def pipeline(ctx: tracking.Ctx = Depends(current_member)):
    return _run(tracking.pipeline, ctx)