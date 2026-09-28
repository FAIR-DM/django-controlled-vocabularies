"""Tests for controlled_vocabularies.management.rendering."""

import inspect
from pathlib import Path

from controlled_vocabularies.exchange.report import (
    ImportReport,
    NormalizedEntry,
    NormalizedReason,
    SetAsideEntry,
    SetAsideReason,
)
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management import rendering
from controlled_vocabularies.management.rendering import ReportRenderer
from tests.i18n_sweep import visit_management_source

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"


class TestReportRendererBucketCounts:
    def test_a_populated_report_renders_each_bucket_count(self):
        report = ImportReport(
            created=["http://example.org/a", "http://example.org/b"],
            updated=["http://example.org/c"],
            set_aside=[
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject="http://example.org/d",
                    params={"language": "de"},
                )
            ],
            normalized=[
                NormalizedEntry(
                    reason=NormalizedReason.FOREIGN_DEFINITION,
                    subject="http://example.org/e",
                    params={"language": "en", "predicate": "skos:scopeNote"},
                )
            ],
            absent_from_source=[
                "http://example.org/f",
                "http://example.org/g",
                "http://example.org/h",
            ],
        )
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any("2" in line and "created" in line for line in lines)
        assert any("1" in line and "updated" in line for line in lines)
        assert any("1" in line and "set aside" in line for line in lines)
        assert any("1" in line and "normalized" in line for line in lines)
        assert any("3" in line and "absent from the source" in line for line in lines)

    def test_an_empty_report_still_prints_every_section_reading_zero(self):
        lines = [str(line) for line in ReportRenderer(ImportReport()).render()]
        assert len(lines) == 5
        assert all("0" in line for line in lines)


class TestReportRendererDryRunLine:
    def test_a_dry_run_renders_one_line_more_than_a_live_run_of_the_same_report(self):
        report = ImportReport()
        dry_run_lines = list(ReportRenderer(report, dry_run=True).render())
        live_lines = list(ReportRenderer(report).render())
        assert dry_run_lines[:-1] == live_lines
        assert len(dry_run_lines) == len(live_lines) + 1


class TestReportRendererSetAsideByReason:
    def test_several_reasons_each_render_one_line_with_the_right_count(self):
        report = ImportReport(
            set_aside=[
                SetAsideEntry(
                    reason=SetAsideReason.NOTATION, subject="http://example.org/a"
                ),
                SetAsideEntry(
                    reason=SetAsideReason.NOTATION, subject="http://example.org/b"
                ),
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject="http://example.org/c",
                    params={"language": "es"},
                ),
            ]
        )
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any(
            "2" in line and str(SetAsideReason.NOTATION.label) in line for line in lines
        )
        assert any(
            "1" in line and str(SetAsideReason.UNCONFIGURED_LANGUAGE.label) in line
            for line in lines
        )

    def test_a_reason_with_no_entries_renders_no_line_for_itself(self):
        report = ImportReport(
            set_aside=[
                SetAsideEntry(
                    reason=SetAsideReason.NOTATION, subject="http://example.org/a"
                )
            ]
        )
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert not any(str(SetAsideReason.MAPPING.label) in line for line in lines)

    def test_a_report_with_no_set_asides_renders_no_by_reason_line(self):
        lines = [str(line) for line in ReportRenderer(ImportReport()).render()]
        assert len(lines) == 5


class TestReportRendererLanguageAccount:
    def test_several_unconfigured_languages_each_render_their_own_count(self):
        report = ImportReport(
            set_aside=[
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject="http://example.org/a",
                    params={"language": "es"},
                ),
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject="http://example.org/b",
                    params={"language": "es"},
                ),
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject="http://example.org/c",
                    params={"language": "ja"},
                ),
            ]
        )
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any("2" in line and "es" in line for line in lines)
        assert any("1" in line and "ja" in line for line in lines)

    def test_a_report_with_no_language_reasons_renders_no_language_line(self):
        lines = [str(line) for line in ReportRenderer(ImportReport()).render()]
        assert len(lines) == 5


class TestReportRendererAgainstARealRun:
    def test_a_real_run_setting_aside_several_reasons_and_languages_groups_them_correctly(
        self, db
    ):
        # Every identifier is absolute, so this fixture can sit in the directory the
        # predicate-coverage walk reads instead of being written to tmp_path.
        report = import_skos(FIXTURES / "setaside_multiple_reasons.ttl")
        grouped = report.set_aside_by_reason()
        assert len(grouped[SetAsideReason.NOTATION]) == 1
        assert len(grouped[SetAsideReason.MAPPING]) == 1
        assert len(grouped[SetAsideReason.UNCONFIGURED_LANGUAGE]) == 3

        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any(
            "1" in line and str(SetAsideReason.NOTATION.label) in line for line in lines
        )
        assert any(
            "1" in line and str(SetAsideReason.MAPPING.label) in line for line in lines
        )
        assert any(
            "3" in line and str(SetAsideReason.UNCONFIGURED_LANGUAGE.label) in line
            for line in lines
        )
        assert any("2" in line and "es" in line for line in lines)
        assert any("1" in line and "ja" in line for line in lines)


class TestReportRendererAbsentFromSource:
    def test_a_reimport_names_the_dropped_concept_as_absent_and_leaves_set_aside_alone(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        report = import_skos(FIXTURES / "rocks_updated.ttl")

        assert "http://example.org/rocks/quartz" in report.absent_from_source
        assert report.set_aside == []

        lines = [str(line) for line in ReportRenderer(report).render()]
        assert any("http://example.org/rocks/quartz" in line for line in lines)
        assert any("1" in line and "absent from the source" in line for line in lines)


class TestReportRendererVerbosity:
    def _report_with_several_hundred_set_asides(self):
        """Build a report holding 300 set-aside values."""
        return ImportReport(
            set_aside=[
                SetAsideEntry(
                    reason=SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject=f"http://example.org/item-{index}",
                    params={"language": "es"},
                )
                for index in range(300)
            ]
        )

    def test_default_verbosity_prints_no_per_value_line(self):
        report = self._report_with_several_hundred_set_asides()
        lines = [str(line) for line in ReportRenderer(report).render()]
        assert not any("item-0" in line for line in lines)

    def test_raised_verbosity_prints_one_line_per_value_matching_the_summary_count(
        self,
    ):
        report = self._report_with_several_hundred_set_asides()
        lines = [str(line) for line in ReportRenderer(report, verbosity=2).render()]
        expected_details = {entry.render() for entry in report.set_aside}
        detail_lines = [line for line in lines if line in expected_details]
        assert len(detail_lines) == len(report.set_aside) == 300

    def test_a_detail_line_is_the_entrys_own_render(self):
        entry = SetAsideEntry(
            reason=SetAsideReason.NOTATION,
            subject="http://example.org/only",
        )
        report = ImportReport(set_aside=[entry])
        lines = [str(line) for line in ReportRenderer(report, verbosity=2).render()]
        assert entry.render() in lines

    def test_verbosity_zero_prints_nothing_at_all(self):
        # Django's contract for --verbosity 0 is no output, so a script silencing the
        # command that way must not get the report.
        report = self._report_with_several_hundred_set_asides()
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
