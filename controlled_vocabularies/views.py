"""The autocomplete endpoint behind the concept search control."""

from typing import TYPE_CHECKING

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django_tomselect.autocompletes import (
    AutocompleteIterablesView,
    AutocompleteModelView,
)

from .fields import ConceptFieldMixin
from .models import Record
from .predicates import Namespaces

if TYPE_CHECKING:
    # Guarded the same way as the base view's import of it.
    from django_tomselect._types import PaginatedResponse


class PredicateAutocompleteView(AutocompleteIterablesView):
    """Search-as-you-type endpoint for the properties of the configured RDF namespaces."""

    page_size = 20

    @property
    def iterable(self) -> list[str]:  # type: ignore[override]
        """The configured namespaces' properties as CURIEs, each its own value and label."""
        # A property, not a class attribute: the terms follow the project's settings.
        return Namespaces.terms()


class ConceptAutocompleteView(AutocompleteModelView):
    """Search-as-you-type endpoint for the concepts of :class:`~controlled_vocabularies.models.Record`."""

    model = Record
    page_size = 20
    ordering = ("pref_label", "pk")
    allow_anonymous = True
    allowed_filter_fields = []
    allowed_ordering_fields = []
    value_fields = ["id"]
    virtual_fields = ["display_label", "vocabulary"]

    def search(self, queryset: QuerySet, query: str) -> QuerySet:
        """Match the query against every label of a concept and its preferred label."""
        # Replaces search_lookups, a flat list of lookups that cannot say "either column".
        if not query:
            return queryset
        return queryset.filter(
            Q(search_text__icontains=query) | Q(pref_label__icontains=query)
        )

    def hook_queryset(self, queryset):
        """Preload what results need, then narrow to the requested field declaration's restriction."""
        return self._restrict_to_declaration(queryset.select_related("scheme"))

    def _resolve_declared_field(self) -> ConceptFieldMixin | None:
        """Return the concept field the request's ``field=`` reference names.

        The reference identifies a declaration and carries no restriction of its own, so
        altering it can only name a different declaration, whose restriction then applies.

        Returns:
            The field, or ``None`` when the reference is absent, does not resolve or names
            a field that is not a concept field.
        """
        reference = self.request.GET.get("field")
        if not reference:
            return None
        try:
            app_label, model_name, field_name = reference.split(".", 2)
            model = apps.get_model(app_label, model_name)
            field = model._meta.get_field(field_name)
        except (ValueError, LookupError, FieldDoesNotExist):
            return None
        if not isinstance(field, ConceptFieldMixin):
            return None
        return field

    def _restrict_to_declaration(self, queryset: QuerySet) -> QuerySet:
        """Narrow a queryset to what the requested field declaration admits.

        Args:
            queryset: The records to narrow.

        Returns:
            The narrowed queryset, or an empty one when the declaration does not resolve,
            which is indistinguishable from a search that matched nothing.
        """
        field = self._resolve_declared_field()
        if field is None:
            return queryset.none()
        # The mixin is not a RelatedField, so mypy cannot see get_limit_choices_to() after narrowing.
        return queryset.complex_filter(field.get_limit_choices_to())  # type: ignore[attr-defined]

    def order_queryset(self, queryset: QuerySet) -> QuerySet:
        """Order by an ordered collection's own sequence while the search box is empty."""
        # A typed query wants relevance, not the curator's browsing sequence.
        if self.query:
            return super().order_queryset(queryset)

        field = self._resolve_declared_field()
        if field is None or field.collection is None:
            return super().order_queryset(queryset)

        (vocabulary,) = field.vocabulary
        collection = Record.objects.filter(
            scheme__slug=vocabulary,
            slug=field.collection,
            type=Record.Type.ORDERED_COLLECTION,
        ).first()
        if collection is None:
            return super().order_queryset(queryset)

        position = Case(
            *(
                When(uri=uri, then=Value(index))
                for index, uri in enumerate(collection.linked_uris("skos:memberList"))
            ),
            default=Value(-1),
            output_field=IntegerField(),
        )
        # Annotated so mypy can resolve the ``Self`` that QuerySet.annotate() returns.
        annotated: QuerySet = queryset.annotate(_collection_position=position)
        return annotated.order_by("_collection_position", "pk")

    def paginate_queryset(self, queryset: QuerySet) -> "PaginatedResponse":
        """Return an empty last page for a page number past the end instead of page 1."""
        # Reads the base's answer rather than copying its body, which would fork code that goes on
        # looking correct after the original changes. The base returns page 1 past the end.
        response = super().paginate_queryset(queryset)
        try:
            page_number = max(1, int(self.page))
        except (TypeError, ValueError):
            return response

        if page_number <= int(response["total_pages"]):
            return response
        return {
            "results": [],
            "page": page_number,
            "has_more": False,
            "next_page": None,
            "total_pages": int(response["total_pages"]),
        }

    def prepare_results(self, results):
        """Shape each result to its identifier, display label and vocabulary name only."""
        # Overridden outright: display_label and vocabulary are virtual fields with no queryset
        # annotation behind them, and the base would add permission and URL keys.
        return [
            {
                "id": concept.pk,
                "display_label": concept.display_label(),
                "vocabulary": concept.scheme.display_label(),
            }
            for concept in results
        ]
