"""Generic lead scoring driven by a profile.

Scores are 0..1 per offering. Weights are relative.
"""
import re

DEFAULT_WEIGHTS = {
    "offering_fit": 30,
    "sector_priority": 20,
    "size": 12.5,
    "footprint": 12.5,
    "cluster": 15,
    "buying_signals": 10,
}


def _int(v):
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d[\d,]*", str(v or ""))
    return int(m.group().replace(",", "")) if m else None


def _text(x):
    return " ".join(map(str, x.values())) if isinstance(x, dict) else str(x)


def lead_from_signals(signals, sector, cluster_size, place, profile):
    """Turn extractor output + Places data into scoring inputs.

    Missing data gets conservative defaults.
    """
    signals, place = signals or {}, place or {}
    kws = [k.lower() for k in profile.get("buying_signal_keywords") or []]
    hiring = [h for h in (signals.get("hiring") or []) if h]
    job_hits = sum(1 for h in hiring if any(k in _text(h).lower() for k in kws))
    return {
        "sector": sector,
        "size_estimate": _int(signals.get("size_estimate")),
        "site_count": _int(signals.get("site_count")) or 1,
        "reviews": place.get("review_count") or 0,
        "cluster_size": cluster_size,
        "signal_count": len(signals.get("growth_signals") or []) + 2 * job_hits,
    }


def score_lead(lead, profile):
    """Score every offering of a profile for one lead. Weights are relative."""
    weights = {
        k: profile.get("weights", {}).get(k, v) for k, v in DEFAULT_WEIGHTS.items()
    }
    total = sum(weights.values()) or 1
    sector = profile.get("sectors", {}).get(lead.get("sector")) or {}
    fit = sector.get("fit") or {}
    size_estimate = _int(lead.get("size_estimate"))
    size = min(size_estimate / 200, 1) if size_estimate else 0.3
    parts = {
        "sector_priority": sector.get("priority", 0.4),
        "size": size,
        # reviews = busyness proxy
        "footprint": max(
            min(lead.get("site_count") or 1, 10) / 10,
            min(lead.get("reviews") or 0, 500) / 500 * 0.5,
        ),
        "cluster": min(lead.get("cluster_size") or 0, 20) / 20,
        "buying_signals": min(lead.get("signal_count") or 0, 3) / 3,
    }
    out = {}
    offerings = profile.get("offerings") or {}
    for offering in offerings:
        fit_val = fit.get(offering, 0.0)
        if offering not in fit:
            fit_val = 0.0
        breakdown = {
            "offering_fit": weights["offering_fit"] * fit_val,
            **{k: weights[k] * v for k, v in parts.items()},
        }
        out[offering] = {
            "score": round(sum(breakdown.values()) / total, 3),
            "breakdown": {k: round(v, 1) for k, v in breakdown.items()},
        }
    return out


def best_offering(scores):
    """The highest-scoring offering, or None when there is nothing to compare."""
    if not scores:
        return None
    return max(scores, key=lambda o: scores[o]["score"]) if scores else None
