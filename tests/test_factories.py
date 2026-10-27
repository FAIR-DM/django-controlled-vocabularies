"""Tests for tests.factories."""

import pytest

from controlled_vocabularies.models import ConceptScheme, Link, Record
from tests.factories import (
    ConceptSchemeFactory,
    LinkFactory,
    RecordFactory,
    collection_with_members,
    labelled,
    relation_graph,
)


@pytest.mark.django_db
class TestConceptSchemeFactory:
    def test_scheme_factory_produces_a_saved_vocabulary_with_a_name_and_identity(self):
        scheme = ConceptSchemeFactory()

        assert isinstance(scheme, ConceptScheme)
        assert scheme.pk is not None
        assert scheme.pref_label
        assert scheme.slug
        assert scheme.uri

    def test_scheme_factory_sequence_avoids_slug_collisions(self):
        first = ConceptSchemeFactory()
        second = ConceptSchemeFactory()

        assert first.slug != second.slug
        assert ConceptScheme.objects.count() == 2

    def test_scheme_factory_accepts_a_name(self):
        scheme = ConceptSchemeFactory(name="Rock types")

        assert scheme.pref_label == "Rock types"


@pytest.mark.django_db
class TestLinkFactory:
    def test_link_factory_produces_a_saved_link_with_its_own_source_record(self):
        link = LinkFactory()

        assert isinstance(link, Link)
        assert link.pk is not None
        assert Record.objects.filter(pk=link.source_id).exists()

    def test_link_factory_targets_do_not_repeat(self):
        first, second = LinkFactory(), LinkFactory()

        assert first.target != second.target


@pytest.mark.django_db
class TestRecordFactory:
    def test_record_factory_produces_a_saved_concept_with_a_name_and_identity(self):
        record = RecordFactory()

        assert isinstance(record, Record)
        assert record.pk is not None
        assert record.type == Record.Type.CONCEPT
        assert record.pref_label
        assert record.slug
        assert record.uri

    def test_record_factory_auto_creates_its_vocabulary(self):
        record = RecordFactory()

        assert ConceptScheme.objects.filter(pk=record.scheme_id).exists()

    def test_record_factory_repeated_calls_do_not_collide(self):
        RecordFactory()
        RecordFactory()

        assert Record.objects.count() == 2

    def test_record_factory_accepts_an_explicit_vocabulary(self):
        scheme = ConceptSchemeFactory()

        record = RecordFactory(scheme=scheme)

        assert record.scheme_id == scheme.pk

    def test_record_factory_names_the_record_in_its_vocabularys_default_language(self):
        scheme = ConceptSchemeFactory(default_language="de")

        record = RecordFactory(scheme=scheme, label="Granit")

        assert record.label("de") == "Granit"


class TestLabelled:
    def test_labelled_names_its_subject_in_the_given_language(self):
        document = labelled("Granit", language="de")

        assert document == {"skos:prefLabel": [{"@value": "Granit", "@language": "de"}]}

    def test_labelled_adds_the_further_statements(self):
        statements = {"skos:notation": [{"@value": "GR-01"}]}

        document = labelled("Granite", statements=statements)

        assert document["skos:notation"] == [{"@value": "GR-01"}]


@pytest.mark.django_db
class TestRelationGraph:
    def test_relation_graph_states_the_broader_link_from_the_child(self):
        graph = relation_graph()

        assert graph["child"].linked_uris("skos:broader") == [graph["parent"].uri]

    def test_relation_graph_states_the_related_link_from_the_left(self):
        graph = relation_graph()

        assert graph["left"].linked_uris("skos:related") == [graph["right"].uri]

    def test_relation_graph_builds_every_concept_in_one_vocabulary(self):
        graph = relation_graph()

        concepts = (graph["parent"], graph["child"], graph["left"], graph["right"])
        assert {concept.scheme_id for concept in concepts} == {graph["scheme"].pk}


@pytest.mark.django_db
class TestCollectionWithMembers:
    def test_collection_with_members_yields_a_collection_listing_its_members(self):
        collection, members = collection_with_members()

        assert collection.type == Record.Type.COLLECTION
        assert collection.member_uris() == [member.uri for member in members]

    def test_collection_with_members_builds_everything_in_one_vocabulary(self):
        collection, members = collection_with_members()

        assert {member.scheme_id for member in members} == {collection.scheme_id}

    def test_collection_with_members_builds_an_ordered_collection(self):
        collection, members = collection_with_members(ordered=True)

        assert collection.type == Record.Type.ORDERED_COLLECTION
        assert collection.values("skos:memberList") == [
            {"@id": member.uri} for member in members
        ]

    def test_collection_with_members_accepts_a_name(self):
        collection, _ = collection_with_members(name="Igneous rocks")

        assert collection.pref_label == "Igneous rocks"
