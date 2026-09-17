"""Tests for ``controlled_vocabularies.views`` (T003, T005, FR-005, FR-012, FR-004).

``TestConceptAutocompleteResults`` — a result carries exactly the identifier, the
preferred label and the vocabulary a concept belongs to (FR-005, FR-012): not the
editorial notes, hidden labels or anything else the concept holds, and not merely
those three among others — the exact key set. A second test bounds the query cost
of a full page under ``django_assert_num_queries`` (R5): ``display_label()`` walks
each concept's ``labels.all()``, so ``hook_queryset()``'s ``prefetch_related`` is
what keeps that from costing a query per row.

``TestConceptAutocompleteSearch`` — a typed string matches a concept by any of its
three kinds of label in the active language, or by the default-language preferred
label every concept carries (FR-004, User Story 2). Every case is displayed under
the concept's preferred label, whichever label matched (FR-005).

Every request here carries a ``field=`` reference, because T006 made one mandatory:
the endpoint derives what a search may return from the declaration that reference
names, and a request without one is refused with an empty page (FR-006). These two
classes are about result shaping and label matching rather than the restriction, so
they name :class:`~tests.testapp.models.Sketch`'s ``subject`` — the declaration that
names no vocabulary and so makes every concept eligible — leaving each assertion
about exactly what its own name says.

``TestConceptAutocompleteOrderedCollectionSequence`` (T022, FR-010, plan.md A5,
decisions.md D8) — an ordered collection's own member sequence reaches this list,
not alphabetical order and not creation order, because that sequence is the whole
reason ``Collection.ordered`` means anything to somebody picking from it. Every
case names :class:`~tests.testapp.models.CoreSample`'s ``rock_type``, the one field
this suite restricts to a collection slug, since a ``field=`` reference is resolved
through Django's app registry rather than built ad hoc in a test.
"""

import json

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

from controlled_vocabularies.views import ConceptAutocompleteView
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
    collection_with_members,
)
from tests.testapp.models import Borehole, CoreSample, Sketch, Specimen


def _field_reference(model, field_name):
    """The ``<app_label>.<model>.<field_name>`` reference the control's
    widget sends (decisions.md D11), built the same way for a test as
    ``ConceptWidgetReferenceMixin.get_autocomplete_params()`` builds it."""
    return f"{model._meta.app_label}.{model._meta.model_name}.{field_name}"


def _unrestricted_get(**params):
    """Search from the one declaration that restricts nothing.

    ``Sketch.subject`` names no vocabulary, so its ``limit_choices_to`` is an
    empty ``Q`` and every concept stays eligible — the restriction T006 added
    is present but neutral, which is what keeps a result-shaping or
    label-matching assertion about result shaping or label matching."""
    return Client().get(
        reverse("controlled_vocabularies:concept-autocomplete"),
        {"field": _field_reference(Sketch, "subject"), **params},
    )


class SpecimenForm(forms.ModelForm):
    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


class TestConceptAutocompleteResults:
    """The endpoint's JSON results carry exactly what FR-012 permits."""

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
    def test_a_full_page_of_concepts_with_labels_and_notes_costs_a_bounded_query_count(
        self, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        for _ in range(20):
            concept = ConceptFactory(scheme=scheme)
            concept.add_label(language="de", kind="alternative", text="alt")
            concept.add_note(language="en", kind="definition", value="A definition.")

        with django_assert_num_queries(3):
            response = _unrestricted_get()

        body = json.loads(response.content)
        assert len(body["results"]) == 20


class TestConceptAutocompleteSearch:
    """A typed string matches a concept by any of its labels, in the active
    language (FR-004, User Story 2). Every case is displayed under the
    concept's preferred label for the active language, whichever label the
    match was made on (FR-005).

    Each search fragment is one no other clause of the filter can match: a
    fragment that is also a substring of the default-language ``label``
    column passes whether or not the label kind under test is searched at
    all, which is a test that asserts nothing about its own scenario."""

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
        # The other half of FR-004's "in the active language": a fragment
        # unique to a label the active language does not own must not find
        # the concept. Without this, dropping the language constraint from
        # the filter altogether leaves every other test in this class green.
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
    """FR-006, plan.md A6 path one, decisions.md D11: the endpoint derives
    what a search may return from the field declaration a ``field=``
    reference names, resolved through Django's app registry — never from
    anything else the request carries (T006)."""

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
                # Names a vocabulary directly, through a parameter the
                # endpoint never reads. FR-006 says the restriction comes
                # from the declaration alone; this is the case that proves
                # it (prohibitions).
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
        # The widget's full context — including autocompleteParams — only
        # builds with a live request in django_tomselect's thread-local
        # storage (widgets.py:610-628), the way TomSelectMiddleware provides
        # it on a real request/response cycle. A bare `str(SpecimenForm())`
        # falls back to the base context, which carries no reference at all,
        # and would pass this assertion vacuously by asserting on nothing.
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        rendered = {}

        def get_response(inner_request):
            rendered["html"] = str(SpecimenForm())
            return HttpResponse()

        TomSelectMiddleware(get_response)(request)

        # The template renders autocompleteParams through Django's `escapejs`
        # filter, which escapes "=" to the literal six characters
        # backslash-u-0-0-3-D — verified against the actual rendered output,
        # not assumed from the raw parameter string.
        escaped_equals = "\\u003D"
        assert (
            f"autocompleteParams: 'field{escaped_equals}testapp.specimen.rock_type'"
            in rendered["html"]
        )


@pytest.mark.django_db
class TestConceptAutocompleteRefusalDisclosesNothing:
    """FR-006: an unresolvable ``field=`` reference never discloses what it
    rejects. All four refusal shapes are byte-identical HTTP responses, and
    identical to a search that simply matched nothing (T007)."""

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
    """FR-007, User Story 5, plan.md A7: the endpoint answers with a bounded
    page and says whether more exist, paging is stable across a search, the
    control's empty-query open is bounded the same way, an over-large
    ``page_size`` is clamped, and a field naming no vocabulary is bounded
    across however many vocabularies the database holds. Every paging
    assertion compares the identifiers collected from both pages against the
    full ordered match set, never page lengths, so a repeat or a skip fails
    rather than cancelling out (prohibitions)."""

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
        # This fails against the inherited behaviour, which re-serves page 1
        # (autocompletes.py:743) — that is the point of this task.
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
        # decisions.md D13: Concept.label is unique only within its own
        # scheme, so two concepts in different vocabularies can share the
        # same label, and a field naming several (or none) can serve such a
        # tie in one page. A black-box paging test cannot discriminate this
        # on SQLite: its scan already returns tied rows in insertion order,
        # so ordering by "label" alone coincidentally reproduces ("label",
        # "pk") here — verified empirically (41 identically labelled
        # concepts across three pages, union and count both matched with the
        # tie-break removed). Asserting the declared ordering directly is
        # the one check this database's behaviour cannot mask.
        assert ConceptAutocompleteView.ordering == ("label", "pk")

    def test_both_ordering_columns_reach_the_database(self):
        """The assertion above says the class declares the tie-break. This one
        says the endpoint applies it: the base view reads ``ordering`` through
        its own ``apply_ordering()``, and a declared-but-unapplied ordering
        would satisfy the assertion above while sorting by nothing in
        particular. Asserted on the SQL the search actually issued."""
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
    """decisions.md D8: ``allowed_filter_fields`` and ``allowed_ordering_fields``
    close the two other request-controlled surfaces the endpoint exposes, and
    they refuse differently (T007)."""

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
    """T022, FR-010, plan.md A5, research.md R6, decisions.md D8: the endpoint
    serves an ordered collection's members in the curator's own sequence, not
    alphabetical order and not creation order — the one requirement
    ``limit_choices_to`` cannot carry, so it is applied here rather than on
    the widget's queryset (which nobody browsing the control ever sees).

    Every case names :class:`~tests.testapp.models.CoreSample`'s ``rock_type``
    — declared with ``vocabulary="rock-type"``, ``collection="core-samples"``
    — so the scheme built here is named "Rock type" (slug ``rock-type``) and
    the collection "core-samples", matching that static declaration exactly;
    a ``field=`` reference only resolves against a real, registered model
    field, not one built ad hoc in a test.
    """

    def _get(self, **params):
        return Client().get(
            reverse("controlled_vocabularies:concept-autocomplete"),
            {"field": _field_reference(CoreSample, "rock_type"), **params},
        )

    def test_an_ordered_collections_sequence_differs_from_both_alphabetical_and_creation_order(
        self,
    ):
        # Created Bravo, Alpha, Charlie in that order (creation/pk order).
        # Alphabetical would read Alpha, Bravo, Charlie. The curator's chosen
        # sequence below is neither, so a missing override (falls to
        # "label") or an accidental default (falls to creation/pk order)
        # both fail this.
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

        # Falls through to the inherited ("label", "pk") ordering once a
        # search term is present (plan.md A5) — alphabetical by label, not
        # the curator's sequence asserted above for the same collection.
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
        # No sequence is promised for an unordered collection: it falls
        # through to the inherited alphabetical ordering, the same as any
        # other unordered result set (plan.md A5).
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
        # research.md R3/R6: a concept belonging to a second collection must
        # not duplicate through a collection_memberships__ join.
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
