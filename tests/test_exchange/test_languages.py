"""Tests for controlled_vocabularies.exchange.languages."""

from controlled_vocabularies.exchange.languages import (
    LanguageMatcher,
    LanguageResolution,
)


class TestLanguageResolution:
    def test_is_exact_true_when_configured_language_matches_the_published_tag(self):
        resolution = LanguageResolution(
            published_tag="en-gb", configured_language="en-gb"
        )
        assert resolution.is_exact is True

    def test_is_exact_is_case_insensitive(self):
        resolution = LanguageResolution(
            published_tag="en-gb", configured_language="EN-GB"
        )
        assert resolution.is_exact is True

    def test_is_exact_false_for_a_variant_match(self):
        resolution = LanguageResolution(published_tag="en-us", configured_language="en")
        assert resolution.is_exact is False

    def test_is_exact_false_when_nothing_matched(self):
        resolution = LanguageResolution(published_tag="fr", configured_language=None)
        assert resolution.is_exact is False


class TestLanguageMatcherResolve:
    def test_exact_match_wins(self):
        matcher = LanguageMatcher(["en", "en-gb"], {})
        resolution = matcher.resolve("en-gb")
        assert resolution.configured_language == "en-gb"
        assert resolution.is_exact is True

    def test_exact_match_is_never_displaced_by_a_more_predominant_variant(self):
        matcher = LanguageMatcher(["en", "en-gb"], {"en-us": 100, "en-gb": 1})
        resolution = matcher.resolve("en-gb")
        assert resolution.configured_language == "en-gb"

    def test_case_mismatch_is_still_an_exact_match_and_returns_the_declared_spelling(
        self,
    ):
        matcher = LanguageMatcher(["en-GB"], {})
        resolution = matcher.resolve("en-gb")
        assert resolution.configured_language == "en-GB", (
            "case folding is for comparison only — the returned code must be exactly as declared"
        )
        assert resolution.is_exact is True

    def test_published_tag_differing_only_in_case_from_the_declared_spelling(self):
        matcher = LanguageMatcher(["en-gb"], {})
        resolution = matcher.resolve("EN-GB")
        assert resolution.configured_language == "en-gb"
        assert resolution.is_exact is True

    def test_general_to_specific_orphan_goes_to_the_least_specific_configured_candidate(
        self,
    ):
        matcher = LanguageMatcher(["en", "en-gb"], {})
        resolution = matcher.resolve("en-us")
        assert resolution.configured_language == "en"
        assert resolution.is_exact is False

    def test_specific_to_general_variant_fills_a_single_general_slot(self):
        matcher = LanguageMatcher(["en"], {})
        resolution = matcher.resolve("en-gb")
        assert resolution.configured_language == "en"
        assert resolution.is_exact is False

    def test_two_equally_specific_candidates_neither_exact_tie_break_by_lower_code(
        self,
    ):
        # zh-hans and zh-hant are the one ambiguous base in Django's default LANGUAGES.
        matcher = LanguageMatcher(["zh-hant", "zh-hans"], {})
        resolution = matcher.resolve("zh")
        assert resolution.configured_language == "zh-hans"

    def test_two_equally_specific_candidates_resolution_is_stable_across_configured_order(
        self,
    ):
        first = LanguageMatcher(["zh-hant", "zh-hans"], {}).resolve("zh")
        second = LanguageMatcher(["zh-hans", "zh-hant"], {}).resolve("zh")
        assert first.configured_language == second.configured_language == "zh-hans"

    def test_no_shared_base_language_resolves_to_none(self):
        matcher = LanguageMatcher(["en"], {})
        resolution = matcher.resolve("fr")
        assert resolution.configured_language is None
        assert resolution.is_exact is False

    def test_more_subtags_than_any_configured_language_still_matches_by_base(self):
        matcher = LanguageMatcher(["zh-hans"], {})
        resolution = matcher.resolve("zh-Hans-CN")
        assert resolution.configured_language == "zh-hans"
        assert resolution.is_exact is False

    def test_sga_regression_a_language_django_ships_no_catalog_for_still_resolves(self):
        # Django refuses `sga` outright (it ships no translation catalog for it), so the
        # matcher must not depend on Django's catalogs.
        matcher = LanguageMatcher(["sga"], {})
        resolution = matcher.resolve("sga")
        assert resolution.configured_language == "sga"
        assert resolution.is_exact is True


class TestLanguageMatcherFromSettings:
    def test_from_settings_reads_configured_languages_from_django_settings(
        self, settings
    ):
        settings.LANGUAGES = [("en", "English"), ("de", "German")]
        matcher = LanguageMatcher.from_settings({})
        assert matcher.resolve("en").configured_language == "en"
        assert matcher.resolve("de").configured_language == "de"
        assert matcher.resolve("fr").configured_language is None

    def test_from_settings_is_constructible_with_no_graph_in_sight(self):
        matcher = LanguageMatcher.from_settings({"en": 3, "de": 1})
        assert isinstance(matcher, LanguageMatcher)


class TestLanguageMatcherResolveWinner:
    def test_exact_match_wins_over_a_more_predominant_variant(self):
        matcher = LanguageMatcher(["en"], {"en-gb": 100, "en": 1})
        winner, losers = matcher.resolve_winner(
            "en", [("en-gb", "Colour"), ("en", "Color")]
        )
        assert winner == ("en", "Color")
        assert losers == [("en-gb", "Colour")]

    def test_predominance_decides_when_no_candidate_is_exact(self):
        matcher = LanguageMatcher(["en"], {"en-gb": 5, "en-us": 2})
        winner, losers = matcher.resolve_winner(
            "en", [("en-us", "Color"), ("en-gb", "Colour")]
        )
        assert winner == ("en-gb", "Colour")
        assert losers == [("en-us", "Color")]

    def test_predominant_variant_the_site_does_not_hold_decides_nothing(self):
        # fr is far more predominant, but it is not competing for this configured slot.
        matcher = LanguageMatcher(["en"], {"fr": 1000, "en-gb": 5, "en-us": 2})
        winner, _losers = matcher.resolve_winner(
            "en", [("en-us", "Color"), ("en-gb", "Colour")]
        )
        assert winner == ("en-gb", "Colour")

    def test_tie_break_is_lexicographic_by_tag_when_predominance_ties(self):
        matcher = LanguageMatcher(["en"], {"en-gb": 3, "en-us": 3})
        winner, _losers = matcher.resolve_winner(
            "en", [("en-us", "Color"), ("en-gb", "Colour")]
        )
        assert winner == ("en-gb", "Colour")

    def test_tie_break_also_applies_with_no_predominance_data_at_all(self):
        matcher = LanguageMatcher(["en"], {})
        winner, _losers = matcher.resolve_winner(
            "en", [("en-us", "Color"), ("en-gb", "Colour")]
        )
        assert winner == ("en-gb", "Colour")

    def test_one_candidate_set_yields_one_winner_deterministically(self):
        matcher = LanguageMatcher(["en"], {"en-gb": 5, "en-us": 2})
        candidates = [("en-us", "Color"), ("en-gb", "Colour")]
        first_winner, _ = matcher.resolve_winner("en", candidates)
        second_winner, _ = matcher.resolve_winner("en", candidates)
        assert first_winner == second_winner

    def test_single_candidate_wins_by_default(self):
        matcher = LanguageMatcher(["en"], {})
        winner, losers = matcher.resolve_winner("en", [("en-gb", "Colour")])
        assert winner == ("en-gb", "Colour")
        assert losers == []

    def test_tag_counts_lookup_is_case_folded_so_a_recased_candidate_tag_still_finds_its_count(
        self,
    ):
        # Language tags are case-insensitive (RFC 5646), and the counts are keyed
        # lowercase, so a re-cased candidate tag must still find its count.
        matcher = LanguageMatcher(["en"], {"en-gb": 16, "en-us": 8})
        winner, _losers = matcher.resolve_winner(
            "en", [("en-us", "Color"), ("EN-GB", "Colour")]
        )
        assert winner == ("EN-GB", "Colour")
