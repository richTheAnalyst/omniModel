"""Tests for the scoring module (pure logic, no I/O)."""

from omnimodel.scoring.weighted_rules import (
    ScoringRule,
    default_rules,
    score_signals,
)


class TestScoreSignals:
    def test_empty_signals_returns_zero(self):
        result = score_signals({}, default_rules())
        assert result.score == 0.0
        assert result.breakdown == {}

    def test_all_signals_scored(self):
        signals = {
            "pricing": [{"plan": "Pro", "price": 49}],
            "hiring": ["Engineer", "PM", "Designer"],
            "tech_stack": ["Python", "React"],
            "growth_signals": ["Series A"],
        }
        result = score_signals(signals, default_rules())
        assert 0.0 <= result.score <= 1.0
        assert set(result.breakdown) == {
            "pricing",
            "hiring",
            "tech_stack",
            "growth_signals",
        }

    def test_missing_signals_skipped(self):
        result = score_signals({"pricing": [{"plan": "Pro"}]}, default_rules())
        assert result.breakdown == {"pricing": 1.0}

    def test_hiring_score_capped_at_one(self):
        # 10+ roles → score 1.0
        result = score_signals(
            {"hiring": [f"role-{i}" for i in range(15)]}, default_rules()
        )
        assert result.breakdown["hiring"] == 1.0

    def test_hiring_score_proportional(self):
        # 5 roles → 0.5
        result = score_signals(
            {"hiring": [f"role-{i}" for i in range(5)]}, default_rules()
        )
        assert result.breakdown["hiring"] == 0.5

    def test_tech_stack_score_proportional(self):
        # 4 of 8 → 0.5
        result = score_signals({"tech_stack": ["a", "b", "c", "d"]}, default_rules())
        assert result.breakdown["tech_stack"] == 0.5

    def test_growth_signals_weighted_higher(self):
        # growth_signals has weight 2.0, so it dominates
        signals = {
            "pricing": [{"plan": "Pro"}],  # weight 1.0, score 1.0
            "growth_signals": ["funding"],  # weight 2.0, score 0.2
        }
        result = score_signals(signals, default_rules())
        # weighted avg = (1*1.0 + 2*0.2) / 3 = 1.4/3 ≈ 0.467
        assert abs(result.score - 1.4 / 3) < 0.001

    def test_custom_rule(self):
        rule = ScoringRule(name="custom", weight=1.0, evaluate=lambda v: 0.7)
        result = score_signals({"custom": "anything"}, [rule])
        assert result.score == 0.7
        assert result.breakdown == {"custom": 0.7}

    def test_rule_evaluate_clamped(self):
        # Score > 1.0 should be clamped
        rule = ScoringRule(name="x", weight=1.0, evaluate=lambda v: 99.0)
        result = score_signals({"x": True}, [rule])
        assert result.score == 1.0

    def test_rule_evaluate_exception_safe(self):
        def boom(_v):
            raise ValueError("kaboom")

        rule = ScoringRule(name="x", weight=1.0, evaluate=boom)
        result = score_signals({"x": True}, [rule])
        assert result.score == 0.0

    def test_default_rules_names(self):
        names = [r.name for r in default_rules()]
        assert names == ["pricing", "hiring", "tech_stack", "growth_signals"]

    def test_default_rules_weights(self):
        weights = {r.name: r.weight for r in default_rules()}
        assert weights["growth_signals"] == 2.0
        assert weights["hiring"] == 1.5
        assert weights["pricing"] == 1.0
        assert weights["tech_stack"] == 0.5
