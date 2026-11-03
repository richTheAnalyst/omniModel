"""Saved leads and everything that happens to them: status, calls and messages, notes, won/lost outcomes.
Plain Python plus SQL, no web code. api/tracking_routes.py turns these functions into endpoints.

Rules that hold everywhere in this file
  * Every query is scoped by the caller's workspace_id, so one business can never read or change another's leads.
    A lead that belongs to another workspace is reported as "not found", never as "forbidden".
  * Guests never reach this file: saving and tracking need a signed-in account.
  * lead_events is append-only history. Statuses and counters on `leads` are kept in step with it inside one transaction.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import accounts, db

STATUSES = ("new", "contacted", "meeting", "proposal", "won", "lost", "not_interested")
OPEN_STATUSES = ("new", "contacted", "meeting", "proposal")
CONTACT_EVENTS = ("call_attempt", "call_answered", "email_sent", "whatsapp_sent", "visit", "meeting", "proposal_sent")
EVENT_TYPES = CONTACT_EVENTS + ("note",)  # what a person can log by hand; the rest are written by the server
LOST_REASONS = ("price", "competitor", "no_need", "no_budget", "no_response", "timing", "other")
MAX_FUTURE = timedelta(minutes=5)  # an event may not be dated further ahead than this (clock drift allowance)


class NotFound(Exception):    # becomes HTTP 404
    pass


class BadInput(Exception):    # becomes HTTP 422
    pass


class Conflict(Exception):    # becomes HTTP 409
    pass


class Forbidden(Exception):   # becomes HTTP 403
    pass


@dataclass(frozen=True)
class Ctx:
    """Who is asking and which business they are working in. Built once per request from the verified token."""
    user_id: str
    workspace_id: str
    role: str


# ---------------------------------------------------------------- request shapes
def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class SaveLead(BaseModel):
    """A company the user wants to keep. Sent from a search result; extra fields are ignored."""
    place_id: str = Field(min_length=1, max_length=300)
    name: str | None = Field(None, max_length=300)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=200)
    region: str | None = Field(None, max_length=200)
    country: str | None = Field(None, max_length=100)
    sector: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=60)
    website: str | None = Field(None, max_length=500)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    types: list[str] = Field(default_factory=list, max_length=20)
    rating: float | None = Field(None, ge=0, le=5)
    review_count: int | None = Field(None, ge=0)
    ownership: Literal["government", "non_government"] | None = None
    ownership_confidence: Literal["high", "assumed", "ai"] | None = None
    snapshot: dict[str, Any] | None = None   # scores, best offering and website analysis as the user saw them

    _clean = field_validator(
        "place_id", "name", "address", "city", "region", "country", "sector", "phone", "website", mode="before"
    )(_blank_to_none)

    @field_validator("types", mode="before")
    @classmethod
    def _types(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [t[:80] for t in value if isinstance(t, str) and t][:20]

    @field_validator("snapshot")
    @classmethod
    def _snapshot_size(cls, value: dict | None) -> dict | None:
        if value is not None and len(json.dumps(value, default=str)) > 100_000:
            raise ValueError("snapshot is too large")
        return value


class PatchLead(BaseModel):
    """Only the fields that are present are changed. `next_follow_up_at: null` clears the reminder."""
    status: Literal["new", "contacted", "meeting", "proposal", "won", "lost", "not_interested"] | None = None
    next_follow_up_at: datetime | None = None
    do_not_contact: bool | None = None


class EventIn(BaseModel):
    type: Literal["call_attempt", "call_answered", "email_sent", "whatsapp_sent", "visit", "meeting", "proposal_sent", "note"]
    note: str | None = Field(None, max_length=2000)
    occurred_at: datetime | None = None    # leave out for "now"; use it to log something that happened earlier
    follow_up_at: datetime | None = None   # set the reminder in the same step ("no answer, call back Friday")

    _clean = field_validator("note", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _note_needed(self) -> "EventIn":
        if self.type == "note" and not self.note:
            raise ValueError("A note needs some text.")
        return self


class OutcomeIn(BaseModel):
    result: Literal["won", "lost"]
    decided_on: date | None = None
    offerings_sold: list[str] = Field(default_factory=list, max_length=20)
    deal_value: Decimal | None = Field(None, ge=0, le=Decimal("999999999999"))
    currency: str | None = Field(None, max_length=8)
    contract_months: int | None = Field(None, ge=0, le=600)
    lost_reason: Literal["price", "competitor", "no_need", "no_budget", "no_response", "timing", "other"] | None = None
    competitor_name: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)

    _clean = field_validator("currency", "competitor_name", "notes", mode="before")(_blank_to_none)

    @field_validator("offerings_sold", mode="before")
    @classmethod
    def _offerings(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [v[:100] for v in value if isinstance(v, str) and v][:20]


# ---------------------------------------------------------------- small helpers
def _plain(value: Any) -> Any:
    """Turns database values into JSON-friendly ones (uuid and dates become text, numeric becomes a number)."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _uid(value: Any) -> str:
    """A lead id that is not a valid uuid cannot exist, so it is simply 'not found'."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise NotFound("Lead not found.")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _jsonb(value: Any):
    return import_module("psycopg.types.json").Jsonb(value)   # lazy, like db.py: the app runs without the database library


def auto_status(current: str, event_type: str) -> str | None:
    """The status a logged event moves a lead to, or None to leave it. It only ever moves a lead forward,
    and never touches a lead that is won, lost or not interested."""
    if event_type == "proposal_sent" and current in ("new", "contacted", "meeting"):
        return "proposal"
    if event_type == "meeting" and current in ("new", "contacted"):
        return "meeting"
    if event_type in CONTACT_EVENTS and current == "new":
        return "contacted"
    return None


LEAD_COLS = """l.id, l.place_id, l.name, l.address, l.city, l.region, l.country, l.sector, l.phone, l.website,
  l.lat, l.lng, l.google_types, l.rating, l.review_count, l.ownership, l.ownership_confidence, l.snapshot,
  l.status, l.status_changed_at, l.do_not_contact, l.contact_attempts, l.last_contacted_at, l.next_follow_up_at,
  l.first_seen_at, l.created_at, l.updated_at,
  (select e.detail->>'note' from lead_events e
    where e.lead_id = l.id and e.type = 'note' order by e.occurred_at desc, e.id desc limit 1) as last_note"""


def _lead_out(row: dict) -> dict:
    out = _plain(dict(row))
    out["types"] = out.pop("google_types", None) or []
    return out


def _fetch_lead(conn, ctx: Ctx, lead_id: str, lock: bool = False) -> dict:
    sql = f"select {LEAD_COLS} from leads l where l.id = %s::uuid and l.workspace_id = %s::uuid"
    if lock:
        sql += " for update of l"     # two people logging on the same lead at once take turns
    row = conn.execute(sql, (lead_id, ctx.workspace_id)).fetchone()
    if row is None:
        raise NotFound("Lead not found.")
    return row


def _add_event(conn, ctx: Ctx, lead_id: str, type_: str, detail: dict, occurred_at: datetime | None = None) -> dict:
    row = conn.execute(
        """insert into lead_events (workspace_id, lead_id, user_id, type, detail, occurred_at)
           values (%s::uuid, %s::uuid, %s::uuid, %s, %s, coalesce(%s::timestamptz, now()))
           returning id, type, detail, occurred_at""",
        (ctx.workspace_id, lead_id, ctx.user_id, type_, _jsonb(detail), occurred_at),
    ).fetchone()
    return _plain(dict(row))


# ---------------------------------------------------------------- who is asking
_MEMBERSHIP_SQL = """select u.id as user_id, m.workspace_id, m.role
                     from users u join workspace_members m on m.user_id = u.id
                     where u.auth_subject = %s order by m.created_at"""


def resolve_member(claims: dict, workspace_id: str | None = None) -> Ctx:
    """Turns verified token claims into a Ctx. A user's first request creates their account and business,
    exactly as /me does. `workspace_id` picks one of their businesses; one they do not belong to is Forbidden."""
    sub = str(claims["sub"])
    wanted = None
    if workspace_id:
        try:
            wanted = str(uuid.UUID(workspace_id))
        except ValueError:
            raise BadInput("X-Workspace-Id is not a valid id.")
    with db.connection() as conn:
        rows = conn.execute(_MEMBERSHIP_SQL, (sub,)).fetchall()
    if not rows:
        accounts.load_account(claims)
        with db.connection() as conn:
            rows = conn.execute(_MEMBERSHIP_SQL, (sub,)).fetchall()
    if not rows:
        raise Forbidden("This account has no business workspace.")
    if wanted is None:
        row = rows[0]
    else:
        row = next((r for r in rows if str(r["workspace_id"]) == wanted), None)
        if row is None:
            raise Forbidden("You are not a member of that workspace.")
    return Ctx(user_id=str(row["user_id"]), workspace_id=str(row["workspace_id"]), role=row["role"])


# ---------------------------------------------------------------- saving and reading
_NOT_WEAKER = "excluded.ownership_confidence = 'assumed' and leads.ownership_confidence in ('ai', 'high')"


def save_lead(ctx: Ctx, data: SaveLead) -> dict:
    """Saves a company, or refreshes it if this business already saved it. Status, history and counters are never touched.
    A weak ownership guess never replaces a checked one."""
    with db.connection() as conn:
        row = conn.execute(
            f"""insert into leads (workspace_id, place_id, name, address, city, region, country, sector, phone, website,
                                   lat, lng, google_types, rating, review_count, ownership, ownership_confidence, snapshot)
                values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (workspace_id, place_id) do update set
                  name = coalesce(excluded.name, leads.name),
                  address = coalesce(excluded.address, leads.address),
                  city = coalesce(excluded.city, leads.city),
                  region = coalesce(excluded.region, leads.region),
                  country = coalesce(excluded.country, leads.country),
                  sector = coalesce(excluded.sector, leads.sector),
                  phone = coalesce(excluded.phone, leads.phone),
                  website = coalesce(excluded.website, leads.website),
                  lat = coalesce(excluded.lat, leads.lat),
                  lng = coalesce(excluded.lng, leads.lng),
                  google_types = case when cardinality(excluded.google_types) > 0 then excluded.google_types else leads.google_types end,
                  rating = coalesce(excluded.rating, leads.rating),
                  review_count = coalesce(excluded.review_count, leads.review_count),
                  ownership = case when {_NOT_WEAKER} then leads.ownership else coalesce(excluded.ownership, leads.ownership) end,
                  ownership_confidence = case when {_NOT_WEAKER} then leads.ownership_confidence
                                              else coalesce(excluded.ownership_confidence, leads.ownership_confidence) end,
                  snapshot = coalesce(excluded.snapshot, leads.snapshot),
                  updated_at = now()
                returning id, (xmax = 0) as created""",
            (ctx.workspace_id, data.place_id, data.name, data.address, data.city, data.region, data.country, data.sector,
             data.phone, data.website, data.lat, data.lng, data.types, data.rating, data.review_count, data.ownership,
             data.ownership_confidence, _jsonb(data.snapshot) if data.snapshot is not None else None),
        ).fetchone()
        lead = _fetch_lead(conn, ctx, str(row["id"]))
    return {"created": bool(row["created"]), "lead": _lead_out(lead)}


def list_leads(ctx: Ctx, status: str | None = None, sector: str | None = None, q: str | None = None,
               due: bool = False, limit: int = 100, offset: int = 0) -> dict:
    if status is not None and status not in STATUSES:
        raise BadInput(f"Unknown status '{status}'.")
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where, params = ["l.workspace_id = %s::uuid"], [ctx.workspace_id]
    if status:
        where.append("l.status = %s")
        params.append(status)
    if sector:
        where.append("l.sector = %s")
        params.append(sector)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(l.name ilike %s or l.city ilike %s or l.address ilike %s)")
        params += [like, like, like]
    if due:
        where.append("l.next_follow_up_at is not null and l.next_follow_up_at <= now() and l.status = any(%s)")
        params.append(list(OPEN_STATUSES))    # psycopg 3 sends a list as an array; a tuple would not work with IN
    clause = " and ".join(where)
    order = "l.next_follow_up_at asc, l.id" if due else "l.updated_at desc, l.id"
    with db.connection() as conn:
        total = conn.execute(f"select count(*) as n from leads l where {clause}", params).fetchone()["n"]
        rows = conn.execute(
            f"select {LEAD_COLS} from leads l where {clause} order by {order} limit %s offset %s",
            params + [limit, offset],
        ).fetchall()
    return {"total": int(total), "limit": limit, "offset": offset, "leads": [_lead_out(r) for r in rows]}


def get_lead(ctx: Ctx, lead_id: str) -> dict:
    """One lead with its full history (newest first) and its won/lost outcome, if any."""
    lead_id = _uid(lead_id)
    with db.connection() as conn:
        lead = _fetch_lead(conn, ctx, lead_id)
        events = conn.execute(
            """select e.id, e.type, e.detail, e.occurred_at, coalesce(u.display_name, u.email) as by
               from lead_events e left join users u on u.id = e.user_id
               where e.lead_id = %s::uuid and e.workspace_id = %s::uuid
               order by e.occurred_at desc, e.id desc limit 200""",
            (lead_id, ctx.workspace_id),
        ).fetchall()
        outcome = conn.execute(
            """select result, decided_on, offerings_sold, deal_value, currency, contract_months, lost_reason,
                      competitor_name, notes, recorded_at
               from outcomes where lead_id = %s::uuid and workspace_id = %s::uuid""",
            (lead_id, ctx.workspace_id),
        ).fetchone()
    return {"lead": _lead_out(lead), "events": [_plain(dict(e)) for e in events],
            "outcome": _plain(dict(outcome)) if outcome else None}


# ---------------------------------------------------------------- changing a lead
def update_lead(ctx: Ctx, lead_id: str, patch: PatchLead) -> dict:
    """Status, follow-up reminder and do-not-contact. Won and lost go through set_outcome so the result is recorded."""
    lead_id = _uid(lead_id)
    fields = patch.model_fields_set
    if patch.status in ("won", "lost"):
        raise BadInput("Record a won or lost result with the outcome form, so the result is saved with it.")
    with db.connection() as conn:
        lead = _fetch_lead(conn, ctx, lead_id, lock=True)
        if "status" in fields and patch.status is not None and patch.status != lead["status"]:
            if lead["status"] in ("won", "lost"):   # reopening a closed lead: its old result no longer holds
                conn.execute("delete from outcomes where lead_id = %s::uuid and workspace_id = %s::uuid", (lead_id, ctx.workspace_id))
            conn.execute("update leads set status = %s, status_changed_at = now(), updated_at = now() where id = %s::uuid",
                         (patch.status, lead_id))
            _add_event(conn, ctx, lead_id, "status_change", {"from": lead["status"], "to": patch.status})
        if "do_not_contact" in fields and patch.do_not_contact is not None and patch.do_not_contact != lead["do_not_contact"]:
            conn.execute("update leads set do_not_contact = %s, updated_at = now() where id = %s::uuid",
                         (patch.do_not_contact, lead_id))
            _add_event(conn, ctx, lead_id, "do_not_contact_on" if patch.do_not_contact else "do_not_contact_off", {})
        if "next_follow_up_at" in fields:
            conn.execute("update leads set next_follow_up_at = %s::timestamptz, updated_at = now() where id = %s::uuid",
                         (_utc(patch.next_follow_up_at), lead_id))
        lead = _fetch_lead(conn, ctx, lead_id)
    return {"lead": _lead_out(lead)}


def log_event(ctx: Ctx, lead_id: str, ev: EventIn) -> dict:
    """Records a call, message, visit, meeting, proposal or note. Contact events also bump the counters and may move
    the lead forward (see auto_status). Contacting a do-not-contact company is refused; notes are always allowed."""
    lead_id = _uid(lead_id)
    now = datetime.now(timezone.utc)
    occurred = _utc(ev.occurred_at) or now
    if occurred > now + MAX_FUTURE:
        raise BadInput("An event cannot be dated in the future.")
    contact = ev.type in CONTACT_EVENTS
    with db.connection() as conn:
        lead = _fetch_lead(conn, ctx, lead_id, lock=True)
        if contact and lead["do_not_contact"]:
            raise Conflict("This company is marked do not contact. Remove the flag first if that changed.")
        event = _add_event(conn, ctx, lead_id, ev.type, {"note": ev.note} if ev.note else {}, occurred)
        if contact:
            conn.execute(
                """update leads set contact_attempts = contact_attempts + 1,
                       last_contacted_at = greatest(coalesce(last_contacted_at, %s::timestamptz), %s::timestamptz),
                       updated_at = now()
                   where id = %s::uuid""",
                (occurred, occurred, lead_id),
            )
            new_status = auto_status(lead["status"], ev.type)
            if new_status:
                conn.execute("update leads set status = %s, status_changed_at = now() where id = %s::uuid", (new_status, lead_id))
                _add_event(conn, ctx, lead_id, "status_change", {"from": lead["status"], "to": new_status, "auto": True})
        if ev.follow_up_at is not None:
            conn.execute("update leads set next_follow_up_at = %s::timestamptz, updated_at = now() where id = %s::uuid",
                         (_utc(ev.follow_up_at), lead_id))
        elif contact and lead["next_follow_up_at"] is not None and _utc(lead["next_follow_up_at"]) <= now:
            # the reminder that was due has now been acted on
            conn.execute("update leads set next_follow_up_at = null where id = %s::uuid", (lead_id,))
        if not contact:
            conn.execute("update leads set updated_at = now() where id = %s::uuid", (lead_id,))
        lead = _fetch_lead(conn, ctx, lead_id)
    return {"event": event, "lead": _lead_out(lead)}


def set_outcome(ctx: Ctx, lead_id: str, o: OutcomeIn) -> dict:
    """Closes a lead as won or lost, with the details that make the result useful later (value, reason, competitor)."""
    lead_id = _uid(lead_id)
    lost_reason = o.lost_reason if o.result == "lost" else None
    competitor = o.competitor_name if o.result == "lost" else None
    with db.connection() as conn:
        lead = _fetch_lead(conn, ctx, lead_id, lock=True)
        outcome = conn.execute(
            """insert into outcomes (lead_id, workspace_id, result, decided_on, offerings_sold, deal_value, currency,
                                     contract_months, lost_reason, competitor_name, notes, recorded_by)
               values (%s::uuid, %s::uuid, %s, coalesce(%s::date, current_date), %s, %s, %s, %s, %s, %s, %s, %s::uuid)
               on conflict (lead_id) do update set
                 result = excluded.result, decided_on = excluded.decided_on, offerings_sold = excluded.offerings_sold,
                 deal_value = excluded.deal_value, currency = excluded.currency, contract_months = excluded.contract_months,
                 lost_reason = excluded.lost_reason, competitor_name = excluded.competitor_name, notes = excluded.notes,
                 recorded_by = excluded.recorded_by, recorded_at = now()
               returning result, decided_on, offerings_sold, deal_value, currency, contract_months, lost_reason,
                         competitor_name, notes, recorded_at""",
            (lead_id, ctx.workspace_id, o.result, o.decided_on, o.offerings_sold, o.deal_value, o.currency,
             o.contract_months, lost_reason, competitor, o.notes, ctx.user_id),
        ).fetchone()
        if lead["status"] != o.result:
            conn.execute("update leads set status = %s, status_changed_at = now() where id = %s::uuid", (o.result, lead_id))
            _add_event(conn, ctx, lead_id, "status_change", {"from": lead["status"], "to": o.result})
        conn.execute("update leads set next_follow_up_at = null, updated_at = now() where id = %s::uuid", (lead_id,))
        detail: dict[str, Any] = {}
        if lost_reason:
            detail["lost_reason"] = lost_reason
        if o.deal_value is not None:
            detail["deal_value"] = float(o.deal_value)
        _add_event(conn, ctx, lead_id, o.result, detail)
        lead = _fetch_lead(conn, ctx, lead_id)
    return {"lead": _lead_out(lead), "outcome": _plain(dict(outcome))}


def delete_lead(ctx: Ctx, lead_id: str) -> dict:
    """Removes a saved lead and its whole history. Only an owner or admin of the business may do this."""
    lead_id = _uid(lead_id)
    if ctx.role not in ("owner", "admin"):
        raise Forbidden("Only an owner or admin can delete a lead.")
    with db.connection() as conn:
        row = conn.execute("delete from leads where id = %s::uuid and workspace_id = %s::uuid returning id",
                           (lead_id, ctx.workspace_id)).fetchone()
    if row is None:
        raise NotFound("Lead not found.")
    return {"deleted": True}


# ---------------------------------------------------------------- the board
def pipeline(ctx: Ctx) -> dict:
    """Counts per status, how many follow-ups are due, and this week's calls and messages."""
    with db.connection() as conn:
        rows = conn.execute(
            """select status, count(*) as n,
                      count(*) filter (where next_follow_up_at is not null and next_follow_up_at <= now()) as due
               from leads where workspace_id = %s::uuid group by status""",
            (ctx.workspace_id,),
        ).fetchall()
        week = conn.execute(
            """select type, count(*) as n from lead_events
               where workspace_id = %s::uuid and occurred_at >= now() - interval '7 days'
                 and type in ('call_attempt', 'call_answered', 'email_sent', 'whatsapp_sent', 'visit', 'meeting',
                              'proposal_sent', 'won')
               group by type""",
            (ctx.workspace_id,),
        ).fetchall()
    counts = {s: 0 for s in STATUSES}
    due = 0
    for r in rows:
        counts[r["status"]] = int(r["n"])
        if r["status"] in OPEN_STATUSES:
            due += int(r["due"])
    return {"counts": counts, "total": sum(counts.values()), "due": due, "week": {r["type"]: int(r["n"]) for r in week}}