"""Pick a contact email out of a company's website text."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_FOUND = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
_JUNK_DOMAINS = ("example.", "sentry", "wixpress", "domain.com", "email.com", "yourdomain", "yoursite", "mysite", "schema.org", "w3.org")
_JUNK_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_JUNK_NAMES = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "abuse", "privacy", "dpo", "webmaster", "user", "name", "your")
_WELCOME = ("info", "contact", "hello", "sales", "enquiries", "enquiry", "office", "admin", "support", "mail")


def _site_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def find_emails(text: str, site_url: str = "") -> list[str]:
    """Distinct addresses found in the text, best first: on the company's own domain, then a general mailbox like info@."""
    domain = _site_domain(site_url)
    seen: dict[str, int] = {}
    for raw in _FOUND.findall(text or ""):
        addr = raw.strip(".").lower()
        local, _, host = addr.partition("@")
        if addr.endswith(_JUNK_ENDINGS) or any(j in host for j in _JUNK_DOMAINS) or local in _JUNK_NAMES or len(addr) > 254:
            continue
        score = 0
        if domain and (host == domain or host.endswith("." + domain) or domain.endswith("." + host)):
            score -= 10
        if local in _WELCOME:
            score -= 3
        seen.setdefault(addr, score)
    return sorted(seen, key=lambda a: (seen[a], a))[:5]