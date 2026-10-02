"""Weighted rule-based scoring for extracted signals.

Each signal contributes a configurable weight and score. The final
score is a weighted average of all applicable signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoringRule:
    name: str
    weight: float = 1.0
    # A callable that takes the extracted signal value and returns a
    # score in [0, 1]. When None the rule contributes nothing.
    evaluate: Any = None


@dataclass
class ScoreResult:
    score: float  # 0.0 - 1.0
    breakdown: dict[str, float] = field(default_factory=dict)


def score_signals(
    signals: dict[str, Any],
    rules: list[ScoringRule],
) -> ScoreResult:
    """Compute a weighted score from extracted signals.

    Parameters
    ----------
    signals:
        The dict returned by ``Claude extractor``.
    rules:
        List of ``ScoringRule`` definitions.

    Returns
    -------
    ScoreResult
        The final weighted score and per-rule contributions.
    """
    total_weight = 0.0
    weighted_sum = 0.0
    breakdown: dict[str, float] = {}

    for rule in rules:
        raw = signals.get(rule.name)
        if rule.evaluate is None or raw is None:
            continue
        try:
            contribution = rule.evaluate(raw)
        except Exception:
            contribution = 0.0
        contribution = max(0.0, min(1.0, float(contribution)))
        weighted_sum += rule.weight * contribution
        total_weight += rule.weight
        breakdown[rule.name] = contribution

    final = weighted_sum / total_weight if total_weight > 0 else 0.0
    return ScoreResult(score=final, breakdown=breakdown)


def default_rules() -> list[ScoringRule]:
    """Return a starter set of rules tuned for B2B SaaS signals."""
    return [
        ScoringRule(
            name="pricing",
            weight=1.0,
            evaluate=lambda v: 1.0 if v else 0.0,
        ),
        ScoringRule(
            name="hiring",
            weight=1.5,
            evaluate=lambda v: min(1.0, len(v) / 10.0) if v else 0.0,
        ),
        ScoringRule(
            name="tech_stack",
            weight=0.5,
            evaluate=lambda v: min(1.0, len(v) / 8.0) if v else 0.0,
        ),
        ScoringRule(
            name="growth_signals",
            weight=2.0,
            evaluate=lambda v: min(1.0, len(v) / 5.0) if v else 0.0,
        ),
    ]