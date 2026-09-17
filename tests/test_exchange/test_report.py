"""T003 — ``ImportReport`` and ``SetAsideEntry`` (FR-015, decisions.md D7).

The report is the structured contract #51 and #52 consume: what was created,
what was updated, what was set aside and why, and what the source no longer
mentions, all inspectable as data rather than only as text (spec Acceptance
Scenario US1-11). Every set-aside reason comes from a closed, translatable
vocabulary (Article XII) rather than freeform prose, so a caller can group and
count without parsing a message.
"""

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

# One example params dict per reason, exercising every named placeholder its
# template declares (beyond the universal %(subject)s).
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

# One example params dict per fatal reason (T007), the same shape as _EXAMPLE_PARAMS.
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

# One example params dict per normalized reason (T021), the same shape as _EXAMPLE_PARAMS.
_EXAMPLE_NORMALIZED_PARAMS = {
    NormalizedReason.FOREIGN_DEFINITION: {
        "predicate": "dcterms:description",
        "language": "en",
    },
    NormalizedReason.LANGUAGE_SUBSTITUTION: {"language": "en-gb", "kept_as": "en"},
}


class TestImportReportBuckets:
    """``ImportReport`` starts with four empty buckets, and each ``add_*``
    method appends only to its own — never fatal, which is tracked apart."""

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
        # Adding to one bucket never touches another.
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
        # Inspectable as data (spec US1-11): the reason and subject are read directly,
        # never by parsing a rendered message.
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
    """T004 — the per-published-language account (FR-008, research.md R3): a
    fold over :attr:`ImportReport.set_aside`, not a field accumulated beside
    it, so the count can never disagree with the entries a caller can also
    read directly. Membership is an explicit set of reasons —
    ``UNCONFIGURED_LANGUAGE`` and ``VARIANT_NOT_KEPT``, nothing else — keyed
    on ``params["language"]``, which both members put the *published* tag
    under (T022)."""

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
        # FR-008/T022: en-us lost the contest to en-gb, but it is en-us — the
        # language configuring would actually recover — that must be counted.
        report = ImportReport()
        report.add_set_aside(
            SetAsideReason.VARIANT_NOT_KEPT,
            "https://example.org/a",
            language="en-us",
            kept_as="en-gb",
        )
        assert report.language_account() == {"en-us": 1}

    def test_a_same_language_surplus_is_excluded(self):
        # SURPLUS_PREFERRED_LABEL's language is a configured code the site
        # already holds; nothing recovers a same-language duplicate (D14).
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
        # Ranked without parsing any rendered message — read as plain data.
        ranked = sorted(report.language_account().items(), key=lambda item: -item[1])
        assert ranked[0] == ("fr", 2)

    def test_mixed_case_spellings_of_one_language_fold_into_one_entry(self):
        # CORR-003/SEC-003: a file tagging some values @PT-br and some @pt-BR
        # must rank as one recoverable language, not two — FR-001's
        # case-insensitivity applies to the account as much as to matching.
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
    """A ``SetAsideEntry`` is a frozen record — nothing downstream can mutate
    a reason, subject or params after it has been reported."""

    def test_set_aside_entry_is_immutable(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.NOTATION, subject="https://example.org/vocab/x"
        )
        with pytest.raises((AttributeError, TypeError)):
            entry.subject = "changed"


class TestAnEmptyLanguageTagRendersAsAPhraseNotAnEmptyQuote:
    """SEC-406, decisions.md D64 (fix cycle 5): ``SkosGraph.first_literal_with_language`` reports
    ``""`` (D52) for an untagged literal. When that value is over-long, ``winning_tag`` carries
    ``""`` straight into ``VALUE_TOO_LONG``'s or ``VOCABULARY_NAME_UNUSABLE``'s ``%(language)s``
    placeholder, rendering "...in ''..." — nothing unsafe or leaked, just uninformative.
    """

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
    """Every member of the closed ``SetAsideReason`` vocabulary is lazily
    translatable, carries a named ``%(subject)s`` placeholder, and renders
    with its own example params (Article XII)."""

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
    """T022 — a value that lost a variant contest is set aside under its own
    reason, not ``SURPLUS_PREFERRED_LABEL``, whose message means more than one
    preferred label in one and the same language and is factually false here
    (S3R SPEC-002, decisions.md D14). The published tag goes under
    ``language``, identically to ``UNCONFIGURED_LANGUAGE``, and the configured
    destination it lost to under ``kept_as`` — the wrong way round keys T004's
    account under a language the site already holds."""

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
        # A contest loser's file carries exactly one preferred label in its own
        # published tag — SURPLUS_PREFERRED_LABEL's "more than one" claim would
        # be false here (research.md R4).
        assert "more than one preferred label" not in rendered
        assert "en-us" in rendered
        assert "en-gb" in rendered

    def test_surplus_preferred_label_meaning_and_message_are_unchanged(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.SURPLUS_PREFERRED_LABEL,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "de"},
        )
        assert entry.render() == (
            "'https://example.org/vocab/rocks/granite' carries more than one preferred label in the "
            "language 'de'; only one is kept and the surplus value was set aside."
        )


class TestFatalBucketAndFinding:
    """T007 — the fatal bucket starts empty, ``add_fatal`` records reason,
    subject and params as data, and a recorded ``FatalFinding`` is frozen."""

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
    """Every member of the closed ``FatalReason`` vocabulary is lazily
    translatable, carries a named ``%(subject)s`` placeholder, and renders
    with its own example params (Article XII)."""

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
    """decisions.md D3/D8: a fatal finding is never one of the set-aside
    reasons — the two closed vocabularies never overlap."""

    def test_set_aside_reason_and_fatal_reason_are_disjoint_vocabularies(self):
        set_aside_values = {reason.value for reason in SetAsideReason}
        fatal_values = {reason.value for reason in FatalReason}
        assert set_aside_values.isdisjoint(fatal_values)


class TestImportReportNormalizedBucket:
    """T021 — the normalised bucket starts empty, ``add_normalized`` records
    reason, subject and params as data without touching any other bucket, and
    a recorded ``NormalizedEntry`` is frozen. Deliberately apart from
    :attr:`ImportReport.set_aside`: a normalised value *was* stored (T021,
    FR-009, decisions.md D24) — only under a different predicate than the
    file itself asserted — whereas everything in ``set_aside`` was not."""

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
    """Every member of the closed ``NormalizedReason`` vocabulary is lazily
    translatable, carries a named ``%(subject)s`` placeholder, and renders
    with its own example params (Article XII)."""

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
    """T003 — a value stored under a configured language other than its
    published tag carries a translatable, named-placeholder entry naming
    both (FR-006), inspectable as data and distinct from a value that was
    not stored at all (research.md R4)."""

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
        # A caller filtering for "things that did not make it in" (research.md
        # R4) must still get a truthful answer: the value *was* stored.
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
    """A normalised value was stored; a set-aside or fatal one was not
    (decisions.md D24) — the three closed vocabularies never share a value."""

    def test_normalized_reason_shares_no_value_with_set_aside_or_fatal_reason(self):
        normalized_values = {reason.value for reason in NormalizedReason}
        set_aside_values = {reason.value for reason in SetAsideReason}
        fatal_values = {reason.value for reason in FatalReason}
        assert normalized_values.isdisjoint(set_aside_values)
        assert normalized_values.isdisjoint(fatal_values)


class TestReasonTemplatesUseOnlyNamedPlaceholders:
    """T031 (FR-016, spec User Story 6 Acceptance Scenario 1) — one closed-world
    sweep across all three report-reason vocabularies. The per-reason tests above
    assert each template is lazily translatable and carries a named
    ``%(subject)s``; this asserts there is nothing *besides* named placeholders in
    any of them — the "named rather than positional" half FR-016 states but the
    per-reason tests don't check for the absence of. A reason added later without
    its own dedicated test is still caught here."""

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
    """SEC-702 (review, security lens, decisions.md D22) — every value in an entry is
    text the source document chose, and since #52 that document can come from a remote
    server and its account is written to an operator's terminal.

    ``\\x1b[2K\\r`` erases the line being written and ``\\x1b[1A`` moves the cursor over
    the one above, so before this a published label could overwrite the report of itself.
    Measured on the branch: a refusal read ``'Innocent\\x1b[2K\\rALL CLEAR - 0 problems
    found.\\x1b[1A' has no identifier that survives re-serialization`` — with the escape
    sequences intact. It matters most under ``--dry-run``, whose only product is the
    text an operator reads before deciding to commit.

    Stripping happens at ``_render_params``, the one boundary all three entry kinds pass
    through, so all three are covered by construction rather than one at a time.
    """

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
        # The text itself survives — this strips the control characters, it does not
        # discard the value or replace it with a placeholder.
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
        # The carve-out the usual "control characters minus \n and \t" rule would leave:
        # a report entry is one line by construction, so an embedded newline both breaks
        # the format and lets a document write a line of the account itself.
        entry = SetAsideEntry(
            reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
            subject="granite\n8 records created.",
            params={"language": "es"},
        )
        assert "\n" not in entry.render()

    def test_an_ordinary_subject_and_params_are_untouched(self):
        # The control: stripping must be invisible to every real vocabulary.
        entry = SetAsideEntry(
            reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
            subject="https://example.org/vocab/rocks/granite (Granit, Gränit)",
            params={"language": "es"},
        )
        rendered = entry.render()
        assert "https://example.org/vocab/rocks/granite (Granit, Gränit)" in rendered
        assert "es" in rendered
