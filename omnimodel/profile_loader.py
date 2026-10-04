"""Load and validate business profiles (YAML in ./profiles). The engine reads everything business-specific from here."""
from pathlib import Path
import yaml

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"
REQUIRED = ["name", "country", "business", "offerings", "sectors", "geography", "signal_schema", "outreach"]

def list_profiles():
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))

def load_profile(stem):
    data = yaml.safe_load((PROFILE_DIR / f"{stem}.yaml").read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"Profile '{stem}' is missing: {', '.join(missing)}")
    for sk, s in data["sectors"].items():
        bad = [o for o in s.get("fit", {}) if o not in data["offerings"]]
        if bad:
            raise ValueError(f"Sector '{sk}' scores unknown offerings: {bad}")
    for kind in ("email", "proposal", "followup"):
        if kind not in data["outreach"]:
            raise ValueError(f"Profile '{stem}' needs an outreach.{kind} template")
    return data

def context_notes(profile, region, sector, offering):
    return [n["note"] for n in profile.get("context_notes") or []
            if n.get("region", region) == region and n.get("sector", sector) == sector and n.get("offering", offering) == offering]
