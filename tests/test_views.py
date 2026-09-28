"""Tests for controlled_vocabularies.views."""

import inspect
import json
from pathlib import Path

import pytest
from django import forms
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
from django_tomselect.middleware import TomSelectMiddleware

from controlled_vocabularies import views as views_module
from controlled_vocabularies.views import ConceptAutocompleteView
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
    collection_with_members,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import Borehole, CoreSample, Sketch, Specimen


def _field_reference(model, field_name):
    """Return the ``<app_label>.<model>.<field_name>`` reference the widget sends.

    Args:
        model: The model class declaring the field.
        field_name: The name of the concept field on ``model``.

    Returns:
        The dotted reference the endpoint resolves through the app registry.
    """
    return f"{model._meta.app_label}.{model._meta.model_name}.{field_name}"


def _unrestricted_get(**params):
    """Search from ``Sketch.subject``, the one declaration that restricts nothing.

    Args:
        **params: Extra query parameters sent with the ``field`` reference.

    Returns:
        The endpoint's response.
    """
    return Client().get(
        reverse("controlled_vocabularies:concept-autocomplete"),
        {"field": _field_reference(Sketch, "subject"), **params},
    )


class SpecimenForm(forms.ModelForm):
    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


class TestConceptAutocompleteResults:
    @pytest.mark.django_db
    def test_a_result_carries_exactly_the_id_display_label_and_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Rock types")
        concept = ConceptFactory(scheme=scheme, label="Granite")
        concept.add_note(language="en", kind="definition", value="An igneous rock.")
        concept.add_label(language="en", kind="alternative", text="granitic rock")
        concept.add_label(language="en", kind="hidden", text="granit")

        response = _unrestricted_get()

        body = json.loads(response.content)
        assert len(body["results"]) == 1
        result = body["results"][0]
        assert set(result.keys()) == {"id", "display_label", "vocabulary"}
        assert result["id"] == concept.pk
        assert result["display_label"] == "Granite"
        assert result["vocabulary"] == "Rock types"

    @pytest.mark.django_db
    def test_a_full_page_of_concepts_costs_the_same_queries_as_one_concept(
        self, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme)
        concept.add_label(language="de", kind="alternative", text="alt")
        concept.add_note(language="en", kind="definition", value="A definition.")
        with CaptureQueriesContext(connection) as one_concept:
            _unrestricted_get()

        for _ in range(19):
            concept = ConceptFactory(scheme=scheme)
            concept.add_label(language="de", kind="alternative", text="alt")
            concept.add_note(language="en", kind="definition", value="A definition.")

        with django_assert_num_queries(len(one_concept)):
            response = _unrestricted_get()

        body = json.loads(response.content)
        assert len(body["results"]) == 20


# Each search fragment must match through one clause only: a fragment that is also a
# substring of the default-language ``label`` passes whichever label kind is under test.
class TestConceptAutocompleteSearch:
    @pytest.mark.django_db
    def test_a_fragment_of_an_alternative_label_finds_the_concept_by_its_preferred_label(
        self,
    ):
        concept = ConceptFactory(label="Granite")
        concept.add_label(language="en", kind="alternative", text="granitic rock")
        ConceptFactory(label="Basalt")

        response = _unrestricted_get(q="granitic")

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]
        assert body["results"][0]["display_label"] == "Granite"

    @pytest.mark.django_db
    def test_a_fragment_of_a_hidden_label_finds_the_concept_by_its_preferred_label(
        self,
    ):
        concept = ConceptFactory(label="Granite")
        concept.add_label(language="en", kind="hidden", text="granyte")
        ConceptFactory(label="Basalt")

        response = _unrestricted_get(q="granyte")

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]
        assert body["results"][0]["display_label"] == "Granite"

    @pytest.mark.django_db
    def test_a_fragment_of_either_the_active_or_default_language_preferred_label_finds_the_concept_by_the_active_one(
        self,
    ):
        concept = ConceptFactory(
            label="Granite", multilingual=True, german_label__text="Granitgestein"
        )
        ConceptFactory(label="Basalt", multilingual=True, german_label__text="Basalt")

        with translation.override("de"):
            by_active_language = _unrestricted_get(q="gestein")
            by_default_language = _unrestricted_get(q="Granite")

        for response in (by_active_language, by_default_language):
            body = json.loads(response.content)
            assert [result["id"] for result in body["results"]] == [concept.pk]
            assert body["results"][0]["display_label"] == "Granitgestein"

    @pytest.mark.django_db
    def test_a_concept_with_no_active_language_labels_is_found_and_shown_by_its_default_label(
        self,
    ):
        concept = ConceptFactory(label="Granite")
        ConceptFactory(label="Basalt")

        with translation.override("de"):
            response = _unrestricted_get(q="Granite")

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]
        assert body["results"][0]["display_label"] == "Granite"

    @pytest.mark.django_db
    def test_a_label_in_another_language_does_not_match(self):
        # Without this, dropping the language constraint from the filter
        # altogether leaves every other test in this class green.
        concept = ConceptFactory(label="Granite")
        concept.add_label(language="de", kind="alternative", text="Tiefengestein")

        response = _unrestricted_get(q="Tiefengestein")

        body = json.loads(response.content)
        assert body["results"] == []

        with translation.override("de"):
            in_its_own_language = _unrestricted_get(q="Tiefengestein")

        body = json.loads(in_its_own_language.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]

    @pytest.mark.django_db
    def test_a_concept_matching_on_two_of_its_labels_appears_once(self):
        concept = ConceptFactory(label="Granite")
        concept.add_label(language="en", kind="alternative", text="Granite rock")
        concept.add_label(language="en", kind="hidden", text="Granites")
        ConceptFactory(label="Basalt")

        response = _unrestricted_get(q="Granit")

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]

    @pytest.mark.django_db
    def test_a_search_differing_only_in_case_from_a_label_still_matches(self):
        concept = ConceptFactory(label="Granite")
        ConceptFactory(label="Basalt")

        response = _unrestricted_get(q="GRANITE")

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [concept.pk]
        assert body["results"][0]["display_label"] == "Granite"


@pytest.mark.django_db
class TestConceptAutocompleteRestrictionFromDeclaration:
    def test_a_field_declared_against_one_vocabulary_returns_only_that_vocabularys_concepts(
        self,
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        fossil_scheme = ConceptSchemeFactory(name="Fossil")
        rock_concept = ConceptFactory(scheme=rock_scheme, label="Granite rock")
        ConceptFactory(scheme=mineral_scheme, label="Granite ore")
        ConceptFactory(scheme=fossil_scheme, label="Granite fossil")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Granite", "field": _field_reference(Specimen, "rock_type")},
        )

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [rock_concept.pk]

    def test_the_request_naming_a_different_vocabulary_directly_is_ignored(self):
        rock_scheme = ConceptSchemeFactory(name="Rock type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        rock_concept = ConceptFactory(scheme=rock_scheme, label="Granite rock")
        ConceptFactory(scheme=mineral_scheme, label="Granite ore")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {
                "q": "Granite",
                "field": _field_reference(Specimen, "rock_type"),
                # A parameter the endpoint never reads: the restriction comes
                # from the declaration alone.
                "vocabulary": mineral_scheme.slug,
            },
        )

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [rock_concept.pk]

    def test_a_field_declared_against_several_vocabularies_returns_exactly_those(self):
        rock_scheme = ConceptSchemeFactory(name="Rock type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        fossil_scheme = ConceptSchemeFactory(name="Fossil")
        rock_concept = ConceptFactory(scheme=rock_scheme, label="Basalt rock")
        mineral_concept = ConceptFactory(scheme=mineral_scheme, label="Basalt ore")
        ConceptFactory(scheme=fossil_scheme, label="Basalt fossil")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Basalt", "field": _field_reference(Borehole, "dominant_material")},
        )

        body = json.loads(response.content)
        assert {result["id"] for result in body["results"]} == {
            rock_concept.pk,
            mineral_concept.pk,
        }

    def test_a_field_declared_against_no_vocabulary_makes_every_concept_eligible(self):
        rock_scheme = ConceptSchemeFactory(name="Rock type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        fossil_scheme = ConceptSchemeFactory(name="Fossil")
        rock_concept = ConceptFactory(scheme=rock_scheme, label="Quartz rock")
        mineral_concept = ConceptFactory(scheme=mineral_scheme, label="Quartz ore")
        fossil_concept = ConceptFactory(scheme=fossil_scheme, label="Quartz fossil")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Quartz", "field": _field_reference(Sketch, "subject")},
        )

        body = json.loads(response.content)
        assert {result["id"] for result in body["results"]} == {
            rock_concept.pk,
            mineral_concept.pk,
            fossil_concept.pk,
        }

    def test_the_rendered_widget_carries_the_reference(self):
        # autocompleteParams only builds with the live request TomSelectMiddleware
        # stores; a bare `str(SpecimenForm())` carries no reference and would pass
        # the assertion below vacuously.
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        rendered = {}

        def get_response(inner_request):
            rendered["html"] = str(SpecimenForm())
            return HttpResponse()

        TomSelectMiddleware(get_response)(request)

        # The template runs autocompleteParams through `escapejs`, which turns "="
        # into the six characters backslash-u-0-0-3-D.
        escaped_equals = "\\u003D"
        assert (
            f"autocompleteParams: 'field{escaped_equals}testapp.specimen.rock_type'"
            in rendered["html"]
        )


@pytest.mark.django_db
class TestConceptAutocompleteRefusalDisclosesNothing:
    def _get(self, **params):
        return Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"), params
        )

    def test_four_unresolvable_references_and_a_true_empty_search_are_byte_identical(
        self,
    ):
        baseline = self._get(field=_field_reference(Specimen, "rock_type"))
        assert baseline.status_code == 200

        naming_a_model_that_does_not_exist = self._get(
            field="testapp.nosuchmodel.rock_type"
        )
        naming_a_field_that_is_not_one_of_this_packages = self._get(
            field="testapp.specimen.name"
        )
        naming_a_field_that_does_not_exist = self._get(
            field="testapp.specimen.no_such_field"
        )
        with_no_reference_at_all = self._get()

        for response in (
            naming_a_model_that_does_not_exist,
            naming_a_field_that_is_not_one_of_this_packages,
            naming_a_field_that_does_not_exist,
            with_no_reference_at_all,
        ):
            assert response.status_code == 200
            assert response.content == baseline.content


@pytest.mark.django_db
class TestConceptAutocompletePagination:
    def test_a_search_matching_more_than_one_page_returns_one_page_and_says_more_exist(
        self,
    ):
        for i in range(25):
            ConceptFactory(label=f"Quartz {i:02d}")

        response = _unrestricted_get(q="Quartz")

        body = json.loads(response.content)
        assert len(body["results"]) == 20
        assert body["has_more"] is True

    def test_the_following_page_returns_the_rest_with_none_repeated_and_none_skipped(
        self,
    ):
        concepts = [ConceptFactory(label=f"Quartz {i:02d}") for i in range(25)]
        full_match_set = {concept.pk for concept in concepts}

        first_page = _unrestricted_get(q="Quartz")
        second_page = _unrestricted_get(q="Quartz", p=2)

        first_ids = [
            result["id"] for result in json.loads(first_page.content)["results"]
        ]
        second_ids = [
            result["id"] for result in json.loads(second_page.content)["results"]
        ]

        # Collected from both pages and compared against the full ordered
        # match set, not page lengths: a repeat shrinks the union below the
        # combined count, a skip shrinks the union below the full set.
        assert set(first_ids) | set(second_ids) == full_match_set
        assert len(first_ids) + len(second_ids) == len(full_match_set)
        assert json.loads(second_page.content)["has_more"] is False

    def test_opening_with_nothing_typed_offers_a_first_page_in_a_stable_order(self):
        concepts = [
            ConceptFactory(label=label) for label in ["Charlie", "Alpha", "Bravo"]
        ]
        expected_order = sorted(
            concepts, key=lambda concept: (concept.label, concept.pk)
        )

        response = _unrestricted_get()

        body = json.loads(response.content)
        assert [result["id"] for result in body["results"]] == [
            concept.pk for concept in expected_order
        ]

    def test_a_page_past_the_last_returns_nothing_and_says_no_more_exist(self):
        # The inherited behaviour re-serves page 1 for a page past the last.
        ConceptFactory(label="Granite")

        response = _unrestricted_get(p=5)

        body = json.loads(response.content)
        assert body["results"] == []
        assert body["has_more"] is False

    def test_a_request_asking_for_more_than_max_page_size_is_clamped(self):
        for i in range(205):
            ConceptFactory(label=f"Quartz {i:03d}")

        response = _unrestricted_get(q="Quartz", page_size=1000)

        body = json.loads(response.content)
        assert len(body["results"]) == 200

    def test_a_field_naming_no_vocabulary_is_bounded_the_same_way_across_several_vocabularies(
        self,
    ):
        for scheme_index in range(3):
            scheme = ConceptSchemeFactory()
            for i in range(10):
                ConceptFactory(scheme=scheme, label=f"Quartz {scheme_index}-{i:02d}")

        # Sketch.subject (via _unrestricted_get) names no vocabulary, so all
        # 30 concepts across the three schemes are eligible.
        response = _unrestricted_get(q="Quartz")

        body = json.loads(response.content)
        assert len(body["results"]) == 20
        assert body["has_more"] is True

    def test_the_ordering_breaks_ties_with_pk_so_identically_labelled_concepts_stay_stable(
        self,
    ):
        # Concept.label is unique only within a scheme, so ties are possible. SQLite
        # returns tied rows in insertion order, which masks a missing "pk" tie-break
        # in any paging test, so the declared ordering is asserted directly.
        assert ConceptAutocompleteView.ordering == ("label", "pk")

    def test_both_ordering_columns_reach_the_database(self):
        # Asserted on the SQL issued: a declared-but-unapplied ordering would pass the
        # test above while sorting by nothing in particular.
        for name in ("Mineral", "Rock Type", "Lithology"):
            ConceptFactory(scheme=ConceptSchemeFactory(name=name), label="Tied label")

        with CaptureQueriesContext(connection) as ctx:
            _unrestricted_get(q="Tied")

        selects = [q["sql"] for q in ctx.captured_queries if "ORDER BY" in q["sql"]]
        assert selects, [q["sql"] for q in ctx.captured_queries]
        order_by = selects[0].split("ORDER BY", 1)[1]
        assert '"label" ASC' in order_by
        assert order_by.index('"label" ASC') < order_by.index('"id" ASC')


@pytest.mark.django_db
class TestConceptAutocompleteRequestControlledSurfacesAreClosed:
    def test_a_blocked_filter_field_empties_the_page(self):
        ConceptFactory(label="Granite")
        reference = _field_reference(
            Sketch, "subject"
        )  # unrestricted: nothing to hide the guard behind

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": reference, "f": "x__label=Granite"},
        )

        body = json.loads(response.content)
        assert body["results"] == []

    def test_a_blocked_ordering_parameter_leaves_the_views_own_order_in_place(self):
        ConceptFactory(label="Basalt")
        ConceptFactory(label="Granite")
        reference = _field_reference(
            Sketch, "subject"
        )  # unrestricted: nothing to hide the guard behind

        default = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": reference},
        )
        with_ordering = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": reference, "ordering": "-label"},
        )

        default_ids = [
            result["id"] for result in json.loads(default.content)["results"]
        ]
        ordered_ids = [
            result["id"] for result in json.loads(with_ordering.content)["results"]
        ]
        assert default_ids  # the guard is being tested against real, non-empty results
        assert ordered_ids == default_ids


@pytest.mark.django_db
class TestConceptAutocompleteOrderedCollectionSequence:
    def _get(self, **params):
        return Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": _field_reference(CoreSample, "rock_type"), **params},
        )

    def test_an_ordered_collections_sequence_differs_from_both_alphabetical_and_creation_order(
        self,
    ):
        # The curator's sequence is neither alphabetical nor creation order, so a
        # missing override or an accidental default both fail this.
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo", "Alpha", "Charlie"),
        )
        bravo, alpha, charlie = members
        collection.set_member_order([charlie, bravo, alpha])

        body = json.loads(self._get().content)

        assert [result["id"] for result in body["results"]] == [
            charlie.pk,
            bravo.pk,
            alpha.pk,
        ]

    def test_a_position_change_is_reflected_on_the_next_read(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo", "Alpha", "Charlie"),
        )
        bravo, alpha, charlie = members
        collection.set_member_order([charlie, bravo, alpha])
        first_read = json.loads(self._get().content)
        assert [result["id"] for result in first_read["results"]] == [
            charlie.pk,
            bravo.pk,
            alpha.pk,
        ]

        collection.set_member_order([alpha, charlie, bravo])

        second_read = json.loads(self._get().content)
        assert [result["id"] for result in second_read["results"]] == [
            alpha.pk,
            charlie.pk,
            bravo.pk,
        ]

    def test_a_typed_search_term_returns_to_relevance_order(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo Basalt", "Alpha Basalt", "Charlie Basalt"),
        )
        bravo, alpha, charlie = members
        collection.set_member_order([charlie, bravo, alpha])

        body = json.loads(self._get(q="Basalt").content)

        # A search term falls back to the inherited ("label", "pk") ordering.
        assert [result["id"] for result in body["results"]] == [
            alpha.pk,
            bravo.pk,
            charlie.pk,
        ]

    def test_an_unordered_collection_stays_restricted_with_no_sequence_promised(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=False,
            labels=("Charlie", "Bravo", "Alpha"),
        )
        charlie, bravo, alpha = members
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        body = json.loads(self._get().content)

        returned_ids = [result["id"] for result in body["results"]]
        assert set(returned_ids) == {charlie.pk, bravo.pk, alpha.pk}
        assert outsider.pk not in returned_ids
        # An unordered collection promises no sequence and gets the inherited ordering.
        assert returned_ids == [alpha.pk, bravo.pk, charlie.pk]

    def test_a_removed_member_leaves_the_survivors_in_relative_order(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo", "Alpha", "Charlie", "Delta"),
        )
        bravo, alpha, charlie, delta = members
        collection.set_member_order([delta, bravo, charlie, alpha])
        collection.remove(bravo)

        body = json.loads(self._get().content)

        assert [result["id"] for result in body["results"]] == [
            delta.pk,
            charlie.pk,
            alpha.pk,
        ]

    def test_a_concept_in_a_second_collection_too_is_not_duplicated(self):
        # A concept in a second collection must not duplicate through a
        # collection_memberships__ join.
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme, name="core-samples", ordered=True, labels=("Bravo", "Alpha")
        )
        bravo, alpha = members
        collection.set_member_order([alpha, bravo])
        other_collection = CollectionFactory(scheme=scheme, name="Display Samples")
        other_collection.add(bravo)

        body = json.loads(self._get().content)

        ids = [result["id"] for result in body["results"]]
        assert len(ids) == len(set(ids))
        assert set(ids) == {alpha.pk, bravo.pk}


class TestViewsI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(views_module)).read_text()
        visitor = visit_fields_checks_source(source)
        assert visitor.bare_literals == [], (
            f"{views_module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{views_module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
