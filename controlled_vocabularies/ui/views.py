"""Views for the opt-in vocabulary-browsing front end."""

from itertools import count

from django.db.models import Count, F, OuterRef, Subquery
from django.db.models.functions import Coalesce, Lower
from django.http import Http404
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from mvp.views import MVPDetailView, MVPListView

from controlled_vocabularies.exchange.mapping import (
    BROADER_CURIE,
    COLLECTION_TYPE_CURIE,
    CONCEPT_TYPE_CURIE,
    IN_SCHEME_CURIE,
    LABEL_CURIES,
    MEMBER_CURIE,
    MEMBER_LIST_CURIE,
    NARROWER_CURIE,
    NOTE_CURIES,
    ORDERED_COLLECTION_TYPE_CURIE,
    RELATED_CURIE,
    TYPE_CURIE,
    curie_uri,
)
from controlled_vocabularies.models import (
    Collection,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptScheme,
)


class VocabularyListView(MVPListView):
    """Every vocabulary the site holds, narrowed by an optional search."""

    model = ConceptScheme
    list_item_template = "controlled_vocabularies/ui/conceptscheme_list_item.html"

    # No page template of our own: the page is django-mvp's `list_view.html` and this package supplies
    # only the row. An override would outlive the upstream fix it worked around (django-mvp#282, fixed
    # in 0.19.2). One test stays skipped for a gap that release left open (django-mvp#291).

    search_fields = ["name", "description"]

    # A class attribute: Django applies `ordering` before django-mvp's search mixin adds `.distinct()`,
    # which an order_by() in get_queryset() would land after. `pk` makes the order total for pagination.
    ordering = [Lower("name"), "pk"]

    # Declaring these is what makes django-mvp render the sort control. Each is one expression, so a
    # chosen sort has no `pk` tiebreak and equal names can swap pages (django-mvp#290).
    order_by = [
        ("name_asc", _("Name (A-Z)"), Lower("name")),
        ("name_desc", _("Name (Z-A)"), Lower("name").desc()),
    ]

    max_search_words = 100

    def setup(self, request, *args, **kwargs):
        """Bound the search term to ``max_search_words`` words before anything reads it."""
        # django-mvp ORs one condition per word with no bound. Past roughly 400 words the expression
        # exceeds SQLite's parser depth limit and the page raises OperationalError (django-mvp#281).
        # The bound is far above any real search, because dropping words from an OR search drops matches.
        super().setup(request, *args, **kwargs)
        words = request.GET.get("q", "").split()
        if len(words) > self.max_search_words:
            bounded = request.GET.copy()
            bounded["q"] = " ".join(words[: self.max_search_words])
            request.GET = bounded

    def get_queryset(self):
        """Annotate each vocabulary with its concept count."""
        return super().get_queryset().annotate(concept_count=Count("concepts"))

    def get_search_term(self):
        """Return the stripped search term.

        Returns:
            The ``?q=`` value with surrounding whitespace removed, empty when none was given.
        """
        # Stripped as django-mvp's search mixin does, so "a search is in force" means the same to the
        # empty states as to the queryset. `search_query` in the context is the raw value.
        return self.request.GET.get("q", "").strip()

    def get_context_data(self, **kwargs):
        """Add the stripped search term, and make it the value the search box shows."""
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.get_search_term()
        # django-mvp fills the search box from the raw `?q=`, so a whitespace-only query would put
        # whitespace back in the box and read as searched while filtering nothing (#140).
        context["search_query"] = context["search_term"]
        return context

    def get_empty_state_heading(self):
        """Return a heading that names the search term, or says the site holds no vocabularies."""
        # Plain translatable text, never mark_safe: django-mvp's empty state autoescapes the string, so
        # the way back to the full list is a link in the actions block, not markup here.
        search_term = self.get_search_term()
        if search_term:
            return _("Nothing matches “%(term)s”") % {"term": search_term}
        return _("This site holds no vocabularies")

    def get_empty_state_message(self):
        """Return a hint after an unmatched search, and no message for an empty site."""
        if self.get_search_term():
            return _("Try a different search term.")
        # None: the base class's default points at a create button this page does not show.
        return None


def concept_property_rows(
    concept: Concept, language: str, default_language: str | None = None
) -> list[dict]:
    """Return the fixed-order property rows a concept's own page renders.

    One row per SKOS statement the concept makes about itself: type, preferred label,
    alternative labels, notes, broader, narrower and related concepts, then the
    vocabulary holding it. Collection membership is never a row, because other records
    make that statement. A hidden label is never read. A property with no value in
    either language contributes no row.

    Each row is a dict of ``term``, ``term_uri``, ``value``, ``short_form``, ``uri``,
    ``href`` and ``identifier_id``, the names the ``property_row`` component takes. A
    record-valued row carries ``short_form``, ``uri`` and ``href`` and leaves ``value`` empty.

    Args:
        concept: The concept to describe.
        language: The language being read.
        default_language: The language a value absent in ``language`` falls back to.
            ``None``, the default, requests no fallback.

    Returns:
        The rows in display order.
    """
    identifier_ids = count()

    def row(term: str, *, value=None, short_form=None, uri=None, href=None) -> dict:
        """Build one row dict.

        Args:
            term: The CURIE naming the property.
            value: The plain value, for a row that is not record-valued.
            short_form: The link text of a record-valued row.
            uri: The record's canonical identifier.
            href: The address of the record's own page.

        Returns:
            The row.
        """
        # A term is a CURIE, so a reader hovering it is asking which URI it abbreviates.
        return {
            "term": term,
            "term_uri": curie_uri(term),
            "value": value,
            "short_form": short_form,
            "uri": uri,
            "href": href,
            # Only a record-valued row has a hidden span for aria-describedby to name, and its id
            # must be unique on the page.
            "identifier_id": f"identifier-{next(identifier_ids)}" if uri else None,
        }

    def localized_text(getter):
        """Return a value in the reading language, or in the default language when it has none.

        Args:
            getter: Returns the value for a given language.

        Returns:
            The value found.
        """
        value = getter(language)
        if not value and default_language and default_language != language:
            value = getter(default_language)
        return value

    def localized_list(getter):
        """Return values in the reading language, or in the default language when there are none.

        Args:
            getter: Returns the values for a given language.

        Returns:
            The values found.
        """
        values = getter(language)
        if not values and default_language and default_language != language:
            values = getter(default_language)
        return values

    def record_row(term: str, record: Concept) -> dict:
        """Build the row for a related concept.

        Args:
            term: The CURIE naming the relation.
            record: The related concept.

        Returns:
            The row.
        """
        # The prefix comes from the vocabulary holding the record, and the link is reversed
        # through this app's namespace: `local_url` is an identifier, not a route.
        return row(
            term,
            short_form=f"{record.scheme.slug}:{record.slug}",
            uri=record.uri,
            href=reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": record.scheme.slug, "concept_slug": record.slug},
            ),
        )

    rows = [row(TYPE_CURIE, value=CONCEPT_TYPE_CURIE)]

    preferred_label = localized_text(concept.preferred_label)
    if preferred_label:
        rows.append(
            row(LABEL_CURIES[ConceptLabel.Kind.PREFERRED], value=preferred_label)
        )

    rows.extend(
        row(LABEL_CURIES[ConceptLabel.Kind.ALTERNATIVE], value=text)
        for text in localized_list(concept.alt_labels)
    )

    for kind in ConceptNote.Kind:
        rows.extend(
            row(NOTE_CURIES[kind], value=value)
            for value in localized_list(
                lambda lang, kind=kind: concept.notes(lang, kind=kind)
            )
        )

    # None of these three is prefetchable (each builds a fresh queryset), so each chains its own
    # select_related("scheme").
    rows.extend(
        record_row(BROADER_CURIE, related)
        for related in concept.broader().select_related("scheme")
    )
    rows.extend(
        record_row(NARROWER_CURIE, related)
        for related in concept.narrower().select_related("scheme")
    )
    rows.extend(
        record_row(RELATED_CURIE, related)
        for related in concept.related().select_related("scheme")
    )

    scheme = concept.scheme
    rows.append(
        row(
            IN_SCHEME_CURIE,
            # A vocabulary records no short prefix, so its row names it by display name.
            short_form=scheme.name,
            uri=scheme.uri,
            href=reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            ),
        )
    )

    return rows


def collection_property_rows(collection: Collection) -> list[dict]:
    """Return the fixed-order property rows a collection's own page renders.

    Mirrors :func:`concept_property_rows`: type, name, members, then the vocabulary
    holding it. An ordered collection is a ``skos:OrderedCollection`` with members
    under ``skos:memberList``, an unordered one a ``skos:Collection`` with members
    under ``skos:member``. Membership is one row carrying every member in its
    ``entries`` key, and a collection with no members has no such row.

    Args:
        collection: The collection to describe.

    Returns:
        The rows in display order.
    """
    identifier_ids = count()

    def row(
        term: str, *, value=None, short_form=None, uri=None, href=None, entries=None
    ) -> dict:
        """Build one row dict.

        Args:
            term: The CURIE naming the property.
            value: The plain value, for a row that is not record-valued.
            short_form: The link text of a record-valued row.
            uri: The record's canonical identifier.
            href: The address of the record's own page.
            entries: The ``short_form``, ``uri``, ``href`` and ``identifier_id`` of each
                member, for the membership row.

        Returns:
            The row.
        """
        return {
            "term": term,
            "term_uri": curie_uri(term),
            "value": value,
            "short_form": short_form,
            "uri": uri,
            "href": href,
            "entries": entries,
            # As in concept_property_rows.row(). The membership row carries entries, not a uri of
            # its own, so it never claims an id.
            "identifier_id": f"identifier-{next(identifier_ids)}" if uri else None,
        }

    def member_entry(member: Concept) -> dict:
        """Build the entry for one member of the collection.

        Args:
            member: The member concept.

        Returns:
            A dict of ``short_form``, ``uri``, ``href`` and ``identifier_id``.
        """
        # Collection.members() does not select_related the scheme, and every membership is
        # intra-vocabulary, so the collection's loaded scheme is assigned to spare a query per member.
        member.scheme = collection.scheme
        return {
            "short_form": f"{collection.scheme.slug}:{member.slug}",
            "uri": member.uri,
            "href": reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": collection.scheme.slug, "concept_slug": member.slug},
            ),
            # Shares the counter with row(), so ids never collide.
            "identifier_id": f"identifier-{next(identifier_ids)}",
        }

    type_curie = (
        ORDERED_COLLECTION_TYPE_CURIE if collection.ordered else COLLECTION_TYPE_CURIE
    )
    member_curie = MEMBER_LIST_CURIE if collection.ordered else MEMBER_CURIE

    rows = [
        row(TYPE_CURIE, value=type_curie),
        row(LABEL_CURIES[ConceptLabel.Kind.PREFERRED], value=collection.name),
    ]
    entries = [member_entry(member) for member in collection.members()]
    if entries:
        rows.append(row(member_curie, entries=entries))

    scheme = collection.scheme
    rows.append(
        row(
            IN_SCHEME_CURIE,
            short_form=scheme.name,
            uri=scheme.uri,
            href=reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            ),
        )
    )

    return rows


class ConceptDetailView(MVPDetailView):
    """A single concept's own page, resolved within the vocabulary its address names."""

    model = Concept
    slug_url_kwarg = "concept_slug"
    template_name = "controlled_vocabularies/ui/concept_detail.html"

    def setup(self, request, *args, **kwargs):
        """Resolve the vocabulary segment of the address, or raise a 404."""
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc

    def get_queryset(self):
        """Limit to the vocabulary's concepts, preloading the labels and notes the rows read."""
        # Keeps the property rows to one query per relation. broader(), narrower() and related()
        # build fresh querysets, so they are not prefetchable.
        return (
            Concept.objects.filter(scheme=self.vocabulary)
            .select_related("scheme")
            .prefetch_related("labels", "concept_notes")
        )

    def get_breadcrumbs(self):
        """Link the trail to the concept's vocabulary rather than to every concept."""
        # The default trail names the model's plural and links nowhere. self.vocabulary is already
        # resolved in setup(), so this costs no query.
        return [
            {"text": _("Home"), "href": "/"},
            {
                "text": self.vocabulary.name,
                "href": reverse(
                    "controlled_vocabularies_ui:vocabulary-detail",
                    kwargs={"slug": self.vocabulary.slug},
                ),
            },
            {"text": self.get_page_title()},
        ]

    def get_context_data(self, **kwargs):
        """Add the property rows and the collections that gather the concept."""
        # Passing default_language is what opts this page into the per-property language fallback.
        context = super().get_context_data(**kwargs)
        context["rows"] = concept_property_rows(
            self.object,
            get_language(),
            default_language=self.object.scheme.effective_default_language,
        )
        # Never a row: membership is a statement other records make about this concept.
        # collections() builds a fresh queryset, so this is an extra query.
        context["concept_collections"] = self.object.collections()
        return context


class CollectionDetailView(MVPDetailView):
    """A single collection's own page, resolved within the vocabulary its address names."""

    model = Collection
    slug_url_kwarg = "collection_slug"
    template_name = "controlled_vocabularies/ui/collection_detail.html"

    def setup(self, request, *args, **kwargs):
        """Resolve the vocabulary segment of the address, or raise a 404."""
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc

    def get_queryset(self):
        """Limit to the vocabulary's collections."""
        # collection_property_rows() reads collection.scheme for the vocabulary row and every
        # member's short form.
        return Collection.objects.filter(scheme=self.vocabulary).select_related(
            "scheme"
        )

    def get_breadcrumbs(self):
        """Link the trail to the collection's vocabulary rather than to every collection."""
        # As ConceptDetailView.get_breadcrumbs().
        return [
            {"text": _("Home"), "href": "/"},
            {
                "text": self.vocabulary.name,
                "href": reverse(
                    "controlled_vocabularies_ui:vocabulary-detail",
                    kwargs={"slug": self.vocabulary.slug},
                ),
            },
            {"text": self.get_page_title()},
        ]

    def get_context_data(self, **kwargs):
        """Add the property rows and whether the collection has members."""
        context = super().get_context_data(**kwargs)
        context["rows"] = collection_property_rows(self.object)
        # An empty collection has no member row, so the template needs its own flag. Computed from
        # the built rows to avoid a second .members() query.
        context["collection_has_members"] = any(
            row["term"] in (MEMBER_CURIE, MEMBER_LIST_CURIE) for row in context["rows"]
        )
        return context


class VocabularyDetailView(MVPListView):
    """A single vocabulary's page: its description, provenance and the concepts it holds.

    A list view over ``Concept`` rather than a detail view over ``ConceptScheme``,
    because django-mvp's detail view is empty below its heading and would mean
    re-implementing search, pagination and empty states. The vocabulary is resolved
    once in ``setup()`` and kept on ``self.vocabulary``.
    """

    model = Concept
    template_name = "controlled_vocabularies/ui/conceptscheme_detail.html"
    list_item_template = "controlled_vocabularies/ui/concept_list_item.html"

    # By the label shown, not the stored default-language one. `pk` makes the order total for
    # pagination (#140).
    ordering = [Lower("resolved_label"), "pk"]

    # By the label shown, as `ordering` above. The single-expression limit is the list view's
    # (django-mvp#290).
    order_by = [
        ("label_asc", _("Label (A-Z)"), Lower("resolved_label")),
        ("label_desc", _("Label (Z-A)"), Lower("resolved_label").desc()),
    ]

    # `labels__text` reaches every label: other languages, alternative and hidden. Notes are left out
    # on purpose. A hidden label is matched but never shown, since display reads only preferred labels.
    search_fields = ["label", "labels__text"]

    def setup(self, request, *args, **kwargs):
        """Resolve the vocabulary and build the queryset of its concepts."""
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc
        # Assigned to self.queryset rather than annotated on the way out of get_queryset(): Django applies
        # `ordering` before the mixins' get_queryset(), so a later annotation would not exist yet.
        # The active language is matched exactly, as labels are stored under the site's configured ones.
        preferred_in_active_language = ConceptLabel.objects.filter(
            concept=OuterRef("pk"),
            language=get_language(),
            kind=ConceptLabel.Kind.PREFERRED,
        ).values("text")[:1]
        # select_related: the row partial reverses its link from `object.scheme.slug` in an isolated
        # context, so without the join it costs a query per row.
        self.queryset = (
            Concept.objects.filter(scheme=self.vocabulary)
            .select_related("scheme")
            .annotate(
                resolved_label=Coalesce(
                    Subquery(preferred_in_active_language), F("label")
                )
            )
        )

    def get_page_title(self):
        """Return the vocabulary's name."""
        # Otherwise the title reads as the concept model's plural.
        return self.vocabulary.name

    def get_search_term(self):
        """Return the stripped search term.

        Returns:
            The ``?q=`` value with surrounding whitespace removed, empty when none was given.
        """
        # Stripped as django-mvp's search mixin does, so "a search is in force" means the same to the
        # empty states and the back link as to the queryset (#140).
        return self.request.GET.get("q", "").strip()

    def get_context_data(self, **kwargs):
        """Add the vocabulary, the stripped search term and the vocabulary's collections."""
        context = super().get_context_data(**kwargs)
        context["vocabulary"] = self.vocabulary
        context["search_term"] = self.get_search_term()
        # The stripped term, as in VocabularyListView.
        context["search_query"] = context["search_term"]
        context["collections"] = self.vocabulary.collections.order_by(Lower("name"))
        return context

    def get_empty_state_heading(self):
        """Return a heading that names the search term, or says the vocabulary holds no concepts."""
        search_term = self.get_search_term()
        if search_term:
            return _("Nothing matches “%(term)s”") % {"term": search_term}
        return _("This vocabulary holds no concepts")

    def get_empty_state_message(self):
        """Return a hint after an unmatched search, and no message otherwise."""
        if self.get_search_term():
            return _("Try a different search term.")
        return None
