"""Views for the opt-in vocabulary-browsing front end."""

from urllib.parse import urlencode

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import CASCADE, Count, F, Q
from django.db.models.functions import Lower
from django.http import Http404
from django.urls import reverse
from django.utils.text import Truncator, capfirst
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext_lazy as _
from mvp.views import (
    MVPCreateView,
    MVPDeleteView,
    MVPDetailView,
    MVPListView,
    MVPUpdateView,
)

from controlled_vocabularies.models import ConceptScheme, Record
from controlled_vocabularies.ui.filters import ConceptFilter, VocabularyFilter
from controlled_vocabularies.ui.forms import (
    StatementFormSet,
    StatementsFormSet,
    VocabularyForm,
)
from controlled_vocabularies.ui.rows import (
    PropertyRows,
    PublicationDetails,
)


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


class _VocabularyPageMixin:
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


class ConceptDetailView(_VocabularyPageMixin, MVPDetailView):
    """A single concept's own page, resolved within the vocabulary its address names."""

    model = Record
    slug_url_kwarg = "concept_slug"
    template_name = "controlled_vocabularies/ui/concept_detail.html"

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
        collections = Record.objects.filter(
            scheme=self.vocabulary, type__in=Record.COLLECTION_TYPES
        ).mentioning(concept.uri)
        context["concept_collections"] = [
            collection
            for collection in collections.order_by("pref_label", "pk")
            if concept.uri in collection.member_uris()
        ]
        return context


class CollectionDetailView(_VocabularyPageMixin, MVPDetailView):
    """A single collection's own page, resolved within the vocabulary its address names."""

    model = Record
    slug_url_kwarg = "collection_slug"
    template_name = "controlled_vocabularies/ui/collection_detail.html"

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


class VocabularyDetailView(_StrippedSearchMixin, MVPListView):
    """A single vocabulary's page: the concepts it holds, and a side panel about the vocabulary.

    A list view over ``Record`` rather than a detail view over ``ConceptScheme``,
    because django-mvp's detail view is empty below its heading and would mean
    re-implementing search, pagination and empty states. The vocabulary is resolved
    once in ``setup()`` and kept on ``self.vocabulary``.
    """

    model = Record
    template_name = "controlled_vocabularies/ui/conceptscheme_detail.html"
    list_item_template = "controlled_vocabularies/ui/concept_list_item.html"

    # By the preferred label in the default language, which the column holds. `pk` makes the
    # order total for pagination (#140).
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
        # select_related: the row partial reverses its links from `object.scheme.slug` in an
        # isolated context, so without the join it costs a query per row.
        self.queryset = Record.objects.filter(
            scheme=self.vocabulary, type=Record.Type.CONCEPT
        ).select_related("scheme")

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
        """Add the vocabulary, what the side panel says about it, and what each row names."""
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
        # A concept with no broader concept is a way into the hierarchy. A flat vocabulary has
        # nothing but top concepts, so listing them would only repeat the concept list.
        has_hierarchy = concepts.filter(data__has_key="skos:broader").exists()
        context["top_concepts"] = (
            concepts.exclude(data__has_key="skos:broader").order_by(
                Lower("pref_label"), "pk"
            )
            if has_hierarchy
            else []
        )
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

    def describe_rows(self, context, collections):
        """Give each concept on the page what its row names beyond its own label.

        Reads the broader concept's label, the definition and the collections holding the
        concept, so the row partial, which sees only the object, costs no query per row.

        Args:
            context: The page's context, whose ``object_list`` is replaced by a list.
            collections: The vocabulary's collections.
        """
        concepts = context["object_list"] = list(context["object_list"])
        members = {
            collection.pk: set(collection.member_uris()) for collection in collections
        }
        broader = {
            concept: next(iter(concept.linked_uris("skos:broader")), None)
            for concept in concepts
        }
        labels = {
            record.uri: record.display_label()
            for record in Record.objects.filter(
                scheme=self.vocabulary, uri__in=set(broader.values())
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


class _StatementsMixin:
    """Add the statements formset to the create and edit pages of a vocabulary."""

    def get_statements(self, form):
        """Return the page's statements formset, built once per request.

        Args:
            form: The vocabulary form, which decides the default language.

        Returns:
            The formset, bound to the submission on a POST.
        """
        if not hasattr(self, "_statements"):
            language = form["default_language"].value()
            self._statements = StatementsFormSet(
                self.request.POST if self.request.method == "POST" else None,
                initial=StatementFormSet.initial_for(form.instance, language),
                default_language=language,
            )
        return self._statements

    def get_context_data(self, **kwargs):
        """Add the statements formset."""
        context = super().get_context_data(**kwargs)
        context["formset"] = self.get_statements(context["form"])
        return context

    def form_valid(self, form):
        """Save only when the statements are valid too, and write them as the document."""
        if not self.get_statements(form).is_valid():
            return self.form_invalid(form)
        form.instance.data = self.get_statements(form).to_data()
        return super().form_valid(form)


class VocabularyCreateView(_StatementsMixin, PermissionRequiredMixin, MVPCreateView):
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
        return _("Created the vocabulary %(name)s.") % {
            "name": self.object.display_label()
        }

    def get_context_data(self, **kwargs):
        """Add where Cancel leads and what the save button says."""
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = vocabulary_list_url()
        context["submit_label"] = _("Create vocabulary")
        return context


class VocabularyUpdateView(_StatementsMixin, PermissionRequiredMixin, MVPUpdateView):
    """A curator edits a vocabulary held on this site. An imported one is refused."""

    permission_required = "controlled_vocabularies.change_conceptscheme"
    model = ConceptScheme
    form_class = VocabularyForm
    template_name = "controlled_vocabularies/ui/conceptscheme_form.html"
    page_title = _("Edit vocabulary")

    def get_object(self, queryset=None):
        """Refuse a vocabulary that is not managed here."""
        vocabulary = super().get_object(queryset)
        if not vocabulary.managed:
            raise PermissionDenied(_("An imported vocabulary cannot be edited here."))
        # A form that fails to validate has already written its values onto the instance, so the
        # page names the vocabulary by what is stored.
        self.stored_name = vocabulary.display_label()
        return vocabulary

    def get_page_subtitle(self):
        """Name the vocabulary being edited."""
        return self.stored_name

    def get_breadcrumbs(self):
        """Return the trail back through the vocabulary's page."""
        return [
            {"text": _("Vocabularies"), "href": vocabulary_list_url()},
            {"text": self.stored_name, "href": vocabulary_url(self.object)},
            {"text": _("Edit")},
        ]

    def get_success_url(self):
        """Land on the vocabulary's page; the slug never changes, whatever the new name."""
        return vocabulary_url(self.object)

    def get_success_message(self, cleaned_data):
        """Name the vocabulary that was saved."""
        return _("Saved your changes to %(name)s.") % {
            "name": self.object.display_label()
        }

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
        return self.object.display_label()

    def get_breadcrumbs(self):
        """Return the trail back through the vocabulary's page."""
        return [
            {"text": _("Vocabularies"), "href": vocabulary_list_url()},
            {"text": self.object.display_label(), "href": vocabulary_url(self.object)},
            {"text": _("Delete")},
        ]

    def get_back_url(self):
        """Go back to a same-site ``back`` address, else to the vocabulary's page."""
        # django-mvp checks ``back`` against this site, and offers nothing else here: the package
        # registers no route under its default list name, and a vocabulary has no absolute URL.
        return super().get_back_url() or vocabulary_url(self.object)

    def get_success_url(self):
        """Land on the list of vocabularies."""
        return vocabulary_list_url()

    def get_success_message(self, cleaned_data):
        """Name the vocabulary that was deleted."""
        return _("Deleted the vocabulary %(name)s.") % {
            "name": self.object.display_label()
        }

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
            kinds.append((capfirst(owner._meta.verbose_name_plural), count))
        return sorted(kinds)

    def get_context_data(self, **kwargs):
        """Add how much goes with the vocabulary, and what is using its concepts."""
        context = super().get_context_data(**kwargs)
        records = self.object.records
        context["concept_count"] = records.filter(type=Record.Type.CONCEPT).count()
        context["collection_count"] = records.filter(
            type__in=Record.COLLECTION_TYPES
        ).count()
        context["protected_kinds"] = self.protected_kinds(context["protected_objects"])
        return context
