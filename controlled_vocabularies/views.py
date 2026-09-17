"""Views for :mod:`controlled_vocabularies` (T002, T003, FR-002, FR-005, FR-012).

One route serves both the FK and M2M concept fields, since both target the same
``Concept`` model. The multi-name search and the allowlists that close the
filter/order surface are later tasks. Result shaping is this task's: a result
carries exactly the identifier, the preferred label and the vocabulary a concept
belongs to (FR-005, FR-012) — not the editorial notes or hidden/alternative
labels the concept also holds.
"""

from typing import TYPE_CHECKING

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.utils.translation import get_language
from django_tomselect.autocompletes import AutocompleteModelView

from .fields import ConceptFieldMixin
from .models import Collection, CollectionMember, Concept, ConceptLabel

if TYPE_CHECKING:
    # Matches the base view's own guarded import (autocompletes.py) — this
    # override's return type must satisfy the same contract.
    from django_tomselect._types import PaginatedResponse

#: The label kinds a typed string matches against, in the active language
#: (FR-004, plan.md A4). The default-language preferred label — every
#: concept's own ``label`` column — is matched separately, unconditional on
#: the active language.
_SEARCHED_LABEL_KINDS = [
    ConceptLabel.Kind.PREFERRED,
    ConceptLabel.Kind.ALTERNATIVE,
    ConceptLabel.Kind.HIDDEN,
]


class ConceptAutocompleteView(AutocompleteModelView):
    """Search-as-you-type endpoint for :class:`~controlled_vocabularies.models.Concept`."""

    model = Concept
    page_size = 20
    ordering = ("label", "pk")
    allow_anonymous = True
    allowed_filter_fields = []
    allowed_ordering_fields = []
    value_fields = ["id"]
    virtual_fields = ["display_label", "vocabulary"]

    def search(self, queryset: QuerySet, query: str) -> QuerySet:
        """Match ``query`` against a concept's names (FR-004, plan.md A4).

        Replaces the base ``search_lookups`` mechanism, left empty because it
        expresses one flat list of ORM lookups and cannot express "the active
        language's labels, of three kinds, or the default-language column".
        ``query`` is exactly what the base view's ``get_queryset()`` already
        extracted from the request (``autocompletes.py:396``) — nothing else
        is read off the request here (decisions.md D8). ``icontains`` gives
        case-insensitivity portably and folds no accents (decisions.md D4).
        ``.distinct()`` is what makes a concept matching on several of its
        labels appear once (FR-004).
        """
        if not query:
            return queryset
        active_language = get_language() or settings.LANGUAGE_CODE
        return queryset.filter(
            Q(label__icontains=query)
            | Q(
                labels__language=active_language,
                labels__kind__in=_SEARCHED_LABEL_KINDS,
                labels__text__icontains=query,
            )
        ).distinct()

    def hook_queryset(self, queryset):
        """Attach what ``prepare_results()`` needs, then narrow to what the
        requested field declaration allows (T006, FR-006, plan.md A6 path
        one) — both before filtering, searching and ordering run, at the
        library's documented extension point rather than an override of
        ``get_queryset()``: ``select_related("scheme")`` for the vocabulary
        name, ``prefetch_related("labels")`` because ``display_label()``
        walks ``self.labels.all()`` and a bounded page would otherwise cost a
        query per row (R5).
        """
        queryset = queryset.select_related("scheme").prefetch_related("labels")
        return self._restrict_to_declaration(queryset)

    def _resolve_declared_field(self) -> ConceptFieldMixin | None:
        """Resolve the ``field=`` reference the request names to the concept
        field declaration it identifies, or ``None`` when it does not
        resolve (FR-006, decisions.md D11).

        ``field`` is a ``<app_label>.<model>.<field_name>`` reference the
        control's widget appends (plan.md A6 path one); it identifies which
        declaration is searching and carries no restriction of its own —
        altering it can only name a different declaration, whose own
        restriction then applies. Resolution happens through Django's app
        registry, exactly as it does when Django itself loads a string
        ``to``; nothing here reads a vocabulary, a collection, an ordering,
        or anything else directly off the request.

        Shared by :meth:`_restrict_to_declaration` (T006, filtering) and
        :meth:`order_queryset` (T022, ordering) — both need exactly the same
        declaration, resolved the same way, rather than parsing the
        reference twice.
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
        """Narrow ``queryset`` to what the field declaration the request
        names allows (FR-006, decisions.md D11).

        A reference that fails to resolve, names a field that is not one of
        this package's concept fields, or is absent, returns
        ``Concept.objects.none()`` — an ordinary empty page, HTTP 200,
        identical in shape to a search that matched nothing. No exception
        escapes, so a missing model and an existing-but-wrong field are
        indistinguishable from outside (plan.md A6 point 3).
        """
        field = self._resolve_declared_field()
        if field is None:
            return queryset.none()
        # ConceptFieldMixin is a plain mixin, not itself a RelatedField, so
        # get_limit_choices_to() (from ForeignKey/ManyToManyField, which
        # ConceptField/ConceptsField also inherit) is invisible to mypy after
        # narrowing on the mixin alone.
        return queryset.complex_filter(field.get_limit_choices_to())  # type: ignore[attr-defined]

    def order_queryset(self, queryset: QuerySet) -> QuerySet:
        """Apply an ordered collection's own member sequence, and only while
        the search box is empty (T022, FR-010, plan.md A5, decisions.md D8,
        research.md R6).

        This overrides the hook the base view's own ``get_queryset()``
        actually calls (``django_tomselect/autocompletes.py:399``,
        ``order_queryset()`` at line 685). The design notes for this story
        name the method ``apply_ordering()``; the installed
        ``django-tomselect`` exposes no method by that name, so an override
        written under it would sit dead and never run. ``order_queryset()``
        is the real seam and reads exactly the way the design intended:
        overridden outright, one condition, one annotation.

        The collection's order applies when, and only when, both hold: the
        request carries no search term (``self.query``, set in ``setup()``
        before this runs — never read again here), and the field
        declaration's restriction is a collection the curator marked
        ``ordered``. Everything else — no restriction, an unordered
        collection, an unresolved declaration, a typed query — falls
        through to ``super()`` and the inherited ``("label", "pk")``: a
        typed query wants relevance, not the curator's browsing sequence.

        The position is read through a ``Subquery`` annotation keyed on the
        declaration's own collection and vocabulary slugs, never through a
        ``collection_memberships__`` lookup: a concept may belong to more
        than one collection, and that lookup joins ``CollectionMember`` onto
        a queryset this view reaches with ``complex_filter()`` bare —
        duplicate rows, silently (research.md R3).
        """
        if self.query:
            return super().order_queryset(queryset)

        field = self._resolve_declared_field()
        if field is None or field.collection is None:
            return super().order_queryset(queryset)

        (vocabulary,) = field.vocabulary
        is_ordered_collection = Collection.objects.filter(
            slug=field.collection, scheme__slug=vocabulary, ordered=True
        ).exists()
        if not is_ordered_collection:
            return super().order_queryset(queryset)

        position = Subquery(
            CollectionMember.objects.filter(
                concept=OuterRef("pk"),
                collection__slug=field.collection,
                collection__scheme__slug=vocabulary,
            ).values("position")[:1]
        )
        # ``QuerySet.annotate()``'s stub returns ``Self``, which mypy cannot
        # resolve past ``Any`` when ``queryset`` is a bare, unparametrised
        # ``QuerySet`` parameter rather than a manager's own result — an
        # explicit variable annotation gives ``order_by()`` a concrete type
        # to resolve ``Self`` against, rather than suppressing the check.
        annotated: QuerySet = queryset.annotate(_collection_position=position)
        return annotated.order_by("_collection_position", "pk")

    def paginate_queryset(self, queryset: QuerySet) -> "PaginatedResponse":
        """Bounded and stable past the end (FR-007, plan.md A7).

        ``page_size``, the inherited ``MAX_PAGE_SIZE`` clamp (applied in
        ``setup()`` before this runs) and the total ordering
        (``ordering = ("label", "pk")`` above) are unchanged and stay
        inherited. Only the one branch ``plan.md`` A7 names is replaced: the
        base catches ``EmptyPage`` and returns page 1
        (``autocompletes.py:743``), so a request past the end silently
        re-serves the beginning. Here it returns an ordinary empty page
        saying no more exist — the same shape a search that matched nothing
        already returns.

        The base does the paginating and this reads its answer, rather than
        reimplementing it. Copying the base's body to change one branch would
        fork thirty lines of somebody else's code, and the fork would go on
        looking correct after the original changed. The one cost is that a
        request past the end pays for the page-1 results the base prepared
        before this discards them, which is the price of exactly one ordinary
        first-page request, on the rarest path the endpoint has.
        """
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
        """Shape each result down to exactly what FR-012 permits (FR-005): the
        identifier, the preferred label — ``display_label()``, active-language
        with default-language fallback — and the vocabulary's name. Overridden
        outright rather than through ``hook_prepare_results()``: ``display_label``
        and ``vocabulary`` are ``virtual_fields`` with no queryset annotation
        behind them, so the base implementation's ``.values()`` field extraction
        has nothing to build on here, and letting it run first would put
        permission/URL keys in a response FR-012 says must carry only these three.
        """
        return [
            {
                "id": concept.pk,
                "display_label": concept.display_label(),
                "vocabulary": concept.scheme.name,
            }
            for concept in results
        ]
