"""US-4 — Ready-made test scaffolding (factories).

Covers the test factories that downstream stories build their fixtures on:
``ConceptSchemeFactory`` and ``ConceptFactory``. The factories must produce
valid, saved objects with derived slugs/URIs, ``ConceptFactory`` must
auto-create its owning scheme, and repeated calls must not collide on the
app-wide-unique scheme slug or the per-scheme-unique concept slug.

US-6 extends the family with ``ConceptLabelFactory`` and ``ConceptNoteFactory``
and a ``multilingual`` trait on ``ConceptFactory`` that hangs an en+de pair of
preferred labels and notes off a single concept in a couple of lines.
"""

import pytest

from controlled_vocabularies.models import (
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptScheme,
)
from tests.factories import (
    ConceptFactory,
    ConceptLabelFactory,
    ConceptNoteFactory,
    ConceptSchemeFactory,
)


@pytest.mark.django_db
def test_scheme_factory_produces_saved_valid_object():
    scheme = ConceptSchemeFactory()
    assert isinstance(scheme, ConceptScheme)
    assert scheme.pk is not None
    assert scheme.name
    assert scheme.slug
    assert scheme.uri == f"https://example.org/vocabularies/{scheme.slug}"


@pytest.mark.django_db
def test_concept_factory_produces_saved_valid_object():
    concept = ConceptFactory()
    assert isinstance(concept, Concept)
    assert concept.pk is not None
    assert concept.label
    assert concept.slug
    assert concept.uri == f"{concept.scheme.uri}/{concept.slug}"


@pytest.mark.django_db
def test_concept_factory_auto_creates_its_scheme():
    concept = ConceptFactory()
    assert concept.scheme is not None
    assert concept.scheme.pk is not None
    assert ConceptScheme.objects.filter(pk=concept.scheme.pk).exists()


@pytest.mark.django_db
def test_scheme_factory_sequence_avoids_slug_collisions():
    first = ConceptSchemeFactory()
    second = ConceptSchemeFactory()
    assert first.slug != second.slug
    assert ConceptScheme.objects.count() == 2


@pytest.mark.django_db
def test_concept_factory_repeated_calls_do_not_collide():
    # Each ConceptFactory() call mints a fresh scheme *and* a fresh label via
    # sequences, so a second call never trips the collision guards in save().
    first = ConceptFactory()
    second = ConceptFactory()
    assert first.slug != second.slug or first.scheme_id != second.scheme_id
    assert first.scheme_id != second.scheme_id
    assert Concept.objects.count() == 2


@pytest.mark.django_db
def test_concept_factory_accepts_an_explicit_scheme():
    scheme = ConceptSchemeFactory()
    concept = ConceptFactory(scheme=scheme)
    assert concept.scheme_id == scheme.pk


@pytest.mark.django_db
def test_concept_label_factory_produces_saved_valid_object():
    label = ConceptLabelFactory()
    assert isinstance(label, ConceptLabel)
    assert label.pk is not None
    assert label.concept_id is not None
    assert label.language
    assert label.kind == ConceptLabel.Kind.PREFERRED
    assert label.text


@pytest.mark.django_db
def test_concept_note_factory_produces_saved_valid_object():
    note = ConceptNoteFactory()
    assert isinstance(note, ConceptNote)
    assert note.pk is not None
    assert note.concept_id is not None
    assert note.language
    assert note.kind == ConceptNote.Kind.DEFINITION
    assert note.value


@pytest.mark.django_db
def test_concept_factory_has_no_extra_labels_or_notes_without_the_trait():
    # The trait is opt-in: a plain concept carries only its default-language
    # anchor label, no ConceptLabel/ConceptNote rows.
    concept = ConceptFactory()
    assert concept.labels.count() == 0
    assert concept.concept_notes.count() == 0


@pytest.mark.django_db
def test_multilingual_trait_yields_preferred_labels_in_more_than_one_language():
    concept = ConceptFactory(multilingual=True)
    # en is the scheme's effective default language, so its preferred label is
    # the anchor field itself; de is carried as a separate ConceptLabel row.
    default_pref = concept.preferred_label()
    german_pref = concept.preferred_label("de")
    assert default_pref
    assert german_pref
    assert default_pref != german_pref
    languages_with_a_preferred_label = {
        language for language in ("en", "de") if concept.preferred_label(language)
    }
    assert len(languages_with_a_preferred_label) > 1


@pytest.mark.django_db
def test_multilingual_trait_yields_notes_in_more_than_one_language():
    concept = ConceptFactory(multilingual=True)
    assert concept.notes("en")
    assert concept.notes("de")
    languages_with_a_note = {
        language for language in ("en", "de") if concept.notes(language)
    }
    assert len(languages_with_a_note) > 1


@pytest.mark.django_db
def test_multilingual_trait_uses_the_concepts_own_scheme_default_language():
    # The German preferred label sits on a real ConceptLabel row (not the anchor),
    # and the anchor still resolves as the en preferred label.
    concept = ConceptFactory(multilingual=True)
    assert concept.labels.filter(
        language="de", kind=ConceptLabel.Kind.PREFERRED
    ).exists()
    assert concept.preferred_label("en") == concept.label


# --- FS-003 US-4: relation scaffolding ---


@pytest.mark.django_db
def test_relation_factory_produces_a_broader_edge_navigable_both_ways():
    from controlled_vocabularies.models import ConceptRelation
    from tests.factories import ConceptRelationFactory

    relation = ConceptRelationFactory()
    assert isinstance(relation, ConceptRelation)
    assert relation.pk is not None
    assert relation.kind == ConceptRelation.Kind.BROADER
    # both endpoints share one vocabulary, and the edge reads both ways
    assert relation.source.scheme_id == relation.target.scheme_id
    assert relation.target in relation.source.broader()
    assert relation.source in relation.target.narrower()


@pytest.mark.django_db
def test_relation_factory_builds_a_single_related_association():
    from controlled_vocabularies.models import ConceptRelation
    from tests.factories import ConceptRelationFactory

    relation = ConceptRelationFactory(kind=ConceptRelation.Kind.RELATED)
    assert relation.source in relation.target.related()
    assert relation.target in relation.source.related()
    assert (
        ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count() == 1
    )


@pytest.mark.django_db
def test_relation_graph_helper_yields_a_navigable_graph():
    from tests.factories import relation_graph

    graph = relation_graph()
    assert graph["parent"] in graph["child"].broader()
    assert graph["child"] in graph["parent"].narrower()
    assert graph["right"] in graph["left"].related()
    # everything is in one vocabulary
    schemes = {
        c.scheme_id
        for c in (graph["parent"], graph["child"], graph["left"], graph["right"])
    }
    assert len(schemes) == 1


# --- FS-004 US-4: collection scaffolding ---


@pytest.mark.django_db
def test_collection_factory_produces_saved_valid_object():
    from controlled_vocabularies.models import Collection
    from tests.factories import CollectionFactory

    collection = CollectionFactory()
    assert isinstance(collection, Collection)
    assert collection.pk is not None
    assert collection.name
    assert collection.slug
    assert collection.ordered is False
    assert collection.uri == f"{collection.scheme.uri}/collection/{collection.slug}"


@pytest.mark.django_db
def test_collection_member_factory_joins_a_collection_and_a_concept_in_one_scheme():
    from controlled_vocabularies.models import CollectionMember
    from tests.factories import CollectionMemberFactory

    member = CollectionMemberFactory()
    assert isinstance(member, CollectionMember)
    assert member.pk is not None
    # both ends share one vocabulary — the cross-vocabulary guard never trips
    assert member.collection.scheme_id == member.concept.scheme_id
    assert member.concept in member.collection.members()


@pytest.mark.django_db
def test_collection_with_members_helper_yields_a_populated_collection():
    from tests.factories import collection_with_members

    collection, members = collection_with_members()
    assert set(collection.members()) == set(members)
    # every member is in the collection's own vocabulary
    assert {c.scheme_id for c in members} == {collection.scheme_id}


@pytest.mark.django_db
def test_collection_with_members_helper_builds_an_ordered_collection():
    from tests.factories import collection_with_members

    collection, members = collection_with_members(ordered=True)
    assert collection.ordered is True
    assert list(collection.members()) == members


class TestExternalTrait:
    """FS-005 US-5 — the ``external`` trait produces a record carrying a fixed,
    plausible externally assigned ``static_uri``, opt-in like ``multilingual``,
    on each of ``ConceptSchemeFactory``, ``ConceptFactory``, and
    ``CollectionFactory``. Without the trait, each factory stays provisional.
    """

    @pytest.mark.django_db
    def test_scheme_factory_without_the_trait_is_provisional(self):
        scheme = ConceptSchemeFactory()
        assert scheme.static_uri is None
        assert scheme.has_static_uri is False

    @pytest.mark.django_db
    def test_scheme_factory_external_trait_yields_a_fixed_externally_assigned_uri(self):
        scheme = ConceptSchemeFactory(external=True)
        assert scheme.has_static_uri is True
        assert scheme.static_uri
        assert scheme.uri == scheme.static_uri

    @pytest.mark.django_db
    def test_concept_factory_without_the_trait_is_provisional(self):
        concept = ConceptFactory()
        assert concept.static_uri is None
        assert concept.has_static_uri is False

    @pytest.mark.django_db
    def test_concept_factory_external_trait_yields_a_fixed_externally_assigned_uri(
        self,
    ):
        concept = ConceptFactory(external=True)
        assert concept.has_static_uri is True
        assert concept.uri == concept.static_uri
        # the concept's own identifier, independent of its (here, provisional) scheme
        assert concept.scheme.has_static_uri is False

    @pytest.mark.django_db
    def test_collection_factory_without_the_trait_is_provisional(self):
        from tests.factories import CollectionFactory

        collection = CollectionFactory()
        assert collection.static_uri is None
        assert collection.has_static_uri is False

    @pytest.mark.django_db
    def test_collection_factory_external_trait_yields_a_fixed_externally_assigned_uri(
        self,
    ):
        from tests.factories import CollectionFactory

        collection = CollectionFactory(external=True)
        assert collection.has_static_uri is True
        assert collection.uri == collection.static_uri
