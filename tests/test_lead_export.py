"""Excel export of saved leads. The first group needs no database; the rest need TEST_DATABASE_URL (see conftest.py)."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pytest

openpyxl = pytest.importorskip("openpyxl")

from omnimodel import lead_export, tracking
from omnimodel.lead_export import ExportIn
from omnimodel.tracking import EventIn, OutcomeIn, SaveLead


def lead(place_id="p1", **kw) -> SaveLead:
    base = dict(place_id=place_id, name="Acme Ltd", city="Accra", region="Greater Accra", sector="it", phone="+233301234567",
                website="https://acme.example", types=["office"], rating=4.5, review_count=12,
                ownership="non_government", ownership_confidence="assumed",
                snapshot={"best_offering": "web", "scores": {"web": {"score": 0.8}}})
    base.update(kw)
    return SaveLead(**base)


def save(ctx, **kw) -> dict:
    return tracking.save_lead(ctx, lead(**kw))["lead"]


def make(ctx, **req) -> openpyxl.Workbook:
    blob, name = lead_export.export_workbook(ctx, ExportIn(**req))
    assert name.endswith(".xlsx")
    return openpyxl.load_workbook(io.BytesIO(blob))


def rows(ws):
    return [[c.value for c in r] for r in ws.iter_rows(min_row=2)]


PROFILE = {"business": {"our_name": "Shield Security", "our_email": "hi@shield.example", "service": "Guarding and K9"}, "country": "Ghana",
           "offerings": {"guarding": {"label": "Manned Guarding", "description": "On-site guards"}}}


# ------------------------------------------------------------------ no database needed
def test_week_bounds_runs_monday_to_sunday():
    start, end, first, last = lead_export.week_bounds(date(2026, 11, 4), 0)   # a Wednesday
    assert (first, last) == (date(2026, 11, 2), date(2026, 11, 8))
    assert end - start == timedelta(days=7) and start == datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_week_bounds_follow_the_persons_time_zone():
    # JavaScript reports +300 for UTC-5: their Monday 00:00 is 05:00 UTC.
    start, _, _, _ = lead_export.week_bounds(date(2026, 11, 2), 300)
    assert start == datetime(2026, 11, 2, 5, tzinfo=timezone.utc)


def test_request_rejects_a_bad_time_zone():
    with pytest.raises(Exception):
        ExportIn(tz_offset_minutes=99999)


def test_describe_status_change_and_note():
    assert lead_export._describe("status_change", {"from": "new", "to": "contacted"}) == "New to Contacted"
    assert lead_export._describe("note", {"note": "Call back"}) == "Call back"
    assert lead_export._describe("visit", None) == ""


# ------------------------------------------------------------------ with a database
def test_all_leads_workbook_layout(member):
    ctx = member("a")
    a = save(ctx, place_id="a1", name="Alpha")
    save(ctx, place_id="a2", name="Beta")
    tracking.log_event(ctx, a["id"], EventIn(type="call_answered", note="Spoke to the manager"))
    wb = make(ctx, scope="all", profile=PROFILE)
    assert wb.sheetnames == ["Summary", "Leads", "History", "Business profile"]
    leads = wb["Leads"]
    assert [c.value for c in leads[1]][:3] == ["Company", "Status", "Sector"]
    by_name = {r[0]: r for r in rows(leads)}
    assert set(by_name) == {"Alpha", "Beta"}
    assert by_name["Alpha"][1] == "Contacted" and by_name["Beta"][1] == "New"
    assert by_name["Alpha"][12] == "Manned Guarding" or by_name["Alpha"][12] == "Web"   # best-fit service label
    assert by_name["Alpha"][13] == 80
    assert by_name["Alpha"][7] == "+233301234567"           # phone numbers keep their plus sign
    history = rows(wb["History"])
    assert any(r[0] == "Alpha" and r[2] == "Spoke by phone" and "manager" in r[3] for r in history)
    assert any(r[2] == "Status changed" and r[3] == "New to Contacted" for r in history)


def test_business_profile_is_the_last_sheet(member):
    wb = make(member("p"), scope="all", profile=PROFILE)
    items = {r[0]: r[1] for r in rows(wb["Business profile"])}
    assert items["Company / sender"] == "Shield Security"
    assert items["Email"] == "hi@shield.example"
    assert items["What we offer"] == "Guarding and K9"
    assert items["Service: Manned Guarding"] == "On-site guards"
    assert wb.sheetnames[-1] == "Business profile"


def test_missing_profile_still_exports(member):
    wb = make(member("np"), scope="all")
    assert "No business profile" in wb["Business profile"]["A1"].value


def test_single_lead(member):
    ctx = member("s")
    one = save(ctx, place_id="s1", name="Solo Ltd")
    save(ctx, place_id="s2", name="Other")
    wb = make(ctx, scope="lead", lead_id=one["id"])
    assert [r[0] for r in rows(wb["Leads"])] == ["Solo Ltd"]
    assert "Solo Ltd" in wb["Summary"]["B3"].value


def test_single_lead_of_another_business_is_not_found(member):
    mine, theirs = member("mine"), member("theirs")
    stranger = save(theirs, place_id="x1", name="Not yours")
    with pytest.raises(tracking.NotFound):
        lead_export.export_workbook(mine, ExportIn(scope="lead", lead_id=stranger["id"]))


def test_other_businesses_leads_never_appear(member):
    mine, theirs = member("m2"), member("t2")
    save(mine, place_id="m1", name="Mine")
    save(theirs, place_id="t1", name="Theirs")
    wb = make(mine, scope="all")
    assert [r[0] for r in rows(wb["Leads"])] == ["Mine"]


def test_status_filter(member):
    ctx = member("f")
    a = save(ctx, place_id="f1", name="Called")
    save(ctx, place_id="f2", name="Fresh")
    tracking.log_event(ctx, a["id"], EventIn(type="call_attempt"))
    wb = make(ctx, scope="all", status="contacted")
    assert [r[0] for r in rows(wb["Leads"])] == ["Called"]
    assert "status: Contacted" in wb["Summary"]["B3"].value


def test_week_scope_includes_this_week_and_excludes_old_weeks(member):
    ctx = member("w")
    save(ctx, place_id="w1", name="This week")
    today = datetime.now(timezone.utc).date()
    wb = make(ctx, scope="week", week_start=today)
    assert wb.sheetnames[2] == "Activity this week"
    assert [r[0] for r in rows(wb["Leads"])] == ["This week"]
    old = make(ctx, scope="week", week_start=today - timedelta(days=70))
    assert rows(old["Leads"]) == []


def test_week_scope_only_lists_that_weeks_activity(member):
    ctx = member("w2")
    one = save(ctx, place_id="w2a", name="Busy")
    tracking.log_event(ctx, one["id"], EventIn(type="email_sent"))
    last_month = datetime.now(timezone.utc) - timedelta(days=40)
    tracking.log_event(ctx, one["id"], EventIn(type="call_attempt", occurred_at=last_month))
    wb = make(ctx, scope="week", week_start=datetime.now(timezone.utc).date())
    kinds = {r[2] for r in rows(wb["Activity this week"])}
    assert "Emailed" in kinds and "Called, no answer" not in kinds


def test_won_lead_carries_its_outcome(member):
    ctx = member("o")
    one = save(ctx, place_id="o1", name="Big client")
    tracking.set_outcome(ctx, one["id"], OutcomeIn(result="won", deal_value=12000, currency="GHS", offerings_sold=["guarding"]))
    two = save(ctx, place_id="o2", name="Gone")
    tracking.set_outcome(ctx, two["id"], OutcomeIn(result="lost", lost_reason="price", competitor_name="Rival"))
    by_name = {r[0]: r for r in rows(make(ctx, scope="all")["Leads"])}
    assert by_name["Big client"][1] == "Won" and by_name["Big client"][20] == "Won" and by_name["Big client"][21] == 12000
    assert by_name["Big client"][22] == "GHS"
    assert by_name["Gone"][23] == "Price" and by_name["Gone"][24] == "Rival"


def test_text_from_the_web_never_becomes_a_formula(member):
    ctx = member("x")
    save(ctx, place_id="e1", name='=HYPERLINK("http://evil.example","click")', address="@SUM(1+1)")
    tracking.log_event(ctx, tracking.list_leads(ctx)["leads"][0]["id"], EventIn(type="note", note="=1+1"))
    wb = make(ctx, scope="all")
    cell = wb["Leads"]["A2"]
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")
    assert wb["Leads"]["G2"].data_type == "s"
    assert wb["History"]["D2"].data_type == "s"


def test_control_characters_do_not_break_the_file(member):
    ctx = member("c")
    save(ctx, place_id="c1", name="Bad\x0bName\x07")      # Postgres itself refuses NUL, but allows these
    assert rows(make(ctx, scope="all")["Leads"])[0][0] == "BadName"
    assert lead_export._clean_text("a\x00b") == "ab"


def test_bad_requests(member):
    ctx = member("v")
    with pytest.raises(tracking.BadInput):
        lead_export.export_workbook(ctx, ExportIn(scope="lead"))
    with pytest.raises(tracking.BadInput):
        lead_export.export_workbook(ctx, ExportIn(scope="week"))
    with pytest.raises(tracking.BadInput):
        lead_export.export_workbook(ctx, ExportIn(scope="all", status="nonsense"))
    with pytest.raises(tracking.NotFound):
        lead_export.export_workbook(ctx, ExportIn(scope="lead", lead_id="00000000-0000-0000-0000-000000000000"))


def test_empty_workspace_still_gives_a_valid_file(member):
    wb = make(member("empty"), scope="all")
    assert rows(wb["Leads"]) == [] and wb["Summary"]["B6"].value == 0