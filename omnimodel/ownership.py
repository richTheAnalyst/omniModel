"""Is an organisation part of government or the public sector? Best-effort, always with a confidence level.
Signals, strongest first: Google place type, website domain (.gov.xx, .go.xx), name patterns. Otherwise "assumed" non-government."""
import re
from urllib.parse import urlparse

GOV_TYPES = {"local_government_office", "government_office", "city_hall", "courthouse", "embassy", "police", "fire_station"}
GOV_LABELS = {"gov", "govt", "gob", "gouv", "mil"}

# Phrases that clearly name a public body. Extend this list for your market (the Ghana entries are examples).
NAME_PHRASES = [
    "ministry of", "ministries", "municipal assembly", "metropolitan assembly", "district assembly", "municipality of",
    "city council", "county council", "county government", "regional coordinating council", "local government",
    "government of", "government hospital", "government school", "government college", "government office",
    "public service", "police service", "police station", "fire service", "immigration service", "customs division",
    "revenue authority", "revenue agency", "department of", "parliament of", "national assembly", "judicial service",
    "high court", "supreme court", "high commission", "ghana health service", "ghana education service",
    "ghana revenue authority", "ghana ports and harbours", "ghana highway authority",
]
_NAME_RX = re.compile(r"\b(" + "|".join(re.escape(p) for p in NAME_PHRASES) + r")\b", re.I)


def _host(website):
    if not website:
        return ""
    return (urlparse(website if "//" in website else "//" + website).hostname or "").lower()


def _gov_domain(host):
    parts = host.split(".")
    return any(p in GOV_LABELS for p in parts) or (len(parts) >= 3 and parts[-2] == "go" and len(parts[-1]) == 2)


def classify(name, website=None, types=None):
    """Returns ownership ("government" | "non_government"), ownership_confidence ("high" | "assumed"),
    ownership_source and ownership_reason."""
    hit = set(types or []) & GOV_TYPES
    if hit:
        return _r("government", "high", "places_type", f"Listed on Google Maps as: {', '.join(sorted(hit))}.")
    host = _host(website)
    if host and _gov_domain(host):
        return _r("government", "high", "website_domain", f"The website address ({host}) is a government domain.")
    m = _NAME_RX.search(name or "")
    if m:
        return _r("government", "high", "name", f"The name contains \"{m.group(1)}\".")
    return _r("non_government", "assumed", "none", "No government indicators found. Not verified; run Analyze to check.")


def refine(base, ai):
    """Combine the quick check with the AI's judgement. Strong evidence (high confidence) is never overridden."""
    if base["ownership_confidence"] == "high" or not ai:
        return base
    return _r(ai["value"], "ai", "ai", ai.get("reason") or "Judged from the website content.")


def _r(own, conf, src, reason):
    return {"ownership": own, "ownership_confidence": conf, "ownership_source": src, "ownership_reason": reason}