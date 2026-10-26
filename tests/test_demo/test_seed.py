"""Tests for the demo project's ``seed_demo`` command."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse

from controlled_vocabularies.models import ConceptScheme, Record
from demo.management.commands.seed_demo import Command
from tests.factories import ConceptSchemeFactory

AUTHORED_NAME = "Data Collection Methods"
IMPORTED_NAME = "DCMI Type Vocabulary"


def run_seed_demo():
    """Run the ``seed_demo`` command against the test database."""
    call_command(Command())


def record_counts():
    """Return how many records each vocabulary holds, keyed by its preferred label."""
    return {
        scheme.pref_label: scheme.records.count()
        for scheme in ConceptScheme.objects.all()
    }


@pytest.mark.django_db
class TestSeedDemo:
    def test_both_vocabularies_exist_with_their_records_after_one_run(self):
        run_seed_demo()

        assert ConceptScheme.objects.count() == 2
        assert set(record_counts()) == {AUTHORED_NAME, IMPORTED_NAME}
        assert all(count > 0 for count in record_counts().values())

    def test_a_second_run_returns_the_same_counts(self):
        run_seed_demo()
        first = record_counts()

        run_seed_demo()

        assert record_counts() == first

    def test_a_vocabulary_added_by_hand_between_runs_is_gone_afterwards(self):
        run_seed_demo()
        ConceptSchemeFactory(name="Added by hand")

        run_seed_demo()

        assert not ConceptScheme.objects.filter(pref_label="Added by hand").exists()

    def test_seeded_concepts_carry_alternative_and_hidden_labels_through_the_real_importer(
        self,
    ):
        # Loaded through import_skos(), never a fixture behind it, so a hidden label is
        # exercised the way a real import loads it.
        run_seed_demo()

        dataset = Record.objects.get(pref_label="Dataset")
        assert dataset.values("skos:hiddenLabel") == [
            {"@value": "Datset", "@language": "en"}
        ]
        fieldwork = Record.objects.get(pref_label="Fieldwork")
        assert fieldwork.values("skos:altLabel") == [
            {"@value": "Field work", "@language": "en"}
        ]
        assert fieldwork.values("skos:hiddenLabel") == [
            {"@value": "Feildwork", "@language": "en"}
        ]

    def test_a_second_run_does_not_duplicate_the_seeded_labels(self):
        run_seed_demo()
        run_seed_demo()

        fieldwork = Record.objects.get(pref_label="Fieldwork")
        assert fieldwork.values("skos:altLabel") == [
            {"@value": "Field work", "@language": "en"}
        ]
        assert fieldwork.values("skos:hiddenLabel") == [
            {"@value": "Feildwork", "@language": "en"}
        ]

    def test_seeded_collections_load_through_the_real_importer_with_one_of_each_kind(
        self,
    ):
        # Loaded through import_skos() from research_methods.ttl, never a fixture behind
        # it.
        run_seed_demo()

        authored = ConceptScheme.objects.get(pref_label=AUTHORED_NAME)
        types = sorted(
            authored.records.filter(type__in=Record.COLLECTION_TYPES).values_list(
                "type", flat=True
            )
        )

        assert types == [Record.Type.COLLECTION, Record.Type.ORDERED_COLLECTION]

    def test_a_second_run_does_not_duplicate_the_seeded_collections(self):
        run_seed_demo()
        run_seed_demo()

        authored = ConceptScheme.objects.get(pref_label=AUTHORED_NAME)
        assert authored.records.filter(type__in=Record.COLLECTION_TYPES).count() == 2

    def test_both_seeded_collections_render_on_their_vocabularys_page(self, client):
        run_seed_demo()

        authored = ConceptScheme.objects.get(pref_label=AUTHORED_NAME)
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": authored.slug},
            )
        )
        content = response.content.decode()

        for collection in authored.records.filter(type__in=Record.COLLECTION_TYPES):
            assert collection.display_label() in content


@pytest.mark.django_db
class TestSeedDemoAccounts:
    def test_the_standard_accounts_exist_and_sign_in_with_the_demo_password(
        self, client
    ):
        run_seed_demo()

        for username in ("regular.user", "staff.user", "super.user"):
            assert User.objects.filter(username=username).exists()
            # The demo's published password.
            assert client.login(username=username, password="password")  # noqa: S106

    def test_the_regular_user_holds_no_permission_and_is_not_staff(self):
        run_seed_demo()

        regular = User.objects.get(username="regular.user")
        assert not regular.get_all_permissions()
        assert not regular.is_staff

    def test_the_staff_user_may_sign_in_to_the_admin_without_being_a_superuser(self):
        run_seed_demo()

        staff = User.objects.get(username="staff.user")
        assert staff.is_staff
        assert not staff.is_superuser

    def test_the_super_user_is_a_superuser(self):
        run_seed_demo()

        assert User.objects.get(username="super.user").is_superuser

    def test_a_second_run_resets_an_account_that_was_changed(self):
        run_seed_demo()
        User.objects.filter(username="regular.user").update(is_staff=True)

        run_seed_demo()

        assert not User.objects.get(username="regular.user").is_staff
