"""Tests for controlled_vocabularies.management.rendering."""

import inspect
import re
from pathlib import Path

from controlled_vocabularies.exchange.report import ImportReport
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management import rendering
from controlled_vocabularies.management.rendering import ReportRenderer
from tests.i18n_sweep import visit_management_source

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"


def leading_counts(lines):
    """Return the leading integer of each line: created, updated, absent, in order."""
    return [int(re.match(r"\d+", line).group()) for line in lines]


class TestReportRendererBucketCounts:
    def test_a_populated_report_renders_each_bucket_count(self):
        report = ImportReport(
            created=["http://example.org/a", "http://example.org/b"],
            updated=["http://example.org/c"],
            absent_from_source=[
                "http://example.org/f",
                "http://example.org/g",
                "http://example.org/h",
            ],
        )
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert leading_counts(lines[:3]) == [2, 1, 3]

    def test_an_empty_report_still_prints_every_count_reading_zero(self):
        lines = [str(line) for line in ReportRenderer(ImportReport()).render()]
        assert len(lines) == 4
        assert all("0" in line for line in lines)


class TestReportRendererDryRunLine:
    def test_a_dry_run_renders_one_line_more_than_a_live_run_of_the_same_report(self):
        report = ImportReport()
        dry_run_lines = list(ReportRenderer(report, dry_run=True).render())
        live_lines = list(ReportRenderer(report).render())
        assert dry_run_lines[:-1] == live_lines
        assert len(dry_run_lines) == len(live_lines) + 1


class TestReportRendererAbsentFromSource:
    def test_a_reimport_names_the_dropped_concept_as_absent(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        report = import_skos(FIXTURES / "rocks_updated.ttl")

        assert "http://example.org/rocks/quartz" in report.absent_from_source

        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any("http://example.org/rocks/quartz" in line for line in lines)
        assert leading_counts(lines[:3])[2] == 1


class TestReportRendererVerbosity:
    def test_verbosity_zero_prints_nothing_at_all(self):
        # Django's contract for --verbosity 0 is no output, so a script silencing the
        # command that way must not get the report.
        report = ImportReport(absent_from_source=["http://example.org/gone"])
        assert list(ReportRenderer(report, verbosity=0).render()) == []

    def test_verbosity_zero_silences_the_dry_run_line_too(self):
        # The dry-run line gets no exception: at 0 there is no output to qualify.
        assert (
            list(ReportRenderer(ImportReport(), dry_run=True, verbosity=0).render())
            == []
        )

    def test_the_default_verbosity_still_prints_the_counts(self):
        assert list(ReportRenderer(ImportReport()).render()) != []


class TestReportRendererI18nSweep:
    def test_every_output_string_is_translatable_with_named_placeholders(self):
        source = Path(inspect.getfile(rendering)).read_text()
        visitor = visit_management_source(source)
        assert visitor.positional_placeholders == [], (
            f"{rendering.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
        assert visitor.bare_literals == [], (
            f"{rendering.__name__} passes a bare, untranslated literal to an output sink: {visitor.bare_literals}"
        )
