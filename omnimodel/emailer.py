"""Send an email (a proposal, an introduction, a follow-up) from the app, with the sender's replies going to them.

Mail goes out through whatever SMTP service the server is set up with (Gmail with an app password, Brevo, Zoho, SendGrid's
SMTP and so on). Settings, all environment variables:
  SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_SECURITY (starttls | ssl | none, default starttls),
  SMTP_FROM       the address mail is sent from, e.g. proposals@yourdomain.com
  EMAIL_DAILY_LIMIT   emails per business per day (default 50)

The message is From the server's own address (shown as the business's name) and Reply-To the business's own email, so the
person's replies reach them. It is not sent "as" their address: that needs their own mail login and is a different feature."""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal

from pydantic import BaseModel, Field

from . import db, proposal_pdf
from .tracking import BadInput, Ctx, EventIn, NotFound

MAX_ATTACHMENT = 10 * 1024 * 1024
_ADDRESS = re.compile(r"^[^\s@<>\",;]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,}$")
_FOOTER = ("\n\n--\nSent with Omni Model on behalf of {name}. Reply to this email to reach them directly. "
           "If you would rather not hear from them again, just reply and say so.")


class NotConfigured(RuntimeError):
    """The server has no mail settings yet."""


class Attachment(BaseModel):
    kind: Literal["none", "designed", "text"] = "none"
    render: proposal_pdf.RenderIn | None = None      # kind "designed": the person's own PDF design, filled in and edited
    text: str | None = Field(default=None, max_length=50_000)   # kind "text": the editable proposal, sent as a PDF
    filename: str = Field(default="Proposal", max_length=80)


class SendIn(BaseModel):
    to: str = Field(max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    sender_name: str = Field(default="", max_length=120)       # the business's name, shown as the sender
    reply_to: str = Field(default="", max_length=254)           # where replies go: the business's own email
    lead_id: str | None = None                                  # a saved lead: the send is logged on its history
    kind: Literal["email", "proposal", "followup"] = "email"
    attachment: Attachment = Field(default_factory=Attachment)


def settings() -> dict | None:
    host, sender = os.getenv("SMTP_HOST", "").strip(), os.getenv("SMTP_FROM", "").strip()
    if not host or not sender:
        return None
    return {"host": host, "port": int(os.getenv("SMTP_PORT", "587") or 587), "user": os.getenv("SMTP_USER", ""),
            "password": os.getenv("SMTP_PASSWORD", ""), "security": os.getenv("SMTP_SECURITY", "starttls").lower(), "from": sender}


def enabled() -> bool:
    return settings() is not None


def daily_limit() -> int:
    try:
        return max(1, int(os.getenv("EMAIL_DAILY_LIMIT", "50")))
    except ValueError:
        return 50


def sent_today(ctx: Ctx) -> int:
    with db.connection() as conn:
        row = conn.execute(
            "select count(*) as n from email_sends where workspace_id = %s::uuid and status <> 'failed' "
            "and created_at > now() - interval '24 hours'", (ctx.workspace_id,)).fetchone()
    return int(row["n"])


def status(ctx: Ctx) -> dict:
    return {"enabled": enabled(), "sent_today": sent_today(ctx) if enabled() else 0, "daily_limit": daily_limit()}


def _clean_line(text: str) -> str:
    return re.sub(r"[\r\n\t]+", " ", text).strip()


def _attachment_bytes(ctx: Ctx, att: Attachment) -> tuple[bytes, str] | None:
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", att.filename).strip(" ._") or "Proposal"
    if att.kind == "designed":
        if att.render is None:
            raise BadInput("Choose what to attach.")
        return proposal_pdf.render(ctx, att.render), f"{safe}.pdf"
    if att.kind == "text":
        if not (att.text or "").strip():
            raise BadInput("There is no proposal text to attach.")
        from .export import export_pdf
        return export_pdf(att.text), f"{safe}.pdf"
    return None


def build_message(req: SendIn, sender: str, reply_to: str, attachment: tuple[bytes, str] | None) -> EmailMessage:
    name = _clean_line(req.sender_name) or "Omni Model"
    msg = EmailMessage()
    msg["From"] = formataddr((name, sender))
    msg["To"] = req.to
    msg["Subject"] = _clean_line(req.subject)
    if reply_to:
        msg["Reply-To"] = formataddr((name, reply_to))
    msg.set_content(req.body.replace("\r\n", "\n").rstrip() + _FOOTER.format(name=name))
    if attachment:
        data, filename = attachment
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=filename)
    return msg


def _deliver(cfg: dict, msg: EmailMessage) -> None:
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
    with server:
        if cfg["security"] == "starttls":
            server.starttls(context=ssl.create_default_context())
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def send(ctx: Ctx, req: SendIn) -> dict:
    cfg = settings()
    if cfg is None:
        raise NotConfigured("Sending email from the app is not switched on for this server yet.")
    to = req.to.strip()
    if not _ADDRESS.match(to):
        raise BadInput("Enter one valid email address to send to.")
    reply_to = req.reply_to.strip()
    if reply_to and not _ADDRESS.match(reply_to):
        raise BadInput("Your reply-to email address does not look right. Check it in Settings.")
    if sent_today(ctx) >= daily_limit():
        raise BadInput(f"You have reached today's limit of {daily_limit()} emails. It resets within 24 hours.")
    attachment = _attachment_bytes(ctx, req.attachment)
    if attachment and len(attachment[0]) > MAX_ATTACHMENT:
        raise BadInput("The attachment is larger than 10 MB.")

    req = req.model_copy(update={"to": to})
    msg = build_message(req, cfg["from"], reply_to, attachment)
    with db.connection() as conn:
        row = conn.execute(
            "insert into email_sends (workspace_id, user_id, lead_id, to_address, subject) "
            "values (%s::uuid, %s::uuid, %s::uuid, %s, %s) returning id",
            (ctx.workspace_id, ctx.user_id, req.lead_id, to, msg["Subject"])).fetchone()
    record = row["id"]
    try:
        _deliver(cfg, msg)
    except smtplib.SMTPRecipientsRefused:
        _mark(record, "failed", "recipient refused")
        raise BadInput("That email address was refused. Check it for typing mistakes.")
    except smtplib.SMTPAuthenticationError:
        _mark(record, "failed", "smtp login rejected")
        raise NotConfigured("The server's email login was rejected. Tell whoever runs the server to check the email settings.")
    except (smtplib.SMTPException, OSError) as exc:
        _mark(record, "failed", type(exc).__name__)
        raise NotConfigured("The email service could not be reached right now. Nothing was sent; please try again.")
    _mark(record, "sent", None)

    logged = False
    if req.lead_id:
        try:                                       # remember the address for next time, unless one is already stored
            with db.connection() as conn:
                conn.execute("update leads set email = %s where id = %s::uuid and workspace_id = %s::uuid and email is null",
                             (to, req.lead_id, ctx.workspace_id))
        except Exception:
            pass
        try:                                       # the email is already out, so a failure here must not look like one
            from . import tracking
            kind = "proposal_sent" if req.kind == "proposal" else "email_sent"
            tracking.log_event(ctx, req.lead_id, EventIn(type=kind, note=f"Emailed {to}: {msg['Subject']}"[:2000]))
            logged = True
        except (NotFound, BadInput):
            pass
    return {"ok": True, "to": to, "subject": msg["Subject"], "logged": logged, "sent_today": sent_today(ctx)}


def _mark(record, state: str, error: str | None) -> None:
    with db.connection() as conn:
        conn.execute("update email_sends set status = %s, error = %s where id = %s::uuid", (state, error, record))