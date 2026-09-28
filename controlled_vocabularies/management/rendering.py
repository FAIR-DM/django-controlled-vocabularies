"""Rendering an import report as translated terminal lines (FS-008)."""

from __future__ import annotations

from collections.abc import Iterator

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from controlled_vocabularies.exchange.report import ImportReport


class ReportRenderer:
    """Turn an :class:`ImportReport` into translated lines a curator reads at a terminal.

    Every section prints whatever it holds, because a section reading zero and a section
    silently missing mean different things to a reader.

    Args:
        report: The report to render.
        dry_run: Add a line stating that nothing was kept, so a dry run's counts are never
            mistaken for a completed import.
        verbosity: Django's ``--verbosity``. At 0 nothing prints, at 1 the set-aside
            account is counts only, and from 2 each set-aside entry prints too.
    """

    def __init__(
        self, report: ImportReport, *, dry_run: bool = False, verbosity: int = 1
    ) -> None:
        self.report = report
        self.dry_run = dry_run
        self.verbosity = verbosity

    def render(self) -> Iterator[str]:
        """Yield the report's lines: bucket counts, the set-aside account, then the rest.

        After the counts come the set-aside groups by reason, the per-entry detail at raised
        verbosity, the per-language account, the records absent from the source and the
        dry-run line.

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
                "%(count)d value set aside.",
                "%(count)d values set aside.",
                len(self.report.set_aside),
            )
        ) % {"count": len(self.report.set_aside)}
        yield str(
            ngettext_lazy(
                "%(count)d value normalized.",
                "%(count)d values normalized.",
                len(self.report.normalized),
            )
        ) % {"count": len(self.report.normalized)}
        yield str(
            ngettext_lazy(
                "%(count)d record absent from the source.",
                "%(count)d records absent from the source.",
                len(self.report.absent_from_source),
            )
        ) % {"count": len(self.report.absent_from_source)}
        yield from self._render_set_aside_by_reason()
        if self.verbosity >= 2:
            yield from self._render_set_aside_detail()
        yield from self._render_language_account()
        yield from self._render_absent_from_source_detail()
        if self.dry_run:
            yield str(_("This was a dry run: nothing was kept."))

    def _render_set_aside_by_reason(self) -> Iterator[str]:
        """Yield one line per set-aside reason with its count.

        Read from :meth:`ImportReport.set_aside_by_reason`, never by parsing a message. A
        reason with no entries has no group and so no line.

        Yields:
            One translated line per reason that has entries.
        """
        for reason, entries in self.report.set_aside_by_reason().items():
            count = len(entries)
            yield str(
                ngettext_lazy(
                    "%(count)d value set aside for '%(reason)s'.",
                    "%(count)d values set aside for '%(reason)s'.",
                    count,
                )
            ) % {"count": count, "reason": reason.label}

    def _render_set_aside_detail(self) -> Iterator[str]:
        """Yield one line per set-aside entry, rendered by the entry itself.

        Yields:
            The entry's own message, one per set-aside value.
        """
        for entry in self.report.set_aside:
            yield entry.render()

    def _render_language_account(self) -> Iterator[str]:
        """Yield one line per language the set-aside values were published in.

        Read from :meth:`ImportReport.language_account`.

        Yields:
            One translated line per language, with how many values configuring it
            recovers.
        """
        for language, count in self.report.language_account().items():
            yield str(
                ngettext_lazy(
                    "%(count)d value set aside in the language '%(language)s'.",
                    "%(count)d values set aside in the language '%(language)s'.",
                    count,
                )
            ) % {"count": count, "language": language}

    def _render_absent_from_source_detail(self) -> Iterator[str]:
        """Yield a line for each record the source no longer mentions.

        They get a section of their own, visibly separate from set-asides and never counted
        among them: the existing data is left untouched.

        Yields:
            One translated line per absent record.
        """
        for subject in self.report.absent_from_source:
            yield str(
                _("'%(subject)s' is present but no longer mentioned by the source.")
            ) % {"subject": subject}
