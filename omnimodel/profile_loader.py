"""Load and validate business profiles (YAML in omnimodel/profiles).

The engine reads everything business-specific from here.
"""
from pathlib import Path

import yaml

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
REQUIRED = [
    "name",
    "country",
    "business",
    "offerings",
    "sectors",
    "geography",
    "signal_schema",
    "outreach",
]
OUTREACH_KINDS = ("email", "proposal", "followup")


def list_profiles():
    """Return the stems of every profile YAML shipped with the package."""
    if not PROFILE_DIR.is_dir():
        return []
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def profile_path(stem):
    """Resolve a profile stem to its YAML file, refusing paths outside PROFILE_DIR."""
    if not stem or stem != Path(stem).name or stem.startswith("."):
        raise ValueError(f"Invalid profile name {stem!r}.")
    path = (PROFILE_DIR / f"{stem}.yaml").resolve()
    if path.parent != PROFILE_DIR.resolve():
        raise ValueError(f"Invalid profile name {stem!r}.")
    if not path.is_file():
        raise FileNotFoundError(f"No profile named '{stem}' in {PROFILE_DIR}.")
    return path


def load_profile(stem):
    data = yaml.safe_load(profile_path(stem).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Profile '{stem}' must be a YAML mapping.")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"Profile '{stem}' is missing: {', '.join(missing)}")
    for sk, s in data["sectors"].items():
        bad = [o for o in s.get("fit", {}) if o not in data["offerings"]]
        if bad:
            raise ValueError(f"Sector '{sk}' scores unknown offerings: {bad}")
    for kind in OUTREACH_KINDS:
        if kind not in data["outreach"]:
            raise ValueError(f"Profile '{stem}' needs an outreach.{kind} template")
    for rk, cities in data["geography"].items():
        if not cities:
            raise ValueError(f"Region '{rk}' in profile '{stem}' has no cities")
    return data


def context_notes(profile, region, sector, offering):
    """Notes that apply to this exact region/sector/offering (blank key = any)."""
    return [
        n["note"]
        for n in profile.get("context_notes") or []
        if n.get("region", region) == region
        and n.get("sector", sector) == sector
        and n.get("offering", offering) == offering
    ]
