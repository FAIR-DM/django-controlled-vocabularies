"""Tests for the demo project's ``seed_demo`` command."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from controlled_vocabularies.models import Concept, ConceptScheme
from demo.management.commands.seed_demo import Command
from tests.factories import ConceptSchemeFactory


def run_seed_demo():
    """Run the ``seed_demo`` command against the test database."""
    call_command(Command())


@pytest.mark.django_db
class TestSeedDemo:
    def test_both_vocabularies_exist_with_their_concepts_after_one_run(self):
        run_seed_demo()
        schemes = list(ConceptScheme.objects.all())
        assert len(schemes) == 2
        for scheme in schemes:
            assert scheme.concepts.count() > 0

    def test_a_second_run_returns_the_same_counts(self):
        run_seed_demo()
        first = {
            scheme.name: scheme.concepts.count()
            for scheme in ConceptScheme.objects.all()
        }

        run_seed_demo()
        second = {
            scheme.name: scheme.concepts.count()
            for scheme in ConceptScheme.objects.all()
        }

        assert first == second

    def test_a_vocabulary_added_by_hand_between_runs_is_gone_afterwards(self):
        run_seed_demo()
        ConceptSchemeFactory(name="Added by hand")

        run_seed_demo()

        assert not ConceptScheme.objects.filter(name="Added by hand").exists()

    def test_one_vocabulary_reads_as_imported_and_the_other_as_authored_here(self):
        run_seed_demo()

        imported = ConceptScheme.objects.exclude(static_uri__isnull=True)
        authored = ConceptScheme.objects.filter(static_uri__isnull=True)

        assert imported.count() == 1
        assert authored.count() == 1

    def test_seeded_concepts_carry_alternative_and_hidden_labels_through_the_real_importer(
        self,
    ):
        # Loaded through import_skos(), never a fixture behind it, so a hidden label is
        # exercised the way a real import loads it.
        run_seed_demo()

        dataset = Concept.objects.get(label="Dataset")
        assert dataset.alt_labels("en") == ["Data set"]
        assert dataset.hidden_labels("en") == ["Datset"]

        fieldwork = Concept.objects.get(label="Fieldwork")
        assert fieldwork.alt_labels("en") == ["Field work"]
        assert fieldwork.hidden_labels("en") == ["Feildwork"]

    def test_a_second_run_does_not_duplicate_the_seeded_labels(self):
        run_seed_demo()
        run_seed_demo()

        dataset = Concept.objects.get(label="Dataset")
        assert dataset.alt_labels("en") == ["Data set"]
        assert dataset.hidden_labels("en") == ["Datset"]

    def test_seeded_collections_load_through_the_real_importer_with_one_of_each_kind(
        self,
    ):
        # Loaded through import_skos() from research_methods.ttl, never a fixture behind
        # it.
        run_seed_demo()

        authored = ConceptScheme.objects.get(static_uri__isnull=True)
        collections = {
            collection.name: collection for collection in authored.collections.all()
        }

        assert len(collections) == 2
        ordered = [c for c in collections.values() if c.ordered]
        unordered = [c for c in collections.values() if not c.ordered]
        assert len(ordered) == 1
        assert len(unordered) == 1

    def test_a_second_run_does_not_duplicate_the_seeded_collections(self):
        run_seed_demo()
        run_seed_demo()

        authored = ConceptScheme.objects.get(static_uri__isnull=True)
        assert authored.collections.count() == 2

    def test_both_seeded_collections_render_on_their_vocabularys_page(self, client):
        run_seed_demo()

        authored = ConceptScheme.objects.get(static_uri__isnull=True)
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": authored.slug},
            )
        )
        content = response.content.decode()

        for collection in authored.collections.all():
            assert collection.name in content
