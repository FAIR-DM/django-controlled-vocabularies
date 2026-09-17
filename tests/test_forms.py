"""Tests for ``controlled_vocabularies.forms`` (T004, FR-001, FR-003, FR-009).

``TestConceptFieldRendersAsTheControl`` — an ordinary ``ModelForm`` built from a
consuming model, with no widget declared and no form field declared, gets this
package's control from ``ConceptFieldMixin.formfield()`` alone (FR-001).

``TestConceptFieldRenderingIsBoundedByVocabularySize`` — FR-003 properly: the
control renders no concept into the page, so the rendered length and the absence
of any concept's label hold identically whether the vocabulary is five concepts
or several thousand.

``TestConceptFieldSubmissionSurvives`` — decisions.md D12 is the point of this
task: the widget's own ``get_queryset()`` builds the validation queryset from the
model field instance directly, with no request consulted, so a legitimate
submission does not fail with ``invalid_choice`` the way it would if validation
fell back to the library's default (an ambient request whose ``GET`` is empty
during a POST). Both the single- (``ConceptField``) and multiple-valued
(``ConceptsField``) fields are proved, and a foreign concept is still refused —
FR-009 promises nothing already guaranteed was taken away.
"""

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings
from django.utils import translation
from django_tomselect.middleware import TomSelectMiddleware

from controlled_vocabularies.forms import ConceptChoiceField, ConceptsChoiceField
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
    OutcropFactory,
    SampleFactory,
    collection_with_members,
)
from tests.testapp.models import (
    BranchSample,
    ChipSample,
    CoreSample,
    Deposit,
    Outcrop,
    Sample,
)


def _rendered_under_an_ambient_request(build):
    """Render ``build()`` (a callable returning the string to render) under an
    ambient request, the way ``TomSelectMiddleware`` supplies one for every real
    HTTP response. ``tests/settings.py`` installs no middleware, so nothing else
    sets ``django_tomselect``'s thread-local request — without one,
    ``TomSelectModelWidget.get_context()`` returns its base context before ever
    reaching ``_get_selected_options()``: it requires ``request`` truthy and
    ``validate_request(request)``, and the latter requires ``request.user``
    (confirmed against the installed wheel, ``2026.6.2``, ``widgets.py:619-633``
    and ``widgets.py:1093-1116``, not against the README).
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
    """No widget declared, no form field declared — the field alone is enough (FR-001)."""

    def test_a_concept_field_binds_this_packages_form_field_and_widget(self):
        bound_field = SampleForm().fields["mineral"]

        assert isinstance(bound_field, ConceptChoiceField)

    def test_a_concepts_field_binds_this_packages_form_field_and_widget(self):
        bound_field = DepositForm().fields["rock_types"]

        assert isinstance(bound_field, ConceptsChoiceField)


@pytest.mark.django_db
class TestConceptFieldRenderingIsBoundedByVocabularySize:
    """FR-003: rendering never loads the vocabulary into the page."""

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


@pytest.mark.django_db
class TestConceptFieldSubmissionSurvives:
    """decisions.md D12: the widget's own get_queryset() is what makes a submission
    of a legitimate concept survive validation, on both fields' shapes.

    The ``ConceptsField`` half uses :class:`Outcrop` (``minerals``, ``blank=True``)
    rather than :class:`Deposit`, to keep the assertions on D12 alone. A *required*
    ``ConceptsField`` has one submission path of its own that fails for an unrelated,
    pre-existing reason (#124): editing a saved record whose relation is still empty.
    ``_post_clean()`` runs model-level ``full_clean()`` — and so FS-010's
    ``_install_required_set_check`` — before ``save_m2m()`` has attached anything, so
    the submission that would populate the relation is the one refused. Creating a
    record is unaffected: the check skips an instance with no primary key. Nothing
    here is D12's widget queryset.
    """

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
    """T009 (US-1, FR-008's choices half) — a collection restriction narrows
    the offered choices on both paths a form can build them from:
    :class:`~django.forms.ModelChoiceField`'s own ``queryset`` (Django's
    ``Exists()`` wrapper around ``limit_choices_to``) and this package's own
    widget ``get_queryset()`` (a bare ``complex_filter()``, unprotected —
    research.md R3). No duplicate rows on either path for a concept that
    belongs to a second collection too, asserted by count rather than only
    by membership — the assertion that would fail if the restriction were
    ever rewritten as a ``collection_memberships__…`` join."""

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
    """T014 (US-2, FR-008's choices half, "as T009, for this axis") — a
    ``concepts`` restriction narrows the offered choices on both paths a
    form can build them from, asserted by count as well as by membership,
    through :class:`~tests.testapp.models.ChipSample`, restricted to
    "granite" and "basalt"."""

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
    """T018 (US-3, FR-008's choices half, "as T009, for this axis") — a
    ``branch`` restriction narrows the offered choices on both paths a form
    can build them from, asserted by count as well as by membership,
    through :class:`~tests.testapp.models.BranchSample`, restricted to the
    "igneous" branch."""

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
        # As T010 asserts for collection membership.
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")

        form = BranchSampleForm()
        assert set(form.fields["rock_type"].queryset) == {root}

        newcomer = ConceptFactory(scheme=scheme, label="Granite")
        newcomer.add_broader(root)

        form_again = BranchSampleForm()
        assert set(form_again.fields["rock_type"].queryset) == {root, newcomer}


class TestConceptFieldRenderingWithoutTheRouteIncluded:
    """T008, decisions.md D14: a project that ignores the system check's warning
    still reaches a render. The library's own ``get_autocomplete_url()`` would
    re-raise ``NoReverseMatch`` verbatim there — a message naming a URL pattern
    the developer never wrote. This widget catches it and raises
    ``ImproperlyConfigured`` naming both wiring steps instead, so the assertion
    is on the message, not the exception type alone.

    Both widgets carry the mixin, so both are asserted: the single-valued and the
    many-valued field reach the render through different widget classes, and one
    covered on its own leaves the other free to raise the library's own error."""

    @override_settings(ROOT_URLCONF=())
    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_rendering_raises_improperlyconfigured_naming_both_steps(self, form_class):
        with pytest.raises(ImproperlyConfigured) as exc_info:
            str(form_class())

        message = str(exc_info.value)
        assert "controlled_vocabularies.urls" in message
        assert "INSTALLED_APPS" in message


@pytest.mark.django_db
class TestConceptFieldShowsWhatARecordAlreadyHolds:
    """T009, FR-008, plan.md A8, decisions.md D12: an existing record's attached
    concept renders unrestricted, because A6 path two narrows
    ``ConceptWidgetValidationMixin.get_queryset()`` to the field's current
    declaration and the library resolves already-selected values through that
    same method (``widgets.py:965``). What a record already holds is displayed
    unrestricted; what a submission newly contains is still validated against
    the declaration — the validation path (T004) is untouched, and its own
    refusal tests above still pass.

    Both fields' shapes are covered independently: :class:`Sample`'s
    ``mineral`` (the single-valued ``ConceptField``, ``ConceptWidget``) and
    :class:`Outcrop`'s ``minerals`` (the multiple-valued ``ConceptsField``,
    ``ConceptsWidget``). Each reaches the render through a different widget
    class, so a property proved for one alone would leave the other free to
    regress — the exact gap T008 found and repaired.
    """

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
        """The un-overridden widget drops this concept (plan.md A8, R1): the
        record already holds it, but ``_get_selected_options()`` resolves it
        through the same narrowed ``get_queryset()`` the validation path uses,
        and this concept's scheme is not the field's declared vocabulary."""
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
        """The multiple-valued field's own widget class, proved independently
        (see the single-valued case above for why the un-overridden widget
        drops it).

        ``fields.py``'s ``_refuse_concepts_the_restriction_does_not_admit`` (an
        ``m2m_changed`` receiver) refuses ``.add()``ing a concept outside the
        vocabulary outright, by design (D2) — so unlike the single-valued
        case above, a concept cannot be attached directly from a foreign
        scheme. The realistic route to the same state is the one that
        receiver does not — and, by its own docstring, is not meant to —
        guard against: the concept is attached while still in-vocabulary,
        then its *own* scheme is reassigned afterwards, exactly as an editor
        recategorising a concept would leave it.
        """
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
class TestTheControlIsActuallyInstantiated:
    """US-6 repair, decisions.md D15 — every other render assertion in this module
    is about what the page does *not* carry (no concept labels, FR-003) or about
    which form field class is bound (FR-001). None of them would notice the page
    carrying no search control at all, which is exactly what a project missing
    ``TomSelectMiddleware`` gets: ``get_context()`` returns its base context and
    the ``<select>`` is rendered with no JavaScript to turn it into one.

    Asserted for both widget classes, and asserted the other way round too — the
    same render without the ambient request must NOT carry it, or the assertion
    proves nothing about the middleware."""

    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_the_page_carries_the_instantiated_control(self, form_class):
        rendered = _rendered_under_an_ambient_request(lambda: str(form_class()))

        assert "new TomSelect" in rendered

    @pytest.mark.parametrize("form_class", [SampleForm, DepositForm])
    def test_the_page_carries_no_control_without_the_ambient_request(self, form_class):
        rendered = str(form_class())

        assert "new TomSelect" not in rendered


@pytest.mark.django_db
class TestDisplayingAnAttachedConceptLeavesValidationNarrow:
    """US-6 repair — ``ConceptWidgetDisplayMixin`` widens ``get_queryset()`` for
    the duration of one library call and must leave it exactly as it found it.
    Without the restore, the same widget instance validates every later
    submission against every concept, which is the leak D12 exists to prevent,
    and no other test in the suite notices."""

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


class TestConceptFieldDeclinesTheAdminWrapper:
    """T007: FR-004, FR-005. ``tests/test_admin.py``'s
    ``TestConceptFieldOffersNoRelatedObjectAffordance`` (T005) proves the
    outcome at a rendered admin page; this proves the seam
    ``DeclinesAdminRelatedWrapperMixin`` owns directly, at the form-field level.

    Each test mirrors exactly what ``options.py:215`` does: wrap the field's
    own already-built widget, then assign the wrapper back onto ``widget`` —
    so "model_field binding intact" means the field holds the very same
    widget instance it already carried, not a freshly constructed one."""

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


class TestConceptWidgetsShipTheInlineInitialisationScript:
    """T010: FR-003, US-3 scenarios 2 and 5 — the asset ships in the package
    and is declared in both widgets' ``Media`` (decisions.md D12). The
    listener itself, ``concept-inline.js``, is browser behaviour and is a
    documented manual check (D12), not asserted here."""

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
