"""Management command that reloads the demo's seed vocabularies and sign-in accounts."""

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand

from controlled_vocabularies.models import ConceptScheme

#: The slug ``CONTROLLED_VOCABULARIES`` declares the authored vocabulary under. Its file,
#: ``seed/research_methods.ttl``, declares no vocabulary of its own, so the sync loads it
#: into the one created here.
AUTHORED_SLUG = "data-collection-methods"

AUTHORED_NAME = "Data Collection Methods"
AUTHORED_DESCRIPTION = (
    "Categories of method by which a research dataset was produced — authored for this "
    "demo rather than imported from a publisher."
)


class Command(BaseCommand):
    """Delete every vocabulary and reload the demo's seed vocabularies and accounts."""

    help = (
        "Delete every vocabulary, then reload the demo's two seed vocabularies and "
        "the sign-in accounts. Destructive: anything entered through the admin is lost."
    )

    def handle(self, *args, **options):
        """Delete every vocabulary, then load the seed vocabularies and accounts."""
        ConceptScheme.objects.all().delete()

        self.create_scheme(AUTHORED_SLUG, AUTHORED_NAME, AUTHORED_DESCRIPTION)
        call_command("sync_vocabularies", stdout=self.stdout, stderr=self.stderr)

        seed_accounts()

        self.stdout.write(
            self.style.SUCCESS(
                "seed_demo loaded 2 vocabularies and the sign-in accounts"
            )
        )

    @staticmethod
    def create_scheme(slug, name, description):
        """Create a vocabulary for a seed file that declares none of its own.

        Args:
            slug: The slug ``CONTROLLED_VOCABULARIES`` declares it under.
            name: The vocabulary's name, in English.
            description: What it covers, in English.

        Returns:
            The saved vocabulary.
        """
        return ConceptScheme.objects.create(
            slug=slug,
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
