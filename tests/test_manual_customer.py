"""Companies added by hand, and existing customers. Needs TEST_DATABASE_URL (see conftest.py)."""
from __future__ import annotations

import uuid

from omnimodel import tracking
from omnimodel.tracking import EventIn, OutcomeIn, SaveLead


def manual(ctx, name="Old Client Ltd", **kw) -> dict:
    data = dict(place_id=f"manual:{uuid.uuid4()}", name=name, city="Kumasi", phone="0244000000")
    data.update(kw)
    return tracking.save_lead(ctx, SaveLead(**data))["lead"]


def test_a_company_added_by_hand_is_saved_and_listed(member):
    ctx = member("m1")
    lead = manual(ctx)
    assert lead["status"] == "new" and lead["place_id"].startswith("manual:") and lead["snapshot"] is None
    assert [l["name"] for l in tracking.list_leads(ctx)["leads"]] == ["Old Client Ltd"]


def test_adding_the_same_company_twice_by_hand_makes_two_entries(member):
    ctx = member("m2")
    manual(ctx), manual(ctx)     # each form submission gets its own id
    assert tracking.list_leads(ctx)["total"] == 2


def test_existing_customer_is_won_but_not_counted_as_a_win_this_week(member):
    ctx = member("m3")
    lead = manual(ctx)
    res = tracking.set_outcome(ctx, lead["id"], OutcomeIn(result="won", imported=True))
    assert res["lead"]["status"] == "won"
    assert tracking.pipeline(ctx)["week"].get("won", 0) == 0
    assert tracking.pipeline(ctx)["counts"]["won"] == 1


def test_a_real_win_still_counts_this_week(member):
    ctx = member("m4")
    lead = manual(ctx)
    tracking.set_outcome(ctx, lead["id"], OutcomeIn(result="won"))
    assert tracking.pipeline(ctx)["week"]["won"] == 1


def test_notes_and_contacts_work_on_a_manual_lead(member):
    ctx = member("m5")
    lead = manual(ctx)
    out = tracking.log_event(ctx, lead["id"], EventIn(type="call_answered", note="Renewal talk"))
    assert out["lead"]["status"] == "contacted"