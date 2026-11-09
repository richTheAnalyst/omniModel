"""Sending email from the app. Mail goes to a fake SMTP connection; the database tests need TEST_DATABASE_URL."""
import email
import smtplib

import pytest

from omnimodel import emailer
from omnimodel.emailer import Attachment, SendIn


def req(**kw):
    base = dict(to="buyer@client.example", subject="Proposal for Client Ltd", body="Hello,\nPlease see attached.", sender_name="Shield Security",
                reply_to="hi@shield.example", kind="proposal")
    base.update(kw)
    return SendIn(**base)


# ------------------------------------------------------------------ no database needed
def test_message_has_the_right_headers_and_a_footer():
    msg = emailer.build_message(req(), "proposals@omni.example", "hi@shield.example", None)
    assert msg["To"] == "buyer@client.example" and msg["Subject"] == "Proposal for Client Ltd"
    assert "proposals@omni.example" in msg["From"] and "Shield Security" in msg["From"]
    assert "hi@shield.example" in msg["Reply-To"]
    body = msg.get_content()
    assert body.startswith("Hello,\nPlease see attached.") and "reply and say so" in body


def test_a_pdf_is_attached():
    msg = emailer.build_message(req(), "p@omni.example", "", (b"%PDF-1.4 fake", "Proposal.pdf"))
    parts = list(msg.iter_attachments())
    assert len(parts) == 1 and parts[0].get_filename() == "Proposal.pdf" and parts[0].get_content_type() == "application/pdf"
    assert msg["Reply-To"] is None


def test_line_breaks_cannot_be_smuggled_into_headers():
    msg = emailer.build_message(req(subject="Hi\r\nBcc: spam@evil.example", sender_name="Shield\nBcc: x@y.example"), "p@omni.example", "", None)
    assert "Bcc" not in msg.keys() and "\n" not in msg["Subject"]


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert emailer.settings() is None and not emailer.enabled()
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_FROM", "p@omni.example")
    monkeypatch.setenv("SMTP_PORT", "2525")
    assert emailer.settings()["port"] == 2525 and emailer.enabled()


def test_delivery_uses_starttls_and_login(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, host, port, timeout=0): calls.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): calls.append("starttls")
        def login(self, u, p): calls.append(("login", u))
        def send_message(self, m): calls.append(("send", m["To"]))

    monkeypatch.setattr(smtplib, "SMTP", Fake)
    cfg = {"host": "smtp.example", "port": 587, "user": "me", "password": "pw", "security": "starttls", "from": "p@omni.example"}
    emailer._deliver(cfg, emailer.build_message(req(), "p@omni.example", "", None))
    assert calls == [("connect", "smtp.example", 587), "starttls", ("login", "me"), ("send", "buyer@client.example")]


# ------------------------------------------------------------------ with a database
from omnimodel import tracking
from omnimodel.tracking import SaveLead


@pytest.fixture()
def outbox(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_FROM", "p@omni.example")
    sent = []
    monkeypatch.setattr(emailer, "_deliver", lambda cfg, msg: sent.append(msg))
    return sent


def lead(ctx):
    return tracking.save_lead(ctx, SaveLead(place_id="e1", name="Client Ltd", city="Accra", sector="it"))["lead"]


def test_send_logs_the_email_on_the_lead(member, outbox):
    ctx = member("em")
    one = lead(ctx)
    res = emailer.send(ctx, req(lead_id=one["id"], kind="email"))
    assert res["ok"] and res["logged"] and res["sent_today"] == 1 and len(outbox) == 1
    detail = tracking.get_lead(ctx, one["id"])
    assert any(e["type"] == "email_sent" and "buyer@client.example" in ((e.get("detail") or {}).get("note") or "") for e in detail["events"])


def test_a_proposal_is_logged_as_proposal_sent(member, outbox):
    ctx = member("em2")
    one = lead(ctx)
    emailer.send(ctx, req(lead_id=one["id"], kind="proposal"))
    assert any(e["type"] == "proposal_sent" for e in tracking.get_lead(ctx, one["id"])["events"])


def test_not_configured_is_a_clear_error(member, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(emailer.NotConfigured):
        emailer.send(member("em3"), req())


def test_bad_addresses_are_refused_before_anything_is_sent(member, outbox):
    ctx = member("em4")
    for bad in ("not-an-email", "a@b", "two@x.com, three@y.com", "a b@c.com"):
        with pytest.raises(tracking.BadInput):
            emailer.send(ctx, req(to=bad))
    with pytest.raises(tracking.BadInput):
        emailer.send(ctx, req(reply_to="nope"))
    assert outbox == []


def test_daily_limit(member, outbox, monkeypatch):
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "2")
    ctx = member("em5")
    emailer.send(ctx, req())
    emailer.send(ctx, req())
    with pytest.raises(tracking.BadInput, match="limit"):
        emailer.send(ctx, req())
    assert len(outbox) == 2
    assert emailer.status(ctx) == {"enabled": True, "sent_today": 2, "daily_limit": 2}


def test_a_failed_delivery_does_not_use_up_the_limit(member, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_FROM", "p@omni.example")
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "1")

    def boom(cfg, msg):
        raise smtplib.SMTPRecipientsRefused({"x": (550, b"no")})

    monkeypatch.setattr(emailer, "_deliver", boom)
    ctx = member("em6")
    with pytest.raises(tracking.BadInput, match="refused"):
        emailer.send(ctx, req())
    assert emailer.sent_today(ctx) == 0


def test_the_limit_is_per_business(member, outbox, monkeypatch):
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "1")
    a, b = member("em7"), member("em8")
    emailer.send(a, req())
    emailer.send(b, req())
    assert len(outbox) == 2


def test_text_attachment_is_made_from_the_proposal_text(member, outbox):
    ctx = member("em9")
    emailer.send(ctx, req(attachment=Attachment(kind="text", text="Our proposal\n\nBody text here.", filename="Proposal Client")))
    part = list(outbox[0].iter_attachments())[0]
    assert part.get_filename() == "Proposal Client.pdf" and part.get_content().startswith(b"%PDF")


def test_the_address_is_remembered_on_the_lead_and_not_overwritten(member, outbox):
    ctx = member("em9")
    one = lead(ctx)
    assert tracking.get_lead(ctx, one["id"])["lead"]["email"] is None if "lead" in tracking.get_lead(ctx, one["id"]) else True
    emailer.send(ctx, req(lead_id=one["id"], to="first@client.example"))
    emailer.send(ctx, req(lead_id=one["id"], to="second@client.example"))
    got = tracking.get_lead(ctx, one["id"])
    assert (got.get("lead") or got)["email"] == "first@client.example"


def test_a_lead_can_be_saved_with_an_email(member):
    ctx = member("em10")
    saved = tracking.save_lead(ctx, SaveLead(place_id="p-mail", name="Mail Co", email="  hello@mail.example "))
    assert saved["lead"]["email"] == "hello@mail.example"