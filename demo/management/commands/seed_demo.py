"""Management command that reloads the demo's seed vocabularies and sign-in accounts."""

from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from controlled_vocabularies.exchange import import_skos
from controlled_vocabularies.models import ConceptScheme

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"

#: Declares its own skos:ConceptScheme with an externally published URI.
IMPORTED_FILE = SEED_DIR / "dcmi_types.ttl"

#: Declares no vocabulary of its own, so it is loaded into one created for it.
AUTHORED_FILE = SEED_DIR / "research_methods.ttl"

AUTHORED_NAME = "Data Collection Methods"
AUTHORED_DESCRIPTION = (
    "Categories of method by which a research dataset was produced — authored for this "
    "demo rather than imported from a publisher."
)


class Command(BaseCommand):
    """Delete every vocabulary and reload the demo's seed vocabularies and accounts."""

    help = (
        "Delete every vocabulary, then reload the demo's two seed vocabularies and the sign-in "
        "accounts. Destructive: anything entered through the admin is lost."
    )

    def handle(self, *args, **options):
        """Delete every vocabulary, then load the seed vocabularies and accounts."""
        ConceptScheme.objects.all().delete()

        import_skos(IMPORTED_FILE)

        authored_scheme = self.create_scheme(AUTHORED_NAME, AUTHORED_DESCRIPTION)
        import_skos(AUTHORED_FILE, scheme=authored_scheme)

        seed_accounts()

        self.stdout.write(
            self.style.SUCCESS(
                "seed_demo loaded 2 vocabularies and the sign-in accounts"
            )
        )

    @staticmethod
    def create_scheme(name, description):
        """Create a vocabulary for a seed file that declares none of its own.

        Args:
            name: The vocabulary's name, in English.
            description: What it covers, in English.

        Returns:
            The saved vocabulary.
        """
        return ConceptScheme.objects.create(
            default_language="en",
            data={
                "skos:prefLabel": [{"@value": name, "@language": "en"}],
                "dcterms:description": [{"@value": description, "@language": "en"}],
            },
        )


#: The standard sign-in accounts, all with the password "password".
ACCOUNTS = {
    "regular.user": {},
    "staff.user": {"is_staff": True},
    "super.user": {"is_staff": True, "is_superuser": True},
}


def seed_accounts():
    """Create or reset the standard sign-in accounts."""
    for username, spec in ACCOUNTS.items():
        user, _ = User.objects.get_or_create(username=username)
        user.email = f"{username}@example.com"
        user.is_staff = spec.get("is_staff", False)
        user.is_superuser = spec.get("is_superuser", False)
        user.set_password("password")
        user.save()
