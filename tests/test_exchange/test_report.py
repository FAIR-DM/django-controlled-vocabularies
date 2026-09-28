"""Tests for controlled_vocabularies.exchange.report."""

import pytest
from django.utils.functional import Promise

from controlled_vocabularies.exchange.report import (
    FatalFinding,
    FatalReason,
    ImportReport,
    NormalizedEntry,
    NormalizedReason,
    SetAsideEntry,
    SetAsideReason,
)

# Exercises every named placeholder each template declares beyond the universal
# %(subject)s.
_EXAMPLE_PARAMS = {
    SetAsideReason.UNCONFIGURED_LANGUAGE: {"language": "es"},
    SetAsideReason.UNMODELLED_PREDICATE: {"predicate": "skos:hiddenLabel-ish"},
    SetAsideReason.NOTATION: {},
    SetAsideReason.MAPPING: {"predicate": "skos:exactMatch"},
    SetAsideReason.MISSING_RELATION_END: {"other": "https://example.org/vocab/missing"},
    SetAsideReason.MISSING_MEMBER: {
        "collection": "https://example.org/vocab/collection/rocks"
    },
    SetAsideReason.NO_PREFERRED_LABEL: {"language": "en"},
    SetAsideReason.VOCABULARY_MISMATCH: {"other": "https://example.org/vocab/other"},
    SetAsideReason.DEFAULT_LANGUAGE_FROZEN: {"declared": "fr", "frozen": "en"},
    SetAsideReason.RELATION_DISJOINTNESS: {"other": "https://example.org/vocab/other"},
    SetAsideReason.SURPLUS_PREFERRED_LABEL: {"language": "de"},
    SetAsideReason.EMPTY_SLUG: {},
    SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY: {
        "current": "https://example.org/vocab/current",
        "target": "https://example.org/vocab/target",
    },
    SetAsideReason.URI_HELD_BY_DIFFERENT_KIND: {},
    SetAsideReason.NO_LANGUAGE_TAG: {"predicate": "skos:altLabel"},
    SetAsideReason.VARIANT_NOT_KEPT: {"language": "en-us", "kept_as": "en-gb"},
    SetAsideReason.VALUE_TOO_LONG: {"language": "en-gb"},
    SetAsideReason.STORED_SLUG_INVALID: {},
    SetAsideReason.COLLECTION_NOT_CREATED: {},
}

_EXAMPLE_FATAL_PARAMS = {
    FatalReason.MISSING_IDENTITY: {},
    FatalReason.REFUSED_IDENTITY: {},
    FatalReason.VOCABULARY_UNDETERMINED: {},
    FatalReason.VOCABULARY_TARGET_MISMATCH: {
        "target": "https://example.org/vocab/target"
    },
    FatalReason.VOCABULARY_AMBIGUOUS: {
        "declared": "https://example.org/vocab/a, https://example.org/vocab/b"
    },
    FatalReason.DEFAULT_LANGUAGE_UNCONFIGURED: {"language": "en-us"},
    FatalReason.VOCABULARY_SLUG_UNUSABLE: {},
    FatalReason.VOCABULARY_NAME_UNUSABLE: {"language": "en"},
    FatalReason.VOCABULARY_RECORD_INVALID: {},
    FatalReason.VOCABULARY_NAME_UNPUBLISHED: {},
}

_EXAMPLE_NORMALIZED_PARAMS = {
    NormalizedReason.FOREIGN_DEFINITION: {
        "predicate": "dcterms:description",
        "language": "en",
    },
    NormalizedReason.LANGUAGE_SUBSTITUTION: {"language": "en-gb", "kept_as": "en"},
}


class TestImportReportBuckets:
    def test_import_report_starts_with_four_empty_buckets(self):
        report = ImportReport()
        assert report.created == []
        assert report.updated == []
        assert report.set_aside == []
        assert report.absent_from_source == []

    def test_add_created_and_add_updated_append_to_their_own_bucket(self):
        report = ImportReport()
        report.add_created("https://example.org/vocab/rocks")
        report.add_updated("https://example.org/vocab/rocks/granite")
        assert report.created == ["https://example.org/vocab/rocks"]
        assert report.updated == ["https://example.org/vocab/rocks/granite"]
        assert report.set_aside == []
        assert report.absent_from_source == []

    def test_add_absent_from_source_appends_the_subject(self):
        report = ImportReport()
        report.add_absent_from_source("https://example.org/vocab/rocks/basalt")
        assert report.absent_from_source == ["https://example.org/vocab/rocks/basalt"]

    def test_add_set_aside_records_reason_subject_and_params_as_data(self):
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE,
            "https://example.org/vocab/rocks/granite",
            language="es",
        )
        assert len(report.set_aside) == 1
        entry = report.set_aside[0]
        assert isinstance(entry, SetAsideEntry)
        assert entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        assert entry.subject == "https://example.org/vocab/rocks/granite"
        assert entry.params == {"language": "es"}

    def test_set_aside_by_reason_groups_and_counts_without_parsing_prose(self):
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.NOTATION, "https://example.org/vocab/rocks/granite"
        )
        report.add_set_aside(
            SetAsideReason.NOTATION, "https://example.org/vocab/rocks/basalt"
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE,
            "https://example.org/vocab/rocks/granite",
            language="es",
        )
        grouped = report.set_aside_by_reason()
        assert len(grouped[SetAsideReason.NOTATION]) == 2
        assert len(grouped[SetAsideReason.UNCONFIGURED_LANGUAGE]) == 1
        assert SetAsideReason.MAPPING not in grouped


class TestLanguageAccount:
    def test_counts_every_value_not_stored_for_a_language_reason_broken_down_by_published_language(
        self,
    ):
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/a", language="fr"
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/b", language="fr"
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/c", language="es"
        )
        assert report.language_account() == {"fr": 2, "es": 1}

    def test_a_value_that_was_stored_is_not_counted(self):
        report = ImportReport()
        report.add_created("https://example.org/a")
        report.add_updated("https://example.org/b")
        assert report.language_account() == {}

    def test_a_contest_loser_is_counted_under_its_own_published_tag_not_what_it_lost_to(
        self,
    ):
        # The loser counts under its own tag, since configuring that language is what
        # recovers it.
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.VARIANT_NOT_KEPT,
            "https://example.org/a",
            language="en-us",
            kept_as="en-gb",
        )
        assert report.language_account() == {"en-us": 1}

    def test_a_same_language_surplus_is_excluded(self):
        # A same-language duplicate is in a language the site already holds, so
        # configuring nothing recovers it.
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.SURPLUS_PREFERRED_LABEL,
            "https://example.org/a",
            language="de",
        )
        assert report.language_account() == {}

    def test_present_and_empty_after_a_run_that_left_nothing_behind(self):
        report = ImportReport()
        report.add_created("https://example.org/a")
        assert report.language_account() == {}
        assert "en" not in report.language_account()

    def test_a_caller_can_rank_languages_by_what_configuring_them_would_recover(self):
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/a", language="fr"
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/b", language="fr"
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE, "https://example.org/c", language="es"
        )
        ranked = sorted(report.language_account().items(), key=lambda item: -item[1])
        assert ranked[0] == ("fr", 2)

    def test_mixed_case_spellings_of_one_language_fold_into_one_entry(self):
        # Language tags are case-insensitive, so @PT-br and @pt-BR must rank as one
        # language.
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE,
            "https://example.org/a",
            language="PT-br",
        )
        report.add_set_aside(
            SetAsideReason.UNCONFIGURED_LANGUAGE,
            "https://example.org/b",
            language="pt-BR",
        )
        account = report.language_account()
        assert len(account) == 1
        assert sum(account.values()) == 2


class TestSetAsideEntry:
    def test_set_aside_entry_is_immutable(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.NOTATION, subject="https://example.org/vocab/x"
        )
        with pytest.raises((AttributeError, TypeError)):
            entry.subject = "changed"


class TestAnEmptyLanguageTagRendersAsAPhraseNotAnEmptyQuote:
    def test_value_too_long_with_an_untagged_literal_names_no_language_tag_not_empty_quotes(
        self,
    ):
        entry = SetAsideEntry(
            reason=SetAsideReason.VALUE_TOO_LONG,
            subject="https://example.org/vocab/rocks",
            params={"language": ""},
        )
        rendered = entry.render()
        assert "''" not in rendered
        assert "no language tag" in rendered

    def test_vocabulary_name_unusable_with_an_untagged_literal_names_no_language_tag_not_empty_quotes(
        self,
    ):
        finding = FatalFinding(
            reason=FatalReason.VOCABULARY_NAME_UNUSABLE,
            subject="https://example.org/vocab/rocks",
            params={"language": ""},
        )
        rendered = finding.render()
        assert "''" not in rendered
        assert "no language tag" in rendered


class TestSetAsideReasonVocabulary:
    @pytest.mark.parametrize("reason", list(SetAsideReason))
    def test_every_reason_has_a_translatable_label(self, reason):
        assert isinstance(reason.label, Promise), (
            f"{reason} label is not lazily translatable"
        )

    @pytest.mark.parametrize("reason", list(SetAsideReason))
    def test_every_reason_template_is_translatable_with_a_named_subject_placeholder(
        self, reason
    ):
        assert isinstance(reason.template, Promise), (
            f"{reason} template is not lazily translatable"
        )
        assert "%(subject)s" in str(reason.template), (
            f"{reason} template lacks a named %(subject)s placeholder"
        )

    @pytest.mark.parametrize("reason", list(SetAsideReason))
    def test_every_reason_renders_with_its_example_params(self, reason):
        entry = SetAsideEntry(
            reason=reason,
            subject="https://example.org/vocab/x",
            params=_EXAMPLE_PARAMS[reason],
        )
        rendered = entry.render()
        assert isinstance(rendered, str)
        assert "https://example.org/vocab/x" in rendered
        for value in _EXAMPLE_PARAMS[reason].values():
            assert value in rendered


class TestVariantNotKeptReason:
    def test_the_entry_carries_the_published_tag_under_language_and_the_destination_under_kept_as(
        self,
    ):
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.VARIANT_NOT_KEPT,
            "https://example.org/vocab/rocks/granite",
            language="en-us",
            kept_as="en-gb",
        )
        entry = report.set_aside[0]
        assert entry.reason is SetAsideReason.VARIANT_NOT_KEPT
        assert entry.params == {"language": "en-us", "kept_as": "en-gb"}

    def test_the_rendered_message_is_true_of_the_case_it_names(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.VARIANT_NOT_KEPT,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-us", "kept_as": "en-gb"},
        )
        rendered = entry.render()
        assert "en-us" in rendered
        assert "en-gb" in rendered


class TestFatalBucketAndFinding:
    def test_import_report_starts_with_an_empty_fatal_bucket(self):
        assert ImportReport().fatal == []

    def test_add_fatal_records_reason_subject_and_params_as_data(self):
        report = ImportReport()
        report.add_fatal(
            FatalReason.MISSING_IDENTITY, "https://example.org/vocab/rocks/blank"
        )
        assert len(report.fatal) == 1
        entry = report.fatal[0]
        assert isinstance(entry, FatalFinding)
        assert entry.reason is FatalReason.MISSING_IDENTITY
        assert entry.subject == "https://example.org/vocab/rocks/blank"
        assert entry.params == {}

    def test_fatal_finding_is_immutable(self):
        finding = FatalFinding(
            reason=FatalReason.MISSING_IDENTITY, subject="https://example.org/vocab/x"
        )
        with pytest.raises((AttributeError, TypeError)):
            finding.subject = "changed"


class TestFatalReasonVocabulary:
    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_fatal_reason_has_a_translatable_label(self, reason):
        assert isinstance(reason.label, Promise), (
            f"{reason} label is not lazily translatable"
        )

    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_fatal_reason_template_is_translatable_with_a_named_subject_placeholder(
        self, reason
    ):
        assert isinstance(reason.template, Promise), (
            f"{reason} template is not lazily translatable"
        )
        assert "%(subject)s" in str(reason.template), (
            f"{reason} template lacks a named %(subject)s placeholder"
        )

    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_fatal_reason_renders_with_its_example_params(self, reason):
        entry = FatalFinding(
            reason=reason,
            subject="https://example.org/vocab/x",
            params=_EXAMPLE_FATAL_PARAMS[reason],
        )
        rendered = entry.render()
        assert isinstance(rendered, str)
        assert "https://example.org/vocab/x" in rendered
        for value in _EXAMPLE_FATAL_PARAMS[reason].values():
            assert value in rendered


class TestReasonVocabulariesAreDisjoint:
    def test_set_aside_reason_and_fatal_reason_are_disjoint_vocabularies(self):
        set_aside_values = {reason.value for reason in SetAsideReason}
        fatal_values = {reason.value for reason in FatalReason}
        assert set_aside_values.isdisjoint(fatal_values)


class TestImportReportNormalizedBucket:
    def test_import_report_starts_with_an_empty_normalized_bucket(self):
        assert ImportReport().normalized == []

    def test_add_normalized_records_reason_subject_and_params_as_data(self):
        report = ImportReport()
        report.add_normalized(
            NormalizedReason.FOREIGN_DEFINITION,
            "https://example.org/vocab/rocks/gadget",
            predicate="dcterms:description",
            language="en",
        )
        assert len(report.normalized) == 1
        entry = report.normalized[0]
        assert isinstance(entry, NormalizedEntry)
        assert entry.reason is NormalizedReason.FOREIGN_DEFINITION
        assert entry.subject == "https://example.org/vocab/rocks/gadget"
        assert entry.params == {"predicate": "dcterms:description", "language": "en"}
        # Adding a normalized entry never touches any other bucket.
        assert report.set_aside == []
        assert report.fatal == []

    def test_normalized_entry_is_immutable(self):
        entry = NormalizedEntry(
            reason=NormalizedReason.FOREIGN_DEFINITION,
            subject="https://example.org/vocab/x",
        )
        with pytest.raises((AttributeError, TypeError)):
            entry.subject = "changed"


class TestNormalizedReasonVocabulary:
    @pytest.mark.parametrize("reason", list(NormalizedReason))
    def test_every_normalized_reason_has_a_translatable_label(self, reason):
        assert isinstance(reason.label, Promise), (
            f"{reason} label is not lazily translatable"
        )

    @pytest.mark.parametrize("reason", list(NormalizedReason))
    def test_every_normalized_reason_template_is_translatable_with_a_named_subject_placeholder(
        self, reason
    ):
        assert isinstance(reason.template, Promise), (
            f"{reason} template is not lazily translatable"
        )
        assert "%(subject)s" in str(reason.template), (
            f"{reason} template lacks a named %(subject)s placeholder"
        )

    @pytest.mark.parametrize("reason", list(NormalizedReason))
    def test_every_normalized_reason_renders_with_its_example_params(self, reason):
        entry = NormalizedEntry(
            reason=reason,
            subject="https://example.org/vocab/x",
            params=_EXAMPLE_NORMALIZED_PARAMS[reason],
        )
        rendered = entry.render()
        assert isinstance(rendered, str)
        assert "https://example.org/vocab/x" in rendered
        for value in _EXAMPLE_NORMALIZED_PARAMS[reason].values():
            assert value in rendered


class TestLanguageSubstitutionReason:
    def test_the_entry_is_inspectable_as_data(self):
        report = ImportReport()
        report.add_normalized(
            NormalizedReason.LANGUAGE_SUBSTITUTION,
            "https://example.org/vocab/rocks/granite",
            language="en-gb",
            kept_as="en",
        )
        entry = report.normalized[0]
        assert entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
        assert entry.subject == "https://example.org/vocab/rocks/granite"
        assert entry.params == {"language": "en-gb", "kept_as": "en"}

    def test_it_renders_naming_both_the_published_tag_and_the_language_stored_under(
        self,
    ):
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb", "kept_as": "en"},
        )
        rendered = entry.render()
        assert "en-gb" in rendered
        assert "en" in rendered

    def test_it_sits_in_the_normalized_bucket_not_the_set_aside_one(self):
        # The value was stored, so a filter for what did not make it in must not see it
        # (docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md).
        report = ImportReport()
        report.add_normalized(
            NormalizedReason.LANGUAGE_SUBSTITUTION,
            "https://example.org/vocab/rocks/granite",
            language="en-gb",
            kept_as="en",
        )
        assert len(report.normalized) == 1
        assert report.set_aside == []


class TestNormalizedReasonIsDisjointFromSetAsideAndFatal:
    def test_normalized_reason_shares_no_value_with_set_aside_or_fatal_reason(self):
        normalized_values = {reason.value for reason in NormalizedReason}
        set_aside_values = {reason.value for reason in SetAsideReason}
        fatal_values = {reason.value for reason in FatalReason}
        assert normalized_values.isdisjoint(set_aside_values)
        assert normalized_values.isdisjoint(fatal_values)


class TestReasonTemplatesUseOnlyNamedPlaceholders:
    @pytest.mark.parametrize(
        "reason", list(SetAsideReason) + list(FatalReason) + list(NormalizedReason)
    )
    def test_reason_template_has_no_positional_placeholder(
        self, reason, uses_only_named_placeholders
    ):
        template = str(reason.template)
        assert uses_only_named_placeholders(template), (
            f"{reason} template carries something other than a named placeholder: {template!r}"
        )


class TestDocumentSuppliedTextCannotDriveTheTerminal:
    _HOSTILE = "Innocent\x1b[2K\rALL CLEAR - 0 problems found.\x1b[1A"

    def test_a_set_aside_subject_cannot_carry_an_escape_sequence(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
            subject=self._HOSTILE,
            params={"language": "es"},
        )
        rendered = entry.render()
        assert "\x1b" not in rendered
        assert "\r" not in rendered
        assert "Innocent" in rendered

    def test_a_fatal_subject_cannot_carry_an_escape_sequence(self):
        finding = FatalFinding(
            reason=FatalReason.REFUSED_IDENTITY, subject=self._HOSTILE, params={}
        )
        assert "\x1b" not in finding.render()

    def test_a_normalized_param_cannot_carry_an_escape_sequence(self):
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb\x1b[1A", "kept_as": "en"},
        )
        assert "\x1b" not in entry.render()

    def test_a_newline_cannot_fake_an_additional_report_line(self):
        # The usual "strip control characters except \n and \t" rule would let a newline
        # through, and a report entry is one line by construction.
        entry = SetAsideEntry(
            reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
            subject="granite\n8 records created.",
            params={"language": "es"},
        )
        assert "\n" not in entry.render()

    def test_an_ordinary_subject_and_params_are_untouched(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
            subject="https://example.org/vocab/rocks/granite (Granit, Gränit)",
            params={"language": "es"},
        )
        rendered = entry.render()
        assert "https://example.org/vocab/rocks/granite (Granit, Gränit)" in rendered
        assert "es" in rendered


class TestLanguageReasonMessagesUseNamedPlaceholders:
    def test_language_substitution_reason_message_uses_named_placeholders(self):
        assert isinstance(NormalizedReason.LANGUAGE_SUBSTITUTION.template, Promise), (
            "LANGUAGE_SUBSTITUTION template is not lazily translatable"
        )
        template = str(NormalizedReason.LANGUAGE_SUBSTITUTION.template)
        assert "%(language)s" in template and "%(kept_as)s" in template, (
            "LANGUAGE_SUBSTITUTION template lacks named %(language)s/%(kept_as)s placeholders"
        )
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb", "kept_as": "en"},
        )
        rendered = entry.render()
        assert "en-gb" in rendered
        assert "en" in rendered

    def test_the_kept_as_placeholder_actually_interpolates_its_own_value(self):
        # "en" is a substring of "en-gb", so the test above still passes if %(kept_as)s
        # stops interpolating. These values do not overlap.
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb", "kept_as": "zh-hans"},
        )
        rendered = entry.render()
        assert "en-gb" in rendered
        assert "zh-hans" in rendered

    def test_variant_not_kept_reason_message_uses_named_placeholders(self):
        assert isinstance(SetAsideReason.VARIANT_NOT_KEPT.template, Promise), (
            "VARIANT_NOT_KEPT template is not lazily translatable"
        )
        template = str(SetAsideReason.VARIANT_NOT_KEPT.template)
        assert "%(language)s" in template and "%(kept_as)s" in template, (
            "VARIANT_NOT_KEPT template lacks named %(language)s/%(kept_as)s placeholders"
        )
        entry = SetAsideEntry(
            reason=SetAsideReason.VARIANT_NOT_KEPT,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-us", "kept_as": "en-gb"},
        )
        rendered = entry.render()
        assert "en-us" in rendered
        assert "en-gb" in rendered
