"""Form fields for :mod:`controlled_vocabularies` (T004, FR-001, FR-003, FR-009).

``ConceptFieldMixin.formfield()`` (``fields.py``) returns ``ConceptChoiceField``
for a ``ConceptField`` and ``ConceptsChoiceField`` for a ``ConceptsField``, so an
ordinary ``ModelForm`` built from a consuming model gets the search-as-you-type
control from the model declaration alone — a project never names a widget or
declares a form field (FR-001, plan.md A3).

Both fields' widgets carry the load-bearing part of this task (decisions.md D12,
plan.md A6 path two). The library's own ``TomSelectModelWidget.get_queryset()``
walks back to the autocomplete endpoint through an *ambient* request; during a
form POST that request is the page's own submission, whose ``GET`` carries no
``field=`` reference, so the endpoint's fail-closed refusal (a missing/invalid
reference) would be the guaranteed state on every submission and
``ModelChoiceField.to_python()`` would raise ``invalid_choice`` for a legitimate
concept. This module's widgets override ``get_queryset()`` to build the
restriction directly from the model field instance ``formfield()`` already holds
— ``Concept.objects.complex_filter(field.get_limit_choices_to())`` — with no
request consulted, restoring what an unmodified ``ModelChoiceField`` already does
with ``limit_choices_to``.
"""

from urllib.parse import urlencode

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from django_tomselect.app_settings import AllowedCSSFrameworks, TomSelectConfig
from django_tomselect.forms import (
    TomSelectModelChoiceField,
    TomSelectModelMultipleChoiceField,
)
from django_tomselect.widgets import TomSelectModelMultipleWidget, TomSelectModelWidget

from .admin import related_field_widget_wrapper_class
from .checks import AUTOCOMPLETE_URL_NAME
from .models import Concept

_MISSING_ROUTE_MESSAGE = _(
    "controlled_vocabularies's URL configuration is not included in the project's "
    'URLconf. Add path("<prefix>/", include("controlled_vocabularies.urls")) to the '
    'project\'s root URLconf, and add "django_tomselect" to INSTALLED_APPS.'
)


def _config() -> TomSelectConfig:
    """The one configuration both concept widgets render with.

    ``css_framework`` is pinned to the framework-free default explicitly
    (plan.md A3) rather than left to whatever a project's own
    ``PROJECT_TOMSELECT`` setting configures — this package imposes no
    Bootstrap on a project that uses none, regardless of that project's other
    TomSelect widgets. ``label_field`` names ``display_label``, the virtual
    field T003's view exposes; ``value_field`` stays the default ``"id"``.

    ``css_framework`` takes the enum's *value*, not the member: the wheel's
    own ``TomSelectConfig.validate()`` checks membership against
    ``{f.value for f in AllowedCSSFrameworks}``, so the member itself fails
    validation despite the field's type annotation naming the enum (verified
    against ``django_tomselect`` ``2026.6.2``, not the annotation).
    """
    return TomSelectConfig(
        url=AUTOCOMPLETE_URL_NAME,
        value_field="id",
        label_field="display_label",
        css_framework=AllowedCSSFrameworks.DEFAULT.value,  # type: ignore[arg-type]
    )


class ConceptWidgetValidationMixin:
    """The ``get_queryset()`` override decisions.md D12 exists for.

    ``model_field`` is set by the owning form field's ``__init__`` (below), from
    the model field instance ``ConceptFieldMixin.formfield()`` passes through.
    Absent — a widget built without going through ``formfield()`` — refuses
    outright rather than falling back to the library's request-derived default,
    the same fail-closed shape ``get_limit_choices_to()`` itself takes when a
    declaration names no vocabulary (an empty ``Q`` matches everything; a
    genuinely absent field reference should not).
    """

    model_field = None

    def get_queryset(self):
        if self.model_field is None:
            return Concept.objects.none()
        return Concept.objects.complex_filter(self.model_field.get_limit_choices_to())


class ConceptWidgetReferenceMixin:
    """The ``get_autocomplete_params()`` override T006 exists for (plan.md
    A6 path one, decisions.md D11).

    Appends ``field=<app_label>.<model>.<field_name>`` — a reference to this
    widget's own declaration, read from the same ``model_field`` attribute
    :class:`ConceptWidgetValidationMixin` reads — to every autocomplete
    request the control's browser plugin makes. It identifies which
    declaration is searching and carries no restriction of its own: the
    restriction is read from that declaration on the server (T006), never
    from this parameter's value.

    Absent — a widget built without going through ``formfield()`` — sends no
    reference, which the endpoint's own fail-closed refusal already covers.
    """

    model_field = None

    def get_autocomplete_params(self) -> str:
        if self.model_field is None:
            return ""
        meta = self.model_field.model._meta
        return urlencode(
            {"field": f"{meta.app_label}.{meta.model_name}.{self.model_field.name}"}
        )


class ConceptWidgetRouteMixin:
    """The render-time counterpart to the two ``checks.py`` warnings
    (decisions.md D14): a project that ignores them still reaches a render.

    ``TomSelectModelWidget.get_autocomplete_context()`` resolves this
    package's route twice while building a single widget's context — once
    through ``get_search_lookups()`` (``widgets.py:1209-1216``, via
    ``LazyView.get_url()``), before ``get_autocomplete_url()`` itself
    (``widgets.py:225-241``) ever runs. Both re-raise ``NoReverseMatch``
    verbatim on failure, and the first one to run wins, so overriding only
    ``get_autocomplete_url()`` — the hook D14 names — does not observably
    catch a missing route: confirmed against the installed wheel (``2026.6.2``),
    where the earlier call fails first. Wrapping ``get_autocomplete_context()``
    instead is the seam that actually runs for both concept widgets, model or
    multiple, since it is the one call both roads pass through before either
    named hook executes.
    """

    def get_autocomplete_context(self):
        try:
            return super().get_autocomplete_context()
        except NoReverseMatch as exc:
            raise ImproperlyConfigured(_MISSING_ROUTE_MESSAGE) from exc


class ConceptWidgetDisplayMixin:
    """The two overrides T009 (FR-008, plan.md A8) requires for an
    already-attached concept — the third path, kept apart from both restricted
    ones (:class:`ConceptWidgetValidationMixin` narrows what a *submission*
    may newly contain; :class:`ConceptWidgetReferenceMixin` carries only a
    reference for *searching*). What a record already holds is displayed
    unrestricted; this mixin is where that happens, and it touches neither of
    the other two.

    ``_get_selected_options()`` (``widgets.py:959``) is where the library
    resolves an already-attached value into what the control renders as
    selected, and it does so through ``self.get_queryset()`` —
    :class:`ConceptWidgetValidationMixin`'s narrowed queryset (D12) — so
    without this override an attached concept whose vocabulary the field no
    longer names would be silently dropped from the render, and the absence
    saved back on the next submission (R1). The swap is scoped to this one
    call: ``get_queryset`` is shadowed on the instance only for the duration
    of the library's own ``_get_selected_options()`` and the shadow is deleted
    in a ``finally``, leaving the instance exactly as it was found, so nothing
    else that reads ``self.get_queryset()`` — including validation — ever
    observes the unrestricted queryset.

    ``get_label_for_object()`` (``widgets.py:1039``) is the other property
    A8 calls out ("labels must come out as ``display_label()`` ... rather
    than ``str(obj)``"). With ``label_field="display_label"``
    (:func:`_config`), the library reads it straight off the model instance
    with ``getattr(obj, "display_label")`` — and
    :meth:`~controlled_vocabularies.models.Concept.display_label` is a
    method, not a property, so unmodified this stringifies the *bound
    method* rather than calling it. Confirmed against the installed wheel
    (``2026.6.2``) with a real ``Concept`` instance: the rendered label came
    out as ``"<bound method Concept.display_label of ...>"``, not a label.
    T003's AJAX search path (``prepare_results()``) never hits this — it
    builds a plain dict with ``"display_label"`` already a string — so this
    only ever affects the already-selected render this mixin owns, and only
    ``Concept`` instances ever reach it through this package's widgets.
    """

    def _get_selected_options(self, value, autocomplete_view):
        self.get_queryset = lambda: Concept.objects.all()
        try:
            return super()._get_selected_options(value, autocomplete_view)
        finally:
            del self.get_queryset

    def get_label_for_object(self, obj, autocomplete_view):
        if isinstance(obj, Concept):
            return escape(obj.display_label())
        return super().get_label_for_object(obj, autocomplete_view)


class ConceptWidget(
    ConceptWidgetRouteMixin,
    ConceptWidgetReferenceMixin,
    ConceptWidgetValidationMixin,
    ConceptWidgetDisplayMixin,
    TomSelectModelWidget,
):
    """The control :class:`ConceptChoiceField` renders (FR-001).

    ``Media.js`` merges with the base widget's own (``media_property``
    walks the MRO), adding ``concept-inline.js`` (T010, decisions.md D12) —
    the listener that initialises this control in an inline row a person
    adds with "Add another", which the library's own paths do not reach
    (research.md R4).
    """

    class Media:
        js = ["controlled_vocabularies/js/concept-inline.js"]


class ConceptsWidget(
    ConceptWidgetRouteMixin,
    ConceptWidgetReferenceMixin,
    ConceptWidgetValidationMixin,
    ConceptWidgetDisplayMixin,
    TomSelectModelMultipleWidget,
):
    """The control :class:`ConceptsChoiceField` renders (FR-001). See
    :class:`ConceptWidget` for ``Media``."""

    class Media:
        js = ["controlled_vocabularies/js/concept-inline.js"]


class DeclinesAdminRelatedWrapperMixin:
    """The T006 mixin (FR-004, plan.md "US-2"): ``widget`` becomes a property
    whose setter unwraps a ``RelatedFieldWidgetWrapper`` — the admin's add,
    change, delete and view affordances, applied unconditionally at
    ``options.py:215`` — back to the widget it holds, and stores every other
    value unchanged. No Django code is patched: the wrap still happens, this
    field just declines to keep it, the same way any attribute assignment can
    be declined by owning a property for it.

    Must come **before** the django-tomselect field class in a subclass's
    bases. Django's ``ChoiceField`` sets ``widget`` as a plain class
    attribute (``forms/fields.py``), and a plain attribute earlier in the MRO
    than this property would shadow it — attribute lookup stops at the first
    class in the MRO that defines the name, and only a data descriptor found
    first wins over one found later.

    The getter returns ``None`` before anything has been stored, and both
    shipped field classes rely on never reaching it. ``django/forms/fields.py``
    evaluates ``widget = widget or self.widget`` during ``Field.__init__`` and
    then sets ``widget.is_required`` on the result, so a ``None`` there is an
    ``AttributeError``, not a tolerated fallback. What keeps it unreachable is
    ``django_tomselect``'s ``_create_widget``, which assigns the widget before
    ``Field.__init__`` runs — a third-party invariant, named here so that a
    library change surfaces as a known coupling rather than a bare
    ``AttributeError``. A subclass of this mixin that relies on Django's
    class-level widget default instead would hit exactly that.

    Each field subclass carries ``# type: ignore[misc]``: adding this mixin as
    a second explicit base makes mypy validate the full inherited MRO, which
    surfaces an existing conflict between ``django_tomselect``'s own
    ``BaseTomSelectModelMixin`` and Django's ``ModelChoiceField`` over
    ``queryset``/``to_field_name`` — third-party, unrelated to this mixin, and
    silent before this task only because a single-base subclass never
    triggered the check.
    """

    @property
    def widget(self):
        return getattr(self, "_widget", None)

    @widget.setter
    def widget(self, value):
        wrapper_class = related_field_widget_wrapper_class()
        if wrapper_class is not None and isinstance(value, wrapper_class):
            value = value.widget
        self._widget = value


class ConceptChoiceField(DeclinesAdminRelatedWrapperMixin, TomSelectModelChoiceField):  # type: ignore[misc]
    """The form field :class:`~controlled_vocabularies.fields.ConceptField`
    renders as, through ``ConceptFieldMixin.formfield()``.

    ``model_field`` is the model field instance ``formfield()`` was called on
    — popped here rather than left in ``kwargs``, since neither
    :class:`~django_tomselect.forms.TomSelectModelChoiceField` nor Django's own
    ``ModelChoiceField`` accepts it — and handed to the widget after
    construction for its own ``get_queryset()`` (decisions.md D12).
    """

    widget_class = ConceptWidget

    def __init__(self, *args, model_field=None, **kwargs):
        kwargs.setdefault("config", _config())
        super().__init__(*args, **kwargs)
        self.widget.model_field = model_field


class ConceptsChoiceField(  # type: ignore[misc]
    DeclinesAdminRelatedWrapperMixin, TomSelectModelMultipleChoiceField
):
    """The form field :class:`~controlled_vocabularies.fields.ConceptsField`
    renders as, through ``ConceptFieldMixin.formfield()``. See
    :class:`ConceptChoiceField` for ``model_field``.
    """

    widget_class = ConceptsWidget

    def __init__(self, *args, model_field=None, **kwargs):
        kwargs.setdefault("config", _config())
        super().__init__(*args, **kwargs)
        self.widget.model_field = model_field
