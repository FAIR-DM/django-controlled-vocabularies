"""Tests for controlled_vocabularies.forms."""

import inspect
from pathlib import Path

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings
from django.utils import translation
from django.utils.functional import Promise
from django_tomselect.middleware import TomSelectMiddleware

from controlled_vocabularies import forms as forms_module
from controlled_vocabularies.forms import ConceptChoiceField, ConceptsChoiceField
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
    OutcropFactory,
    SampleFactory,
    collection_with_members,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import (
    BranchSample,
    ChipSample,
    CoreSample,
    Deposit,
    Outcrop,
    Sample,
)


def _rendered_under_an_ambient_request(build):
    """Render ``build()`` under an ambient request, as ``TomSelectMiddleware`` does.

    ``tests/settings.py`` installs no middleware, and without an ambient request
    ``TomSelectModelWidget.get_context()`` returns its base context.

    Args:
        build: Callable returning the string to render.

    Returns:
        What ``build()`` returned.
    """
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    return TomSelectMiddleware(lambda r: build())(request)


class SampleForm(forms.ModelForm):
    class Meta:
        model = Sample
        fields = ["name", "mineral"]


class DepositForm(forms.ModelForm):
    class Meta:
        model = Deposit
        fields = ["name", "rock_types"]


class OutcropForm(forms.ModelForm):
    class Meta:
        model = Outcrop
        fields = ["name", "minerals"]


class CoreSampleForm(forms.ModelForm):
    class Meta:
        model = CoreSample
        fields = ["name", "rock_type"]


class ChipSampleForm(forms.ModelForm):
    class Meta:
        model = ChipSample
        fields = ["name", "rock_type"]


class BranchSampleForm(forms.ModelForm):
    class Meta:
        model = BranchSample
        fields = ["name", "rock_type"]


class TestConceptFieldRendersAsTheControl:
    def test_a_concept_field_binds_this_packages_form_field_and_widget(self):
        bound_field = SampleForm().fields["mineral"]

        assert isinstance(bound_field, ConceptChoiceField)

    def test_a_concepts_field_binds_this_packages_form_field_and_widget(self):
        bound_field = DepositForm().fields["rock_types"]

        assert isinstance(bound_field, ConceptsChoiceField)


@pytest.mark.django_db
class TestConceptFieldRenderingIsBoundedByVocabularySize:
    def test_rendered_length_and_absence_of_labels_hold_for_a_small_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Small vocab concept {i}")
            for i in range(5)
        ]

        rendered = str(SampleForm())

        assert not any(concept.label in rendered for concept in concepts)

    def test_rendered_length_is_identical_for_a_large_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        for i in range(5):
            ConceptFactory(scheme=scheme, label=f"Small vocab concept {i}")
        small_rendered = str(SampleForm())

        large_concepts = [
            ConceptFactory(scheme=scheme, label=f"Large vocab concept {i}")
            for i in range(2000)
        ]
        large_rendered = str(SampleForm())

        assert len(large_rendered) == len(small_rendered)
        assert not any(concept.label in large_rendered for concept in large_concepts)


# The widget's get_queryset() builds the validation queryset from the model field, not
# from an ambient request, whose GET is empty during a POST.
@pytest.mark.django_db
class TestConceptFieldSubmissionSurvives:
    def test_a_legitimate_concept_is_valid_and_saves_for_a_concept_field(self):
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=mineral_scheme)

        form = SampleForm(data={"name": "Sample A", "mineral": concept.pk})

        assert form.is_valid(), form.errors
        instance = form.save()
        assert instance.mineral_id == concept.pk

    def test_a_foreign_concept_is_still_refused_for_a_concept_field(self):
        other_scheme = ConceptSchemeFactory(name="Rock Type")
        foreign_concept = ConceptFactory(scheme=other_scheme)

        form = SampleForm(data={"name": "Sample B", "mineral": foreign_concept.pk})

        assert not form.is_valid()
        assert "mineral" in form.errors

    def test_a_legitimate_concept_is_valid_and_saves_for_a_concepts_field(self):
        # Outcrop (blank=True), not Deposit: editing a saved record whose required
        # relation is still empty is refused for an unrelated reason (#124).
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=mineral_scheme)
        outcrop = OutcropFactory()

        form = OutcropForm(
            data={"name": "Outcrop A", "minerals": [concept.pk]}, instance=outcrop
        )

        assert form.is_valid(), form.errors
        instance = form.save()
        assert list(instance.minerals.values_list("pk", flat=True)) == [concept.pk]

    def test_a_foreign_concept_is_still_refused_for_a_concepts_field(self):
        other_scheme = ConceptSchemeFactory(name="Rock Type")
        foreign_concept = ConceptFactory(scheme=other_scheme)
        outcrop = OutcropFactory()

        form = OutcropForm(
            data={"name": "Outcrop B", "minerals": [foreign_concept.pk]},
            instance=outcrop,
        )

        assert not form.is_valid()
        assert "minerals" in form.errors


@pytest.mark.django_db
class TestConceptFieldCollectionRestrictionFormChoices:
    def test_the_modelforms_own_queryset_is_exactly_the_members(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        choices = list(CoreSampleForm().fields["rock_type"].queryset)

        assert set(choices) == set(members)
        assert len(choices) == len(members)
        assert outsider not in choices

    def test_the_widgets_own_queryset_is_exactly_the_members(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        widget = CoreSampleForm().fields["rock_type"].widget
        choices = list(widget.get_queryset())

        assert set(choices) == set(members)
        assert len(choices) == len(members)
        assert outsider not in choices

    def test_a_member_of_a_second_collection_too_is_not_duplicated_on_either_path(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        other_collection = CollectionFactory(scheme=scheme, name="Display Samples")
        other_collection.add(members[0])

        form = CoreSampleForm()
        modelform_choices = list(form.fields["rock_type"].queryset)
        widget_choices = list(form.fields["rock_type"].widget.get_queryset())

        assert modelform_choices == [members[0]]
        assert widget_choices == [members[0]]


@pytest.mark.django_db
class TestConceptFieldConceptsRestrictionFormChoices:
    def test_the_modelforms_own_queryset_is_exactly_the_listed_concepts(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        choices = list(ChipSampleForm().fields["rock_type"].queryset)

        assert set(choices) == {granite, basalt}
        assert len(choices) == 2
        assert outsider not in choices

    def test_the_widgets_own_queryset_is_exactly_the_listed_concepts(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        widget = ChipSampleForm().fields["rock_type"].widget
        choices = list(widget.get_queryset())

        assert set(choices) == {granite, basalt}
        assert len(choices) == 2
        assert outsider not in choices


@pytest.mark.django_db
class TestConceptFieldBranchRestrictionFormChoices:
    def test_the_modelforms_own_queryset_is_exactly_the_closure(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        child.add_broader(root)
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        choices = list(BranchSampleForm().fields["rock_type"].queryset)

        assert set(choices) == {root, child}
        assert len(choices) == 2
        assert outsider not in choices

    def test_the_widgets_own_queryset_is_exactly_the_closure(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        child.add_broader(root)
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        widget = BranchSampleForm().fields["rock_type"].widget
        choices = list(widget.get_queryset())

        assert set(choices) == {root, child}
        assert len(choices) == 2
        assert outsider not in choices

    def test_a_concept_added_below_the_root_appears_on_the_next_read(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")

        form = BranchSampleForm()
        assert set(form.fields["rock_type"].queryset) == {root}

        newcomer = ConceptFactory(scheme=scheme, label="Granite")
        newcomer.add_broader(root)

        form_again = BranchSampleForm()
        assert set(form_again.fields["rock_type"].queryset) == {root, newcomer}


class TestConceptFieldRenderingWithoutTheRouteIncluded:
    @override_settings(ROOT_URLCONF=())
    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_rendering_raises_improperlyconfigured(self, form_class):
        with pytest.raises(ImproperlyConfigured):
            str(form_class())


@pytest.mark.django_db
class TestConceptFieldShowsWhatARecordAlreadyHolds:
    def test_a_concept_field_shows_the_attached_concept_under_its_active_language_label(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme, multilingual=True, label="Quartz")
        sample = SampleFactory(mineral=concept)

        with translation.override("de"):
            rendered = _rendered_under_an_ambient_request(
                lambda: str(SampleForm(instance=sample))
            )

        assert concept.preferred_label("de") in rendered
        assert "Quartz" not in rendered

    def test_a_concepts_field_shows_every_attached_concept_under_its_active_language_label(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, multilingual=True, label=f"Concept {i}")
            for i in range(3)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)

        with translation.override("de"):
            rendered = _rendered_under_an_ambient_request(
                lambda: str(OutcropForm(instance=outcrop))
            )

        for concept in concepts:
            assert concept.preferred_label("de") in rendered

    def test_submitting_the_concepts_field_form_untouched_leaves_all_three_attached(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Concept {i}") for i in range(3)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)

        form = OutcropForm(
            data={
                "name": outcrop.name,
                "minerals": [concept.pk for concept in concepts],
            },
            instance=outcrop,
        )

        assert form.is_valid(), form.errors
        instance = form.save()
        assert set(instance.minerals.values_list("pk", flat=True)) == {
            concept.pk for concept in concepts
        }

    def test_removing_one_attached_concept_and_saving_removes_exactly_that_one(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            ConceptFactory(scheme=scheme, label=f"Concept {i}") for i in range(3)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)
        kept = concepts[:2]

        form = OutcropForm(
            data={"name": outcrop.name, "minerals": [concept.pk for concept in kept]},
            instance=outcrop,
        )

        assert form.is_valid(), form.errors
        instance = form.save()
        assert set(instance.minerals.values_list("pk", flat=True)) == {
            concept.pk for concept in kept
        }

    def test_a_concept_field_still_shows_an_attached_concept_outside_the_current_vocabulary(
        self,
    ):
        # The stock widget drops it: _get_selected_options() resolves the value
        # through the same narrowed get_queryset() that validation uses.
        outside_scheme = ConceptSchemeFactory(name="Rock Type")
        outside_concept = ConceptFactory(scheme=outside_scheme, label="Basalt")
        sample = SampleFactory(mineral=outside_concept)

        rendered = _rendered_under_an_ambient_request(
            lambda: str(SampleForm(instance=sample))
        )

        assert "Basalt" in rendered

    def test_a_concepts_field_still_shows_an_attached_concept_outside_the_current_vocabulary(
        self,
    ):
        # Attaching a foreign concept is refused, so the state is reached the way an
        # editor recategorising a concept reaches it: reassign its scheme afterwards.
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=mineral_scheme, label="Basalt")
        outcrop = OutcropFactory()
        outcrop.minerals.add(concept)

        other_scheme = ConceptSchemeFactory(name="Rock Type")
        concept.scheme = other_scheme
        concept.save()

        rendered = _rendered_under_an_ambient_request(
            lambda: str(OutcropForm(instance=outcrop))
        )

        assert "Basalt" in rendered


@pytest.mark.django_db
# Every other render test asserts an absence or a form field class, and none would
# notice a page with no search control, which is what a project without
# TomSelectMiddleware gets.
class TestTheControlIsActuallyInstantiated:
    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_the_page_carries_the_instantiated_control(self, form_class):
        rendered = _rendered_under_an_ambient_request(lambda: str(form_class()))

        assert "new TomSelect" in rendered

    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_the_page_carries_no_control_without_the_ambient_request(self, form_class):
        rendered = str(form_class())

        assert "new TomSelect" not in rendered


@pytest.mark.django_db
# ConceptWidgetDisplayMixin widens get_queryset() for one library call. Without the
# restore the widget would validate later submissions against every concept.
class TestDisplayingAnAttachedConceptLeavesValidationNarrow:
    @pytest.mark.parametrize(
        ("form_class", "field_name", "instance_factory"),
        [
            (SampleForm, "mineral", SampleFactory),
            (OutcropForm, "minerals", OutcropFactory),
        ],
    )
    def test_the_widget_queryset_is_narrow_again_after_a_render(
        self, form_class, field_name, instance_factory
    ):
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        attached = ConceptFactory(scheme=mineral_scheme)
        foreign = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        instance = instance_factory()
        if field_name == "mineral":
            instance.mineral = attached
            instance.save()
        else:
            instance.minerals.add(attached)

        form = form_class(instance=instance)
        widget = form.fields[field_name].widget
        _rendered_under_an_ambient_request(lambda: str(form))

        assert "get_queryset" not in widget.__dict__
        assert not widget.get_queryset().filter(pk=foreign.pk).exists()


# Each test mirrors ModelAdmin: wrap the field's own widget, then assign the wrapper
# back.
class TestConceptFieldDeclinesTheAdminWrapper:
    def test_a_concept_field_unwraps_a_related_field_widget_wrapper_to_its_own_widget(
        self,
    ):
        model_field = Sample._meta.get_field("mineral")
        field = ConceptChoiceField(model_field=model_field, required=False)
        original_widget = field.widget
        wrapper = RelatedFieldWidgetWrapper(
            field.widget, model_field.remote_field, AdminSite()
        )

        field.widget = wrapper

        assert field.widget is original_widget
        assert field.widget.model_field is model_field

    def test_a_concept_field_holds_an_ordinary_widget_as_given(self):
        model_field = Sample._meta.get_field("mineral")
        field = ConceptChoiceField(model_field=model_field, required=False)
        ordinary_widget = forms.TextInput()

        field.widget = ordinary_widget

        assert field.widget is ordinary_widget

    def test_a_concepts_field_unwraps_a_related_field_widget_wrapper_to_its_own_widget(
        self,
    ):
        model_field = Outcrop._meta.get_field("minerals")
        field = ConceptsChoiceField(model_field=model_field, required=False)
        original_widget = field.widget
        wrapper = RelatedFieldWidgetWrapper(
            field.widget, model_field.remote_field, AdminSite()
        )

        field.widget = wrapper

        assert field.widget is original_widget
        assert field.widget.model_field is model_field

    def test_a_concepts_field_holds_an_ordinary_widget_as_given(self):
        model_field = Outcrop._meta.get_field("minerals")
        field = ConceptsChoiceField(model_field=model_field, required=False)
        ordinary_widget = forms.SelectMultiple()

        field.widget = ordinary_widget

        assert field.widget is ordinary_widget


# The listener in concept-inline.js is browser behaviour, so these tests check only that
# it ships.
class TestConceptWidgetsShipTheInlineInitialisationScript:
    _ASSET = "controlled_vocabularies/js/concept-inline.js"

    def test_the_asset_is_discoverable_as_a_static_file(self):
        from django.contrib.staticfiles.finders import find

        assert find(self._ASSET) is not None

    def test_the_concept_widget_declares_the_asset_in_its_media(self):
        widget = ConceptChoiceField(
            model_field=Sample._meta.get_field("mineral"), required=False
        ).widget

        assert self._ASSET in widget.media._js

    def test_the_concepts_widget_declares_the_asset_in_its_media(self):
        widget = ConceptsChoiceField(
            model_field=Outcrop._meta.get_field("minerals"), required=False
        ).widget

        assert self._ASSET in widget.media._js


class TestFormsI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(forms_module)).read_text()
        visitor = visit_fields_checks_source(source)
        assert visitor.bare_literals == [], (
            f"{forms_module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{forms_module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )


class TestMissingRouteMessage:
    def test_missing_route_message_is_a_lazy_translation(self):
        assert isinstance(forms_module._MISSING_ROUTE_MESSAGE, Promise), (
            "_MISSING_ROUTE_MESSAGE is not lazily translatable"
        )
