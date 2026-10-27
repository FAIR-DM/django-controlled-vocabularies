"""The ``sync_vocabularies`` command, which loads every vocabulary a site uses (FS-008)."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from controlled_vocabularies import conf
from controlled_vocabularies.checks import concept_fields
from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
)
from controlled_vocabularies.exchange.report import ImportReport
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.fields import Vocabulary
from controlled_vocabularies.management.commands.import_skos import DryRun
from controlled_vocabularies.management.rendering import ReportRenderer
from controlled_vocabularies.management.sources import SourceResolver
from controlled_vocabularies.models import ConceptScheme


def field_vocabularies() -> dict[str, list[Vocabulary]]:
    """Return every vocabulary a concept field on an installed, concrete model names.

    A field inherited from an abstract model counts once for each concrete model that
    inherits it. An abstract model nothing inherits names nothing.

    Returns:
        Each URI with the declarations naming it, in model order, those carrying a
        source first.
    """
    named: dict[str, list[Vocabulary]] = {}
    for field in concept_fields():
        for vocabulary in field.vocabulary:
            declarations = named.setdefault(vocabulary.uri, [])
            if vocabulary not in declarations:
                declarations.append(vocabulary)
    return {
        uri: sorted(declarations, key=lambda vocabulary: vocabulary.source is None)
        for uri, declarations in named.items()
    }


class Command(BaseCommand):
    """Import or refresh every vocabulary the site declares or its concept fields name."""

    # django-stubs types BaseCommand.help as str, so the lazy proxy needs the cast (Article XII).
    help = cast(
        str,
        _(
            "Import or refresh every vocabulary declared in the CONTROLLED_VOCABULARIES "
            "setting, and every vocabulary a concept field names."
        ),
    )

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> Any:
        """Build the parser with ``help`` forced to a real string."""
        # argparse runs the description through re.sub, which rejects a gettext_lazy proxy.
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.description = str(parser.description)
        return parser

    def add_arguments(self, parser: Any) -> None:
        """Add the optional vocabularies and ``--dry-run``."""
        parser.add_argument(
            "vocabularies",
            nargs="*",
            help=str(
                _(
                    "Load only these vocabularies: a slug declared in CONTROLLED_VOCABULARIES, "
                    "or a URI a concept field names. All of them when none is given."
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
        """Load each vocabulary in its own transaction and report on each.

        The declared vocabularies load first. A vocabulary a field names loads after them,
        unless one of them was it.
        """
        declarations = conf.get_declared_vocabularies()
        named = field_vocabularies()
        requested = options["vocabularies"]
        unknown = [
            name for name in requested if name not in declarations and name not in named
        ]
        if unknown:
            raise CommandError(
                str(
                    _(
                        "Neither declared in CONTROLLED_VOCABULARIES nor named by a concept "
                        "field: %(vocabularies)s."
                    )
                )
                % {"vocabularies": ", ".join(unknown)}
            )
        slugs = [slug for slug in declarations if not requested or slug in requested]
        uris = [uri for uri in named if not requested or uri in requested]
        dry_run = options["dry_run"]
        verbosity = options["verbosity"]
        outcomes = {
            slug: self.attempt(
                slug,
                partial(self.load, slug, declarations[slug]),
                dry_run=dry_run,
                verbosity=verbosity,
            )
            for slug in slugs
        }
        loaded = set(outcomes.values())
        for uri in uris:
            if uri in loaded:
                continue
            held = ConceptScheme.objects.filter(uri=uri).first()
            if held is not None and held.slug in declarations:
                # Declared, so never read from a field. One this run attempted has reported.
                if held.slug not in outcomes:
                    outcomes[held.slug] = self.attempt(
                        held.slug,
                        partial(self.load, held.slug, declarations[held.slug]),
                        dry_run=dry_run,
                        verbosity=verbosity,
                    )
                continue
            vocabulary, *others = named[uri]
            outcomes[uri] = self.attempt(
                uri,
                partial(self.load_named, vocabulary),
                dry_run=dry_run,
                verbosity=verbosity,
            )
            if outcomes[uri] is not None:
                self.report_unused_sources(vocabulary, others, verbosity)
        failed = sum(outcome is None for outcome in outcomes.values())
        if failed:
            raise CommandError(
                str(
                    ngettext_lazy(
                        "%(failed)d of %(total)d vocabulary could not be loaded.",
                        "%(failed)d of %(total)d vocabularies could not be loaded.",
                        len(outcomes),
                    )
                )
                % {"failed": failed, "total": len(outcomes)}
            )

    def attempt(
        self,
        name: str,
        load: Callable[[], tuple[ImportReport, str]],
        *,
        dry_run: bool,
        verbosity: int,
    ) -> str | None:
        """Load one vocabulary and print its report, or report why it could not be loaded.

        Args:
            name: The slug or URI it is named by.
            load: Loads it, returning the import's report and the vocabulary's URI.
            dry_run: Whether to roll the import back once it has reported.
            verbosity: The command's verbosity.

        Returns:
            The vocabulary's URI, or ``None`` when it could not be loaded.
        """
        try:
            report, uri = self.sync(load, dry_run=dry_run)
        except CommandError as exc:
            self.fail(name, exc)
            return None
        self.render(name, report, dry_run=dry_run, verbosity=verbosity)
        return uri

    def fail(self, name: str, exc: CommandError) -> None:
        """Report one vocabulary that could not be loaded.

        Args:
            name: The slug or URI it was named by.
            exc: Why it could not be loaded.
        """
        self.stderr.write(str(_("%(name)s: %(error)s")) % {"name": name, "error": exc})

    def render(
        self, name: str, report: ImportReport, *, dry_run: bool, verbosity: int
    ) -> None:
        """Print one vocabulary's report under the name it was loaded by.

        Args:
            name: The slug or URI it was named by.
            report: The import's report.
            dry_run: Whether the run was a dry run.
            verbosity: The command's verbosity.
        """
        if verbosity:
            self.stdout.write(name)
        for line in ReportRenderer(
            report, dry_run=dry_run, verbosity=verbosity
        ).render():
            self.stdout.write(f"  {line}")

    def report_unused_sources(
        self, used: Vocabulary, others: list[Vocabulary], verbosity: int
    ) -> None:
        """Name every other source fields gave for a vocabulary loaded from ``used``.

        Args:
            used: The declaration the vocabulary was loaded from.
            others: The other declarations naming the same URI.
            verbosity: The command's verbosity.
        """
        if not verbosity:
            return
        for other in others:
            if other.source is not None and other.source != used.source:
                self.stdout.write(
                    "  "
                    + str(
                        _("Also named with the source %(source)s, which was not read.")
                    )
                    % {"source": other.source}
                )

    def sync(
        self, load: Callable[[], tuple[ImportReport, str]], *, dry_run: bool
    ) -> tuple[ImportReport, str]:
        """Load one vocabulary in a transaction of its own.

        Args:
            load: Loads it, returning the import's report and the vocabulary's URI.
            dry_run: Roll the transaction back once the import has reported.

        Returns:
            The import's report, and the URI of the vocabulary it loaded.

        Raises:
            CommandError: The vocabulary could not be loaded; nothing of it was kept.
            DryRun: Raised inside the transaction to roll it back, and caught here.
        """
        try:
            with transaction.atomic():
                report, uri = load()
                if dry_run:
                    raise DryRun(report)  # noqa: TRY301 - must sit inside the block it unwinds
        except DryRun as done:
            return done.report, uri
        except SkosImportFailed as exc:
            raise CommandError(
                "\n".join(finding.render() for finding in exc.report.fatal)
            ) from exc
        except SkosImportError as exc:
            raise CommandError(str(exc)) from exc
        return report, uri

    def read(
        self,
        source: str,
        serialization: str | None,
        scheme: ConceptScheme | None,
    ) -> ImportReport:
        """Fetch ``source`` when it is an address, and import it.

        Args:
            source: A local path or an http(s) address.
            serialization: The serialization it is in, when named.
            scheme: The vocabulary to import into, for a source that declares none.

        Returns:
            The import's report.
        """
        resolver = SourceResolver(source, serialization=serialization)
        try:
            resolved = resolver.resolve()
            return import_skos(
                resolved.path,
                serialization=resolved.serialization,
                scheme=scheme,
                base_uri=resolved.base_uri,
            )
        finally:
            resolver.cleanup()

    def load(self, slug: str, declaration: dict) -> tuple[ImportReport, str]:
        """Import a declared source into the vocabulary held under its slug.

        A vocabulary is found again by its declared slug, never by re-deriving one from its
        URI. One the import creates takes the declared slug.

        Args:
            slug: The declared key.
            declaration: Its ``source`` and optional ``format``.

        Returns:
            The import's report, and the URI of the vocabulary it loaded.

        Raises:
            CommandError: The declaration names no source, its key is not a usable slug,
                or the source is a vocabulary already held under another slug.
        """
        source = declaration.get("source")
        if not source:
            raise CommandError(str(_("The declaration names no source.")))
        try:
            ConceptScheme._meta.get_field("slug").run_validators(slug)
        except ValidationError as exc:
            raise CommandError(
                str(_("The declared key is not a usable slug: %(error)s"))
                % {"error": " ".join(exc.messages)}
            ) from exc
        held = ConceptScheme.objects.filter(slug=slug).first()
        report = self.read(str(source), declaration.get("format"), held)
        if held is not None:
            return report, held.uri
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
        return report, scheme.uri

    def load_named(self, vocabulary: Vocabulary) -> tuple[ImportReport, str]:
        """Import a vocabulary a concept field names, from its source or its URI.

        Args:
            vocabulary: The field's declaration.

        Returns:
            The import's report, and the vocabulary's URI.

        Raises:
            CommandError: The source publishes some other vocabulary.
        """
        held = ConceptScheme.objects.filter(uri=vocabulary.uri).first()
        source = vocabulary.uri if vocabulary.source is None else str(vocabulary.source)
        report = self.read(source, vocabulary.format, held)
        if held is None and vocabulary.uri not in report.created:
            raise CommandError(
                str(
                    _(
                        "'%(source)s' does not publish the vocabulary '%(uri)s', and was "
                        "not loaded."
                    )
                )
                % {"source": source, "uri": vocabulary.uri}
            )
        return report, vocabulary.uri
