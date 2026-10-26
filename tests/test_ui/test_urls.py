"""Tests for controlled_vocabularies.ui.urls."""

from urllib.parse import unquote, urlparse

import pytest
from django.urls import reverse

from controlled_vocabularies.models import Record
from tests.factories import ConceptSchemeFactory, RecordFactory


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
    def test_reverses_to_the_path_of_the_identifier_this_site_mints(self):
        concept = RecordFactory(label="Granite")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # The identifier carries the base address's scheme and host and no trailing
        # slash, so compare paths.
        assert url.rstrip("/") == urlparse(concept.uri).path

    @pytest.mark.django_db
    def test_a_concept_slugged_in_a_non_latin_script_reverses_the_same_way(self):
        concept = RecordFactory(label="地質時代")

        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        # reverse() percent-encodes the non-ASCII segment and the identifier does not.
        assert unquote(url).rstrip("/") == urlparse(concept.uri).path

    @pytest.mark.django_db
    def test_a_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        scheme_a = ConceptSchemeFactory()
        scheme_b = ConceptSchemeFactory()
        concept_a = RecordFactory(scheme=scheme_a, label="Granite")
        concept_b = RecordFactory(scheme=scheme_b, label="Granite")
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
        concept = RecordFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": "no-such-vocabulary", "concept_slug": concept.slug},
            )
        )

        assert response.status_code == 404


class TestCollectionDetailUrl:
    @pytest.mark.django_db
    def test_a_collection_slugged_in_a_non_latin_script_still_serves_its_page(
        self, client
    ):
        collection = RecordFactory(label="火成岩", type=Record.Type.COLLECTION)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.status_code == 200
        assert response.context["object"] == collection

    @pytest.mark.django_db
    def test_a_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        scheme_a = ConceptSchemeFactory()
        scheme_b = ConceptSchemeFactory()
        collection_a = RecordFactory(
            scheme=scheme_a, label="Igneous Rocks", type=Record.Type.COLLECTION
        )
        collection_b = RecordFactory(
            scheme=scheme_b, label="Igneous Rocks", type=Record.Type.COLLECTION
        )
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
        collection = RecordFactory(type=Record.Type.COLLECTION)

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
