"""Tests for the YAML business-profile pipeline.

These cover the loader, the profile scoring model and the outreach renderer.
They are pure-logic: no network, no LLM and no Playwright.
"""

import pytest

from omnimodel.profile_loader import (
    PROFILE_DIR,
    REQUIRED,
    context_notes,
    list_profiles,
    load_profile,
    profile_path,
)
from omnimodel.scoring.profile_scoring import (
    best_offering,
    lead_from_signals,
    score_lead,
)
from omnimodel.templates.profile_templates import render


@pytest.fixture(scope="module")
def profile():
    assert list_profiles(), "no profiles found"
    return load_profile(list_profiles()[0])


# ------------------------------------------------------------------ loader
class TestProfileLoader:
    def test_profile_dir_exists(self):
        # Regression: PROFILE_DIR once pointed at a repo-root folder that does
        # not exist, so every profile lookup silently returned nothing.
        assert PROFILE_DIR.is_dir()
        assert PROFILE_DIR.name == "profiles"

    def test_shipped_profiles_are_found(self):
        stems = list_profiles()
        assert stems, "no profile YAML files were discovered"
        assert stems == sorted(stems)

    def test_every_shipped_profile_is_valid(self):
        for stem in list_profiles():
            data = load_profile(stem)
            for key in REQUIRED:
                assert key in data, f"{stem} is missing {key}"
            assert data["offerings"]
            assert data["sectors"]
            assert data["geography"]

    def test_unknown_profile_raises(self):
        with pytest.raises(FileNotFoundError):
            load_profile("no_such_profile")

    @pytest.mark.parametrize("bad", ["../secrets", "..\\secrets", "", ".hidden", "a/b"])
    def test_path_traversal_is_refused(self, bad):
        with pytest.raises(ValueError):
            profile_path(bad)


# ------------------------------------------------------------------ scoring
class TestProfileScoring:
    def test_scores_every_offering_in_range(self, profile):
        lead = lead_from_signals(None, "bank", 5, {"review_count": 40}, profile)
        scores = score_lead(lead, profile)
        assert set(scores) == set(profile["offerings"])
        for entry in scores.values():
            assert 0.0 <= entry["score"] <= 1.0
            assert entry["breakdown"]

    def test_missing_signals_use_defaults(self, profile):
        lead = lead_from_signals(None, "bank", 0, {}, profile)
        assert lead["site_count"] == 1
        assert lead["size_estimate"] is None
        assert lead["reviews"] == 0
        assert lead["signal_count"] == 0

    def test_sector_fit_drives_the_winner(self, profile):
        """Each sector's highest-fit offering must beat its lowest-fit one."""
        for sector, spec in profile["sectors"].items():
            fit = spec.get("fit") or {}
            if len(fit) < 2:
                continue
            best_fit = max(fit, key=fit.get)
            worst_fit = min(fit, key=fit.get)
            if fit[best_fit] == fit[worst_fit]:
                continue
            scores = score_lead({"sector": sector, "cluster_size": 0}, profile)
            assert scores[best_fit]["score"] > scores[worst_fit]["score"], sector

    def test_more_buying_signals_never_lowers_the_score(self, profile):
        base = {"sector": next(iter(profile["sectors"])), "cluster_size": 0}
        low = score_lead({**base, "signal_count": 0}, profile)
        high = score_lead({**base, "signal_count": 50}, profile)
        assert high[next(iter(high))]["score"] > low[next(iter(low))]["score"]

    def test_missing_sector_is_tolerated(self, profile):
        scores = score_lead({"sector": "not_a_sector"}, profile)
        assert set(scores) == set(profile["offerings"])

    def test_size_estimate_parsed_from_text(self, profile):
        lead = lead_from_signals(
            {"size_estimate": "about 1,200 staff"}, None, 0, {}, profile
        )
        assert lead["size_estimate"] == 1200

    def test_best_offering_of_empty_is_none(self):
        assert best_offering({}) is None

    def test_best_offering_picks_the_highest(self, profile):
        scores = score_lead({"sector": next(iter(profile["sectors"]))}, profile)
        best = best_offering(scores)
        assert scores[best]["score"] == max(s["score"] for s in scores.values())


# ------------------------------------------------------------------ outreach
class TestProfileTemplates:
    LEAD = {
        "name": "Kumasi Gold Ltd",
        "region": "Ashanti",
        "city": "Kumasi",
        "sector": "mining",
    }

    def test_renders_every_kind_and_offering(self, profile):
        for kind in ("email", "proposal", "followup"):
            for offering in profile["offerings"]:
                text = render(profile, kind, self.LEAD, offering, profile["business"])
                assert text.strip()
                assert "Kumasi Gold Ltd" in text
                assert "{" not in text, f"unfilled placeholder in {kind}/{offering}"

    def test_missing_business_details_do_not_crash(self, profile):
        text = render(profile, "email", {}, list(profile["offerings"])[0], None)
        assert text.strip()
        assert "{" not in text

    def test_unknown_offering_raises(self, profile):
        with pytest.raises(KeyError):
            render(profile, "email", self.LEAD, "not_an_offering", {})

    def test_unknown_kind_raises(self, profile):
        offering = list(profile["offerings"])[0]
        with pytest.raises(KeyError):
            render(profile, "carrier_pigeon", self.LEAD, offering, {})

    def test_context_notes_match_on_blank_keys(self, profile):
        notes = profile.get("context_notes") or []
        for note in notes:
            matched = context_notes(
                profile,
                note.get("region", "Ashanti"),
                note.get("sector", "mining"),
                note.get("offering", list(profile["offerings"])[0]),
            )
            assert note["note"] in matched

    def test_context_notes_exclude_other_regions(self, profile):
        offering = list(profile["offerings"])[0]
        assert context_notes(profile, "Nowhere", "mining", offering) == []
