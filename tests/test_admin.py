"""Tests for the concept fields in the Django admin."""

import inspect
import re
from pathlib import Path

import pytest
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import ProtectedError
from django.test import override_settings
from django.urls import include, path, reverse

from controlled_vocabularies import admin as admin_module
from controlled_vocabularies.models import Concept
from tests.factories import (
    ConceptFactory,
    ConceptSchemeFactory,
    LocalityFactory,
    OutcropFactory,
    SpecimenFactory,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import Locality, Outcrop, Specimen


def _field_reference(model, field_name):
    """Return the ``<app_label>.<model>.<field_name>`` reference the widget sends.

    Args:
        model: The model class declaring the field.
        field_name: The name of the concept field on ``model``.

    Returns:
        The dotted reference the autocomplete endpoint resolves.
    """
    return f"{model._meta.app_label}.{model._meta.model_name}.{field_name}"


def _assert_control_rendered(content, model, field_name):
    """Assert the page carries the control for one field, wired to its own reference.

    The select carries ``data-tomselect``, the widget's configuration script is on
    the page, and the autocomplete reference is present, escaped as ``escapejs``
    renders it.

    Args:
        content: The rendered page.
        model: The model class declaring the field.
        field_name: The name of the concept field on ``model``.
    """
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


# The widget reverses concept-autocomplete while rendering, so the urlconf must include
# this package's urls. A plain object, not SimpleNamespace: its value-based __eq__
# makes it unhashable for the resolver cache.
class URLConf:
    """A ``ROOT_URLCONF`` mounting one admin site plus this package's own route.

    Args:
        site: The ``AdminSite`` mounted under ``admin/``.
    """

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
    """Assert no related-object link ``RelatedFieldWidgetWrapper`` renders.

    Args:
        content: The rendered page.
    """
    # Not data-context="available-source": the wrapper writes it onto the wrapped
    # widget's attrs before it is unwrapped, so it survives harmlessly.
    for marker in _RELATED_OBJECT_AFFORDANCE_MARKERS:
        assert marker not in content


@pytest.fixture
def concept_registered_admin_site():
    # Never the default site: it already registers Specimen and Outcrop, and Django
    # refuses to register a model twice on one site.
    site = admin.AdminSite(name="us2_with_concept")
    site.register(Specimen)
    site.register(Outcrop)
    site.register(Concept)
    return site


@pytest.fixture
def bare_admin_site():
    site = admin.AdminSite(name="us2_without_concept")
    site.register(Specimen)
    site.register(Outcrop)
    return site


@pytest.mark.django_db
class TestConceptFieldOffersNoRelatedObjectAffordance:
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
        # Django suppresses the links itself when the related model is unregistered,
        # so this passes with or without the unwrap. The tests above are the ones
        # that go red if the unwrap regresses.
        with override_settings(ROOT_URLCONF=URLConf(bare_admin_site)):
            response = admin_client.get(reverse("admin:testapp_specimen_add"))
        content = response.content.decode()

        assert response.status_code == 200
        _assert_no_related_object_affordance(content)
        _assert_control_rendered(content, Specimen, "rock_type")


class SpecimenTabularInline(admin.TabularInline):
    """``Specimen`` inline with ``extra = 1``."""

    model = Specimen
    extra = 1


class SpecimenStackedInline(admin.StackedInline):
    """``Specimen`` inline with ``extra = 0``: no numbered row until one is added."""

    model = Specimen
    extra = 0


class LocalityTabularAdmin(admin.ModelAdmin):
    inlines = [SpecimenTabularInline]


class LocalityStackedAdmin(admin.ModelAdmin):
    inlines = [SpecimenStackedInline]


@pytest.fixture
def locality_tabular_site():
    site = admin.AdminSite(name="us3_locality_tabular")
    site.register(Locality, LocalityTabularAdmin)
    return site


@pytest.fixture
def locality_stacked_site():
    site = admin.AdminSite(name="us3_locality_stacked")
    site.register(Locality, LocalityStackedAdmin)
    return site


def _assert_inline_row_control_rendered(content, model, field_name, prefix, index):
    """Assert a saved inline row carries the control, under the row's own element id.

    Args:
        content: The rendered page.
        model: The model class declaring the field.
        field_name: The name of the concept field on ``model``.
        prefix: The inline formset prefix.
        index: The row's position in the formset.
    """
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
        locality = LocalityFactory()

        with override_settings(ROOT_URLCONF=URLConf(locality_tabular_site)):
            response = admin_client.get(
                reverse("admin:testapp_locality_change", args=[locality.pk])
            )
        content = response.content.decode()

        # Mirrors concept-inline.js: only the innermost -<digits>- segment belongs to
        # the row being added, which matters under a third-party nested inline.
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
    """Admin naming ``rock_type`` in ``autocomplete_fields``."""

    autocomplete_fields = ["rock_type"]


class ConceptSearchAdmin(admin.ModelAdmin):
    """Admin registering ``Concept`` with the ``search_fields`` autocomplete needs."""

    search_fields = ["label"]


class RawIdSpecimenAdmin(admin.ModelAdmin):
    """Admin naming ``rock_type`` in ``raw_id_fields``."""

    raw_id_fields = ["rock_type"]


class DeclaredWidgetSpecimenForm(forms.ModelForm):
    """Form declaring its own widget for ``rock_type`` through ``Meta.widgets``."""

    class Meta:
        model = Specimen
        fields = "__all__"
        widgets = {"rock_type": forms.Select()}


class DeclaredWidgetSpecimenAdmin(admin.ModelAdmin):
    form = DeclaredWidgetSpecimenForm


@pytest.fixture
def autocomplete_site():
    site = admin.AdminSite(name="us4_autocomplete")
    site.register(Specimen, AutocompleteSpecimenAdmin)
    site.register(Concept, ConceptSearchAdmin)
    return site


@pytest.fixture
def raw_id_site():
    site = admin.AdminSite(name="us4_raw_id")
    site.register(Specimen, RawIdSpecimenAdmin)
    return site


@pytest.fixture
def declared_widget_site():
    site = admin.AdminSite(name="us4_declared_widget")
    site.register(Specimen, DeclaredWidgetSpecimenAdmin)
    site.register(Concept, ConceptSearchAdmin)
    return site


@pytest.mark.django_db
class TestExplicitDeclarationWins:
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
    """Admin naming the single-valued ``rock_type`` in ``readonly_fields``."""

    readonly_fields = ["rock_type"]


class ReadOnlyMineralsOutcropAdmin(admin.ModelAdmin):
    """Admin naming the multi-valued ``minerals`` in ``readonly_fields``."""

    readonly_fields = ["minerals"]


@pytest.fixture
def readonly_concept_site():
    site = admin.AdminSite(name="us4_readonly")
    site.register(Specimen, ReadOnlyRockTypeSpecimenAdmin)
    site.register(Outcrop, ReadOnlyMineralsOutcropAdmin)
    site.register(Concept)
    return site


def _view_only_staff_user(*codenames):
    """Return a saved staff user holding exactly the named ``view_*`` permissions.

    Args:
        *codenames: The ``view_*`` permission codenames to grant.

    Returns:
        A user who may view the page but never change it.
    """
    # No password: callers use ``force_login``, and a literal would be a
    # credential-shaped string in the repository for nothing.
    user = get_user_model().objects.create_user(
        username="readonly-viewer", is_staff=True
    )
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return user


@pytest.mark.django_db
class TestReadOnlyPresentationRendersNoControl:
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
    site = admin.AdminSite(name="us5_custom")
    site.register(Specimen)
    site.register(Concept)
    return site


@pytest.mark.django_db
class TestCustomAdminSiteGetsTheSameBehaviour:
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


class TestAdminModuleI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(admin_module)).read_text()
        visitor = visit_fields_checks_source(source)
        assert visitor.bare_literals == [], (
            f"{admin_module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{admin_module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
