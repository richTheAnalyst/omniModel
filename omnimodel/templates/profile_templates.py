"""Fill a profile's outreach templates.

Only supplied facts are used; nothing is invented.
"""
import re

from omnimodel.profile_loader import context_notes

_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}", re.IGNORECASE)


class _Safe(dict):
    """format_map source that leaves unknown placeholders visible instead of raising."""

    def __missing__(self, key):
        return "{" + key + "}"


def _tidy(text: str) -> str:
    """Collapse double spaces and any space left in front of punctuation."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def render(profile, kind, lead, offering, biz=None) -> str:
    """Render one outreach artefact for a lead from a profile's template."""
    if kind not in profile["outreach"]:
        raise KeyError(f"Profile has no outreach.{kind} template")
    if offering not in profile["offerings"]:
        raise KeyError(f"Profile has no offering '{offering}'")
    chosen = profile["offerings"][offering]
    region = lead.get("region") or ""
    notes = context_notes(profile, region, lead.get("sector") or "", offering)
    fields = {
        "company": lead.get("name") or "your company",
        "city": lead.get("city") or region or "your area",
        "offering_label": chosen["label"],
        "offering_desc": chosen["description"],
        "local_context": " ".join(notes),
        **profile.get("business", {}),
        **(biz or {}),
    }
    text = profile["outreach"][kind].format_map(_Safe(fields))
    # A placeholder the profile never defined must not reach a draft.
    return _tidy(_PLACEHOLDER_RE.sub("", text))
