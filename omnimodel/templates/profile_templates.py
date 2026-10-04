"""Fill a profile's outreach templates. Only supplied facts are used; nothing is invented."""
from omnimodel.profile_loader import context_notes

class _Safe(dict):
    def __missing__(self, k): return "{" + k + "}"

def render(profile, kind, lead, offering, biz):
    o = profile["offerings"][offering]
    notes = context_notes(profile, lead["region"], lead["sector"], offering)
    return profile["outreach"][kind].format_map(_Safe(
        company=lead.get("name") or "your company", city=lead.get("city") or lead["region"],
        offering_label=o["label"], offering_desc=o["description"], local_context=" ".join(notes), **biz)).strip()
