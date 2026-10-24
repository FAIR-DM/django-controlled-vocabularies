"""Views for the opt-in vocabulary-browsing front end."""

from itertools import count
from urllib.parse import urlencode

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import CASCADE, Count, F, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce, Lower
from django.http import Http404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import Truncator
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext_lazy as _
from mvp.views import (
    MVPCreateView,
    MVPDeleteView,
    MVPDetailView,
    MVPListView,
    MVPUpdateView,
)

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
    CollectionMember,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
)
from controlled_vocabularies.ui.filters import (
    ConceptFilter,
    VocabularyFilter,
    language_expression,
)
from controlled_vocabularies.ui.forms import VocabularyForm


class _StrippedSearchMixin:
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


class VocabularyListView(_StrippedSearchMixin, MVPListView):
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
    ordering = [Lower("name"), "pk"]

    def get_queryset(self):
        """Annotate each vocabulary with its counts and its effective default language."""
        return (
            super()
            .get_queryset()
            .annotate(
                concept_count=Count("concepts", distinct=True),
                collection_count=Count("collections", distinct=True),
                language=language_expression(),
            )
        )

    def get_context_data(self, **kwargs):
        """Count each facet option before the filter panel draws it."""
        self.get_filterset().count_facets()
        return super().get_context_data(**kwargs)


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


class VocabularyDetailView(_StrippedSearchMixin, MVPListView):
    """A single vocabulary's page: the concepts it holds, and a side panel about the vocabulary.

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
        # Assigned to self.queryset rather than annotated on the way out of get_queryset(): Django applies
        # `ordering` before the mixins' get_queryset(), so a later annotation would not exist yet.
        # The active language is matched exactly, as labels are stored under the site's configured ones.
        preferred_in_active_language = ConceptLabel.objects.filter(
            concept=OuterRef("pk"),
            language=get_language(),
            kind=ConceptLabel.Kind.PREFERRED,
        ).values("text")[:1]
        # Kept for the side panel's top concepts, which are named the way the rows are.
        self.labelled_concepts = Concept.objects.filter(
            scheme=self.vocabulary
        ).annotate(
            resolved_label=Coalesce(Subquery(preferred_in_active_language), F("label"))
        )

        def definition_in(language):
            """Return the concept's definition in ``language``, as a subquery.

            Args:
                language: The language code to read.

            Returns:
                The subquery.
            """
            return Subquery(
                ConceptNote.objects.filter(
                    concept=OuterRef("pk"),
                    language=language,
                    kind=ConceptNote.Kind.DEFINITION,
                ).values("value")[:1]
            )

        # The one broader concept a row names for context, named the way the rows are. A concept with
        # several shows the one whose relation was stored first.
        broader_preferred = ConceptLabel.objects.filter(
            concept=OuterRef("target"),
            language=get_language(),
            kind=ConceptLabel.Kind.PREFERRED,
        ).values("text")[:1]
        broader_label = (
            ConceptRelation.objects.filter(
                source=OuterRef("pk"), kind=ConceptRelation.Kind.BROADER
            )
            .order_by("pk")
            .annotate(name=Coalesce(Subquery(broader_preferred), F("target__label")))
            .values("name")[:1]
        )
        # The collections each row names, alphabetically, in one query for the page.
        memberships = Prefetch(
            "collection_memberships",
            queryset=CollectionMember.objects.select_related("collection").order_by(
                Lower("collection__name")
            ),
        )
        # select_related: the row partial reverses its links from `object.scheme.slug` in an isolated
        # context, so without the join it costs a query per row.
        self.queryset = (
            self.labelled_concepts.select_related("scheme")
            .prefetch_related(memberships)
            .annotate(
                resolved_definition=Coalesce(
                    definition_in(get_language()),
                    definition_in(self.vocabulary.effective_default_language),
                ),
                broader_label=Subquery(broader_label),
            )
        )

    def get_page_title(self):
        """Return the vocabulary's name."""
        # Otherwise the title reads as the concept model's plural.
        return self.vocabulary.name

    def get_page_subtitle(self):
        """Return the vocabulary's description, cut to the length of a lead paragraph."""
        return Truncator(self.vocabulary.description).words(40)

    def get_context_data(self, **kwargs):
        """Add the vocabulary and what the side panel says about it."""
        context = super().get_context_data(**kwargs)
        vocabulary = self.vocabulary
        context["vocabulary"] = vocabulary
        language = vocabulary.effective_default_language
        try:
            context["language_name"] = get_language_info(language)["name_translated"]
        except KeyError:
            context["language_name"] = language
        context["concept_count"] = vocabulary.concepts.count()
        # A concept with no broader concept is a way into the hierarchy. A flat vocabulary has
        # nothing but top concepts, so listing them would only repeat the concept list.
        has_hierarchy = ConceptRelation.objects.filter(
            source__scheme=vocabulary, kind=ConceptRelation.Kind.BROADER
        ).exists()
        context["top_concepts"] = (
            self.labelled_concepts.exclude(
                relations_as_source__kind=ConceptRelation.Kind.BROADER
            ).order_by(Lower("resolved_label"), "pk")
            if has_hierarchy
            else []
        )
        context["collections"] = vocabulary.collections.annotate(
            member_count=Count("memberships")
        ).order_by(Lower("name"))
        return context


def vocabulary_list_url():
    """Return the address of the list of vocabularies."""
    return reverse("controlled_vocabularies_ui:vocabulary-list")


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


class VocabularyCreateView(PermissionRequiredMixin, MVPCreateView):
    """A curator creates a vocabulary held on this site."""

    permission_required = "controlled_vocabularies.add_conceptscheme"
    model = ConceptScheme
    form_class = VocabularyForm
    template_name = "controlled_vocabularies/ui/conceptscheme_form.html"
    page_title = _("New vocabulary")

    def get_breadcrumbs(self):
        """Return the trail back to the list of vocabularies."""
        return [
            {"text": _("Vocabularies"), "href": vocabulary_list_url()},
            {"text": self.get_page_title()},
        ]

    def get_success_url(self):
        """Land on the new vocabulary's page."""
        return vocabulary_url(self.object)

    def get_success_message(self, cleaned_data):
        """Name the vocabulary that was created."""
        return _("Created the vocabulary %(name)s.") % {"name": self.object.name}

    def get_context_data(self, **kwargs):
        """Add where Cancel leads and what the save button says."""
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = vocabulary_list_url()
        context["submit_label"] = _("Create vocabulary")
        return context


class VocabularyUpdateView(PermissionRequiredMixin, MVPUpdateView):
    """A curator edits a vocabulary held on this site. An imported one is refused."""

    permission_required = "controlled_vocabularies.change_conceptscheme"
    model = ConceptScheme
    form_class = VocabularyForm
    template_name = "controlled_vocabularies/ui/conceptscheme_form.html"
    page_title = _("Edit vocabulary")

    def get_object(self, queryset=None):
        """Refuse a vocabulary a publisher fixed the identifier of."""
        vocabulary = super().get_object(queryset)
        if vocabulary.static_uri:
            raise PermissionDenied(_("An imported vocabulary cannot be edited here."))
        return vocabulary

    def get_page_subtitle(self):
        """Name the vocabulary being edited."""
        return self.object.name

    def get_breadcrumbs(self):
        """Return the trail back through the vocabulary's page."""
        return [
            {"text": _("Vocabularies"), "href": vocabulary_list_url()},
            {"text": self.object.name, "href": vocabulary_url(self.object)},
            {"text": _("Edit")},
        ]

    def get_success_url(self):
        """Land on the vocabulary's page, at the address its name now produces."""
        return vocabulary_url(self.object)

    def get_success_message(self, cleaned_data):
        """Name the vocabulary that was saved."""
        return _("Saved your changes to %(name)s.") % {"name": self.object.name}

    def get_delete_url(self):
        """Offer deletion only to someone who may delete, and come back here on Back."""
        if not self.request.user.has_perm(
            "controlled_vocabularies.delete_conceptscheme"
        ):
            return ""
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-delete", args=[self.object.slug]
        )
        return f"{url}?{urlencode({'back': self.request.path})}"

    def get_context_data(self, **kwargs):
        """Add where Cancel leads and what the save button says."""
        context = super().get_context_data(**kwargs)
        # The slug only changes inside save(), so it is the stored one even when the form is re-shown.
        context["cancel_url"] = vocabulary_url(self.object)
        context["submit_label"] = _("Save changes")
        return context


class VocabularyDeleteView(PermissionRequiredMixin, MVPDeleteView):
    """A curator deletes a vocabulary, held here or imported, unless its concepts are in use."""

    permission_required = "controlled_vocabularies.delete_conceptscheme"
    model = ConceptScheme
    template_name = "controlled_vocabularies/ui/conceptscheme_confirm_delete.html"
    page_title = _("Delete vocabulary")

    def get_page_subtitle(self):
        """Name the vocabulary being deleted."""
        return self.object.name

    def get_breadcrumbs(self):
        """Return the trail back through the vocabulary's page."""
        return [
            {"text": _("Vocabularies"), "href": vocabulary_list_url()},
            {"text": self.object.name, "href": vocabulary_url(self.object)},
            {"text": _("Delete")},
        ]

    def get_back_url(self):
        """Go back to where the curator came from: the edit page, else the vocabulary's page."""
        candidate = self.request.GET.get("back", "")
        if url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return candidate
        return vocabulary_url(self.object)

    def get_success_url(self):
        """Land on the list of vocabularies."""
        return vocabulary_list_url()

    def get_success_message(self, cleaned_data):
        """Name the vocabulary that was deleted."""
        return _("Deleted the vocabulary %(name)s.") % {"name": self.object.name}

    @staticmethod
    def protected_kinds(protected_objects):
        """Group the records holding the vocabulary's concepts by the model that owns them.

        A ``ConceptsField`` holds a concept through a generated row, so that row is counted
        against the model carrying the field, once per record however many concepts it holds.

        Args:
            protected_objects: The records whose foreign key blocked the delete.

        Returns:
            ``(label, count)`` pairs, sorted by label.
        """
        by_model = {}
        for record in protected_objects:
            owner = record._meta.auto_created or type(record)
            by_model.setdefault(owner, []).append(record)
        kinds = []
        for owner, records in by_model.items():
            if type(records[0]) is owner:
                count = len({record.pk for record in records})
            else:
                # The collector loads a through row with its primary key only.
                through = type(records[0])
                owner_key = next(
                    field.name
                    for field in through._meta.fields
                    if field.is_relation
                    and field.remote_field.model is owner
                    and field.remote_field.on_delete is CASCADE
                )
                count = (
                    through.objects.filter(pk__in=[record.pk for record in records])
                    .values(owner_key)
                    .distinct()
                    .count()
                )
            kinds.append((str(owner._meta.verbose_name_plural).capitalize(), count))
        return sorted(kinds)

    def get_context_data(self, **kwargs):
        """Add how much goes with the vocabulary, and what is using its concepts."""
        context = super().get_context_data(**kwargs)
        vocabulary = self.object
        context["concept_count"] = vocabulary.concepts.count()
        context["collection_count"] = vocabulary.collections.count()
        context["protected_kinds"] = self.protected_kinds(context["protected_objects"])
        return context
