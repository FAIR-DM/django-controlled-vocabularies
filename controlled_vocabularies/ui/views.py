"""Views for the opt-in vocabulary-browsing front end."""

from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.functions import Lower
from django.http import Http404
from django.urls import reverse
from django.utils.text import Truncator
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext_lazy as _
from mvp.views import MVPDetailView, MVPListView

from controlled_vocabularies.models import ConceptScheme, Link, Record
from controlled_vocabularies.ui.filters import ConceptFilter, VocabularyFilter
from controlled_vocabularies.ui.representations import RepresentationMixin
from controlled_vocabularies.ui.rows import PropertyRows, PublicationDetails

__all__ = [
    "CollectionDetailView",
    "ConceptDetailView",
    "VocabularyDetailView",
    "VocabularyListView",
    "vocabulary_url",
]


class StrippedSearchMixin:
    """Strip the search term in the request before the filterset reads it."""

    def setup(self, request, *args, **kwargs):
        """Replace a ``?q=`` carrying surrounding whitespace with its stripped value."""
        # The search filter strips the term it searches with, but the search box shows the raw one, so
        # a whitespace-only query would come back in the box and read as searched while filtering
        # nothing (#140).
        super().setup(request, *args, **kwargs)
        term = request.GET.get("q")
        if term is not None and term != term.strip():
            stripped = request.GET.copy()
            stripped["q"] = term.strip()
            request.GET = stripped


class VocabularyPageMixin:
    """Resolve the vocabulary segment of the address and link the trail back to it."""

    def setup(self, request, *args, **kwargs):
        """Resolve the vocabulary segment of the address, or raise a 404."""
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc

    def get_breadcrumbs(self):
        """Link the trail to the record's vocabulary rather than to every record."""
        # The default trail names the model's plural and links nowhere.
        return [
            {"text": _("Home"), "href": "/"},
            {
                "text": self.vocabulary.display_label(),
                "href": vocabulary_url(self.vocabulary),
            },
            {"text": self.get_page_title()},
        ]


class VocabularyListView(StrippedSearchMixin, MVPListView):
    """Every vocabulary the site holds, narrowed by an optional search and facets."""

    model = ConceptScheme
    # The page template only draws the rows as a list. A search that matches nothing gets
    # django-mvp's no-match state, which repeats the term and offers Clear all as the way back.
    template_name = "controlled_vocabularies/ui/conceptscheme_list.html"
    list_item_template = "controlled_vocabularies/ui/conceptscheme_list_item.html"

    # An empty site says so, rather than pointing at a create button this page does not show.
    empty_state_heading = _("This site holds no vocabularies")
    empty_state_message = None

    filterset_class = VocabularyFilter
    # The facets go in django-mvp's filter panel, set where the vocabulary page sets its About
    # panel, so the two pages share one frame.
    toolbar_filters = ["q", "o"]
    filter_panel_attrs = {"position": "end", "align": "content", "width": "md"}

    # A class attribute: Django applies `ordering` before the search adds `.distinct()`, which an
    # order_by() in get_queryset() would land after. `pk` makes the order total for pagination.
    ordering = [Lower("pref_label"), "pk"]

    def get_queryset(self):
        """Annotate each vocabulary with its counts and its modified date."""
        return (
            super()
            .get_queryset()
            .annotate(
                concept_count=Count(
                    "records", filter=Q(records__type=Record.Type.CONCEPT)
                ),
                collection_count=Count(
                    "records", filter=Q(records__type__in=Record.COLLECTION_TYPES)
                ),
                modified=F("data__dcterms:modified__0__@value"),
            )
        )

    def get_context_data(self, **kwargs):
        """Count each facet option, and read each row's publication details."""
        self.get_filterset().count_facets()
        context = super().get_context_data(**kwargs)
        context["object_list"] = schemes = list(context["object_list"])
        for scheme in schemes:
            scheme.details = PublicationDetails.of(scheme)
            entries = PropertyRows.in_reading_language(
                scheme.values("dcterms:description"),
                get_language() or "",
                scheme.default_language,
            )
            scheme.summary = str(entries[0]["@value"]) if entries else ""
        return context


class ConceptDetailView(RepresentationMixin, VocabularyPageMixin, MVPDetailView):
    """A single concept's own page, resolved within the vocabulary its address names."""

    model = Record
    slug_url_kwarg = "concept_slug"
    template_name = "controlled_vocabularies/ui/concept_detail.html"

    def get_representation_subject(self):
        """Return the record the address names."""
        return self.get_object()

    def get_queryset(self):
        """Limit to the vocabulary's concepts."""
        return Record.objects.filter(
            scheme=self.vocabulary, type=Record.Type.CONCEPT
        ).select_related("scheme")

    def get_context_data(self, **kwargs):
        """Add the property rows and the collections that gather the concept."""
        context = super().get_context_data(**kwargs)
        concept = self.object
        context["rows"] = PropertyRows(concept, get_language() or "").build()
        # Never a row: membership is a statement the collection makes, not the concept.
        context["concept_collections"] = list(
            Record.objects.filter(
                scheme=self.vocabulary, type__in=Record.COLLECTION_TYPES
            )
            .linking_to(concept.uri, "skos:member", "skos:memberList")
            .order_by("pref_label", "pk")
        )
        return context


class CollectionDetailView(RepresentationMixin, VocabularyPageMixin, MVPDetailView):
    """A single collection's own page, resolved within the vocabulary its address names."""

    model = Record
    slug_url_kwarg = "collection_slug"
    template_name = "controlled_vocabularies/ui/collection_detail.html"

    def get_representation_subject(self):
        """Return the record the address names."""
        return self.get_object()

    def get_queryset(self):
        """Limit to the vocabulary's collections."""
        return Record.objects.filter(
            scheme=self.vocabulary, type__in=Record.COLLECTION_TYPES
        ).select_related("scheme")

    def get_context_data(self, **kwargs):
        """Add the property rows and whether the collection has members."""
        context = super().get_context_data(**kwargs)
        context["rows"] = PropertyRows(self.object, get_language() or "").build()
        # An empty collection has no member row, so the template needs its own flag.
        context["collection_has_members"] = bool(self.object.member_uris())
        return context


class VocabularyDetailView(RepresentationMixin, StrippedSearchMixin, MVPListView):
    """A single vocabulary's page: the concepts it holds, and a side panel about the vocabulary.

    A list view over ``Record`` rather than a detail view over ``ConceptScheme``,
    because django-mvp's detail view is empty below its heading and would mean
    re-implementing search, pagination and empty states. The vocabulary is resolved
    once in ``setup()`` and kept on ``self.vocabulary``.
    """

    model = Record
    template_name = "controlled_vocabularies/ui/conceptscheme_detail.html"
    list_item_template = "controlled_vocabularies/ui/concept_list_item.html"

    # By the preferred label in the default language, which the column holds. `pk` makes
    # the order total for pagination (#140).
    ordering = [Lower("pref_label"), "pk"]

    filterset_class = ConceptFilter
    toolbar_filters = ["q", "o"]

    empty_state_heading = _("This vocabulary holds no concepts")
    empty_state_message = None

    def setup(self, request, *args, **kwargs):
        """Resolve the vocabulary and build the queryset of its concepts."""
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc
        # select_related: the row partial reverses its links from `object.scheme.slug`
        # in an isolated context, so without the join it costs a query per row.
        self.queryset = Record.objects.filter(
            scheme=self.vocabulary, type=Record.Type.CONCEPT
        ).select_related("scheme")

    def get_representation_subject(self):
        """Return the vocabulary the address names."""
        return self.vocabulary

    def get_page_title(self):
        """Return the vocabulary's name."""
        # Otherwise the title reads as the record model's plural.
        return self.vocabulary.display_label()

    def get_page_subtitle(self):
        """Return the vocabulary's description, cut to the length of a lead paragraph."""
        entries = PropertyRows.in_reading_language(
            self.vocabulary.values("dcterms:description"),
            get_language() or "",
            self.vocabulary.default_language,
        )
        return Truncator(entries[0]["@value"] if entries else "").words(40)

    def get_context_data(self, **kwargs):
        """Add the vocabulary, its side panel text, and what each row names."""
        context = super().get_context_data(**kwargs)
        vocabulary = self.vocabulary
        context["vocabulary"] = vocabulary
        context["details"] = PublicationDetails.of(vocabulary)
        try:
            context["language_name"] = get_language_info(vocabulary.default_language)[
                "name_translated"
            ]
        except KeyError:
            context["language_name"] = vocabulary.default_language
        concepts = vocabulary.records.filter(type=Record.Type.CONCEPT)
        context["concept_count"] = concepts.count()
        context["top_concepts"] = self.top_concepts(concepts)
        collections = list(
            vocabulary.records.filter(type__in=Record.COLLECTION_TYPES).order_by(
                Lower("pref_label"), "pk"
            )
        )
        for collection in collections:
            collection.member_count = len(collection.member_uris())
        context["collections"] = collections
        self.describe_rows(context, collections)
        return context

    def concept_links(self):
        """Return the links the vocabulary's concepts state.

        Returns:
            The ``Link`` rows whose source is a concept of the vocabulary.
        """
        return Link.objects.filter(
            source__scheme=self.vocabulary, source__type=Record.Type.CONCEPT
        )

    def top_concepts(self, concepts):
        """Return the concepts with no broader concept, from either end.

        A file may state a hierarchy only with ``skos:broader``, only with
        ``skos:narrower``, or with both, as a concept's own page reads it. A flat
        vocabulary has nothing but top concepts, so listing them would only repeat the
        concept list.

        Args:
            concepts: The vocabulary's concepts.

        Returns:
            The concepts that state no ``skos:broader`` and that no concept names with
            ``skos:narrower``, by name, or none when the vocabulary states no hierarchy.
        """
        links = self.concept_links()
        if not links.filter(predicate__in=["skos:broader", "skos:narrower"]).exists():
            return []
        states_broader = links.filter(source=OuterRef("pk"), predicate="skos:broader")
        named_narrower = links.filter(target=OuterRef("uri"), predicate="skos:narrower")
        return (
            concepts.exclude(Exists(states_broader))
            .exclude(Exists(named_narrower))
            .order_by(Lower("pref_label"), "pk")
        )

    def describe_rows(self, context, collections):
        """Give each concept on the page what its row names beyond its own label.

        Reads the broader concept's label, the definition and the collections holding
        the concept, so the row partial, which sees only the object, costs no query per
        row.

        Args:
            context: The page's context, whose ``object_list`` is replaced by a list.
            collections: The vocabulary's collections.
        """
        concepts = context["object_list"] = list(context["object_list"])
        members = {
            collection.pk: set(collection.member_uris()) for collection in collections
        }
        stated = {
            concept: next(iter(concept.linked_uris("skos:broader")), None)
            for concept in concepts
        }
        # A concept that states no parent is placed by a concept naming it narrower.
        naming = (
            self.concept_links()
            .filter(
                target__in={c.uri for c, parent in stated.items() if parent is None},
                predicate="skos:narrower",
            )
            .order_by("source_id", "pk")
            .values_list("target", "source__uri")
        )
        named_by: dict[str, str] = {}
        for target, parent_uri in naming:
            named_by.setdefault(target, parent_uri)
        broader = {
            concept: parent or named_by.get(concept.uri)
            for concept, parent in stated.items()
        }
        labels = {
            record.uri: record.display_label()
            for record in Record.objects.filter(
                scheme=self.vocabulary, uri__in=set(broader.values()) - {None}
            )
        }
        for concept in concepts:
            definitions = PropertyRows.in_reading_language(
                concept.values("skos:definition"),
                get_language() or "",
                self.vocabulary.default_language,
            )
            concept.definition = str(definitions[0]["@value"]) if definitions else ""
            concept.broader_label = labels.get(broader[concept], "")
            concept.collections = [
                collection
                for collection in collections
                if concept.uri in members[collection.pk]
            ]


def vocabulary_url(vocabulary):
    """Return the address of a vocabulary's own page.

    Args:
        vocabulary: The vocabulary.

    Returns:
        The address.
    """
    return reverse(
        "controlled_vocabularies_ui:vocabulary-detail", args=[vocabulary.slug]
    )
