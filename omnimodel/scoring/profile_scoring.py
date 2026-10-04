"""Generic lead scoring driven by a profile. Scores are 0..1 per offering. Weights are relative."""
import re

DEFAULT_WEIGHTS = dict(offering_fit=30, sector_priority=20, size=12.5, footprint=12.5, cluster=15, buying_signals=10)

def _int(v):
    if isinstance(v, (int, float)): return int(v)
    m = re.search(r"\d[\d,]*", str(v or ""))
    return int(m.group().replace(",", "")) if m else None

def _text(x):
    return " ".join(map(str, x.values())) if isinstance(x, dict) else str(x)

def lead_from_signals(signals, sector, cluster_size, place, profile):
    """Turn extractor output + Places data into scoring inputs. Missing data gets conservative defaults."""
    signals, place = signals or {}, place or {}
    kws = [k.lower() for k in profile.get("buying_signal_keywords", [])]
    job_hits = sum(any(k in _text(h).lower() for k in kws) for h in (signals.get("hiring") or []))
    return dict(sector=sector, size_estimate=_int(signals.get("size_estimate")), site_count=_int(signals.get("site_count")) or 1,
                reviews=place.get("review_count") or 0, cluster_size=cluster_size,
                signal_count=len(signals.get("growth_signals") or []) + 2 * job_hits)

def score_lead(lead, profile):
    w = {**DEFAULT_WEIGHTS, **profile.get("weights", {})}
    total = sum(w.values()) or 1
    sec = profile["sectors"].get(lead["sector"], {})
    size = min(lead["size_estimate"] / 200, 1) if lead.get("size_estimate") else .3
    parts = dict(sector_priority=sec.get("priority", .4), size=size,
                 footprint=max(min(lead.get("site_count", 1) / 10, 1), min(lead.get("reviews", 0) / 500, 1) * .5),  # reviews = busyness proxy
                 cluster=min(lead.get("cluster_size", 0) / 20, 1), buying_signals=min(lead.get("signal_count", 0) / 3, 1))
    out = {}
    for o in profile["offerings"]:
        b = {"offering_fit": w["offering_fit"] * sec.get("fit", {}).get(o, .3), **{k: w[k] * v for k, v in parts.items()}}
        out[o] = {"score": round(sum(b.values()) / total, 3), "breakdown": {k: round(v, 1) for k, v in b.items()}}
    return out

def best_offering(scores):
    return max(scores, key=lambda o: scores[o]["score"])
