"""The ``sync_vocabularies`` command, which loads every vocabulary a site declares (FS-008)."""

from __future__ import annotations

from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from controlled_vocabularies import conf
from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
)
from controlled_vocabularies.exchange.report import ImportReport
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management.commands.import_skos import DryRun
from controlled_vocabularies.management.rendering import ReportRenderer
from controlled_vocabularies.management.sources import SourceResolver
from controlled_vocabularies.models import ConceptScheme


class Command(BaseCommand):
    """Import or refresh every vocabulary declared in ``CONTROLLED_VOCABULARIES``."""

    # django-stubs types BaseCommand.help as str, so the lazy proxy needs the cast (Article XII).
    help = cast(
        str,
        _(
            "Import or refresh every vocabulary declared in the CONTROLLED_VOCABULARIES "
            "setting."
        ),
    )

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> Any:
        """Build the parser with ``help`` forced to a real string."""
        # argparse runs the description through re.sub, which rejects a gettext_lazy proxy.
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.description = str(parser.description)
        return parser

    def add_arguments(self, parser: Any) -> None:
        """Add the optional slugs and ``--dry-run``."""
        parser.add_argument(
            "slugs",
            nargs="*",
            help=str(
                _(
                    "Load only these declared vocabularies. All of them when none is given."
                )
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help=str(
                _(
                    "Perform every import and report the outcome, then leave the database exactly as it was."
                )
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Load each declared vocabulary in its own transaction and report on each."""
        declarations = conf.get_declared_vocabularies()
        slugs = options["slugs"] or list(declarations)
        undeclared = [slug for slug in slugs if slug not in declarations]
        if undeclared:
            raise CommandError(
                str(_("Not declared in CONTROLLED_VOCABULARIES: %(slugs)s."))
                % {"slugs": ", ".join(undeclared)}
            )
        dry_run = options["dry_run"]
        verbosity = options["verbosity"]
        failed = 0
        for slug in slugs:
            try:
                report = self.sync(slug, declarations[slug], dry_run=dry_run)
            except CommandError as exc:
                failed += 1
                self.stderr.write(
                    str(_("%(slug)s: %(error)s")) % {"slug": slug, "error": exc}
                )
                continue
            if verbosity:
                self.stdout.write(slug)
            for line in ReportRenderer(
                report, dry_run=dry_run, verbosity=verbosity
            ).render():
                self.stdout.write(f"  {line}")
        if failed:
            raise CommandError(
                str(
                    ngettext_lazy(
                        "%(failed)d of %(total)d vocabulary could not be loaded.",
                        "%(failed)d of %(total)d vocabularies could not be loaded.",
                        len(slugs),
                    )
                )
                % {"failed": failed, "total": len(slugs)}
            )

    def sync(self, slug: str, declaration: dict, *, dry_run: bool) -> ImportReport:
        """Load one declared vocabulary in a transaction of its own.

        Args:
            slug: The declared key, which fields name the vocabulary by.
            declaration: Its ``source`` and optional ``format``.
            dry_run: Roll the transaction back once the import has reported.

        Returns:
            The import's report.

        Raises:
            CommandError: The vocabulary could not be loaded; nothing of it was kept.
        """
        try:
            with transaction.atomic():
                report = self.load(slug, declaration)
                if dry_run:
                    raise DryRun(report)  # noqa: TRY301 - must sit inside the block it unwinds
        except DryRun as done:
            return done.report
        except SkosImportFailed as exc:
            raise CommandError(
                "\n".join(finding.render() for finding in exc.report.fatal)
            ) from exc
        except SkosImportError as exc:
            raise CommandError(str(exc)) from exc
        return report

    def load(self, slug: str, declaration: dict) -> ImportReport:
        """Import a declared source into the vocabulary held under its slug.

        A vocabulary is found again by its declared slug, never by re-deriving one from its
        URI. One the import creates takes the declared slug.

        Args:
            slug: The declared key.
            declaration: Its ``source`` and optional ``format``.

        Returns:
            The import's report.

        Raises:
            CommandError: The declaration names no source, or the source is a vocabulary
                already held under another slug.
        """
        source = declaration.get("source")
        if not source:
            raise CommandError(str(_("The declaration names no source.")))
        held = ConceptScheme.objects.filter(slug=slug).first()
        resolver = SourceResolver(str(source), serialization=declaration.get("format"))
        try:
            resolved = resolver.resolve()
            report = import_skos(
                resolved.path,
                serialization=resolved.serialization,
                scheme=held,
                base_uri=resolved.base_uri,
            )
        finally:
            resolver.cleanup()
        if held is not None:
            return report
        scheme = ConceptScheme.objects.get(uri__in=[*report.created, *report.updated])
        if scheme.uri not in report.created:
            raise CommandError(
                str(
                    _(
                        "'%(uri)s' is already loaded under the slug '%(held)s', and was "
                        "not renamed. Declare it under that slug."
                    )
                )
                % {"uri": scheme.uri, "held": scheme.slug}
            )
        scheme.slug = slug
        scheme.save(update_fields=["slug"])
        return report
