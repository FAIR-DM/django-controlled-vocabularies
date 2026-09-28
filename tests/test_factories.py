"""Tests for tests.factories."""

import pytest

from controlled_vocabularies.models import (
    Collection,
    CollectionMember,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
)
from tests.factories import (
    CollectionFactory,
    CollectionMemberFactory,
    ConceptFactory,
    ConceptLabelFactory,
    ConceptNoteFactory,
    ConceptRelationFactory,
    ConceptSchemeFactory,
    collection_with_members,
    relation_graph,
)


@pytest.mark.django_db
class TestConceptSchemeFactory:
    def test_scheme_factory_produces_saved_valid_object(self):
        scheme = ConceptSchemeFactory()
        assert isinstance(scheme, ConceptScheme)
        assert scheme.pk is not None
        assert scheme.name
        assert scheme.slug
        assert scheme.uri == f"https://example.org/vocabularies/{scheme.slug}"

    def test_scheme_factory_sequence_avoids_slug_collisions(self):
        first = ConceptSchemeFactory()
        second = ConceptSchemeFactory()
        assert first.slug != second.slug
        assert ConceptScheme.objects.count() == 2

    def test_scheme_factory_without_the_external_trait_is_provisional(self):
        scheme = ConceptSchemeFactory()
        assert scheme.static_uri is None
        assert scheme.has_static_uri is False

    def test_scheme_factory_external_trait_yields_a_fixed_externally_assigned_uri(
        self,
    ):
        scheme = ConceptSchemeFactory(external=True)
        assert scheme.has_static_uri is True
        assert scheme.static_uri
        assert scheme.uri == scheme.static_uri


@pytest.mark.django_db
class TestConceptFactory:
    def test_concept_factory_produces_saved_valid_object(self):
        concept = ConceptFactory()
        assert isinstance(concept, Concept)
        assert concept.pk is not None
        assert concept.label
        assert concept.slug
        assert concept.uri == f"{concept.scheme.uri}/{concept.slug}"

    def test_concept_factory_auto_creates_its_scheme(self):
        concept = ConceptFactory()
        assert concept.scheme is not None
        assert concept.scheme.pk is not None
        assert ConceptScheme.objects.filter(pk=concept.scheme.pk).exists()

    def test_concept_factory_repeated_calls_do_not_collide(self):
        first = ConceptFactory()
        second = ConceptFactory()
        assert first.slug != second.slug or first.scheme_id != second.scheme_id
        assert first.scheme_id != second.scheme_id
        assert Concept.objects.count() == 2

    def test_concept_factory_accepts_an_explicit_scheme(self):
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme)
        assert concept.scheme_id == scheme.pk

    def test_concept_factory_has_no_extra_labels_or_notes_without_the_trait(self):
        concept = ConceptFactory()
        assert concept.labels.count() == 0
        assert concept.concept_notes.count() == 0

    def test_multilingual_trait_yields_preferred_labels_in_more_than_one_language(
        self,
    ):
        concept = ConceptFactory(multilingual=True)
        # The default language's preferred label is the anchor field; de is a separate row.
        default_pref = concept.preferred_label()
        german_pref = concept.preferred_label("de")
        assert default_pref
        assert german_pref
        assert default_pref != german_pref
        languages_with_a_preferred_label = {
            language for language in ("en", "de") if concept.preferred_label(language)
        }
        assert len(languages_with_a_preferred_label) > 1

    def test_multilingual_trait_yields_notes_in_more_than_one_language(self):
        concept = ConceptFactory(multilingual=True)
        assert concept.notes("en")
        assert concept.notes("de")
        languages_with_a_note = {
            language for language in ("en", "de") if concept.notes(language)
        }
        assert len(languages_with_a_note) > 1

    def test_multilingual_trait_uses_the_concepts_own_scheme_default_language(self):
        concept = ConceptFactory(multilingual=True)
        assert concept.labels.filter(
            language="de", kind=ConceptLabel.Kind.PREFERRED
        ).exists()
        assert concept.preferred_label("en") == concept.label

    def test_concept_factory_without_the_external_trait_is_provisional(self):
        concept = ConceptFactory()
        assert concept.static_uri is None
        assert concept.has_static_uri is False

    def test_concept_factory_external_trait_yields_a_fixed_externally_assigned_uri(
        self,
    ):
        concept = ConceptFactory(external=True)
        assert concept.has_static_uri is True
        assert concept.uri == concept.static_uri
        assert concept.scheme.has_static_uri is False


@pytest.mark.django_db
class TestConceptLabelFactory:
    def test_concept_label_factory_produces_saved_valid_object(self):
        label = ConceptLabelFactory()
        assert isinstance(label, ConceptLabel)
        assert label.pk is not None
        assert label.concept_id is not None
        assert label.language
        assert label.kind == ConceptLabel.Kind.PREFERRED
        assert label.text


@pytest.mark.django_db
class TestConceptNoteFactory:
    def test_concept_note_factory_produces_saved_valid_object(self):
        note = ConceptNoteFactory()
        assert isinstance(note, ConceptNote)
        assert note.pk is not None
        assert note.concept_id is not None
        assert note.language
        assert note.kind == ConceptNote.Kind.DEFINITION
        assert note.value


@pytest.mark.django_db
class TestConceptRelationFactory:
    def test_relation_factory_produces_a_broader_edge_navigable_both_ways(self):
        relation = ConceptRelationFactory()
        assert isinstance(relation, ConceptRelation)
        assert relation.pk is not None
        assert relation.kind == ConceptRelation.Kind.BROADER
        assert relation.source.scheme_id == relation.target.scheme_id
        assert relation.target in relation.source.broader()
        assert relation.source in relation.target.narrower()

    def test_relation_factory_builds_a_single_related_association(self):
        relation = ConceptRelationFactory(kind=ConceptRelation.Kind.RELATED)
        assert relation.source in relation.target.related()
        assert relation.target in relation.source.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 1
        )


@pytest.mark.django_db
class TestRelationGraph:
    def test_relation_graph_helper_yields_a_navigable_graph(self):
        graph = relation_graph()
        assert graph["parent"] in graph["child"].broader()
        assert graph["child"] in graph["parent"].narrower()
        assert graph["right"] in graph["left"].related()
        schemes = {
            c.scheme_id
            for c in (graph["parent"], graph["child"], graph["left"], graph["right"])
        }
        assert len(schemes) == 1


@pytest.mark.django_db
class TestCollectionFactory:
    def test_collection_factory_produces_saved_valid_object(self):
        collection = CollectionFactory()
        assert isinstance(collection, Collection)
        assert collection.pk is not None
        assert collection.name
        assert collection.slug
        assert collection.ordered is False
        assert collection.uri == f"{collection.scheme.uri}/collection/{collection.slug}"

    def test_collection_factory_without_the_external_trait_is_provisional(self):
        collection = CollectionFactory()
        assert collection.static_uri is None
        assert collection.has_static_uri is False

    def test_collection_factory_external_trait_yields_a_fixed_externally_assigned_uri(
        self,
    ):
        collection = CollectionFactory(external=True)
        assert collection.has_static_uri is True
        assert collection.uri == collection.static_uri


@pytest.mark.django_db
class TestCollectionMemberFactory:
    def test_collection_member_factory_joins_a_collection_and_a_concept_in_one_scheme(
        self,
    ):
        member = CollectionMemberFactory()
        assert isinstance(member, CollectionMember)
        assert member.pk is not None
        assert member.collection.scheme_id == member.concept.scheme_id
        assert member.concept in member.collection.members()


@pytest.mark.django_db
class TestCollectionWithMembers:
    def test_collection_with_members_helper_yields_a_populated_collection(self):
        collection, members = collection_with_members()
        assert set(collection.members()) == set(members)
        assert {c.scheme_id for c in members} == {collection.scheme_id}

    def test_collection_with_members_helper_builds_an_ordered_collection(self):
        collection, members = collection_with_members(ordered=True)
        assert collection.ordered is True
        assert list(collection.members()) == members
