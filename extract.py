"""Claude-backed extraction and pitch drafting (legacy; used by main.py).

The maintained Claude path is ``omnimodel.extraction.claude_extractor``, which
honours ``ANTHROPIC_MODEL`` from the environment.
"""
import json

from omnimodel.config import config

SERVICES = {
    "guarding": (
        "Manned Guarding: trained officers and mobile patrol teams protecting "
        "corporate, residential and industrial sites around the clock."
    ),
    "event_vip": (
        "Event VIP Protection: controlled entrances, managed crowds and discreet "
        "VIP protection for high-profile occasions."
    ),
    "k9": (
        "Canine K9 Security: specialist K9 teams that detect threats, deter "
        "intruders and strengthen security in critical environments."
    ),
    "technical": (
        "Technical Cyber Security: CCTV, access control and cyber-focused "
        "solutions that manage electronic risks."
    ),
}


def _client():
    """Build the Anthropic client lazily so importing this module needs no key."""
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env."
        )
    import anthropic

    return anthropic.Anthropic(api_key=config.anthropic_api_key)


def _json(system: str, user: str, max_tokens: int = 1500) -> dict:
    message = _client().messages.create(
        model=config.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = (
        message.content[0].text.strip().removeprefix("```json").removesuffix("```").strip()
    )
    return json.loads(text)


def extract_profile(text: str) -> dict:
    system = (
        "Extract company-level facts from website text. Return ONLY JSON with "
        "keys: name (string), sector (one of mining, bank, industrial, "
        "logistics, hospital, school, retail, hospitality, events, office), "
        "site_count (int, 1 if unknown), size_estimate (int staff or null), "
        "signals (list of {type: expansion|security_job|tender|incident, "
        "summary}). Only use what the text supports. No personal data about "
        "individuals."
    )
    return _json(system, text[:8000])


def write_pitch(company: dict, service: str, risk_notes: list[str]) -> dict:
    if service not in SERVICES:
        raise ValueError(
            f"Unknown service {service!r}. Choose from: {', '.join(SERVICES)}"
        )
    system = (
        "You write concise, professional outreach for Simba Gate Security Ltd, "
        "a Ghanaian security company. Return ONLY JSON: {subject, body}. Body is "
        "plain text, 150-220 words, warm and specific, ending with a call to "
        "arrange a site assessment. Use ONLY the risk notes supplied for local "
        "context. Do not invent statistics, incidents, clients, or claims about "
        "the recipient. Describe only the service given."
    )
    user = json.dumps(
        {"company": company, "service": SERVICES[service], "risk_notes": risk_notes}
    )
    return _json(system, user, 1200)
