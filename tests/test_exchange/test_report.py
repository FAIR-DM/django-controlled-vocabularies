"""Tests for controlled_vocabularies.exchange.report."""

import pytest
from django.utils.functional import Promise

from controlled_vocabularies.exchange.report import (
    FatalFinding,
    FatalReason,
    ImportReport,
)

# Every named placeholder each template declares beyond the universal %(subject)s.
EXAMPLE_FATAL_PARAMS = {
    FatalReason.MISSING_IDENTITY: {},
    FatalReason.REFUSED_IDENTITY: {},
    FatalReason.IDENTIFIER_TOO_LONG: {"limit": "500"},
    FatalReason.VOCABULARY_UNDETERMINED: {},
    FatalReason.VOCABULARY_TARGET_MISMATCH: {
        "target": "https://example.org/vocab/target"
    },
    FatalReason.VOCABULARY_AMBIGUOUS: {
        "declared": "https://example.org/vocab/a, https://example.org/vocab/b"
    },
}

HOSTILE = "Innocent\x1b[2K\rALL CLEAR - 0 problems found.\x1b[1A"


class TestImportReportBuckets:
    def test_a_new_report_has_four_empty_buckets(self):
        report = ImportReport()

        assert report.created == []
        assert report.updated == []
        assert report.absent_from_source == []
        assert report.fatal == []

    def test_each_report_owns_its_buckets(self):
        first = ImportReport()
        second = ImportReport()

        first.created.append("https://example.org/vocab/rocks")

        assert second.created == []


class TestFatalFinding:
    def test_add_fatal_records_reason_subject_and_params_as_data(self):
        report = ImportReport()

        report.add_fatal(
            FatalReason.VOCABULARY_TARGET_MISMATCH,
            "https://example.org/vocab/rocks",
            target="https://example.org/vocab/target",
        )

        assert len(report.fatal) == 1
        finding = report.fatal[0]
        assert isinstance(finding, FatalFinding)
        assert finding.reason is FatalReason.VOCABULARY_TARGET_MISMATCH
        assert finding.subject == "https://example.org/vocab/rocks"
        assert finding.params == {"target": "https://example.org/vocab/target"}

    def test_add_fatal_leaves_the_other_buckets_alone(self):
        report = ImportReport()

        report.add_fatal(FatalReason.MISSING_IDENTITY, "_:b0")

        assert report.created == []
        assert report.updated == []
        assert report.absent_from_source == []

    def test_a_finding_is_immutable(self):
        finding = FatalFinding(
            reason=FatalReason.MISSING_IDENTITY, subject="https://example.org/vocab/x"
        )

        with pytest.raises((AttributeError, TypeError)):
            finding.subject = "changed"


class TestFatalReasonVocabulary:
    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_reason_has_a_translatable_label(self, reason):
        assert isinstance(reason.label, Promise)

    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_reason_template_is_translatable_with_a_named_subject_placeholder(
        self, reason
    ):
        assert isinstance(reason.template, Promise)
        assert "%(subject)s" in str(reason.template)

    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_reason_template_has_no_positional_placeholder(
        self, reason, uses_only_named_placeholders
    ):
        assert uses_only_named_placeholders(str(reason.template))

    @pytest.mark.parametrize("reason", list(FatalReason))
    def test_every_reason_renders_its_subject_and_params(self, reason):
        params = EXAMPLE_FATAL_PARAMS[reason]
        finding = FatalFinding(
            reason=reason, subject="https://example.org/vocab/x", params=params
        )

        rendered = finding.render()

        assert isinstance(rendered, str)
        assert "https://example.org/vocab/x" in rendered
        for value in params.values():
            assert value in rendered


class TestDocumentSuppliedTextCannotDriveTheTerminal:
    def test_a_subject_cannot_carry_an_escape_sequence(self):
        finding = FatalFinding(
            reason=FatalReason.REFUSED_IDENTITY, subject=HOSTILE, params={}
        )

        rendered = finding.render()

        assert "\x1b" not in rendered
        assert "\r" not in rendered
        assert "Innocent" in rendered

    def test_a_param_cannot_carry_an_escape_sequence(self):
        finding = FatalFinding(
            reason=FatalReason.VOCABULARY_TARGET_MISMATCH,
            subject="https://example.org/vocab/rocks",
            params={"target": HOSTILE},
        )

        assert "\x1b" not in finding.render()

    def test_a_newline_cannot_fake_an_additional_report_line(self):
        # A finding is one line by construction, so newline is stripped with the rest.
        finding = FatalFinding(
            reason=FatalReason.MISSING_IDENTITY,
            subject="granite\n8 records created.",
        )

        assert "\n" not in finding.render()

    def test_an_ordinary_subject_is_untouched(self):
        subject = "https://example.org/vocab/rocks/granite (Granit, Gränit)"
        finding = FatalFinding(reason=FatalReason.MISSING_IDENTITY, subject=subject)

        assert subject in finding.render()
