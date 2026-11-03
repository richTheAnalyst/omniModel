"""Saved leads and tracking. The first group needs no database; the rest need TEST_DATABASE_URL (see conftest.py)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from omnimodel import db, tracking
from omnimodel.tracking import EventIn, OutcomeIn, PatchLead, SaveLead


def lead(place_id="p1", **kw) -> SaveLead:
    base = dict(place_id=place_id, name="Acme Ltd", city="Accra", region="Greater Accra", sector="it", phone="0301234567",
                website="https://acme.example", lat=5.6, lng=-0.18, types=["office"], rating=4.5, review_count=12,
                ownership="non_government", ownership_confidence="assumed",
                snapshot={"best_offering": "web", "scores": {"web": {"score": 0.8}}})
    base.update(kw)
    return SaveLead(**base)


def save(ctx, **kw) -> dict:
    return tracking.save_lead(ctx, lead(**kw))["lead"]


def now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ no database needed
@pytest.mark.parametrize("current,event,expected", [
    ("new", "call_attempt", "contacted"), ("new", "email_sent", "contacted"), ("new", "whatsapp_sent", "contacted"),
    ("new", "meeting", "meeting"), ("contacted", "meeting", "meeting"),
    ("new", "proposal_sent", "proposal"), ("contacted", "proposal_sent", "proposal"), ("meeting", "proposal_sent", "proposal"),
    ("contacted", "call_attempt", None), ("proposal", "meeting", None), ("proposal", "email_sent", None),
    ("won", "call_attempt", None), ("lost", "proposal_sent", None), ("not_interested", "meeting", None),
    ("new", "note", None),
])
def test_auto_status(current, event, expected):
    assert tracking.auto_status(current, event) == expected


def test_save_lead_cleans_input():
    s = SaveLead(place_id="  abc ", name="   ", phone="", types=["a", 5, "", "b" * 200] + ["x"] * 30, extra_field="ignored")
    assert s.place_id == "abc" and s.name is None and s.phone is None
    assert len(s.types) == 20 and s.types[1] == "b" * 80


@pytest.mark.parametrize("bad", [dict(place_id=""), dict(place_id="x", lat=91), dict(place_id="x", lng=-181),
                                 dict(place_id="x", rating=6), dict(place_id="x", ownership="maybe"),
                                 dict(place_id="x", ownership_confidence="sure"),
                                 dict(place_id="x", snapshot={"big": "y" * 120_000})])
def test_save_lead_rejects_bad_input(bad):
    with pytest.raises(ValidationError):
        SaveLead(**bad)


def test_patch_tells_clear_from_absent():
    assert "next_follow_up_at" not in PatchLead(status="contacted").model_fields_set
    assert "next_follow_up_at" in PatchLead(next_follow_up_at=None).model_fields_set


def test_event_and_outcome_validation():
    with pytest.raises(ValidationError):
        EventIn(type="note")
    with pytest.raises(ValidationError):
        EventIn(type="note", note="   ")
    with pytest.raises(ValidationError):
        EventIn(type="status_change")        # written by the server only
    assert EventIn(type="call_attempt").note is None
    with pytest.raises(ValidationError):
        OutcomeIn(result="won", deal_value=-1)
    with pytest.raises(ValidationError):
        OutcomeIn(result="lost", lost_reason="because")


# ------------------------------------------------------------------ accounts and isolation
def test_first_request_creates_one_workspace(member):
    a = member("ama")
    assert a.role == "owner"
    again = tracking.resolve_member({"sub": _sub_of(a)})
    assert again == a


def _sub_of(ctx):
    with db.connection() as conn:
        return conn.execute("select auth_subject from users where id = %s::uuid", (ctx.user_id,)).fetchone()["auth_subject"]


def test_workspace_header(member):
    a, b = member("a"), member("b")
    sub = _sub_of(a)
    assert tracking.resolve_member({"sub": sub}, a.workspace_id) == a
    with pytest.raises(tracking.Forbidden):
        tracking.resolve_member({"sub": sub}, b.workspace_id)
    with pytest.raises(tracking.BadInput):
        tracking.resolve_member({"sub": sub}, "not-a-uuid")


def test_businesses_cannot_see_each_other(member):
    a, b = member("a"), member("b")
    mine = save(a, place_id="shared-place")
    theirs = save(b, place_id="shared-place")           # same company, different business: a separate lead
    assert mine["id"] != theirs["id"]
    assert tracking.list_leads(b)["total"] == 1
    for call in (lambda: tracking.get_lead(b, mine["id"]),
                 lambda: tracking.update_lead(b, mine["id"], PatchLead(status="contacted")),
                 lambda: tracking.log_event(b, mine["id"], EventIn(type="note", note="hi")),
                 lambda: tracking.set_outcome(b, mine["id"], OutcomeIn(result="won")),
                 lambda: tracking.delete_lead(b, mine["id"])):
        with pytest.raises(tracking.NotFound):
            call()
    assert tracking.get_lead(a, mine["id"])["lead"]["status"] == "new"
    assert tracking.get_lead(a, mine["id"])["events"] == []
    with pytest.raises(tracking.NotFound):
        tracking.get_lead(a, "not-a-uuid")


# ------------------------------------------------------------------ saving
def test_save_then_save_again_refreshes_but_keeps_progress(member):
    a = member()
    first = tracking.save_lead(a, lead())
    assert first["created"] is True and first["lead"]["status"] == "new" and first["lead"]["types"] == ["office"]
    tracking.log_event(a, first["lead"]["id"], EventIn(type="call_attempt", note="rang twice"))
    second = tracking.save_lead(a, lead(phone="0309999999", rating=4.0, website=None))
    assert second["created"] is False and second["lead"]["id"] == first["lead"]["id"]
    got = second["lead"]
    assert got["phone"] == "0309999999" and got["website"] == "https://acme.example"   # missing field keeps the old value
    assert got["status"] == "contacted" and got["contact_attempts"] == 1               # progress is untouched
    assert tracking.list_leads(a)["total"] == 1


def test_weak_ownership_guess_never_replaces_a_checked_one(member):
    a = member()
    save(a, ownership="government", ownership_confidence="ai")
    got = save(a, ownership="non_government", ownership_confidence="assumed")
    assert (got["ownership"], got["ownership_confidence"]) == ("government", "ai")
    got = save(a, ownership="non_government", ownership_confidence="high")             # a stronger label does replace it
    assert (got["ownership"], got["ownership_confidence"]) == ("non_government", "high")


# ------------------------------------------------------------------ logging what happens
def test_contact_events_move_status_forward_only(member):
    a = member()
    lid = save(a)["id"]
    r = tracking.log_event(a, lid, EventIn(type="call_attempt"))
    assert r["lead"]["status"] == "contacted" and r["lead"]["contact_attempts"] == 1 and r["lead"]["last_contacted_at"]
    assert tracking.log_event(a, lid, EventIn(type="meeting"))["lead"]["status"] == "meeting"
    assert tracking.log_event(a, lid, EventIn(type="proposal_sent"))["lead"]["status"] == "proposal"
    r = tracking.log_event(a, lid, EventIn(type="email_sent"))
    assert r["lead"]["status"] == "proposal" and r["lead"]["contact_attempts"] == 4    # never goes backwards
    types = [e["type"] for e in tracking.get_lead(a, lid)["events"]]
    assert types.count("status_change") == 3 and types.count("call_attempt") == 1


def test_notes_are_history_only(member):
    a = member()
    lid = save(a)["id"]
    r = tracking.log_event(a, lid, EventIn(type="note", note="Asked us to come back after the audit"))
    assert r["lead"]["status"] == "new" and r["lead"]["contact_attempts"] == 0 and r["lead"]["last_contacted_at"] is None
    assert tracking.get_lead(a, lid)["lead"]["last_note"] == "Asked us to come back after the audit"
    assert r["event"]["detail"] == {"note": "Asked us to come back after the audit"}


def test_backdated_and_future_events(member):
    a = member()
    lid = save(a)["id"]
    earlier = now() - timedelta(days=3)
    tracking.log_event(a, lid, EventIn(type="call_answered", occurred_at=earlier))
    got = tracking.get_lead(a, lid)["lead"]
    assert got["last_contacted_at"].startswith(earlier.date().isoformat()) or got["last_contacted_at"][:10] in (
        (earlier - timedelta(days=1)).date().isoformat(), earlier.date().isoformat())
    with pytest.raises(tracking.BadInput):
        tracking.log_event(a, lid, EventIn(type="call_attempt", occurred_at=now() + timedelta(hours=2)))
    assert tracking.get_lead(a, lid)["lead"]["contact_attempts"] == 1


def test_do_not_contact_blocks_contact_but_not_notes(member):
    a = member()
    lid = save(a)["id"]
    assert tracking.update_lead(a, lid, PatchLead(do_not_contact=True))["lead"]["do_not_contact"] is True
    with pytest.raises(tracking.Conflict):
        tracking.log_event(a, lid, EventIn(type="email_sent"))
    assert tracking.get_lead(a, lid)["lead"]["contact_attempts"] == 0
    tracking.log_event(a, lid, EventIn(type="note", note="Asked not to be contacted"))
    tracking.update_lead(a, lid, PatchLead(do_not_contact=False))
    assert tracking.log_event(a, lid, EventIn(type="email_sent"))["lead"]["status"] == "contacted"
    kinds = [e["type"] for e in tracking.get_lead(a, lid)["events"]]
    assert "do_not_contact_on" in kinds and "do_not_contact_off" in kinds


def test_follow_up_reminders(member):
    a = member()
    lid = save(a)["id"]
    soon = now() + timedelta(days=2)
    r = tracking.log_event(a, lid, EventIn(type="call_attempt", note="no answer", follow_up_at=soon))
    assert r["lead"]["next_follow_up_at"] is not None
    assert tracking.list_leads(a, due=True)["total"] == 0                                # not due yet
    tracking.update_lead(a, lid, PatchLead(next_follow_up_at=now() - timedelta(hours=1)))
    due = tracking.list_leads(a, due=True)
    assert due["total"] == 1 and tracking.pipeline(a)["due"] == 1
    r = tracking.log_event(a, lid, EventIn(type="call_answered"))                        # acting on it clears the reminder
    assert r["lead"]["next_follow_up_at"] is None and tracking.list_leads(a, due=True)["total"] == 0
    tracking.update_lead(a, lid, PatchLead(next_follow_up_at=soon))
    assert tracking.update_lead(a, lid, PatchLead(next_follow_up_at=None))["lead"]["next_follow_up_at"] is None


# ------------------------------------------------------------------ status and outcome
def test_status_changes_and_reopening(member):
    a = member()
    lid = save(a)["id"]
    assert tracking.update_lead(a, lid, PatchLead(status="not_interested"))["lead"]["status"] == "not_interested"
    with pytest.raises(tracking.BadInput):
        tracking.update_lead(a, lid, PatchLead(status="won"))        # won and lost need the outcome form
    tracking.set_outcome(a, lid, OutcomeIn(result="won", deal_value=1500, currency="GHS", offerings_sold=["web"], contract_months=12))
    got = tracking.get_lead(a, lid)
    assert got["lead"]["status"] == "won" and got["outcome"]["deal_value"] == 1500 and got["outcome"]["offerings_sold"] == ["web"]
    assert tracking.update_lead(a, lid, PatchLead(status="proposal"))["lead"]["status"] == "proposal"
    assert tracking.get_lead(a, lid)["outcome"] is None              # reopened, so the old result is gone


def test_outcome_won_and_lost_details(member):
    a = member()
    lid = save(a)["id"]
    tracking.update_lead(a, lid, PatchLead(next_follow_up_at=now() + timedelta(days=1)))
    r = tracking.set_outcome(a, lid, OutcomeIn(result="lost", lost_reason="price", competitor_name="Rival Co", notes="3x cheaper"))
    assert r["lead"]["status"] == "lost" and r["lead"]["next_follow_up_at"] is None
    assert (r["outcome"]["lost_reason"], r["outcome"]["competitor_name"]) == ("price", "Rival Co")
    r = tracking.set_outcome(a, lid, OutcomeIn(result="won", lost_reason="price", competitor_name="Rival Co"))   # changed their mind
    assert r["lead"]["status"] == "won" and r["outcome"]["lost_reason"] is None and r["outcome"]["competitor_name"] is None
    kinds = [e["type"] for e in tracking.get_lead(a, lid)["events"]]
    assert "won" in kinds and "lost" in kinds and kinds.count("status_change") == 2


# ------------------------------------------------------------------ lists, board, delete
def test_list_filters_search_and_paging(member):
    a = member()
    alpha = save(a, place_id="1", name="Alpha Bank", sector="finance", city="Accra")
    save(a, place_id="2", name="Beta 100% Foods", sector="food", city="Kumasi")
    save(a, place_id="3", name="Gamma_Tech", sector="it", city="Accra")
    tracking.log_event(a, alpha["id"], EventIn(type="call_attempt"))
    assert tracking.list_leads(a)["total"] == 3
    assert [l["name"] for l in tracking.list_leads(a, status="contacted")["leads"]] == ["Alpha Bank"]
    assert tracking.list_leads(a, sector="food")["total"] == 1
    assert tracking.list_leads(a, q="accra")["total"] == 2
    assert tracking.list_leads(a, q="100%")["total"] == 1             # a % typed by the user is not a wildcard
    assert tracking.list_leads(a, q="_")["total"] == 1                # nor is _
    assert tracking.list_leads(a, q="zzz")["total"] == 0
    page = tracking.list_leads(a, limit=2, offset=2)
    assert page["total"] == 3 and len(page["leads"]) == 1
    with pytest.raises(tracking.BadInput):
        tracking.list_leads(a, status="great")


def test_pipeline_board(member):
    a = member()
    ids = [save(a, place_id=str(i))["id"] for i in range(4)]
    tracking.log_event(a, ids[0], EventIn(type="call_attempt"))
    tracking.log_event(a, ids[0], EventIn(type="email_sent"))
    tracking.log_event(a, ids[1], EventIn(type="proposal_sent"))
    tracking.set_outcome(a, ids[2], OutcomeIn(result="won"))
    board = tracking.pipeline(a)
    assert board["counts"] == {"new": 1, "contacted": 1, "meeting": 0, "proposal": 1, "won": 1, "lost": 0, "not_interested": 0}
    assert board["total"] == 4
    assert board["week"]["call_attempt"] == 1 and board["week"]["email_sent"] == 1 and board["week"]["won"] == 1


def test_delete_needs_owner_or_admin_and_removes_history(member):
    a = member()
    lid = save(a)["id"]
    tracking.log_event(a, lid, EventIn(type="note", note="x"))
    viewer = tracking.Ctx(user_id=a.user_id, workspace_id=a.workspace_id, role="member")
    with pytest.raises(tracking.Forbidden):
        tracking.delete_lead(viewer, lid)
    assert tracking.delete_lead(a, lid) == {"deleted": True}
    with pytest.raises(tracking.NotFound):
        tracking.get_lead(a, lid)
    with db.connection() as conn:
        assert conn.execute("select count(*) as n from lead_events where lead_id = %s::uuid", (lid,)).fetchone()["n"] == 0


def test_two_people_logging_at_once(member):
    a = member()
    lid = save(a)["id"]
    errors = []

    def work():
        try:
            for _ in range(5):
                tracking.log_event(a, lid, EventIn(type="call_attempt"))
        except Exception as exc:                      # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    got = tracking.get_lead(a, lid)
    assert got["lead"]["contact_attempts"] == 10 and [e["type"] for e in got["events"]].count("status_change") == 1