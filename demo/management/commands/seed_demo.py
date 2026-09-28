"""Management command that reloads the demo's two seed vocabularies."""

from pathlib import Path

from django.core.management.base import BaseCommand

from controlled_vocabularies.exchange import import_skos
from controlled_vocabularies.models import ConceptScheme

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"

#: Declares its own skos:ConceptScheme with an externally published URI, so it reads as "Imported".
IMPORTED_FILE = SEED_DIR / "dcmi_types.ttl"

#: Declares no vocabulary of its own; loaded into one created directly, so it reads as "Held here".
AUTHORED_FILE = SEED_DIR / "research_methods.ttl"

AUTHORED_NAME = "Data Collection Methods"
AUTHORED_DESCRIPTION = (
    "Categories of method by which a research dataset was produced — authored for this "
    "demo rather than imported from a publisher."
)


class Command(BaseCommand):
    """Delete every vocabulary and reload the demo's two seed vocabularies."""

    help = (
        "Delete every vocabulary, then reload the demo's two seed vocabularies: one imported "
        "from a publisher, one authored here. Destructive: anything entered through the admin "
        "is lost."
    )

    def handle(self, *args, **options):
        """Delete every vocabulary, then load the imported and the authored seed vocabularies."""
        ConceptScheme.objects.all().delete()

        import_skos(IMPORTED_FILE)

        authored_scheme = ConceptScheme.objects.create(
            name=AUTHORED_NAME,
            description=AUTHORED_DESCRIPTION,
        )
        import_skos(AUTHORED_FILE, scheme=authored_scheme)

        self.stdout.write(self.style.SUCCESS("seed_demo loaded 2 vocabularies"))
