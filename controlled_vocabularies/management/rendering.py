"""Rendering an :class:`~controlled_vocabularies.exchange.report.ImportReport` for a terminal
(T015, T016, T017, T018, FR-006, FR-007, FR-008, plan.md "Rendering").

The bucket counts an import run leaves behind — created, updated, set aside, normalized, absent
from source — plus the set-aside account in full: grouped by reason with a count each, the
per-language account, records absent from the source named in their own section, and per-entry
detail at raised verbosity (``--verbosity``, decisions.md D6). Every section prints, whatever it
holds: a section reading zero and a section silently missing look identical to a reader but mean
different things (FR-008's own reasoning for ``absent_from_source``, applied here to every bucket)
— which is also why each grouping below is a plain iteration over the report's own accessors: an
empty grouping simply yields nothing, and the bucket count above it already shows the zero.
"""

from __future__ import annotations

from collections.abc import Iterator

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from controlled_vocabularies.exchange.report import ImportReport


class ReportRenderer:
    """Turns an :class:`ImportReport` into translated lines a curator reads at a terminal.

    ``dry_run`` is the one deliberate difference between a dry run's rendering and a live
    run's (T014, FR-010, `decisions.md` D9): when set, one extra line states that nothing was
    kept, so a dry run's counts are never mistaken for a completed import.

    ``verbosity`` carries Django's own ``--verbosity`` (T018, FR-007, `decisions.md` D6): at 0
    nothing prints at all, which is Django's own contract for that value (CORR-004, decisions.md
    D23); at the default of 1, the set-aside account is counts only; at 2 or above, each set-aside
    entry also prints, rendered by the entry's own ``render()``. No flag of this feature's own.
    """

    def __init__(
        self, report: ImportReport, *, dry_run: bool = False, verbosity: int = 1
    ) -> None:
        self.report = report
        self.dry_run = dry_run
        self.verbosity = verbosity

    def render(self) -> Iterator[str]:
        """Yield translated lines: bucket counts, then the set-aside account (grouped by reason,
        per-entry detail at raised verbosity, then the per-language account), then the records
        absent from the source, then the dry-run line. Nothing at all at ``--verbosity 0``."""
        if self.verbosity == 0:
            # CORR-004 (review, correctness): D6 justifies reusing Django's own option on the
            # grounds that it "already means exactly this and every management command an
            # operator has ever run supports it" — and Django's contract for 0 is no output.
            # Only the >= 2 branch below existed, so a deployment script silencing this command
            # the documented Django way got the full report on stdout. A refusal is unaffected:
            # it is raised as a CommandError, not rendered here.
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
        """One line per reason with its count (T016, FR-007), read from
        :meth:`ImportReport.set_aside_by_reason` — never by parsing a rendered message. A reason
        with no entries has no group in that mapping, so it yields no line of its own."""
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
        """One line per set-aside entry, each rendered by the entry's own ``render()`` (T018,
        FR-007). Only reached at raised verbosity — :meth:`render` guards the call."""
        for entry in self.report.set_aside:
            yield entry.render()

    def _render_language_account(self) -> Iterator[str]:
        """The per-language account (T016, FR-007/FR-008), read from
        :meth:`ImportReport.language_account` — how many values a language would recover if
        configured, one line per language."""
        for language, count in self.report.language_account().items():
            yield str(
                ngettext_lazy(
                    "%(count)d value set aside in the language '%(language)s'.",
                    "%(count)d values set aside in the language '%(language)s'.",
                    count,
                )
            ) % {"count": count, "language": language}

    def _render_absent_from_source_detail(self) -> Iterator[str]:
        """Records absent from the source, named in their own section (T017, FR-008,
        `decisions.md` D7): existing data left untouched, visibly separate from set-asides and
        never counted among them."""
        for subject in self.report.absent_from_source:
            yield str(
                _("'%(subject)s' is present but no longer mentioned by the source.")
            ) % {"subject": subject}
