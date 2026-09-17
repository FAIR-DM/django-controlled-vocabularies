"""Tests for the Django admin's rendering of the concept fields (US-1, T002-T004).

The registrations in ``tests/testapp/admin.py`` are deliberately bare — no
``ModelAdmin`` here declares anything about ``Specimen.rock_type`` or
``Outcrop.minerals``. What these tests prove is FR-001, FR-002 and SC-001
together: the control the forms feature already renders reaches the admin
unchanged, through nothing more than ``db_field.formfield()``, and the bare
registration itself is scenario 6's proof that nothing further is configured
for the admin specifically. This story builds no production code — it pins
behaviour that is currently true by accident, so the next stories cannot
quietly break it (plan.md, US-1).

``TestConceptControlRendersOnAdminPages`` (T002) covers scenarios 1-3 and 6:
the add and change pages of both field kinds render the control, and the
change page shows what the record already holds, under its preferred label.

``TestAdminPageRenderingIsBoundedByVocabularySize`` (T003) mirrors
``tests/test_forms.py::TestConceptFieldRenderingIsBoundedByVocabularySize``
so the two read the same — FR-009, SC-006, scenario 4.

``TestAdminSubmissionSavesAndFieldRulesStillBite`` (T004) covers scenario 5:
a POST from the add page saves the chosen concept, one naming a concept
outside the field's declared vocabulary is refused by the field's own
validation, and a concept referenced through the admin is still protected
from deletion — both field kinds.

``TestInlineRowsCarryTheControl`` (T009), ``TestEmptyFormRowIsInitialisable``
(T010) and ``TestNewInlineRowSavesItsConcept`` (T011) cover US-3: ``Locality``
(``tests/testapp/models.py``, T008) is the parent, ``Specimen`` the inline
child, registered on dedicated sites here rather than in
``tests/testapp/admin.py`` per that module's own bare-registrations-only
convention (T008's ``progress.md`` entry).

``TestExplicitDeclarationWins`` (T012) and
``TestReadOnlyPresentationRendersNoControl`` (T013) cover US-4: a project's
own ``autocomplete_fields``, ``raw_id_fields`` or form-declared widget wins
over the control, and a read-only field renders Django's own presentation —
also registered on dedicated sites here rather than in
``tests/testapp/admin.py``, per the same convention (``decisions.md`` D22).
"""

import re

import pytest
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import ProtectedError
from django.test import override_settings
from django.urls import include, path, reverse

from controlled_vocabularies.models import Concept
from tests.factories import (
    ConceptFactory,
    ConceptSchemeFactory,
    LocalityFactory,
    OutcropFactory,
    SpecimenFactory,
)
from tests.testapp.models import Locality, Outcrop, Specimen


def _field_reference(model, field_name):
    """The ``<app_label>.<model>.<field_name>`` reference the control's widget
    sends, spelled the same way ``tests/test_views.py::_field_reference`` is —
    duplicated per module rather than imported, per DAMP."""
    return f"{model._meta.app_label}.{model._meta.model_name}.{field_name}"


def _assert_control_rendered(content, model, field_name):
    """T002's three-part acceptance, factored out because every test in this
    module asserts it: the select carries ``data-tomselect``, the page
    carries the widget's own configuration script, and the autocomplete
    reference for this field is present — escaped the way Django's
    ``escapejs`` filter renders it (``tests/test_views.py`` proves the
    escaping against the same template; this asserts against the admin's
    rendering of it)."""
    assert f'id="id_{field_name}"' in content
    assert "data-tomselect" in content
    assert "window.djangoTomSelect.initialize(element, config);" in content
    escaped_equals = "\\u003D"
    assert (
        f"autocompleteParams: 'field{escaped_equals}{_field_reference(model, field_name)}'"
        in content
    )


@pytest.mark.django_db
class TestConceptControlRendersOnAdminPages:
    """T002: FR-001, FR-002, SC-001, US-1 scenarios 1-3 and 6."""

    def test_add_page_renders_the_control_for_a_concept_field(self, admin_client):
        response = admin_client.get(reverse("admin:testapp_specimen_add"))

        assert response.status_code == 200
        _assert_control_rendered(response.content.decode(), Specimen, "rock_type")

    def test_add_page_renders_the_control_for_a_concepts_field(self, admin_client):
        response = admin_client.get(reverse("admin:testapp_outcrop_add"))

        assert response.status_code == 200
        _assert_control_rendered(response.content.decode(), Outcrop, "minerals")

    def test_change_page_renders_the_control_and_shows_the_held_concept_under_its_preferred_label(
        self, admin_client
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme, label="Granite")
        specimen = SpecimenFactory(rock_type=concept)

        response = admin_client.get(
            reverse("admin:testapp_specimen_change", args=[specimen.pk])
        )
        content = response.content.decode()

        assert response.status_code == 200
        _assert_control_rendered(content, Specimen, "rock_type")
        assert concept.label in content

    def test_change_page_shows_every_concept_a_concepts_field_holds(self, admin_client):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Mineral concept {i}")
            for i in range(3)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)

        response = admin_client.get(
            reverse("admin:testapp_outcrop_change", args=[outcrop.pk])
        )
        content = response.content.decode()

        assert response.status_code == 200
        _assert_control_rendered(content, Outcrop, "minerals")
        for concept in concepts:
            assert concept.label in content


@pytest.mark.django_db
class TestAdminPageRenderingIsBoundedByVocabularySize:
    """T003: FR-009, SC-006, US-1 scenario 4 — mirrors
    ``tests/test_forms.py::TestConceptFieldRenderingIsBoundedByVocabularySize``
    so the two read the same."""

    def test_rendered_length_is_identical_for_a_large_vocabulary(self, admin_client):
        scheme = ConceptSchemeFactory(name="Rock Type")
        for i in range(5):
            ConceptFactory(scheme=scheme, label=f"Small vocab concept {i}")
        small_rendered = admin_client.get(
            reverse("admin:testapp_specimen_add")
        ).content.decode()

        large_concepts = [
            ConceptFactory(scheme=scheme, label=f"Large vocab concept {i}")
            for i in range(2000)
        ]
        large_rendered = admin_client.get(
            reverse("admin:testapp_specimen_add")
        ).content.decode()

        assert len(large_rendered) == len(small_rendered)
        assert not any(concept.label in large_rendered for concept in large_concepts)


@pytest.mark.django_db
class TestAdminSubmissionSavesAndFieldRulesStillBite:
    """T004: FR-010, US-1 scenario 5. A POST from the add page saves the
    chosen concept. A concept from outside the field's declared vocabulary is
    refused at the form field's own level: the widget's ``get_queryset()``
    (``tests/test_forms.py``'s ``TestConceptFieldSubmissionSurvives`` proves
    this is what a legitimate submission survives) is narrowed to the
    declaration, so ``ModelChoiceField.clean()`` rejects the foreign pk with
    Django's own "not one of the available choices" message before the
    model-level ``ConceptField.validate()`` custom message is ever reached —
    the same reason the existing form-level tests assert on the errored
    field, not on message text. And a concept referenced through the admin is
    still protected from deletion — both field kinds."""

    def test_a_legitimate_concept_saves_through_the_add_page_for_a_concept_field(
        self, admin_client
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)

        response = admin_client.post(
            reverse("admin:testapp_specimen_add"),
            {"name": "Granite sample", "rock_type": concept.pk, "_save": "Save"},
        )

        assert response.status_code == 302
        specimen = Specimen.objects.get(name="Granite sample")
        assert specimen.rock_type_id == concept.pk

    def test_a_foreign_concept_is_refused_by_the_add_page_for_a_concept_field(
        self, admin_client
    ):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        foreign_concept = ConceptFactory(scheme=other_scheme)

        response = admin_client.post(
            reverse("admin:testapp_specimen_add"),
            {
                "name": "Wrong vocabulary sample",
                "rock_type": foreign_concept.pk,
                "_save": "Save",
            },
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert not Specimen.objects.filter(name="Wrong vocabulary sample").exists()
        assert 'id="id_rock_type_error"' in content

    def test_a_legitimate_concept_saves_through_the_add_page_for_a_concepts_field(
        self, admin_client
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme)

        response = admin_client.post(
            reverse("admin:testapp_outcrop_add"),
            {"name": "Basalt outcrop", "minerals": [concept.pk], "_save": "Save"},
        )

        assert response.status_code == 302
        outcrop = Outcrop.objects.get(name="Basalt outcrop")
        assert concept in outcrop.minerals.all()

    def test_a_foreign_concept_is_refused_by_the_add_page_for_a_concepts_field(
        self, admin_client
    ):
        other_scheme = ConceptSchemeFactory(name="Rock Type")
        foreign_concept = ConceptFactory(scheme=other_scheme)

        response = admin_client.post(
            reverse("admin:testapp_outcrop_add"),
            {
                "name": "Wrong vocabulary outcrop",
                "minerals": [foreign_concept.pk],
                "_save": "Save",
            },
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert not Outcrop.objects.filter(name="Wrong vocabulary outcrop").exists()
        assert 'id="id_minerals_error"' in content

    def test_a_concept_field_saved_through_the_admin_still_cannot_be_deleted(
        self, admin_client
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        admin_client.post(
            reverse("admin:testapp_specimen_add"),
            {"name": "Protected sample", "rock_type": concept.pk, "_save": "Save"},
        )

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Specimen.objects.filter(
            name="Protected sample", rock_type=concept
        ).exists()

    def test_a_concepts_field_saved_through_the_admin_still_cannot_be_deleted(
        self, admin_client
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme)
        admin_client.post(
            reverse("admin:testapp_outcrop_add"),
            {"name": "Protected outcrop", "minerals": [concept.pk], "_save": "Save"},
        )

        with pytest.raises(ProtectedError):
            concept.delete()

        outcrop = Outcrop.objects.get(name="Protected outcrop")
        assert concept in outcrop.minerals.all()


class URLConf:
    """A ``ROOT_URLCONF`` carrying one ``site``'s own admin plus this
    package's own route, mirroring ``tests/urls.py`` — the control's widget
    reverses ``controlled_vocabularies:concept-autocomplete`` while building
    its render context (``forms.py``'s ``ConceptWidgetRouteMixin``), so a
    urlconf mounting only the admin raises ``ImproperlyConfigured`` before any
    affordance assertion is ever reached. Uses the ``admin:`` app_name every
    ``AdminSite`` uses regardless of instance name, so tests below reuse
    ``reverse("admin:...")`` exactly as :func:`_assert_control_rendered` and
    T002 already do. ``URLResolver.urlconf_module`` accepts any object
    carrying ``urlpatterns``, not only a dotted import path — a plain object
    rather than :class:`types.SimpleNamespace`, since the resolver cache keys
    on it and ``SimpleNamespace``'s value-based ``__eq__`` makes it
    unhashable."""

    def __init__(self, site):
        self.urlpatterns = [
            path("admin/", site.urls),
            path("vocabularies/", include("controlled_vocabularies.urls")),
        ]


_RELATED_OBJECT_AFFORDANCE_MARKERS = (
    "related-widget-wrapper-link",
    "add-related",
    "change-related",
    "delete-related",
    "view-related",
)


def _assert_no_related_object_affordance(content):
    """None of the four related-object links `RelatedFieldWidgetWrapper` can
    render (``related_widget_wrapper.html``) are present. Deliberately not
    asserting on the wrapper's ``data-context="available-source"`` attribute:
    ``RelatedFieldWidgetWrapper.__init__`` mutates the wrapped widget's own
    ``attrs`` dict with it before the T006 setter ever unwraps the widget, so
    it survives harmlessly and is not itself an affordance (tasks.md T005)."""
    for marker in _RELATED_OBJECT_AFFORDANCE_MARKERS:
        assert marker not in content


@pytest.fixture
def concept_registered_admin_site():
    """A dedicated admin site registering ``Concept`` alongside the two
    consuming fields under test — the only configuration under which
    research.md R1 measured the four related-object affordances appearing at
    all. Never the default site: that one already registers ``Specimen`` and
    ``Outcrop`` (``tests/testapp/admin.py``), and Django refuses registering
    the same model on the same site twice."""
    site = admin.AdminSite(name="us2_with_concept")
    site.register(Specimen)
    site.register(Outcrop)
    site.register(Concept)
    return site


@pytest.fixture
def bare_admin_site():
    """The same two consuming models, on a second dedicated site that never
    registers ``Concept`` — US-2 scenario 4: the affordances' absence does not
    depend on what is registered."""
    site = admin.AdminSite(name="us2_without_concept")
    site.register(Specimen)
    site.register(Outcrop)
    return site


@pytest.mark.django_db
class TestConceptFieldOffersNoRelatedObjectAffordance:
    """T005: FR-004, US-2 scenarios 1-5, SC-002.

    ``Concept`` is registered in a dedicated admin site alongside the consuming
    models, and ``admin_client`` signs in as a superuser holding every
    permission — the one configuration research.md R1 measured all four
    related-object affordances (add/change/delete/view) appearing under. Every
    test also proves the control itself is unaffected (scenario 3): it still
    renders and still carries its own autocomplete reference. The last test
    proves scenario 4 — the same absence holds with ``Concept`` not registered
    at all.
    """

    def test_add_page_offers_no_affordance_for_a_concept_field(
        self, admin_client, concept_registered_admin_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Specimen, "rock_type")

    def test_change_page_offers_no_affordance_for_a_concept_field(
        self, admin_client, concept_registered_admin_site
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = admin_client.get(
                reverse("admin:testapp_specimen_change", args=[specimen.pk])
            )
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Specimen, "rock_type")

    def test_add_page_offers_no_affordance_for_a_concepts_field(
        self, admin_client, concept_registered_admin_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = admin_client.get(reverse("admin:testapp_outcrop_add"))
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Outcrop, "minerals")

    def test_change_page_offers_no_affordance_for_a_concepts_field(
        self, admin_client, concept_registered_admin_site
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme)
        outcrop = OutcropFactory()
        outcrop.minerals.add(concept)

        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = admin_client.get(
                reverse("admin:testapp_outcrop_change", args=[outcrop.pk])
            )
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Outcrop, "minerals")

    def test_the_same_absence_holds_with_concept_not_registered(
        self, admin_client, bare_admin_site
    ):
        """Pins US-2 scenario 4, and documents rather than checks it: Django
        suppresses all four links itself when the related model is
        unregistered, so this passes with or without the unwrap. The tests
        above it — ``Concept`` registered, superuser, both field kinds, add
        and change — are the ones that go red if the unwrap regresses."""
        with override_settings(ROOT_URLCONF=URLConf(bare_admin_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Specimen, "rock_type")


class SpecimenTabularInline(admin.TabularInline):
    """The registration T008's acceptance names — ``extra = 1`` — used on
    ``locality_tabular_site``."""

    model = Specimen
    extra = 1


class SpecimenStackedInline(admin.StackedInline):
    """The registration T008's acceptance names — ``extra = 0`` — the
    configuration research.md R4 measured the library failing on, used on
    ``locality_stacked_site``."""

    model = Specimen
    extra = 0


class LocalityTabularAdmin(admin.ModelAdmin):
    inlines = [SpecimenTabularInline]


class LocalityStackedAdmin(admin.ModelAdmin):
    inlines = [SpecimenStackedInline]


@pytest.fixture
def locality_tabular_site():
    """``Locality`` with its ``Specimen`` inline as a ``TabularInline``,
    ``extra = 1`` (T008)."""
    site = admin.AdminSite(name="us3_locality_tabular")
    site.register(Locality, LocalityTabularAdmin)
    return site


@pytest.fixture
def locality_stacked_site():
    """``Locality`` with its ``Specimen`` inline as a ``StackedInline``,
    ``extra = 0`` (T008) — the configuration with no numbered row rendered
    until one is added, the shape research.md R4 measured the library
    failing on."""
    site = admin.AdminSite(name="us3_locality_stacked")
    site.register(Locality, LocalityStackedAdmin)
    return site


def _assert_inline_row_control_rendered(content, model, field_name, prefix, index):
    """T009's per-row counterpart to :func:`_assert_control_rendered`: the
    same three-part acceptance, against a saved inline row's own element id
    (``id_<prefix>-<index>-<field_name>``) rather than the parent form's bare
    one."""
    element_id = f"id_{prefix}-{index}-{field_name}"
    assert f'id="{element_id}"' in content
    assert "data-tomselect" in content
    escaped_equals = "\\u003D"
    assert (
        f"autocompleteParams: 'field{escaped_equals}{_field_reference(model, field_name)}'"
        in content
    )


@pytest.mark.django_db
class TestInlineRowsCarryTheControl:
    """T009: FR-003, US-3 scenarios 1 and 4."""

    def test_two_saved_inline_rows_each_carry_the_control_showing_their_own_concept(
        self, admin_client, locality_tabular_site
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        first_concept = ConceptFactory(scheme=rock_scheme, label="Granite")
        second_concept = ConceptFactory(scheme=rock_scheme, label="Basalt")
        unattached_concept = ConceptFactory(
            scheme=rock_scheme, label="Unattached concept"
        )
        locality = LocalityFactory()
        SpecimenFactory(locality=locality, rock_type=first_concept)
        SpecimenFactory(locality=locality, rock_type=second_concept)

        with override_settings(ROOT_URLCONF=URLConf(locality_tabular_site)):
            response = admin_client.get(
                reverse("admin:testapp_locality_change", args=[locality.pk])
            )
        content = response.content.decode()

        assert response.status_code == 200
        _assert_inline_row_control_rendered(
            content, Specimen, "rock_type", "specimens", 0
        )
        _assert_inline_row_control_rendered(
            content, Specimen, "rock_type", "specimens", 1
        )
        assert first_concept.label in content
        assert second_concept.label in content
        assert unattached_concept.label not in content

    def test_an_inline_row_declaring_a_different_vocabulary_carries_its_own_reference_not_the_parents(
        self, admin_client, locality_tabular_site
    ):
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        parent_concept = ConceptFactory(
            scheme=mineral_scheme, label="Locality primary mineral"
        )
        row_concept = ConceptFactory(scheme=rock_scheme, label="Row rock type")
        locality = LocalityFactory(primary_mineral=parent_concept)
        SpecimenFactory(locality=locality, rock_type=row_concept)

        with override_settings(ROOT_URLCONF=URLConf(locality_tabular_site)):
            response = admin_client.get(
                reverse("admin:testapp_locality_change", args=[locality.pk])
            )
        content = response.content.decode()

        parent_reference = _field_reference(Locality, "primary_mineral")
        row_reference = _field_reference(Specimen, "rock_type")

        assert response.status_code == 200
        assert parent_reference != row_reference
        _assert_control_rendered(content, Locality, "primary_mineral")
        _assert_inline_row_control_rendered(
            content, Specimen, "rock_type", "specimens", 0
        )
        assert parent_concept.label in content
        assert row_concept.label in content


@pytest.mark.django_db
class TestEmptyFormRowIsInitialisable:
    """T010: FR-003, US-3 scenarios 2 and 5. What's provable server-side of
    ``concept-inline.js`` (decisions.md D12): the empty-form template row
    Django always renders (regardless of ``extra``) carries a select with
    ``data-tomselect`` and a registered configuration whose id contains
    ``__prefix__``, and the id substitution the script performs matches the
    identifier Django's own ``inlines.js`` produces for a newly added row.
    The browser click itself is the documented manual check."""

    def test_the_empty_form_row_carries_a_select_with_a_registered_configuration(
        self, admin_client, locality_stacked_site
    ):
        locality = LocalityFactory()

        with override_settings(ROOT_URLCONF=URLConf(locality_stacked_site)):
            response = admin_client.get(
                reverse("admin:testapp_locality_change", args=[locality.pk])
            )
        content = response.content.decode()

        assert response.status_code == 200
        assert 'id="id_specimens-__prefix__-rock_type"' in content
        assert "data-tomselect" in content
        escaped_equals = "\\u003D"
        assert (
            f"autocompleteParams: 'field{escaped_equals}{_field_reference(Specimen, 'rock_type')}'"
            in content
        )

    def test_the_id_substitution_matches_the_identifier_djangos_inlinesjs_produces_for_a_new_row(
        self, admin_client, locality_tabular_site
    ):
        """``concept-inline.js``'s own substitution — the **last**
        ``-<digits>-`` segment swapped for ``-__prefix__-`` — mirrored here in
        Python and checked against two real ids from the same rendered page:
        the numbered row ``extra = 1`` renders (the shape Django's own
        ``updateElementIndex``, ``inlines.js``, produces for a row it adds)
        and the always-present empty-form template row.

        A core-Django inline id carries exactly one such segment, so first and
        last are the same identifier here. The nested-inline id asserted at the
        end is what makes the rule chosen: only the innermost segment belongs
        to the row being added, and this package renders concept controls
        wherever a project puts them, including under a third-party nested
        inline."""
        locality = LocalityFactory()

        with override_settings(ROOT_URLCONF=URLConf(locality_tabular_site)):
            response = admin_client.get(
                reverse("admin:testapp_locality_change", args=[locality.pk])
            )
        content = response.content.decode()

        numbered_row_id = "id_specimens-0-rock_type"
        template_row_id = "id_specimens-__prefix__-rock_type"
        innermost_segment = r"-\d+-(?![\s\S]*-\d+-)"

        assert f'id="{numbered_row_id}"' in content
        assert f'id="{template_row_id}"' in content
        assert (
            re.sub(innermost_segment, "-__prefix__-", numbered_row_id)
            == template_row_id
        )
        assert (
            re.sub(
                innermost_segment,
                "-__prefix__-",
                "id_localities-0-specimens-1-rock_type",
            )
            == "id_localities-0-specimens-__prefix__-rock_type"
        )


@pytest.mark.django_db
class TestNewInlineRowSavesItsConcept:
    """T011: FR-003, US-3 scenario 3, SC-003. The server half of the "Add
    another" journey — a POST carrying a new, unsaved formset row does not
    depend on the browser at all."""

    def test_a_new_inline_row_added_to_the_post_creates_the_child_holding_its_concept(
        self, admin_client, locality_stacked_site
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        locality = LocalityFactory()

        data = {
            "name": locality.name,
            "primary_mineral": "",
            "specimens-TOTAL_FORMS": "1",
            "specimens-INITIAL_FORMS": "0",
            "specimens-MIN_NUM_FORMS": "0",
            "specimens-MAX_NUM_FORMS": "1000",
            "specimens-0-id": "",
            "specimens-0-name": "Newly added specimen",
            "specimens-0-rock_type": str(concept.pk),
            "_save": "Save",
        }

        with override_settings(ROOT_URLCONF=URLConf(locality_stacked_site)):
            response = admin_client.post(
                reverse("admin:testapp_locality_change", args=[locality.pk]), data
            )

        assert response.status_code == 302
        specimen = Specimen.objects.get(name="Newly added specimen")
        assert specimen.locality_id == locality.pk
        assert specimen.rock_type_id == concept.pk


class AutocompleteSpecimenAdmin(admin.ModelAdmin):
    """``rock_type`` named in ``autocomplete_fields`` — Django's own control
    (`django/contrib/admin/widgets.py::AutocompleteSelect`), not this
    package's, per FR-005."""

    autocomplete_fields = ["rock_type"]


class ConceptSearchAdmin(admin.ModelAdmin):
    """``Concept`` registered with ``search_fields`` — the one configuration
    ``autocomplete_fields`` needs to pass ``admin.E039``/``admin.E040`` on the
    site under test, and the configuration under which the related-object
    link would render if FR-004 did not still apply to it."""

    search_fields = ["label"]


class RawIdSpecimenAdmin(admin.ModelAdmin):
    """``rock_type`` named in ``raw_id_fields`` — the one declaration Django
    itself never wraps (research.md R1), so it needs no ``Concept``
    registration to check clean."""

    raw_id_fields = ["rock_type"]


class DeclaredWidgetSpecimenForm(forms.ModelForm):
    """Declares its own widget for ``rock_type`` via ``Meta.widgets`` —
    reaches ``ModelAdmin.formfield_for_dbfield`` as a ``widget=`` constructor
    argument the same way ``autocomplete_fields`` does (plan.md "US-4"), so
    it is wrapped and unwrapped like any other field rather than bypassing
    ``db_field.formfield()`` the way a form-declared field object would."""

    class Meta:
        model = Specimen
        fields = "__all__"
        widgets = {"rock_type": forms.Select()}


class DeclaredWidgetSpecimenAdmin(admin.ModelAdmin):
    form = DeclaredWidgetSpecimenForm


@pytest.fixture
def autocomplete_site():
    """``Specimen`` with ``rock_type`` in ``autocomplete_fields``, alongside
    a searchable ``Concept`` registration (T012)."""
    site = admin.AdminSite(name="us4_autocomplete")
    site.register(Specimen, AutocompleteSpecimenAdmin)
    site.register(Concept, ConceptSearchAdmin)
    return site


@pytest.fixture
def raw_id_site():
    """``Specimen`` with ``rock_type`` in ``raw_id_fields`` (T012)."""
    site = admin.AdminSite(name="us4_raw_id")
    site.register(Specimen, RawIdSpecimenAdmin)
    return site


@pytest.fixture
def declared_widget_site():
    """``Specimen`` registered with a form declaring its own widget for
    ``rock_type`` via ``Meta.widgets``, alongside a registered ``Concept``
    (T012)."""
    site = admin.AdminSite(name="us4_declared_widget")
    site.register(Specimen, DeclaredWidgetSpecimenAdmin)
    site.register(Concept, ConceptSearchAdmin)
    return site


@pytest.mark.django_db
class TestExplicitDeclarationWins:
    """T012: FR-005, US-4 scenarios 1-5, SC-004.

    Each of three admin sites gives ``Specimen.rock_type`` its own explicit
    declaration; each renders what it declared and not this package's
    control, a valid concept still saves and an ineligible one is still
    refused through every one, and none of the three sites reports a system
    check error for its declaration. ``autocomplete_site`` and
    ``declared_widget_site`` also carry a registered ``Concept`` (plan.md
    "US-4": both are wrapped like any other field, so FR-004 still applies to
    whatever renders) and assert no related-object link appears —
    ``raw_id_site`` is the one declaration Django itself never wraps
    (research.md R1), so it renders no control this feature owns and needs
    no such assertion.
    """

    def test_autocomplete_fields_renders_djangos_own_autocomplete_not_the_concept_control(
        self, admin_client, autocomplete_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(autocomplete_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert 'class="admin-autocomplete' in content
        _assert_no_related_object_affordance(content)

    def test_raw_id_fields_renders_the_raw_identifier_control(
        self, admin_client, raw_id_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(raw_id_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert 'class="admin-autocomplete' not in content
        assert 'name="rock_type"' in content
        assert 'type="text"' in content

    def test_a_forms_declared_widget_renders_in_place_of_the_concept_control(
        self, admin_client, declared_widget_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(declared_widget_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert 'class="admin-autocomplete' not in content
        _assert_no_related_object_affordance(content)

    @pytest.mark.parametrize(
        "site_fixture_name",
        ["autocomplete_site", "raw_id_site", "declared_widget_site"],
    )
    def test_a_legitimate_concept_still_saves(
        self, admin_client, request, site_fixture_name
    ):
        site = request.getfixturevalue(site_fixture_name)
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)

        with override_settings(ROOT_URLCONF=URLConf(site)):
            response = admin_client.post(
                reverse("admin:testapp_specimen_add"),
                {
                    "name": f"{site_fixture_name} sample",
                    "rock_type": concept.pk,
                    "_save": "Save",
                },
            )

        assert response.status_code == 302
        specimen = Specimen.objects.get(name=f"{site_fixture_name} sample")
        assert specimen.rock_type_id == concept.pk

    @pytest.mark.parametrize(
        "site_fixture_name",
        ["autocomplete_site", "raw_id_site", "declared_widget_site"],
    )
    def test_an_ineligible_concept_is_still_refused(
        self, admin_client, request, site_fixture_name
    ):
        site = request.getfixturevalue(site_fixture_name)
        other_scheme = ConceptSchemeFactory(name="Mineral")
        foreign_concept = ConceptFactory(scheme=other_scheme)

        with override_settings(ROOT_URLCONF=URLConf(site)):
            response = admin_client.post(
                reverse("admin:testapp_specimen_add"),
                {
                    "name": f"{site_fixture_name} wrong vocabulary",
                    "rock_type": foreign_concept.pk,
                    "_save": "Save",
                },
            )

        assert response.status_code == 200
        assert not Specimen.objects.filter(
            name=f"{site_fixture_name} wrong vocabulary"
        ).exists()

    def test_no_declaration_reports_a_check_error(
        self, autocomplete_site, raw_id_site, declared_widget_site
    ):
        for site in (autocomplete_site, raw_id_site, declared_widget_site):
            assert site.check(None) == []


class ReadOnlyRockTypeSpecimenAdmin(admin.ModelAdmin):
    """``rock_type`` listed in ``readonly_fields`` — the single-valued case,
    scenario 6 (T013)."""

    readonly_fields = ["rock_type"]


class ReadOnlyMineralsOutcropAdmin(admin.ModelAdmin):
    """``minerals`` listed in ``readonly_fields`` — the multi-valued case,
    scenario 6 (T013)."""

    readonly_fields = ["minerals"]


@pytest.fixture
def readonly_concept_site():
    """``Specimen`` and ``Outcrop``, each with its concept field explicitly
    declared read-only, alongside a registered ``Concept`` — the
    configuration D14 says renders a link for the single-valued relation
    (T013 scenario 6)."""
    site = admin.AdminSite(name="us4_readonly")
    site.register(Specimen, ReadOnlyRockTypeSpecimenAdmin)
    site.register(Outcrop, ReadOnlyMineralsOutcropAdmin)
    site.register(Concept)
    return site


def _view_only_staff_user(*codenames):
    """A saved staff user holding exactly the named ``view_*`` permissions —
    never ``change_*`` — for US-4 scenario 7: a person who may view the page
    but not change it (T013)."""
    # No password: every caller reaches the page through ``force_login``, so the
    # user never authenticates, and a literal here is a credential-shaped string
    # in the repository for nothing.
    user = get_user_model().objects.create_user(
        username="readonly-viewer", is_staff=True
    )
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return user


@pytest.mark.django_db
class TestReadOnlyPresentationRendersNoControl:
    """T013: FR-008, US-4 scenarios 6 and 7, decisions.md D14.

    Two independent triggers for the same Django presentation, kept
    deliberately apart: an explicit ``readonly_fields`` declaration
    (scenario 6, exercised through ``admin_client`` — a superuser holding
    full change permission, so the declaration alone is what puts the field
    into ``AdminReadonlyField`` rather than the person's own permissions),
    and a person who may view the page but not change it, on
    ``concept_registered_admin_site`` (T005's fixture) — a bare registration
    that declares no ``readonly_fields`` at all, so ``ModelAdmin.get_form()``
    excluding every field once ``has_change_permission()`` is ``False`` is
    the only thing putting the field into ``AdminReadonlyField`` (scenario
    7). Both render the concept's preferred label and no control, and both
    pin what Django then renders: a link to the concept's own change page
    for the single-valued relation with ``Concept`` registered, plain text
    for the many-to-many.
    """

    def test_a_declared_readonly_field_links_to_the_concepts_own_change_page(
        self, admin_client, readonly_concept_site
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme, label="Granite")
        specimen = SpecimenFactory(rock_type=concept)

        with override_settings(ROOT_URLCONF=URLConf(readonly_concept_site)):
            response = admin_client.get(
                reverse("admin:testapp_specimen_change", args=[specimen.pk])
            )
            concept_change_url = reverse(
                "admin:controlled_vocabularies_concept_change", args=[concept.pk]
            )
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert f'<a href="{concept_change_url}">Granite</a>' in content

    def test_a_declared_readonly_field_renders_plain_text_for_a_many_to_many(
        self, admin_client, readonly_concept_site
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Mineral {i}") for i in range(2)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)

        with override_settings(ROOT_URLCONF=URLConf(readonly_concept_site)):
            response = admin_client.get(
                reverse("admin:testapp_outcrop_change", args=[outcrop.pk])
            )
            concept_change_urls = [
                reverse(
                    "admin:controlled_vocabularies_concept_change", args=[concept.pk]
                )
                for concept in concepts
            ]
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert ", ".join(concept.label for concept in concepts) in content
        for concept_change_url in concept_change_urls:
            assert concept_change_url not in content

    def test_a_view_only_users_undeclared_field_links_to_the_concepts_own_change_page(
        self, client, concept_registered_admin_site
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme, label="Basalt")
        specimen = SpecimenFactory(rock_type=concept)
        viewer = _view_only_staff_user("view_specimen")
        assert not viewer.has_perm("testapp.change_specimen")
        client.force_login(viewer)

        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = client.get(
                reverse("admin:testapp_specimen_change", args=[specimen.pk])
            )
            concept_change_url = reverse(
                "admin:controlled_vocabularies_concept_change", args=[concept.pk]
            )
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert f'<a href="{concept_change_url}">Basalt</a>' in content

    def test_a_view_only_users_undeclared_field_renders_plain_text_for_a_many_to_many(
        self, client, concept_registered_admin_site
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Viewer mineral {i}") for i in range(2)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)
        client.force_login(_view_only_staff_user("view_outcrop"))

        with override_settings(ROOT_URLCONF=URLConf(concept_registered_admin_site)):
            response = client.get(
                reverse("admin:testapp_outcrop_change", args=[outcrop.pk])
            )
            concept_change_urls = [
                reverse(
                    "admin:controlled_vocabularies_concept_change", args=[concept.pk]
                )
                for concept in concepts
            ]
        content = response.content.decode()

        assert response.status_code == 200
        assert "data-tomselect" not in content
        assert ", ".join(concept.label for concept in concepts) in content
        for concept_change_url in concept_change_urls:
            assert concept_change_url not in content


@pytest.fixture
def custom_admin_site():
    """A dedicated, non-default ``AdminSite`` instance registering ``Specimen``
    alongside a registered ``Concept`` — the same configuration
    ``concept_registered_admin_site`` (T005) uses for the default-adjacent
    sites this module already builds, so the four related-object affordances
    would appear here too if FR-007's guarantee were somehow bound to the
    default site rather than to the form field itself (research.md R2,
    decisions.md D9)."""
    site = admin.AdminSite(name="us5_custom")
    site.register(Specimen)
    site.register(Concept)
    return site


@pytest.mark.django_db
class TestCustomAdminSiteGetsTheSameBehaviour:
    """T015: FR-007, US-5 scenarios 3 and 4.

    ``custom_admin_site`` is a fresh ``AdminSite`` instance, never the
    default one ``tests/testapp/admin.py`` registers ``Specimen`` on — the
    declining behaviour (``forms.py``'s ``DeclinesAdminRelatedWrapperMixin``)
    lives on the form field, not on any particular site, so nothing here
    should differ from ``TestConceptControlRendersOnAdminPages`` (T002),
    ``TestConceptFieldOffersNoRelatedObjectAffordance`` (T005) or
    ``TestAdminSubmissionSavesAndFieldRulesStillBite`` (T004) beyond which
    site answers the request.
    """

    def test_add_page_renders_the_control_with_no_related_object_affordance(
        self, admin_client, custom_admin_site
    ):
        with override_settings(ROOT_URLCONF=URLConf(custom_admin_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        _assert_control_rendered(content, Specimen, "rock_type")
        _assert_no_related_object_affordance(content)

    def test_a_legitimate_concept_saves_through_the_custom_sites_add_page(
        self, admin_client, custom_admin_site
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)

        with override_settings(ROOT_URLCONF=URLConf(custom_admin_site)):
            response = admin_client.post(
                reverse("admin:testapp_specimen_add"),
                {
                    "name": "Custom site sample",
                    "rock_type": concept.pk,
                    "_save": "Save",
                },
            )

        assert response.status_code == 302
        specimen = Specimen.objects.get(name="Custom site sample")
        assert specimen.rock_type_id == concept.pk

    def test_an_ineligible_concept_is_refused_through_the_custom_sites_add_page(
        self, admin_client, custom_admin_site
    ):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        foreign_concept = ConceptFactory(scheme=other_scheme)

        with override_settings(ROOT_URLCONF=URLConf(custom_admin_site)):
            response = admin_client.post(
                reverse("admin:testapp_specimen_add"),
                {
                    "name": "Custom site wrong vocabulary",
                    "rock_type": foreign_concept.pk,
                    "_save": "Save",
                },
            )
        content = response.content.decode()

        assert response.status_code == 200
        assert not Specimen.objects.filter(name="Custom site wrong vocabulary").exists()
        assert 'id="id_rock_type_error"' in content

    def test_a_model_registered_on_both_the_default_site_and_a_custom_one_gets_the_control_on_both(
        self, admin_client, custom_admin_site
    ):
        """``Specimen`` is registered on the default site by
        ``tests/testapp/admin.py`` already; ``custom_admin_site`` registers
        it a second time, on a different ``AdminSite`` instance — the one
        configuration Django itself forbids on the *same* site (US-5
        scenario 4)."""
        default_response = admin_client.get(reverse("admin:testapp_specimen_add"))

        with override_settings(ROOT_URLCONF=URLConf(custom_admin_site)):
            custom_response = admin_client.get(reverse("admin:testapp_specimen_add"))

        assert default_response.status_code == 200
        assert custom_response.status_code == 200
        _assert_control_rendered(
            default_response.content.decode(), Specimen, "rock_type"
        )
        _assert_control_rendered(
            custom_response.content.decode(), Specimen, "rock_type"
        )
