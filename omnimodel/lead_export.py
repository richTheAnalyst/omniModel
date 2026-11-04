"""Excel export of saved leads: every lead, one lead, or one week, with statuses, history and the business profile.

Plain Python plus SQL, like tracking.py. api/tracking_routes.py turns `export_workbook` into POST /exports/leads.

Rules
  * Scoped by the caller's workspace_id, exactly like tracking.py. A lead of another business is "not found".
  * Text from the web (company names, notes) is never allowed to turn into an Excel formula: every text cell is
    written as plain text.
  * Dates are shown in the person's own time zone (the browser sends its offset), not the server's.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from . import db
from .tracking import LEAD_COLS, STATUSES, BadInput, Ctx, NotFound, _lead_out, _uid

MAX_EVENTS = 20_000          # a safety cap on the history sheet
MAX_LEADS = 5_000

STATUS_LABEL = {
    "new": "New", "contacted": "Contacted", "meeting": "Meeting", "proposal": "Proposal sent",
    "won": "Won", "lost": "Lost", "not_interested": "Not interested",
}
EVENT_LABEL = {
    "call_attempt": "Called, no answer", "call_answered": "Spoke by phone", "email_sent": "Emailed",
    "whatsapp_sent": "WhatsApp sent", "visit": "Visited", "meeting": "Meeting held", "proposal_sent": "Proposal sent",
    "status_change": "Status changed", "note": "Note", "won": "Won", "lost": "Lost",
    "do_not_contact_on": "Marked do-not-contact", "do_not_contact_off": "Do-not-contact removed",
    "analyzed": "Website analysed", "fit_override": "Fit adjusted",
}
LOST_LABEL = {
    "price": "Price", "competitor": "Chose a competitor", "no_need": "No need", "no_budget": "No budget",
    "no_response": "No response", "timing": "Bad timing", "other": "Other",
}


class ExportIn(BaseModel):
    scope: Literal["all", "lead", "week"] = "all"
    lead_id: UUID | None = None                 # scope "lead"
    status: str | None = Field(None, max_length=30)   # optional filter for "all" and "week"
    week_start: date | None = None              # scope "week": any day in the week; the week runs Monday to Sunday
    tz_offset_minutes: int = Field(0, ge=-840, le=840)   # JavaScript's getTimezoneOffset(): minutes behind UTC
    profile: dict[str, Any] | None = None       # the business profile, kept in the browser, sent along for the last sheet


# ---------------------------------------------------------------- the week
def week_bounds(day: date, tz_offset_minutes: int) -> tuple[datetime, datetime, date, date]:
    """Monday 00:00 to next Monday 00:00 in the person's time zone, as UTC instants, plus the first and last day."""
    monday = day - timedelta(days=day.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc) + timedelta(minutes=tz_offset_minutes)
    return start, start + timedelta(days=7), monday, monday + timedelta(days=6)


# ---------------------------------------------------------------- reading the data
def _events_sql(window: bool) -> str:
    return f"""select e.lead_id, e.type, e.detail, e.occurred_at, coalesce(u.display_name, u.email) as by
               from lead_events e left join users u on u.id = e.user_id
               where e.workspace_id = %s::uuid and e.lead_id = any(%s::uuid[])
               {"and e.occurred_at >= %s and e.occurred_at < %s" if window else ""}
               order by e.occurred_at desc, e.id desc limit {MAX_EVENTS}"""


def gather(ctx: Ctx, req: ExportIn) -> dict:
    """The leads, their history and outcomes for the chosen scope."""
    if req.status is not None and req.status not in STATUSES:
        raise BadInput(f"Unknown status '{req.status}'.")
    period = None
    where, params = ["l.workspace_id = %s::uuid"], [ctx.workspace_id]

    if req.scope == "lead":
        if req.lead_id is None:
            raise BadInput("Say which lead to export.")
        where.append("l.id = %s::uuid")
        params.append(_uid(req.lead_id))
    elif req.scope == "week":
        if req.week_start is None:
            raise BadInput("Choose a week.")
        start, end, first, last = week_bounds(req.week_start, req.tz_offset_minutes)
        period = {"start": start, "end": end, "first": first, "last": last}
        # A lead belongs to the week if it was saved then, or something was logged on it then.
        where.append("""(l.created_at >= %s and l.created_at < %s or exists (
                          select 1 from lead_events e where e.lead_id = l.id and e.workspace_id = l.workspace_id
                            and e.occurred_at >= %s and e.occurred_at < %s))""")
        params += [start, end, start, end]
    if req.status and req.scope != "lead":
        where.append("l.status = %s")
        params.append(req.status)

    clause = " and ".join(where)
    with db.connection() as conn:
        rows = conn.execute(
            f"select {LEAD_COLS} from leads l where {clause} order by l.status_changed_at desc, l.id limit {MAX_LEADS}",
            params,
        ).fetchall()
        if req.scope == "lead" and not rows:
            raise NotFound("Lead not found.")
        ids = [str(r["id"]) for r in rows]
        ev_params: list[Any] = [ctx.workspace_id, ids]
        if period:
            ev_params += [period["start"], period["end"]]
        events = conn.execute(_events_sql(bool(period)), ev_params).fetchall() if ids else []
        outcomes = conn.execute(
            """select lead_id, result, decided_on, offerings_sold, deal_value, currency, contract_months, lost_reason,
                      competitor_name, notes from outcomes where workspace_id = %s::uuid and lead_id = any(%s::uuid[])""",
            (ctx.workspace_id, ids),
        ).fetchall() if ids else []
        who = conn.execute(
            "select w.name as workspace, coalesce(u.display_name, u.email) as person from workspaces w, users u "
            "where w.id = %s::uuid and u.id = %s::uuid",
            (ctx.workspace_id, ctx.user_id),
        ).fetchone()
    return {
        "leads": [_lead_out(r) for r in rows],
        "events": events,
        "outcomes": {str(o["lead_id"]): o for o in outcomes},
        "period": period,
        "who": who or {},
    }


# ---------------------------------------------------------------- building the workbook
def _import_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:                    # surfaced as 503 by the route
        raise RuntimeError("Excel export needs the 'openpyxl' package. Run: uv sync --all-extras") from exc
    return openpyxl


def _clean_text(value: Any, limit: int = 5000) -> str:
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    return text[:limit]


def _local(dt: datetime | None, offset: int) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) - timedelta(minutes=offset)).replace(tzinfo=None)


def _put(ws, row: int, col: int, value: Any, *, fmt: str | None = None, bold: bool = False, wrap: bool = False):
    """Writes one cell. Text is forced to plain text so nothing a website or a person typed can run as a formula."""
    from openpyxl.styles import Alignment, Font
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        cell.value = _clean_text(value)
        cell.data_type = "s"
    elif isinstance(value, bool):
        cell.value = "Yes" if value else "No"
        cell.data_type = "s"
    else:
        cell.value = value
    if fmt:
        cell.number_format = fmt
    if bold:
        cell.font = Font(bold=True)
    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
    return cell


def _table(ws, headers: list[str], rows: list[list[Any]], widths: list[int], formats: dict[int, str] | None = None,
           start_row: int = 1, wrap_cols: tuple[int, ...] = ()):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    head_fill = PatternFill("solid", fgColor="0F1628")
    for c, h in enumerate(headers, 1):
        cell = _put(ws, start_row, c, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r, values in enumerate(rows, start_row + 1):
        for c, v in enumerate(values, 1):
            _put(ws, r, c, v, fmt=(formats or {}).get(c), wrap=c in wrap_cols)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{start_row + len(rows)}"
    ws.row_dimensions[start_row].height = 22


def _offer_label(key: str | None, offerings: dict) -> str:
    if not key:
        return ""
    entry = offerings.get(key)
    return (entry.get("label") if isinstance(entry, dict) else None) or key.replace("_", " ").title()


def _score_of(lead: dict) -> tuple[str, float | None]:
    snap = lead.get("snapshot") if isinstance(lead.get("snapshot"), dict) else {}
    scores = snap.get("scores") if isinstance(snap.get("scores"), dict) else {}
    best = snap.get("best_offering")
    entry = scores.get(best) if best in scores else None
    if entry is None and scores:
        best, entry = max(scores.items(), key=lambda kv: float((kv[1] or {}).get("score") or 0) if isinstance(kv[1], dict) else 0)
    value = entry.get("score") if isinstance(entry, dict) else None
    try:
        return best or "", round(float(value) * 100) if value is not None else None
    except (TypeError, ValueError):
        return best or "", None


def _describe(event_type: str, detail: dict) -> str:
    detail = detail if isinstance(detail, dict) else {}
    if event_type == "status_change":
        return f"{STATUS_LABEL.get(detail.get('from'), detail.get('from') or '')} to {STATUS_LABEL.get(detail.get('to'), detail.get('to') or '')}".strip()
    parts = []
    if detail.get("note"):
        parts.append(str(detail["note"]))
    if detail.get("reason"):
        parts.append(f"Reason: {detail['reason']}")
    return " | ".join(parts)


def _profile_rows(profile: dict | None, who: dict) -> list[tuple[str, str]]:
    """The few profile fields worth printing, read defensively because the browser sent them."""
    rows: list[tuple[str, str]] = []
    profile = profile if isinstance(profile, dict) else {}
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    for key, label in (("our_name", "Company / sender"), ("our_title", "Title"), ("our_email", "Email"), ("our_phone", "Phone"), ("service", "What we offer")):
        if business.get(key):
            rows.append((label, str(business[key])))
    if profile.get("country"):
        rows.append(("Country", str(profile["country"])))
    offerings = profile.get("offerings") if isinstance(profile.get("offerings"), dict) else {}
    for key, entry in list(offerings.items())[:30]:
        label = _offer_label(key, offerings)
        desc = entry.get("description", "") if isinstance(entry, dict) else ""
        rows.append((f"Service: {label}", str(desc)))
    sectors = profile.get("sectors") if isinstance(profile.get("sectors"), dict) else {}
    labels = [str(v.get("label")) for v in sectors.values() if isinstance(v, dict) and v.get("label")]
    if labels and len(labels) <= 40:
        rows.append(("Industries targeted", ", ".join(labels)))
    if rows and who.get("workspace"):
        rows.insert(0, ("Workspace", str(who["workspace"])))
    return rows


def build_workbook(data: dict, req: ExportIn) -> bytes:
    openpyxl = _import_openpyxl()
    from openpyxl.styles import Font
    off = req.tz_offset_minutes
    profile = req.profile if isinstance(req.profile, dict) else {}
    offerings = profile.get("offerings") if isinstance(profile.get("offerings"), dict) else {}
    leads, events, outcomes, period = data["leads"], data["events"], data["outcomes"], data["period"]
    names = {l["id"]: (l.get("name") or "(unnamed)") for l in leads}

    wb = openpyxl.Workbook()

    # ---- Summary
    ws = wb.active
    ws.title = "Summary"
    if req.scope == "lead":
        scope_text = f"One lead: {leads[0].get('name') or '(unnamed)'}" if leads else "One lead"
    elif req.scope == "week":
        scope_text = f"Week of {period['first'].isoformat()} to {period['last'].isoformat()} (leads saved or worked on that week)"
    else:
        scope_text = "All saved leads"
    if req.status and req.scope != "lead":
        scope_text += f", status: {STATUS_LABEL.get(req.status, req.status)}"
    _put(ws, 1, 1, "Omni Model: leads export", bold=True).font = Font(bold=True, size=15)
    info = [("Scope", scope_text),
            ("Exported", _local(datetime.now(timezone.utc), off)),
            ("Exported by", data["who"].get("person") or ""),
            ("Leads in this file", len(leads))]
    r = 3
    for label, value in info:
        _put(ws, r, 1, label, bold=True)
        _put(ws, r, 2, value, fmt="yyyy-mm-dd hh:mm" if isinstance(value, datetime) else None)
        r += 1
    r += 1
    _put(ws, r, 1, "Status", bold=True)
    _put(ws, r, 2, "Leads", bold=True)
    r += 1
    for s in STATUSES:
        _put(ws, r, 1, STATUS_LABEL[s])
        _put(ws, r, 2, sum(1 for l in leads if l["status"] == s))
        r += 1
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 60

    # ---- Leads
    head = ["Company", "Status", "Sector", "City", "Region", "Country", "Address", "Phone", "Website", "Rating",
            "Reviews", "Ownership", "Best-fit service", "Fit score (0-100)", "Contact attempts", "Last contacted",
            "Next follow-up", "Do not contact", "Last note", "Saved on", "Result", "Deal value", "Currency",
            "Lost reason", "Competitor", "Outcome notes"]
    rows = []
    for l in leads:
        best, score = _score_of(l)
        o = outcomes.get(l["id"])
        rows.append([
            l.get("name"), STATUS_LABEL.get(l["status"], l["status"]), l.get("sector"), l.get("city"), l.get("region"),
            l.get("country"), l.get("address"), l.get("phone"), l.get("website"), l.get("rating"), l.get("review_count"),
            {"government": "Government", "non_government": "Private"}.get(l.get("ownership") or "", ""),
            _offer_label(best, offerings), score, l.get("contact_attempts"),
            _local(_dt(l.get("last_contacted_at")), off), _local(_dt(l.get("next_follow_up_at")), off),
            bool(l.get("do_not_contact")), l.get("last_note"), _local(_dt(l.get("created_at")), off),
            (o or {}).get("result", "").title() if o else "", float(o["deal_value"]) if o and o.get("deal_value") is not None else None,
            (o or {}).get("currency"), LOST_LABEL.get((o or {}).get("lost_reason"), "") if o else "",
            (o or {}).get("competitor_name"), (o or {}).get("notes"),
        ])
    dt = "yyyy-mm-dd hh:mm"
    _table(wb.create_sheet("Leads"), head, rows,
           [30, 15, 16, 16, 16, 12, 34, 18, 30, 8, 9, 13, 20, 12, 10, 17, 17, 10, 40, 17, 9, 12, 9, 18, 20, 36],
           formats={16: dt, 17: dt, 20: dt, 22: "#,##0.00"}, wrap_cols=(7, 19, 26))

    # ---- History
    ev_rows = [[names.get(str(e["lead_id"])), _local(_dt(e["occurred_at"]), off), EVENT_LABEL.get(e["type"], e["type"]),
                _describe(e["type"], e["detail"]), e.get("by")] for e in events]
    title = "Activity this week" if req.scope == "week" else "History"
    _table(wb.create_sheet(title), ["Company", "When", "What happened", "Details", "By"], ev_rows,
           [30, 17, 22, 60, 24], formats={2: dt}, wrap_cols=(4,))

    # ---- Business profile, last
    wp = wb.create_sheet("Business profile")
    prof = _profile_rows(profile, data["who"])
    if prof:
        _table(wp, ["Item", "Detail"], [[a, b] for a, b in prof], [30, 70], wrap_cols=(2,))
    else:
        _put(wp, 1, 1, "No business profile was available when this file was made. Fill it in under Settings and export again.")
        wp.column_dimensions["A"].width = 100

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _dt(value: Any) -> datetime | None:
    """_lead_out turns datetimes into ISO text; read them back."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def export_workbook(ctx: Ctx, req: ExportIn) -> tuple[bytes, str]:
    """(xlsx bytes, suggested file name without folder)."""
    data = gather(ctx, req)
    blob = build_workbook(data, req)
    stamp = date.today().isoformat()
    if req.scope == "lead":
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (data["leads"][0].get("name") or "lead")).strip("-")[:40] or "lead"
        name = f"lead-{slug}-{stamp}.xlsx"
    elif req.scope == "week":
        name = f"leads-week-{data['period']['first'].isoformat()}.xlsx"
    else:
        name = f"leads-{stamp}.xlsx"
    return blob, name