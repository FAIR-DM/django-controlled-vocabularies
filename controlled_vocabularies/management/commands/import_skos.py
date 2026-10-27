"""The ``import_skos`` command, which loads a published SKOS vocabulary (FS-008)."""

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
    """Unwind a dry run's outer transaction after a successful run, carrying the report out.

    Args:
        report: The finished run's report.
    """

    def __init__(self, report: ImportReport) -> None:
        self.report = report


class Command(BaseCommand):
    """Import a published SKOS vocabulary from a local file or an http(s) URL."""

    # django-stubs types BaseCommand.help as str, so the lazy proxy needs the cast (Article XII).
    help = cast(
        str,
        _("Import a published SKOS vocabulary from a local file or an http(s) URL."),
    )

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> Any:
        """Build the parser with ``help`` forced to a real string."""
        # argparse runs the description through re.sub, which rejects a gettext_lazy proxy.
        # Forced here, not at class definition, so the active language applies (Article XII).
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.description = str(parser.description)
        return parser

    def add_arguments(self, parser: Any) -> None:
        """Add the source, ``--format`` and ``--dry-run`` arguments."""
        # Help strings are forced to str for the same reason as the parser description.
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
        """Import the source and print the report, or raise a ``CommandError``."""
        source = options["source"]
        dry_run = options["dry_run"]
        # import_skos's own is_file() check passes for a file that exists but cannot be read,
        # so permissions are checked here.
        path = Path(source)
        if path.is_file() and not os.access(path, os.R_OK):
            raise CommandError(
                str(_("'%(file)s' exists but is not readable.")) % {"file": source}
            )
        resolver = SourceResolver(source, serialization=options["format"])
        try:
            resolved = resolver.resolve()
            if dry_run:
                # The outer atomic() is unwound by a sentinel, so the importer's own atomic()
                # becomes a savepoint rolled back with it and the importer learns nothing
                # about a dry run (docs/adr/0005-a-preview-is-the-real-operation-rolled-back.md).
                try:
                    with transaction.atomic():
                        report = import_skos(
                            resolved.path,
                            serialization=resolved.serialization,
                            base_uri=resolved.base_uri,
                        )
                        raise DryRun(report)  # noqa: TRY301 - must sit inside the block it unwinds
                except DryRun as done:
                    report = done.report
            else:
                report = import_skos(
                    resolved.path,
                    serialization=resolved.serialization,
                    base_uri=resolved.base_uri,
                )
        except SkosImportFailed as exc:
            # str(exc) is one generic line; every finding is only on exc.report.fatal.
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
