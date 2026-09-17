"""Tests for :mod:`controlled_vocabularies.ui.urls` (T006, FR-012; T001; 015-read-single-record
T000)."""

from urllib.parse import unquote, urlparse

import pytest
from django.urls import reverse

from tests.factories import CollectionFactory, ConceptFactory, ConceptSchemeFactory


class TestVocabularyListUrl:
    """The route reverses by name, under its own namespace and the project's chosen prefix."""

    def test_reverses_by_name_under_its_own_namespace(self):
        assert reverse("controlled_vocabularies_ui:vocabulary-list") == "/vocabularies/"


class TestVocabularyDetailUrl:
    """The detail route reverses by name and slug, mounted after the list route."""

    def test_reverses_by_name_and_slug(self):
        assert (
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": "geology"},
            )
            == "/vocabularies/geology/"
        )


class TestConceptDetailUrl:
    """A concept's address reverses to what ``local_url`` composes, and resolves the record
    named in it — 015-read-single-record T000, FR-001, FR-002.
    """

    @pytest.mark.django_db
    def test_reverses_to_the_address_local_url_composes(self):
        concept = ConceptFactory(label="Granite")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # local_url carries the configured base address (scheme + host); reverse() gives
        # only the path django-mvp's own trailing slash convention adds. Comparing paths,
        # the way controlled_vocabularies.ui.W001 already does for the vocabulary route,
        # is what "exactly the address local_url composes" means here.
        assert url.rstrip("/") == urlparse(concept.local_url).path

    @pytest.mark.django_db
    def test_a_concept_slugged_in_a_non_latin_script_reverses_the_same_way(self):
        concept = ConceptFactory(label="地質時代")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # reverse() percent-encodes the non-ASCII segment; local_url does not, so the
        # comparison unquotes the reversed path rather than the other way round — the
        # slug itself, not its encoded form, is what local_url and the route agree on.
        assert unquote(url).rstrip("/") == urlparse(concept.local_url).path

    @pytest.mark.django_db
    def test_a_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        scheme_a = ConceptSchemeFactory()
        scheme_b = ConceptSchemeFactory()
        concept_a = ConceptFactory(scheme=scheme_a, label="Granite")
        concept_b = ConceptFactory(scheme=scheme_b, label="Granite")
        assert concept_a.slug == concept_b.slug

        response_a = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": scheme_a.slug, "concept_slug": concept_a.slug},
            )
        )
        response_b = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": scheme_b.slug, "concept_slug": concept_b.slug},
            )
        )

        assert response_a.status_code == 200
        assert response_a.context["object"] == concept_a
        assert response_b.status_code == 200
        assert response_b.context["object"] == concept_b

    @pytest.mark.django_db
    def test_an_address_whose_vocabulary_segment_names_nothing_returns_404(
        self, client
    ):
        concept = ConceptFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": "no-such-vocabulary", "concept_slug": concept.slug},
            )
        )

        assert response.status_code == 404


class TestCollectionDetailUrl:
    """A collection's address reverses to what ``local_url`` composes, and resolves the
    record named in it — 015-read-single-record T000, FR-001, FR-002.
    """

    @pytest.mark.django_db
    def test_reverses_to_the_address_local_url_composes(self):
        collection = CollectionFactory(name="Igneous Rocks")

        url = reverse(
            "controlled_vocabularies_ui:collection-detail",
            kwargs={"slug": collection.scheme.slug, "collection_slug": collection.slug},
        )

        assert url.rstrip("/") == urlparse(collection.local_url).path

    @pytest.mark.django_db
    def test_a_collection_slugged_in_a_non_latin_script_reverses_the_same_way(self):
        collection = CollectionFactory(name="火成岩")

        url = reverse(
            "controlled_vocabularies_ui:collection-detail",
            kwargs={"slug": collection.scheme.slug, "collection_slug": collection.slug},
        )

        assert unquote(url).rstrip("/") == urlparse(collection.local_url).path

    @pytest.mark.django_db
    def test_a_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        scheme_a = ConceptSchemeFactory()
        scheme_b = ConceptSchemeFactory()
        collection_a = CollectionFactory(scheme=scheme_a, name="Igneous Rocks")
        collection_b = CollectionFactory(scheme=scheme_b, name="Igneous Rocks")
        assert collection_a.slug == collection_b.slug

        response_a = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": scheme_a.slug, "collection_slug": collection_a.slug},
            )
        )
        response_b = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": scheme_b.slug, "collection_slug": collection_b.slug},
            )
        )

        assert response_a.status_code == 200
        assert response_a.context["object"] == collection_a
        assert response_b.status_code == 200
        assert response_b.context["object"] == collection_b

    @pytest.mark.django_db
    def test_an_address_whose_vocabulary_segment_names_nothing_returns_404(
        self, client
    ):
        collection = CollectionFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": "no-such-vocabulary",
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.status_code == 404
