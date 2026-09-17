"""``import_skos`` — load a published SKOS vocabulary from a terminal (T003, FR-001, FR-002,
FR-004, FR-005, plan.md "Summary").

Delegates the entire import to :func:`~controlled_vocabularies.exchange.skos.import_skos`
(Article II — no reimplementation of reading, matching or writing) and renders the result
through :class:`~controlled_vocabularies.management.rendering.ReportRenderer` from the first
line written; the command never formats a report itself, here or later (plan.md "Rendering").
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
)
from controlled_vocabularies.exchange.report import ImportReport
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management.rendering import ReportRenderer
from controlled_vocabularies.management.sources import SourceResolver


class DryRun(Exception):
    """Private sentinel that unwinds a dry run's outer transaction after a successful run,
    carrying the report out with it (`research.md` R5, `decisions.md` D4). Caught immediately
    outside the block it is raised in; never seen outside this module."""

    def __init__(self, report: ImportReport) -> None:
        self.report = report


class Command(BaseCommand):
    # django-stubs types BaseCommand.help as `str`; gettext_lazy's proxy satisfies the attribute
    # itself but not the stub, hence the cast (Article XII).
    help = cast(
        str,
        _("Import a published SKOS vocabulary from a local file or an http(s) URL."),
    )

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> Any:
        """Build the parser, then force :attr:`help` to a real string (Article XII).

        argparse formats the parser description through ``re.sub`` (``HelpFormatter._fill_text``),
        which raises ``TypeError: expected string or bytes-like object`` on a ``gettext_lazy``
        proxy — so ``--help`` fails outright rather than printing an untranslated line. Django
        passes :attr:`help` straight through as ``description`` and never calls ``str()`` on it.

        The parser is built once per invocation with the active language already set, so forcing
        the proxy here is both the latest safe moment and a correctly translated one. Doing it at
        class definition would bake in whichever language happened to be active at import.
        """
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.description = str(parser.description)
        return parser

    def add_arguments(self, parser: Any) -> None:
        # Each help is forced for the same reason as the description above: argparse runs every
        # help string through re.sub as it lays the text out. `add_arguments` is called from
        # `create_parser`, so this carries the same per-invocation translation timing.
        parser.add_argument(
            "source",
            help=str(_("A local filesystem path or an http(s) URL to a SKOS file.")),
        )
        parser.add_argument(
            "--format",
            dest="format",
            default=None,
            help=str(
                _(
                    "The source's serialization (turtle, xml, or json-ld), for a source whose extension or "
                    "Content-Type does not name one."
                )
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help=str(
                _(
                    "Perform the whole import and report the outcome, then leave the database exactly as it was."
                )
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = options["source"]
        dry_run = options["dry_run"]
        # A missing path is left to import_skos()/from_file's own is_file() check below, which
        # already names it distinctly (FR-002). A path that *exists* but cannot be opened for
        # permission reasons passes that same is_file() check, so it is caught here instead,
        # without touching exchange/skos.py (spec Edge Cases). A URL source never satisfies
        # is_file(), so this check is a no-op for one (decisions.md D13's revisit condition
        # does not arise: a fetched document's temporary file never reaches this branch).
        path = Path(source)
        if path.is_file() and not os.access(path, os.R_OK):
            raise CommandError(
                str(_("'%(file)s' exists but is not readable.")) % {"file": source}
            )
        resolver = SourceResolver(source, serialization=options["format"])
        try:
            resolved = resolver.resolve()
            if dry_run:
                # An outer atomic() exited by a sentinel, not a savepoint or a flag threaded
                # into the importer: SkosImporter.run's own atomic() becomes a savepoint here,
                # and the outer rollback discards it along with everything else (research.md
                # R5, decisions.md D4). The importer is not modified and learns nothing about
                # a dry run, which is what keeps a dry run's report identical to a live one
                # by construction. A refused run raises SkosImportFailed out of the block below
                # and rolls back for the same reason it does today, so it needs no separate path.
                try:
                    with transaction.atomic():
                        report = import_skos(
                            resolved.path,
                            serialization=resolved.serialization,
                            base_uri=resolved.base_uri,
                        )
                        # This *is* the sentinel-unwind pattern (plan.md "Dry run"): the raise
                        # has to sit here, inside the block it unwinds, not in a helper function.
                        raise DryRun(report)  # noqa: TRY301
                except DryRun as done:
                    report = done.report
            else:
                report = import_skos(
                    resolved.path,
                    serialization=resolved.serialization,
                    base_uri=resolved.base_uri,
                )
        except SkosImportFailed as exc:
            # SkosImportFailed's own str() is one generic "N problem(s) were found" line
            # (exchange/exceptions.py) — every collected finding is only reachable through
            # exc.report.fatal, so this is where FR-011's "all of them, not just the first"
            # actually happens (T020).
            raise CommandError(
                "\n".join(finding.render() for finding in exc.report.fatal)
            ) from exc
        except SkosImportError as exc:
            raise CommandError(str(exc)) from exc
        finally:
            resolver.cleanup()
        for line in ReportRenderer(
            report, dry_run=dry_run, verbosity=options["verbosity"]
        ).render():
            self.stdout.write(line)
