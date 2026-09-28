"""Form fields and widgets that render a concept field as a search-as-you-type control."""

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
    """Return the TomSelect configuration both concept widgets render with.

    Returns:
        A config with the framework-free CSS default, so a project's own TomSelect
        settings cannot impose a CSS framework on these widgets.
    """
    # css_framework takes the enum's value: TomSelectConfig.validate() rejects the member itself.
    return TomSelectConfig(
        url=AUTOCOMPLETE_URL_NAME,
        value_field="id",
        label_field="display_label",
        css_framework=AllowedCSSFrameworks.DEFAULT.value,  # type: ignore[arg-type]
    )


class ConceptWidgetValidationMixin:
    """Limit a widget's queryset to the restriction of its model field."""

    model_field = None

    def get_queryset(self):
        """Return the concepts the model field's restriction admits, or none without a model field."""
        # Built from the model field directly: the library's own version reads an ambient request,
        # whose GET carries no `field=` reference on a form POST, so every submission would fail.
        if self.model_field is None:
            return Concept.objects.none()
        return Concept.objects.complex_filter(self.model_field.get_limit_choices_to())


class ConceptWidgetReferenceMixin:
    """Name the model field a widget belongs to in every autocomplete request it makes."""

    model_field = None

    def get_autocomplete_params(self) -> str:
        """Return the ``field=`` reference to the widget's own model field."""
        if self.model_field is None:
            return ""
        meta = self.model_field.model._meta
        return urlencode(
            {"field": f"{meta.app_label}.{meta.model_name}.{self.model_field.name}"}
        )


class ConceptWidgetRouteMixin:
    """Report a missing autocomplete route as a configuration error at render time."""

    def get_autocomplete_context(self):
        """Raise ``ImproperlyConfigured`` when the autocomplete route is not included."""
        # Wrapped here rather than in get_autocomplete_url(): the library reverses the route in
        # get_search_lookups() first, so the URL hook is never the first to fail.
        try:
            return super().get_autocomplete_context()
        except NoReverseMatch as exc:
            raise ImproperlyConfigured(_MISSING_ROUTE_MESSAGE) from exc


class ConceptWidgetDisplayMixin:
    """Display an already-attached concept whether or not the field's restriction still admits it."""

    def _get_selected_options(self, value, autocomplete_view):
        """Resolve the selected options against every concept, not the restricted queryset."""
        # Otherwise a concept the field no longer admits drops out of the render and is lost on
        # the next save. The shadow lasts one call, so validation still sees the restriction.
        self.get_queryset = lambda: Concept.objects.all()
        try:
            return super()._get_selected_options(value, autocomplete_view)
        finally:
            del self.get_queryset

    def get_label_for_object(self, obj, autocomplete_view):
        """Label a concept with its ``display_label()``."""
        # display_label is a method, so the library's getattr would render the bound method.
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
    """The control :class:`ConceptChoiceField` renders."""

    # Initialises the control in an inline row added by "Add another", which django-tomselect misses (FS-011).
    class Media:
        js = ["controlled_vocabularies/js/concept-inline.js"]


class ConceptsWidget(
    ConceptWidgetRouteMixin,
    ConceptWidgetReferenceMixin,
    ConceptWidgetValidationMixin,
    ConceptWidgetDisplayMixin,
    TomSelectModelMultipleWidget,
):
    """The control :class:`ConceptsChoiceField` renders."""

    class Media:
        js = ["controlled_vocabularies/js/concept-inline.js"]


class DeclinesAdminRelatedWrapperMixin:
    """Keep the admin's add, change, delete and view wrapper off a field's widget.

    Must come before the django-tomselect field class in a subclass's bases, so this
    property is found before ``ChoiceField``'s plain ``widget`` class attribute.
    """

    @property
    def widget(self):
        """The widget stored on the field, or ``None`` before one is set."""
        return getattr(self, "_widget", None)

    @widget.setter
    def widget(self, value):
        """Store the widget, unwrapping the admin's related-field wrapper."""
        wrapper_class = related_field_widget_wrapper_class()
        if wrapper_class is not None and isinstance(value, wrapper_class):
            value = value.widget
        self._widget = value


# The extra base makes mypy check the whole MRO, which surfaces a django_tomselect/Django clash
# over `queryset` and `to_field_name` that is not ours to fix.
class ConceptChoiceField(DeclinesAdminRelatedWrapperMixin, TomSelectModelChoiceField):  # type: ignore[misc]
    """The form field :class:`~controlled_vocabularies.fields.ConceptField` renders as.

    Args:
        *args: Passed to ``TomSelectModelChoiceField``.
        model_field: The model field this form field was built from, handed to the
            widget so it can restrict its choices.
        **kwargs: Passed to ``TomSelectModelChoiceField``.
    """

    widget_class = ConceptWidget

    def __init__(self, *args, model_field=None, **kwargs):
        kwargs.setdefault("config", _config())
        super().__init__(*args, **kwargs)
        self.widget.model_field = model_field


class ConceptsChoiceField(  # type: ignore[misc]
    DeclinesAdminRelatedWrapperMixin, TomSelectModelMultipleChoiceField
):
    """The form field :class:`~controlled_vocabularies.fields.ConceptsField` renders as.

    Args:
        *args: Passed to ``TomSelectModelMultipleChoiceField``.
        model_field: The model field this form field was built from, handed to the
            widget so it can restrict its choices.
        **kwargs: Passed to ``TomSelectModelMultipleChoiceField``.
    """

    widget_class = ConceptsWidget

    def __init__(self, *args, model_field=None, **kwargs):
        kwargs.setdefault("config", _config())
        super().__init__(*args, **kwargs)
        self.widget.model_field = model_field
