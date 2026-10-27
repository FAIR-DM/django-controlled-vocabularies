"""Tests for controlled_vocabularies.migrations.0003_record_links."""

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("controlled_vocabularies", "0002_indexed_concept_search")]
AFTER = [("controlled_vocabularies", "0003_record_links")]


def migrate(targets):
    """Migrate to ``targets`` and return the apps of the state it leaves."""
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.fixture
def records_before_the_migration():
    """Two records of a site that upgrades: one linking, one holding only literals."""
    apps = migrate(BEFORE)
    scheme = apps.get_model("controlled_vocabularies", "ConceptScheme").objects.create(
        uri="https://example.org/scheme", slug="scheme", default_language="en"
    )
    Record = apps.get_model("controlled_vocabularies", "Record")
    linking = Record.objects.create(
        scheme=scheme,
        type="skos:Concept",
        uri="https://example.org/a",
        slug="a",
        data={
            "skos:broader": [{"@id": "https://example.org/root"}],
            "skos:related": [{"@id": "https://example.org/b"}],
            "skos:note": [{"@value": "https://example.org/root"}],
            "skosxl:prefLabel": [
                {"skosxl:literalForm": [{"@id": "https://example.org/nested"}]}
            ],
        },
    )
    Record.objects.create(
        scheme=scheme,
        type="skos:Concept",
        uri="https://example.org/b",
        slug="b",
        data={"skos:note": [{"@value": "plain"}]},
    )
    yield linking.pk
    migrate(AFTER)


class TestRecordLinksMigration:
    def test_it_builds_rows_for_records_that_have_none(
        self, records_before_the_migration
    ):
        apps = migrate(AFTER)

        links = apps.get_model("controlled_vocabularies", "Link").objects.all()

        assert sorted(links.values_list("source_id", "predicate", "target")) == [
            (records_before_the_migration, "skos:broader", "https://example.org/root"),
            (records_before_the_migration, "skos:related", "https://example.org/b"),
        ]

    def test_it_can_be_reversed(self, records_before_the_migration):
        migrate(AFTER)

        apps = migrate(BEFORE)

        assert apps.get_model("controlled_vocabularies", "Record").objects.count() == 2

    def test_it_writes_each_row_once_when_records_span_several_batches(
        self, records_before_the_migration, monkeypatch
    ):
        monkeypatch.setattr(
            import_module("controlled_vocabularies.migrations.0003_record_links"),
            "BATCH_SIZE",
            1,
        )

        apps = migrate(AFTER)

        assert apps.get_model("controlled_vocabularies", "Link").objects.count() == 2
