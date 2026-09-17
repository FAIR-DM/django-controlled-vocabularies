"""``controlled_vocabularies.management.rendering`` — an ``ImportReport`` as
translated lines for a terminal (T015, T016, T017, T018, FR-006, FR-007,
FR-008, plan.md "Rendering").

The bucket counts (created, updated, set aside, normalized, absent from
source), the set-aside account (grouped by reason with a count each, and the
per-language account), records absent from the source named in their own
section, and per-entry set-aside detail at raised verbosity, carried by
Django's own ``--verbosity`` rather than a new flag (decisions.md D6).

Exercised mostly against a hand-built :class:`ImportReport` (tasks.md T015);
``TestReportRendererAgainstARealRun`` and ``TestReportRendererAbsentFromSource``
exercise the same rendering against a report a real ``import_skos`` run
produces, so it is proven without needing a full import for every scenario
(tasks.md T016/T017).
"""

from pathlib import Path

from controlled_vocabularies.exchange.report import (
    ImportReport,
    NormalizedEntry,
    NormalizedReason,
    SetAsideEntry,
    SetAsideReason,
)
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management.rendering import ReportRenderer

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
    """T014, FR-010, `decisions.md` D9 — a dry run's output states plainly that nothing was
    kept; a live run's does not. A flag on the renderer rather than a print in the command, so
    the two renderings differ in exactly one deliberate place (plan.md "Rendering")."""

    def test_a_dry_run_states_that_nothing_was_kept(self):
        lines = [
            str(line) for line in ReportRenderer(ImportReport(), dry_run=True).render()
        ]
        assert any("nothing was kept" in line for line in lines)

    def test_a_live_run_of_the_same_report_does_not_state_that_nothing_was_kept(self):
        lines = [str(line) for line in ReportRenderer(ImportReport()).render()]
        assert not any("nothing was kept" in line for line in lines)


class TestReportRendererSetAsideByReason:
    """T016, FR-007, `decisions.md` D6 — set-asides grouped by reason with a count each, read
    from ``report.set_aside_by_reason()`` rather than by parsing any rendered message."""

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
    """T016, FR-007/FR-008, `decisions.md` D6 — the per-language account, read from
    ``report.language_account()``, for values not stored for a language reason."""

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
    """T016 — the same grouping proven against a report a real ``import_skos`` run produces,
    not only a hand-built one, so the accessors are exercised as the command will actually see
    them (tasks.md T016)."""

    def test_a_real_run_setting_aside_several_reasons_and_languages_groups_them_correctly(
        self, db
    ):
        # Committed under tests/fixtures/skos/ (T025) rather than written to tmp_path: every
        # identifier here is absolute, so — unlike the relative-URI fixtures decisions.md D11
        # documents — nothing about this document requires it to stay out of the directory
        # TestEverySkosPredicateIsReadOrReported walks, and it passes that walk unmodified.
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
    """T017, FR-008, `decisions.md` D7 — records absent from the source render as their own
    section, visibly separate from set-asides and not counted among them."""

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
    """T018, FR-007, `decisions.md` D6 — set-aside entries print individually only at raised
    verbosity, carried by Django's own ``--verbosity`` rather than a new flag."""

    def _report_with_several_hundred_set_asides(self):
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
        # CORR-004 (review, correctness): D6 justifies reusing --verbosity on the grounds
        # that Django's own option "already means exactly this", and Django's contract for
        # 0 is no output. Only the >= 2 branch existed, so a deployment script silencing
        # this command the documented way got the whole report on stdout.
        report = self._report_with_several_hundred_set_asides()
        assert list(ReportRenderer(report, verbosity=0).render()) == []

    def test_verbosity_zero_silences_the_dry_run_line_too(self):
        # The dry run line is the one thing that could argue for an exception, since it
        # says nothing was kept. It does not get one: at 0 there is no output to qualify,
        # and a dry run at --verbosity 0 writes nothing anywhere either way.
        assert (
            list(ReportRenderer(ImportReport(), dry_run=True, verbosity=0).render())
            == []
        )

    def test_the_default_verbosity_still_prints_the_counts(self):
        # The control: silencing 0 must not silence the default.
        assert list(ReportRenderer(ImportReport()).render()) != []
