"""Tests for controlled_vocabularies.ui.urls."""

from urllib.parse import unquote, urlparse

import pytest
from django.urls import reverse

from tests.factories import CollectionFactory, ConceptFactory, ConceptSchemeFactory


class TestVocabularyListUrl:
    def test_reverses_by_name_under_its_own_namespace(self):
        assert reverse("controlled_vocabularies_ui:vocabulary-list") == "/vocabularies/"


class TestVocabularyDetailUrl:
    def test_reverses_by_name_and_slug(self):
        assert (
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": "geology"},
            )
            == "/vocabularies/geology/"
        )


class TestConceptDetailUrl:
    @pytest.mark.django_db
    def test_reverses_to_the_address_local_url_composes(self):
        concept = ConceptFactory(label="Granite")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # local_url carries the base address's scheme and host and no trailing slash, so
        # compare paths.
        assert url.rstrip("/") == urlparse(concept.local_url).path

    @pytest.mark.django_db
    def test_a_concept_slugged_in_a_non_latin_script_reverses_the_same_way(self):
        concept = ConceptFactory(label="地質時代")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # reverse() percent-encodes the non-ASCII segment and local_url does not.
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
