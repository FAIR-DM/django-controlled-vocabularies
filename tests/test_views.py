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
from tests.factories import (
    ConceptSchemeFactory,
    RecordFactory,
    collection_with_members,
    labelled,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import Borehole, CoreSample, Sketch, Specimen


def field_reference(model, field_name):
    """Return the ``<app_label>.<model>.<field_name>`` reference the widget sends.

    Args:
        model: The model class declaring the field.
        field_name: The name of the concept field on ``model``.

    Returns:
        The dotted reference the endpoint resolves through the app registry.
    """
    return f"{model._meta.app_label}.{model._meta.model_name}.{field_name}"


def unrestricted_get(**params):
    """Search from ``Sketch.subject``, the one declaration that restricts no vocabulary.

    Args:
        **params: Extra query parameters sent with the ``field`` reference.

    Returns:
        The endpoint's response.
    """
    return Client().get(
        reverse("controlled_vocabularies:concept-autocomplete"),
        {"field": field_reference(Sketch, "subject"), **params},
    )


def result_uris(response):
    """Return the URIs of a response's results, in the order served.

    Args:
        response: The endpoint's response.

    Returns:
        The list of URIs.
    """
    return [result["uri"] for result in json.loads(response.content)["results"]]


def reorder(collection, *members):
    """Replace an ordered collection's sequence and save it.

    Args:
        collection: The ordered collection.
        *members: The members it lists afterwards, in sequence.
    """
    collection.data["skos:memberList"] = [{"@id": member.uri} for member in members]
    collection.save()


class SpecimenForm(forms.ModelForm):
    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


class TestConceptAutocompleteResults:
    @pytest.mark.django_db
    def test_a_result_carries_exactly_the_id_display_label_and_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Rock types")
        concept = RecordFactory(
            scheme=scheme,
            data=labelled(
                "Granite",
                statements={
                    "skos:definition": [{"@value": "An igneous rock."}],
                    "skos:altLabel": [{"@value": "granitic rock", "@language": "en"}],
                    "skos:hiddenLabel": [{"@value": "granit", "@language": "en"}],
                },
            ),
        )

        response = unrestricted_get()

        body = json.loads(response.content)
        assert len(body["results"]) == 1
        result = body["results"][0]
        assert set(result.keys()) == {"uri", "display_label", "vocabulary"}
        assert result["uri"] == concept.uri
        assert result["display_label"] == "Granite"
        assert result["vocabulary"] == "Rock types"

    @pytest.mark.django_db
    def test_a_full_page_of_concepts_costs_the_same_queries_as_one_concept(
        self, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        statements = {
            "skos:altLabel": [{"@value": "alt", "@language": "de"}],
            "skos:definition": [{"@value": "A definition.", "@language": "en"}],
        }
        RecordFactory(scheme=scheme, data=labelled("Concept 0", statements=statements))
        with CaptureQueriesContext(connection) as one_concept:
            unrestricted_get()

        for i in range(1, 20):
            RecordFactory(
                scheme=scheme, data=labelled(f"Concept {i}", statements=statements)
            )

        with django_assert_num_queries(len(one_concept)):
            response = unrestricted_get()

        body = json.loads(response.content)
        assert len(body["results"]) == 20


@pytest.mark.django_db
class TestConceptAutocompleteSearch:
    def test_a_fragment_of_an_alternative_label_finds_the_concept_by_its_preferred_label(
        self,
    ):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:altLabel": [{"@value": "granitic rock", "@language": "en"}]
                },
            )
        )
        RecordFactory(label="Basalt")

        response = unrestricted_get(q="granitic")

        assert result_uris(response) == [concept.uri]
        assert json.loads(response.content)["results"][0]["display_label"] == "Granite"

    def test_a_fragment_of_a_hidden_label_finds_the_concept_by_its_preferred_label(
        self,
    ):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:hiddenLabel": [{"@value": "granyte", "@language": "en"}]
                },
            )
        )
        RecordFactory(label="Basalt")

        response = unrestricted_get(q="granyte")

        assert result_uris(response) == [concept.uri]
        assert json.loads(response.content)["results"][0]["display_label"] == "Granite"

    def test_a_fragment_of_a_preferred_label_in_any_language_finds_the_concept(
        self,
    ):
        concept = RecordFactory(
            data={
                "skos:prefLabel": [
                    {"@value": "Granite", "@language": "en"},
                    {"@value": "Granitgestein", "@language": "de"},
                ]
            }
        )
        RecordFactory(label="Basalt")

        with translation.override("de"):
            by_german = unrestricted_get(q="gestein")
            by_english = unrestricted_get(q="Granite")

        for response in (by_german, by_english):
            assert result_uris(response) == [concept.uri]
            result = json.loads(response.content)["results"][0]
            assert result["display_label"] == "Granitgestein"

    def test_a_concept_with_no_active_language_label_is_found_by_its_default_label(
        self,
    ):
        concept = RecordFactory(label="Granite")
        RecordFactory(label="Basalt")

        with translation.override("de"):
            response = unrestricted_get(q="Granite")

        assert result_uris(response) == [concept.uri]
        assert json.loads(response.content)["results"][0]["display_label"] == "Granite"

    def test_a_label_in_another_language_finds_the_concept_in_every_active_language(
        self,
    ):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:altLabel": [{"@value": "Tiefengestein", "@language": "de"}]
                },
            )
        )
        RecordFactory(label="Basalt")

        in_english = unrestricted_get(q="Tiefengestein")
        with translation.override("de"):
            in_german = unrestricted_get(q="Tiefengestein")

        assert result_uris(in_english) == [concept.uri]
        assert result_uris(in_german) == [concept.uri]

    def test_a_search_differing_only_in_case_from_a_label_still_matches(self):
        concept = RecordFactory(label="Granite")
        RecordFactory(label="Basalt")

        response = unrestricted_get(q="GRANITE")

        assert result_uris(response) == [concept.uri]
        assert json.loads(response.content)["results"][0]["display_label"] == "Granite"

    def test_a_collection_is_never_offered(self):
        concept = RecordFactory(label="Granite")
        collection, members = collection_with_members(
            scheme=concept.scheme, name="Granite samples", labels=()
        )

        response = unrestricted_get(q="Granite")

        assert result_uris(response) == [concept.uri]
        assert collection.uri not in result_uris(response)


@pytest.mark.django_db
class TestConceptAutocompleteRestrictionFromDeclaration:
    def test_a_field_declared_against_one_vocabulary_returns_only_that_vocabularys_concepts(
        self,
    ):
        rock_concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock type"), label="Granite rock"
        )
        RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"), label="Granite ore")
        RecordFactory(
            scheme=ConceptSchemeFactory(name="Fossil"), label="Granite fossil"
        )

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Granite", "field": field_reference(Specimen, "rock_type")},
        )

        assert result_uris(response) == [rock_concept.uri]

    def test_the_request_naming_a_different_vocabulary_directly_is_ignored(self):
        rock_concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock type"), label="Granite rock"
        )
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        RecordFactory(scheme=mineral_scheme, label="Granite ore")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {
                "q": "Granite",
                "field": field_reference(Specimen, "rock_type"),
                # A parameter the endpoint never reads: the restriction comes
                # from the declaration alone.
                "vocabulary": mineral_scheme.slug,
            },
        )

        assert result_uris(response) == [rock_concept.uri]

    def test_a_field_declared_against_several_vocabularies_returns_exactly_those(self):
        rock_concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock type"), label="Basalt rock"
        )
        mineral_concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Mineral"), label="Basalt ore"
        )
        RecordFactory(scheme=ConceptSchemeFactory(name="Fossil"), label="Basalt fossil")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Basalt", "field": field_reference(Borehole, "dominant_material")},
        )

        assert set(result_uris(response)) == {rock_concept.uri, mineral_concept.uri}

    def test_a_field_declared_against_no_vocabulary_makes_every_concept_eligible(self):
        concepts = [
            RecordFactory(
                scheme=ConceptSchemeFactory(name=name), label=f"Quartz {name}"
            )
            for name in ("Rock type", "Mineral", "Fossil")
        ]

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"q": "Quartz", "field": field_reference(Sketch, "subject")},
        )

        assert set(result_uris(response)) == {concept.uri for concept in concepts}

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
    def get(self, **params):
        return Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"), params
        )

    def test_four_unresolvable_references_and_a_true_empty_search_are_byte_identical(
        self,
    ):
        baseline = self.get(field=field_reference(Specimen, "rock_type"))
        assert baseline.status_code == 200

        naming_a_model_that_does_not_exist = self.get(
            field="testapp.nosuchmodel.rock_type"
        )
        naming_a_field_that_is_not_one_of_this_packages = self.get(
            field="testapp.specimen.name"
        )
        naming_a_field_that_does_not_exist = self.get(
            field="testapp.specimen.no_such_field"
        )
        with_no_reference_at_all = self.get()

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
            RecordFactory(label=f"Quartz {i:02d}")

        response = unrestricted_get(q="Quartz")

        body = json.loads(response.content)
        assert len(body["results"]) == 20
        assert body["has_more"] is True

    def test_the_following_page_returns_the_rest_with_none_repeated_and_none_skipped(
        self,
    ):
        concepts = [RecordFactory(label=f"Quartz {i:02d}") for i in range(25)]
        full_match_set = {concept.uri for concept in concepts}

        first_page = unrestricted_get(q="Quartz")
        second_page = unrestricted_get(q="Quartz", p=2)

        first_uris = result_uris(first_page)
        second_uris = result_uris(second_page)

        # Collected from both pages and compared against the full ordered
        # match set, not page lengths: a repeat shrinks the union below the
        # combined count, a skip shrinks the union below the full set.
        assert set(first_uris) | set(second_uris) == full_match_set
        assert len(first_uris) + len(second_uris) == len(full_match_set)
        assert json.loads(second_page.content)["has_more"] is False

    def test_opening_with_nothing_typed_offers_a_first_page_in_a_stable_order(self):
        concepts = [
            RecordFactory(label=label) for label in ["Charlie", "Alpha", "Bravo"]
        ]
        expected_order = sorted(
            concepts, key=lambda concept: (concept.pref_label, concept.pk)
        )

        response = unrestricted_get()

        assert result_uris(response) == [concept.uri for concept in expected_order]

    def test_opening_with_nothing_typed_orders_by_name_ignoring_case(self):
        # The order a vocabulary's own page lists its concepts in.
        bravo, alpha, charlie = (
            RecordFactory(label=label) for label in ["Bravo", "alpha", "Charlie"]
        )

        response = unrestricted_get()

        assert result_uris(response) == [alpha.uri, bravo.uri, charlie.uri]

    def test_a_page_past_the_last_returns_nothing_and_says_no_more_exist(self):
        # The inherited behaviour re-serves page 1 for a page past the last.
        RecordFactory(label="Granite")

        response = unrestricted_get(p=5)

        body = json.loads(response.content)
        assert body["results"] == []
        assert body["has_more"] is False

    def test_a_request_asking_for_more_than_max_page_size_is_clamped(self):
        for i in range(205):
            RecordFactory(label=f"Quartz {i:03d}")

        response = unrestricted_get(q="Quartz", page_size=1000)

        assert len(json.loads(response.content)["results"]) == 200

    def test_a_field_naming_no_vocabulary_is_bounded_the_same_way_across_several_vocabularies(
        self,
    ):
        for scheme_index in range(3):
            scheme = ConceptSchemeFactory()
            for i in range(10):
                RecordFactory(scheme=scheme, label=f"Quartz {scheme_index}-{i:02d}")

        # Sketch.subject (via unrestricted_get) names no vocabulary, so all
        # 30 concepts across the three schemes are eligible.
        response = unrestricted_get(q="Quartz")

        body = json.loads(response.content)
        assert len(body["results"]) == 20
        assert body["has_more"] is True

    def test_both_ordering_columns_reach_the_database(self):
        # Records are unique by label only within a vocabulary, so ties are possible,
        # and SQLite returns tied rows in insertion order, which masks a missing "pk"
        # tie-break in any paging test. The SQL issued is asserted instead.
        for name in ("Mineral", "Rock Type", "Lithology"):
            RecordFactory(scheme=ConceptSchemeFactory(name=name), label="Tied label")

        with CaptureQueriesContext(connection) as ctx:
            unrestricted_get(q="Tied")

        selects = [q["sql"] for q in ctx.captured_queries if "ORDER BY" in q["sql"]]
        assert selects, [q["sql"] for q in ctx.captured_queries]
        order_by = selects[0].split("ORDER BY", 1)[1]
        assert '"pref_label") ASC' in order_by
        assert order_by.index('"pref_label") ASC') < order_by.index('"id" ASC')


@pytest.mark.django_db
class TestConceptAutocompleteRequestControlledSurfacesAreClosed:
    def test_a_blocked_filter_field_empties_the_page(self):
        RecordFactory(label="Granite")

        response = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            # Sketch.subject restricts nothing: nothing else hides the guard.
            {"field": field_reference(Sketch, "subject"), "f": "x__pref_label=Granite"},
        )

        assert json.loads(response.content)["results"] == []

    def test_a_blocked_ordering_parameter_leaves_the_views_own_order_in_place(self):
        RecordFactory(label="Basalt")
        RecordFactory(label="Granite")
        reference = field_reference(Sketch, "subject")

        default = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": reference},
        )
        with_ordering = Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": reference, "ordering": "-pref_label"},
        )

        default_uris = result_uris(default)
        assert default_uris  # the guard is being tested against real, non-empty results
        assert result_uris(with_ordering) == default_uris


@pytest.mark.django_db
class TestConceptAutocompleteOrderedCollectionSequence:
    def get(self, **params):
        return Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": field_reference(CoreSample, "rock_type"), **params},
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
        reorder(collection, charlie, bravo, alpha)

        assert result_uris(self.get()) == [charlie.uri, bravo.uri, alpha.uri]

    def test_a_position_change_is_reflected_on_the_next_read(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo", "Alpha", "Charlie"),
        )
        bravo, alpha, charlie = members
        reorder(collection, charlie, bravo, alpha)
        assert result_uris(self.get()) == [charlie.uri, bravo.uri, alpha.uri]

        reorder(collection, alpha, charlie, bravo)

        assert result_uris(self.get()) == [alpha.uri, charlie.uri, bravo.uri]

    def test_a_typed_search_term_returns_to_relevance_order(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo Basalt", "Alpha Basalt", "Charlie Basalt"),
        )
        bravo, alpha, charlie = members
        reorder(collection, charlie, bravo, alpha)

        # A search term falls back to the inherited ("pref_label", "pk") ordering.
        assert result_uris(self.get(q="Basalt")) == [alpha.uri, bravo.uri, charlie.uri]

    def test_an_unordered_collection_stays_restricted_with_no_sequence_promised(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=False,
            labels=("Charlie", "Bravo", "Alpha"),
        )
        charlie, bravo, alpha = members
        outsider = RecordFactory(scheme=scheme, label="Marble")

        returned_uris = result_uris(self.get())

        assert set(returned_uris) == {charlie.uri, bravo.uri, alpha.uri}
        assert outsider.uri not in returned_uris
        # An unordered collection promises no sequence and gets the inherited ordering.
        assert returned_uris == [alpha.uri, bravo.uri, charlie.uri]

    def test_a_removed_member_leaves_the_survivors_in_relative_order(self):
        scheme = ConceptSchemeFactory(name="Rock type")
        collection, members = collection_with_members(
            scheme=scheme,
            name="core-samples",
            ordered=True,
            labels=("Bravo", "Alpha", "Charlie", "Delta"),
        )
        bravo, alpha, charlie, delta = members
        reorder(collection, delta, bravo, charlie, alpha)
        reorder(collection, delta, charlie, alpha)

        assert result_uris(self.get()) == [delta.uri, charlie.uri, alpha.uri]
        assert bravo.uri not in result_uris(self.get())


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
