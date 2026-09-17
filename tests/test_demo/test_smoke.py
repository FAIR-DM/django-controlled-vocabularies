"""Tests for ``demo/smoke.py``'s assertions (T017, FR-017, User Story 3 scenario 5).

``demo/smoke.py`` itself speaks real HTTP to a running server and is not run under pytest (its
own docstring; conventions, constitution Article VII). What is tested here is its assertion
logic — ``check_list`` and ``check_search`` — against a page Django's own in-process test client
renders, seeded through the real ``seed_demo`` command (T016): "the script's assertions are
exercised against a served page in-process, so a broken assertion fails here rather than only in
CI" (013-find-a-vocabulary task brief, T017). The failure it exists to catch is the one every
unit test passes through — a template that renders in a test client and not in a browser — so
every passing-case test below reads the same response the failing-case tests corrupt, rather
than a body built by hand.

There is no ``demo/smoke_test.py`` for this to mirror — the subject is the served page's shape,
not one module under ``controlled_vocabularies/`` — so this file is part of the
``tests/test_demo/`` non-mirror exception (``[tool.forge.conformance] non-mirror-paths``, T015).
"""

import pytest
from django.core.management import call_command
from django.urls import reverse

from controlled_vocabularies.models import ConceptScheme
from demo.management.commands.seed_demo import Command as SeedDemoCommand
from demo.smoke import (
    AUTHORED_CONCEPT_COUNT,
    HIDDEN_LABEL_SEARCH_TERM,
    IMPORTED_NAME,
    VOCABULARY_CONCEPT,
    SmokeCheckFailed,
    check_concept_search,
    check_list,
    check_search,
    check_vocabulary_page,
    extract_vocabulary_url,
)


@pytest.fixture
def seeded_list_response(client, db):
    call_command(SeedDemoCommand())
    list_url = reverse("controlled_vocabularies_ui:vocabulary-list")
    response = client.get(list_url)
    return list_url, response


class TestCheckList:
    """FR-016, User Story 3 scenario 2 — both seeded vocabularies are named and carry their
    concept counts."""

    def test_passes_against_the_real_seeded_list(self, seeded_list_response):
        list_url, response = seeded_list_response

        check_list(list_url, response.status_code, response.content.decode())

    def test_fails_when_a_seeded_vocabulary_did_not_load(self, seeded_list_response):
        list_url, response = seeded_list_response
        body = response.content.decode().replace(IMPORTED_NAME, "")

        with pytest.raises(SmokeCheckFailed, match="did not load"):
            check_list(list_url, response.status_code, body)

    def test_fails_when_a_concept_count_is_missing_from_the_page(
        self, seeded_list_response
    ):
        list_url, response = seeded_list_response
        body = response.content.decode().replace(
            f"{AUTHORED_CONCEPT_COUNT} concept", ""
        )

        with pytest.raises(SmokeCheckFailed, match="concept count"):
            check_list(list_url, response.status_code, body)

    def test_fails_on_a_non_200_status(self, seeded_list_response):
        list_url, response = seeded_list_response

        with pytest.raises(SmokeCheckFailed, match="did not serve"):
            check_list(list_url, 500, response.content.decode())


@pytest.mark.django_db
class TestCheckSearch:
    """User Story 3 scenario 5 — a search narrows the list to the vocabulary it matches."""

    def test_passes_when_a_search_narrows_to_one_vocabulary(self, client):
        call_command(SeedDemoCommand())
        search_url = reverse("controlled_vocabularies_ui:vocabulary-list") + "?q=DCMI"

        response = client.get(search_url)

        check_search(search_url, response.status_code, response.content.decode())

    def test_fails_when_the_search_does_not_narrow(self, client):
        # The unsearched list carries both names, so the "excludes the other vocabulary"
        # half of check_search is what this exercises.
        call_command(SeedDemoCommand())
        list_url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(list_url)

        with pytest.raises(SmokeCheckFailed, match="did not narrow"):
            check_search(list_url, response.status_code, response.content.decode())


class TestExtractVocabularyUrl:
    """The walk follows the list to a vocabulary's own page by reading the same rendered
    link a browser would (T017, User Story 3 scenario 1)."""

    def test_extracts_the_href_of_the_anchor_naming_the_vocabulary(self):
        body = '<a href="/browse/dcmi-type-vocabulary/">DCMI Type Vocabulary</a>'

        assert (
            extract_vocabulary_url(body, IMPORTED_NAME)
            == "/browse/dcmi-type-vocabulary/"
        )

    def test_fails_when_no_link_names_the_vocabulary(self):
        with pytest.raises(SmokeCheckFailed, match="no link"):
            extract_vocabulary_url("<p>Nothing here names it.</p>", IMPORTED_NAME)


@pytest.fixture
def seeded_vocabulary_page_response(client, db):
    call_command(SeedDemoCommand())
    slug = ConceptScheme.objects.get(name=IMPORTED_NAME).slug
    url = reverse("controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": slug})
    response = client.get(url)
    return url, response


class TestCheckVocabularyPage:
    """FR-019, User Story 3 scenario 1 — the vocabulary's own page lists a concept it
    actually holds."""

    def test_passes_against_the_real_seeded_page(self, seeded_vocabulary_page_response):
        url, response = seeded_vocabulary_page_response

        check_vocabulary_page(url, response.status_code, response.content.decode())

    def test_fails_when_the_seeded_concept_did_not_load(
        self, seeded_vocabulary_page_response
    ):
        url, response = seeded_vocabulary_page_response
        body = response.content.decode().replace(VOCABULARY_CONCEPT, "")

        with pytest.raises(SmokeCheckFailed, match="did not load"):
            check_vocabulary_page(url, response.status_code, body)

    def test_fails_on_a_non_200_status(self, seeded_vocabulary_page_response):
        url, response = seeded_vocabulary_page_response

        with pytest.raises(SmokeCheckFailed, match="did not serve"):
            check_vocabulary_page(url, 500, response.content.decode())


@pytest.mark.django_db
class TestCheckConceptSearch:
    """FR-019, User Story 3 scenarios 3, 9 — a search inside the vocabulary narrows to the
    concept it matches, including one found only through its hidden label."""

    def test_passes_when_a_search_by_hidden_label_narrows_to_one_concept(self, client):
        call_command(SeedDemoCommand())
        slug = ConceptScheme.objects.get(name=IMPORTED_NAME).slug
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": slug}
        )
        search_url = f"{detail_url}?q={HIDDEN_LABEL_SEARCH_TERM}"

        response = client.get(search_url)

        check_concept_search(
            search_url, response.status_code, response.content.decode()
        )

    def test_fails_when_the_search_does_not_narrow(self, client):
        # The unsearched page carries both concepts, so the "excludes the other concept"
        # half of check_concept_search is what this exercises.
        call_command(SeedDemoCommand())
        slug = ConceptScheme.objects.get(name=IMPORTED_NAME).slug
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": slug}
        )

        response = client.get(detail_url)

        with pytest.raises(SmokeCheckFailed, match="did not narrow"):
            check_concept_search(
                detail_url, response.status_code, response.content.decode()
            )

    def test_fails_when_the_matching_concept_did_not_load(self, client):
        call_command(SeedDemoCommand())
        slug = ConceptScheme.objects.get(name=IMPORTED_NAME).slug
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": slug}
        )
        search_url = f"{detail_url}?q={HIDDEN_LABEL_SEARCH_TERM}"

        response = client.get(search_url)
        body = response.content.decode().replace(VOCABULARY_CONCEPT, "")

        with pytest.raises(SmokeCheckFailed, match="does not narrow"):
            check_concept_search(search_url, response.status_code, body)
