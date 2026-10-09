"""Fill a profile's outreach templates. Only {placeholder} words are replaced, so a template cannot reach into Python objects."""
import re

from omnimodel.profile_loader import context_notes


def render(profile, kind, lead, offering, biz):
    o = profile["offerings"][offering]
    values = {
        "company": lead.get("name") or "your company",
        "city": lead.get("city") or lead.get("region") or "",
        "offering_label": o["label"],
        "offering_desc": o["description"],
        "local_context": " ".join(context_notes(profile, lead.get("region", ""), lead.get("sector", ""), offering)),
        **{str(k): str(v) for k, v in biz.items()},
    }
    template = profile["outreach"][kind]
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template).strip()
