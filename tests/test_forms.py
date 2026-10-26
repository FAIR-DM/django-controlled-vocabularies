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
    ConceptSchemeFactory,
    OutcropFactory,
    RecordFactory,
    SampleFactory,
    collection_with_members,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import CoreSample, Deposit, Outcrop, Sample


def rendered_under_an_ambient_request(build):
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


def bilingual(english, german):
    """Return a document naming its subject in English and in German.

    Args:
        english: The English preferred label.
        german: The German preferred label.

    Returns:
        The document.
    """
    return {
        "skos:prefLabel": [
            {"@value": english, "@language": "en"},
            {"@value": german, "@language": "de"},
        ]
    }


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
        labels = [f"Small vocab concept {i}" for i in range(5)]
        for label in labels:
            RecordFactory(scheme=scheme, label=label)

        rendered = str(SampleForm())

        assert not any(label in rendered for label in labels)

    def test_rendered_length_is_identical_for_a_large_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        for i in range(5):
            RecordFactory(scheme=scheme, label=f"Small vocab concept {i}")
        small_rendered = str(SampleForm())

        large_labels = [f"Large vocab concept {i}" for i in range(500)]
        for label in large_labels:
            RecordFactory(scheme=scheme, label=label)
        large_rendered = str(SampleForm())

        assert len(large_rendered) == len(small_rendered)
        assert not any(label in large_rendered for label in large_labels)


# The widget's get_queryset() builds the validation queryset from the model field, not
# from an ambient request, whose GET is empty during a POST.
@pytest.mark.django_db
class TestConceptFieldSubmissionSurvives:
    def test_a_legitimate_concept_is_valid_and_saves_for_a_concept_field(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        form = SampleForm(data={"name": "Sample A", "mineral": concept.pk})

        assert form.is_valid(), form.errors
        instance = form.save()
        assert instance.mineral_id == concept.pk

    def test_a_foreign_concept_is_still_refused_for_a_concept_field(self):
        foreign_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))

        form = SampleForm(data={"name": "Sample B", "mineral": foreign_concept.pk})

        assert not form.is_valid()
        assert form.has_error("mineral")

    def test_a_collection_is_refused_for_a_concept_field(self):
        collection, members = collection_with_members(
            scheme=ConceptSchemeFactory(name="Mineral")
        )

        form = SampleForm(data={"name": "Sample C", "mineral": collection.pk})

        assert not form.is_valid()
        assert form.has_error("mineral")

    def test_a_legitimate_concept_is_valid_and_saves_for_a_concepts_field(self):
        # Outcrop (blank=True), not Deposit: editing a saved row whose required
        # relation is still empty is refused for an unrelated reason (#124).
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        outcrop = OutcropFactory()

        form = OutcropForm(
            data={"name": "Outcrop A", "minerals": [concept.pk]}, instance=outcrop
        )

        assert form.is_valid(), form.errors
        instance = form.save()
        assert list(instance.minerals.values_list("pk", flat=True)) == [concept.pk]

    def test_a_foreign_concept_is_still_refused_for_a_concepts_field(self):
        foreign_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        outcrop = OutcropFactory()

        form = OutcropForm(
            data={"name": "Outcrop B", "minerals": [foreign_concept.pk]},
            instance=outcrop,
        )

        assert not form.is_valid()
        assert form.has_error("minerals")


@pytest.mark.django_db
class TestConceptFieldCollectionRestrictionFormChoices:
    def test_the_modelforms_own_queryset_is_exactly_the_members(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = RecordFactory(scheme=scheme, label="Marble")

        choices = list(CoreSampleForm().fields["rock_type"].queryset)

        assert set(choices) == set(members)
        assert len(choices) == len(members)
        assert outsider not in choices

    def test_the_widgets_own_queryset_is_exactly_the_members(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = RecordFactory(scheme=scheme, label="Marble")

        widget = CoreSampleForm().fields["rock_type"].widget
        choices = list(widget.get_queryset())

        assert set(choices) == set(members)
        assert len(choices) == len(members)
        assert outsider not in choices

    def test_a_member_added_to_the_collection_appears_on_the_next_read(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        assert set(CoreSampleForm().fields["rock_type"].queryset) == set(members)

        newcomer = RecordFactory(scheme=scheme, label="Basalt")
        collection.data["skos:member"].append({"@id": newcomer.uri})
        collection.save()

        choices = set(CoreSampleForm().fields["rock_type"].queryset)
        assert choices == {*members, newcomer}


class TestConceptFieldRenderingWithoutTheRouteIncluded:
    @override_settings(ROOT_URLCONF=())
    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_rendering_raises_improperlyconfigured(self, form_class):
        with pytest.raises(ImproperlyConfigured):
            str(form_class())


@pytest.mark.django_db
class TestConceptFieldShowsWhatARowAlreadyHolds:
    def test_a_concept_field_shows_the_attached_concept_under_its_active_language_label(
        self,
    ):
        concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Mineral"),
            data=bilingual("Quartz", "Quarz"),
        )
        sample = SampleFactory(mineral=concept)

        with translation.override("de"):
            rendered = rendered_under_an_ambient_request(
                lambda: str(SampleForm(instance=sample))
            )

        assert "Quarz" in rendered
        assert "Quartz" not in rendered

    def test_a_concepts_field_shows_every_attached_concept_under_its_active_language_label(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [
            RecordFactory(scheme=scheme, data=bilingual(f"Concept {i}", f"Begriff {i}"))
            for i in range(3)
        ]
        outcrop = OutcropFactory()
        outcrop.minerals.add(*concepts)

        with translation.override("de"):
            rendered = rendered_under_an_ambient_request(
                lambda: str(OutcropForm(instance=outcrop))
            )

        for i in range(3):
            assert f"Begriff {i}" in rendered
            assert f"Concept {i}" not in rendered

    def test_submitting_the_concepts_field_form_untouched_leaves_all_three_attached(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concepts = [RecordFactory(scheme=scheme) for _ in range(3)]
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
        concepts = [RecordFactory(scheme=scheme) for _ in range(3)]
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
        outside_concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock Type"), label="Basalt"
        )
        sample = SampleFactory(mineral=outside_concept)

        rendered = rendered_under_an_ambient_request(
            lambda: str(SampleForm(instance=sample))
        )

        assert "Basalt" in rendered

    def test_a_concepts_field_still_shows_an_attached_concept_outside_the_current_vocabulary(
        self,
    ):
        # Attaching a foreign concept is refused, so the state is reached the way an
        # editor recategorising a concept reaches it: reassign its scheme afterwards.
        concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Mineral"), label="Basalt"
        )
        outcrop = OutcropFactory()
        outcrop.minerals.add(concept)

        concept.scheme = ConceptSchemeFactory(name="Rock Type")
        concept.save()

        rendered = rendered_under_an_ambient_request(
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
        rendered = rendered_under_an_ambient_request(lambda: str(form_class()))

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
        attached = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        foreign = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        instance = instance_factory()
        if field_name == "mineral":
            instance.mineral = attached
            instance.save()
        else:
            instance.minerals.add(attached)

        form = form_class(instance=instance)
        widget = form.fields[field_name].widget
        rendered_under_an_ambient_request(lambda: str(form))

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
    ASSET = "controlled_vocabularies/js/concept-inline.js"

    def test_the_asset_is_discoverable_as_a_static_file(self):
        from django.contrib.staticfiles.finders import find

        assert find(self.ASSET) is not None

    def test_the_concept_widget_declares_the_asset_in_its_media(self):
        widget = ConceptChoiceField(
            model_field=Sample._meta.get_field("mineral"), required=False
        ).widget

        assert self.ASSET in widget.media._js

    def test_the_concepts_widget_declares_the_asset_in_its_media(self):
        widget = ConceptsChoiceField(
            model_field=Outcrop._meta.get_field("minerals"), required=False
        ).widget

        assert self.ASSET in widget.media._js


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
        assert isinstance(forms_module.MISSING_ROUTE_MESSAGE, Promise), (
            "MISSING_ROUTE_MESSAGE is not lazily translatable"
        )
