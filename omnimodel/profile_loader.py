"""Load and validate business profiles.
A profile is either a YAML file in ./profiles (chosen by id) or an object sent by the frontend with each request."""
import json
from pathlib import Path
import yaml

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"
REQUIRED = ["name", "country", "business", "offerings", "sectors", "geography", "signal_schema", "outreach"]
MAX_PROFILE_CHARS = 300_000   # whole profile, as JSON
MAX_TEMPLATE_CHARS = 5_000    # each outreach template


def list_profiles():
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def _labelled(value, key):
    """Offerings and sectors may arrive as plain text or as {label, description}; make them objects."""
    if isinstance(value, str):
        return {"label": value, "description": value}
    if isinstance(value, dict):
        label = str(value.get("label") or key)
        return {**value, "label": label, "description": str(value.get("description") or label)}
    raise ValueError(f"'{key}' must be text or an object with a label.")


def _normalize_profile(data):
    """Check a profile and fill in safe defaults. Raises ValueError with a readable message."""
    if not isinstance(data, dict):
        raise ValueError("Profile must be an object.")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"missing: {', '.join(missing)}")
    if len(json.dumps(data, default=str)) > MAX_PROFILE_CHARS:
        raise ValueError("profile is too large.")
    p = dict(data)
    p["business"] = {str(k): str(v) for k, v in (p["business"] or {}).items()}
    p["offerings"] = {str(k): _labelled(v, k) for k, v in p["offerings"].items()}
    if not p["offerings"] or len(p["offerings"]) > 30:
        raise ValueError("offerings must contain 1 to 30 items.")
    sectors = {}
    for key, s in p["sectors"].items():
        s: dict = _labelled(s, key)
        s["query"] = str(s.get("query") or s["label"])
        try:
            s["priority"] = float(s.get("priority", 0.5))
        except (TypeError, ValueError):
            s["priority"] = 0.5
        s["fit"] = {o: float(v) for o, v in (s.get("fit") or {}).items() if o in p["offerings"]}
        sectors[str(key)] = s
    p["sectors"] = sectors
    if not isinstance(p["geography"], dict):
        raise ValueError("geography must map regions to city lists.")
    for kind in ("email", "proposal", "followup"):
        t = p["outreach"].get(kind) if isinstance(p["outreach"], dict) else None
        if not isinstance(t, str) or not t.strip():
            raise ValueError(f"outreach.{kind} template is required.")
        if len(t) > MAX_TEMPLATE_CHARS:
            raise ValueError(f"outreach.{kind} template is too long.")
    p.setdefault("weights", {})
    p.setdefault("buying_signal_keywords", [])
    p["context_notes"] = [n for n in (p.get("context_notes") or []) if isinstance(n, dict) and n.get("note")]
    return p


def normalize_profile(data):
    """Same checks, but a wrongly shaped profile (for example a list where an object is expected) gives a clear error."""
    try:
        return _normalize_profile(data)
    except (AttributeError, TypeError) as exc:
        raise ValueError(f"wrong shape ({exc.__class__.__name__}): offerings, sectors, geography, outreach and business must be objects.")


def load_profile(stem):
    data = yaml.safe_load((PROFILE_DIR / f"{stem}.yaml").read_text(encoding="utf-8"))
    try:
        return normalize_profile(data)
    except ValueError as exc:
        raise ValueError(f"Profile '{stem}': {exc}")


def context_notes(profile, region, sector, offering):
    return [str(n["note"]) for n in profile.get("context_notes") or []
            if n.get("region", region) == region and n.get("sector", sector) == sector and n.get("offering", offering) == offering]