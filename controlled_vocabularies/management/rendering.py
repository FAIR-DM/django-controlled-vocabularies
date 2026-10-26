"""Rendering an import report as translated terminal lines (FS-008)."""

from __future__ import annotations

from collections.abc import Iterator

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from controlled_vocabularies.exchange.report import ImportReport


class ReportRenderer:
    """Turn an :class:`ImportReport` into translated lines a curator reads at a terminal.

    Every count prints, because a count reading zero and a line silently missing mean
    different things to a reader.

    Args:
        report: The report to render.
        dry_run: Add a line stating that nothing was kept, so a dry run's counts are never
            mistaken for a completed import.
        verbosity: Django's ``--verbosity``. At 0 nothing prints.
    """

    def __init__(
        self, report: ImportReport, *, dry_run: bool = False, verbosity: int = 1
    ) -> None:
        self.report = report
        self.dry_run = dry_run
        self.verbosity = verbosity

    def render(self) -> Iterator[str]:
        """Yield the report's lines: the counts, each untouched record, then any notice.

        Yields:
            One translated line at a time, and none at all at ``--verbosity 0``.
        """
        # Django's contract for --verbosity 0 is no output. A refusal is unaffected, since
        # it is raised as a CommandError rather than rendered here.
        if self.verbosity == 0:
            return
        yield str(
            ngettext_lazy(
                "%(count)d record created.",
                "%(count)d records created.",
                len(self.report.created),
            )
        ) % {"count": len(self.report.created)}
        yield str(
            ngettext_lazy(
                "%(count)d record updated.",
                "%(count)d records updated.",
                len(self.report.updated),
            )
        ) % {"count": len(self.report.updated)}
        yield str(
            ngettext_lazy(
                "%(count)d record absent from the source.",
                "%(count)d records absent from the source.",
                len(self.report.absent_from_source),
            )
        ) % {"count": len(self.report.absent_from_source)}
        # Left untouched, so they are named apart from anything the run did.
        for subject in self.report.absent_from_source:
            yield str(
                _("'%(subject)s' is present but no longer mentioned by the source.")
            ) % {"subject": subject}
        yield str(
            ngettext_lazy(
                "%(count)d record belonging to another vocabulary left untouched.",
                "%(count)d records belonging to another vocabulary left untouched.",
                len(self.report.held_elsewhere),
            )
        ) % {"count": len(self.report.held_elsewhere)}
        for subject in self.report.held_elsewhere:
            yield str(
                _("'%(subject)s' belongs to another vocabulary and was left untouched.")
            ) % {"subject": subject}
        if self.dry_run:
            yield str(_("This was a dry run: nothing was kept."))
