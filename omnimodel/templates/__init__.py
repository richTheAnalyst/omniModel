"""Ready-made proposal letters and outreach emails.

Templates are filled with company-specific data extracted by the pipeline.
All templates use Python str.format with named fields, so missing values
fall back gracefully.
"""

from __future__ import annotations

from typing import Any


def _safe(value: Any, default: str = "") -> str:
    """Return str(value) or default if value is None/empty."""
    if value is None:
        return default
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else default
    return str(value) if value else default


def _company_name(signals: dict[str, Any]) -> str:
    return _safe(signals.get("company_name"), "the company")


def _industry(signals: dict[str, Any]) -> str:
    types = signals.get("types") or signals.get("tech_stack") or []
    if isinstance(types, list) and types:
        return ", ".join(str(t) for t in types[:3])
    return _safe(signals.get("industry"), "your industry")


def _website(signals: dict[str, Any]) -> str:
    return _safe(signals.get("website"), "their website")


# ---------------------------------------------------------------------------
# Proposal letter
# ---------------------------------------------------------------------------
PROPOSAL_LETTER_TEMPLATE = """\
{company_name}

{date}

Dear {contact_name},

I hope this letter finds you well. I'm reaching out because {our_name} has been
following {company_name}'s work in {industry} and we're impressed by what
you've built.

We specialize in helping companies like yours {value_prop}. After reviewing
{website}, we believe there's a strong fit between your needs and what we
offer.

Here's what we can deliver:

{deliverables}

Next steps: I'd love to schedule a 15-minute call to discuss how we can support
{company_name} in the coming quarter.

Warm regards,

{our_name}
{our_title}
{our_email}
{our_phone}
"""


def generate_proposal_letter(
    signals: dict[str, Any],
    *,
    our_name: str = "Your Company",
    our_title: str = "Business Development",
    our_email: str = "hello@yourcompany.com",
    our_phone: str = "",
    contact_name: str = "",
    deliverables: str = (
        "- Faster, more reliable operations\n"
        "- Cost savings through automation\n"
        "- Better customer experience"
    ),
    value_prop: str = "optimize operations and grow revenue",
) -> str:
    """Generate a ready-to-send proposal letter for a company."""
    from datetime import date

    return PROPOSAL_LETTER_TEMPLATE.format(
        company_name=_company_name(signals),
        date=date.today().strftime("%B %d, %Y"),
        contact_name=_safe(contact_name, "Decision Maker"),
        our_name=our_name,
        industry=_industry(signals),
        website=_website(signals),
        value_prop=value_prop,
        deliverables=deliverables,
        our_title=our_title,
        our_email=our_email,
        our_phone=f"\n{our_phone}" if our_phone else "",
    )


# ---------------------------------------------------------------------------
# Outreach email
# ---------------------------------------------------------------------------
OUTREACH_EMAIL_TEMPLATE = """\
Subject: {subject}

Hi {contact_name},

I came across {company_name} ({website}) and was impressed by your work in
{industry}. I'm with {our_name}, and we help companies like yours {value_prop}.

I'd love to share a quick case study and see if there's a fit. Are you open to
a brief chat next week?

Best,

{our_name}
{our_title}
{our_email}
"""


def generate_outreach_email(
    signals: dict[str, Any],
    *,
    our_name: str = "Your Company",
    our_title: str = "Business Development",
    our_email: str = "hello@yourcompany.com",
    our_phone: str = "",
    contact_name: str = "",
    deliverables: str = "",
    value_prop: str = "optimize operations and grow revenue",
    subject: str = "Quick question about {company_name}",
) -> str:
    """Generate a ready-to-send outreach email for a company."""
    company = _company_name(signals)
    return OUTREACH_EMAIL_TEMPLATE.format(
        subject=subject.format(company_name=company),
        contact_name=_safe(contact_name, "there"),
        company_name=company,
        website=_website(signals),
        industry=_industry(signals),
        our_name=our_name,
        our_title=our_title,
        our_email=our_email,
        value_prop=value_prop,
    )


# ---------------------------------------------------------------------------
# Follow-up email
# ---------------------------------------------------------------------------
FOLLOWUP_EMAIL_TEMPLATE = """\
Subject: Re: {subject}

Hi {contact_name},

Just circling back on my previous note about {company_name}. No pressure at
all — I wanted to make sure it didn't get lost in the inbox.

If now isn't a good time, happy to reconnect later. Either way, I'd love to
hear what {company_name} is working on next.

Best,

{our_name}
{our_title}
{our_email}
{our_phone}
"""


def generate_followup_email(
    signals: dict[str, Any],
    *,
    our_name: str = "Your Company",
    our_title: str = "Business Development",
    our_email: str = "hello@yourcompany.com",
    our_phone: str = "",
    contact_name: str = "",
    deliverables: str = "",
    value_prop: str = "optimize operations and grow revenue",
    subject: str = "Quick question about {company_name}",
) -> str:
    """Generate a follow-up email for a company."""
    company = _company_name(signals)
    return FOLLOWUP_EMAIL_TEMPLATE.format(
        subject=subject.format(company_name=company),
        contact_name=_safe(contact_name, "there"),
        company_name=company,
        our_name=our_name,
        our_title=our_title,
        our_email=our_email,
        our_phone=f"\n{our_phone}" if our_phone else "",
    )