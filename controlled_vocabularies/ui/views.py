"""Views for the opt-in vocabulary-browsing front end (013-find-a-vocabulary,
014-look-inside-a-vocabulary, 015-read-single-record).

``VocabularyListView`` over the vocabularies a site holds, ``VocabularyDetailView`` over
the concepts inside one of them, and ``ConceptDetailView``/``CollectionDetailView`` over
one record's own page. The first two are list views, with search narrowing each rather
than adding another. The last two are detail views (plan.md Key design decision #1) that
share one thing: resolving the record named by an address scoped to its vocabulary.
"""

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
    """Every vocabulary the site holds, narrowed by an optional search — FR-001 through
    FR-013, User Story 1 scenarios 1-7 and User Story 2 scenarios 1-6.
    """

    model = ConceptScheme
    list_item_template = "controlled_vocabularies/ui/conceptscheme_list_item.html"

    # No page template of our own: the page is django-mvp's `list_view.html`, reached through
    # the base class's own fallback. This package supplies the row and nothing else, which is
    # the extension point django-mvp documents. An earlier revision overrode the page to work
    # around two faults in the shipped search control (django-mvp/django-mvp#282); the override
    # was removed on the maintainer's instruction. A template override in a consumer outlives
    # the upstream fix that made it unnecessary, and a shell package whose consumers all carry
    # overrides has stopped being a shell. Waiting was the right call: #282 shipped in
    # django-mvp 0.19.2, which this package now floors on, and the tests it blocked are live
    # again. One test stays skipped for a gap 0.19.2 did not close — a page whose search
    # matched nothing still has nowhere to put a link back (django-mvp#291).

    # django-mvp's SearchMixin reads ?q=, strips it, and applies case-insensitive
    # substring matching across these fields with OR semantics (T011, FR-006).
    search_fields = ["name", "description"]

    # A class attribute, not an `.order_by()` call inside get_queryset() — Django applies
    # `self.ordering` innermost, ahead of both django-mvp's search and order mixins; ordering
    # from our own get_queryset() would land after the search mixin's `.distinct()`, the
    # operand order upstream's own docstring says its mixin order exists to avoid (plan.md
    # Key design decisions #1, decisions.md D2). `pk` is not decoration: without a total
    # order, two same-named vocabularies could land on either of two pages, or on neither,
    # once pagination is in play.
    ordering = [Lower("name"), "pk"]

    # The orderings a reader may choose, as (key, label, expression) — the key is what
    # `?o=` carries and the expression is never built from the request, so an unrecognised
    # `?o=` falls back to `ordering` above rather than reaching the database. Declaring
    # this is what makes the sort control render at all: django-mvp's action is wrapped in
    # `{% if order_by_choices %}`, so a view that declares none shows no control, which is
    # why sorting appeared to be broken rather than absent.
    #
    # Each expression is a single column, because django-mvp applies `order_by(choice[2])`
    # with one argument and Django rejects a sequence there. A chosen sort therefore has no
    # `pk` tiebreak and two identically named vocabularies can swap places between pages —
    # the instability the default `ordering` above exists to prevent. Raised upstream as
    # django-mvp#290; the fix belongs there, not in a local re-implementation of the mixin
    # (decisions.md D16).
    order_by = [
        ("name_asc", _("Name (A-Z)"), Lower("name")),
        ("name_desc", _("Name (Z-A)"), Lower("name").desc()),
    ]

    # A search longer than this many words keeps its first this-many and drops the rest.
    max_search_words = 100

    def setup(self, request, *args, **kwargs):
        # django-mvp's search mixin ORs one condition per word per search field with no
        # bound, and reads `?q=` from the request itself rather than through a method a
        # subclass could override (`mvp/views/list.py`). Past roughly 400 words the resulting
        # expression exceeds SQLite's parser depth limit and the page raises OperationalError
        # — a 500 on a page anyone can reach, from a query string short enough to fit an
        # ordinary request line. Bounding the term once, here, before anything has read it,
        # is what keeps the queryset, the page's own context and the empty states agreeing on
        # what was searched for. Filed upstream as django-mvp#281; this stays correct whether
        # or not upstream grows a bound of its own.
        #
        # The bound is set far above any search a person means and far below where the
        # database gives out, because dropping words from an OR search drops matches: a bound
        # tight enough to trim a real search would answer a different question in silence.
        super().setup(request, *args, **kwargs)
        words = request.GET.get("q", "").split()
        if len(words) > self.max_search_words:
            bounded = request.GET.copy()
            bounded["q"] = " ".join(words[: self.max_search_words])
            request.GET = bounded

    def get_queryset(self):
        # Collections are not counted (decisions.md D3) — Count("concepts") reaches the
        # concepts related_name only, never collection_members or any other relation.
        return super().get_queryset().annotate(concept_count=Count("concepts"))

    def get_search_term(self):
        # Read and stripped exactly as django-mvp's own search mixin does it before
        # filtering (`mvp/views/list.py`), so "a search is in force" means the same thing
        # to the empty states as it does to the queryset. The `search_query` the mixin puts
        # in the context is the raw value, unstripped, and is not a substitute here.
        return self.request.GET.get("q", "").strip()

    def get_context_data(self, **kwargs):
        # The template needs the same stripped term the queryset was filtered on. Branching
        # the page on the raw `search_query` put `?q=%20%20` into a half-searched state: the
        # unfiltered list, but with the box prefilled with whitespace and the way-back link
        # offering to undo a search that never happened.
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.get_search_term()
        # django-mvp fills the search box from `search_query`, which it sets to the raw
        # `?q=` value. A whitespace-only query filters nothing, so leaving the raw value
        # in place puts whitespace back in the box and the page reads as searched when it
        # is not. Overwriting the context variable is the supported way to correct it —
        # the alternative is overriding django-mvp's search component (decisions.md D17).
        context["search_query"] = context["search_term"]
        return context

    def get_empty_state_heading(self):
        # Two distinct empty states, never one (decisions.md D4): a search matching
        # nothing says so and repeats the term; a genuinely empty site keeps its own
        # wording. Both branches return plain translatable text — never mark_safe, never
        # format_html. The way back to the full list is the link the actions block renders
        # (conceptscheme_list.html), not markup here — django-mvp's empty-state component
        # renders this string autoescaped with no slot, so an anchor here would show as
        # literal text, and marking it safe would emit the search term unescaped.
        search_term = self.get_search_term()
        if search_term:
            return _("Nothing matches “%(term)s”") % {"term": search_term}
        return _("This site holds no vocabularies")

    def get_empty_state_message(self):
        if self.get_search_term():
            return _("Try a different search term.")
        # No message: the base class's own default points at a create button this page
        # does not show (show_create_action is never set), and this empty state has
        # nothing else useful to add beyond the heading.
        return None


def concept_property_rows(
    concept: Concept, language: str, default_language: str | None = None
) -> list[dict]:
    """The fixed-order rows a concept's own page renders (015-read-single-record T003,
    T006, FR-003, FR-004, FR-005, FR-006, FR-018).

    One row per SKOS statement the concept makes about itself, in the order plan.md Key
    design decision #4 fixes: type, preferred label, alternative labels, notes (in the
    order :class:`~controlled_vocabularies.models.ConceptNote.Kind` declares them),
    relations — broader, narrower, related — then the vocabulary holding it. Collection
    membership is never a row here: it is a statement *other* records make about this
    one, not one this concept makes about itself, and sits outside this list entirely
    (decisions.md D4). A hidden label is never read at all (FR-004). A property with no
    value in ``language``, and none in ``default_language`` either, contributes no row,
    so a template built over this needs no emptiness logic of its own.

    ``language`` is the language being read. Whether a value absent in ``language``
    falls back to ``default_language`` (FR-005) is the caller's decision, not this
    function's own (decisions.md D6): passing ``default_language=None``, the default,
    requests no fallback at all — a property absent in ``language`` contributes no row,
    full stop, which is what lets a caller ask what a concept holds in exactly one
    language. Passing the vocabulary's own effective default language opts every
    property into the same per-value fallback :meth:`Concept.display_label` already
    applies to the preferred label alone.

    Each row is a plain dict of ``term``/``value``/``short_form``/``uri``/``href`` — the
    same five names the ``property_row`` cotton component takes (T002). A record-valued
    row (a related concept, or the vocabulary) carries ``short_form``/``uri``/``href``
    and leaves ``value`` empty; every other row carries ``value`` and leaves the other
    three empty.
    """

    identifier_ids = count()

    def row(term: str, *, value=None, short_form=None, uri=None, href=None) -> dict:
        # term_uri (T031): the term is itself a CURIE, and a CURIE abbreviates a URI,
        # so a reader hovering one is asking what it stands for — the same disclosure
        # a record-valued row's short form carries (FR-007).
        return {
            "term": term,
            "term_uri": curie_uri(term),
            "value": value,
            "short_form": short_form,
            "uri": uri,
            "href": href,
            # identifier_id (T029, corrected): property_row.html's hover disclosure
            # names a hidden span by id via aria-describedby, so it needs one unique
            # on the page — only a record-valued row (one carrying a uri) has a
            # hidden span to name at all.
            "identifier_id": f"identifier-{next(identifier_ids)}" if uri else None,
        }

    def localized_text(getter):
        value = getter(language)
        if not value and default_language and default_language != language:
            value = getter(default_language)
        return value

    def localized_list(getter):
        values = getter(language)
        if not values and default_language and default_language != language:
            values = getter(default_language)
        return values

    def record_row(term: str, record: Concept) -> dict:
        # The short form's prefix comes from the vocabulary holding the record
        # (decisions.md D2), and the link is reversed through this app's own
        # namespace — never `local_url`, which is an identifier, not a route
        # (plan.md Key design decision #6).
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

    # D-015-02: none of these three is prefetchable (each builds a fresh queryset), so
    # each read chains its own select_related("scheme") rather than relying on a
    # prefetch that would never be consulted.
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
            # A vocabulary records no short prefix of its own (decisions.md D2) — its
            # row names it by its plain display name rather than the "{prefix}:{slug}"
            # short form only a record it holds carries.
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
    """The fixed-order rows a collection's own page renders (015-read-single-record
    T011, T012, T028, FR-008, FR-012, FR-013, FR-017).

    Mirrors :func:`concept_property_rows`'s shape (plan.md Key design decision #4):
    type, name, members, then the vocabulary holding it. Unlike a concept's, a
    collection's ``name`` carries no per-language variants (a plain ``CharField``), so
    there is no reading-language argument here. The type row and the membership
    property both depend on :attr:`Collection.ordered` (decisions.md, "What
    distinguishes an ordered collection..."): an ordered collection is
    ``skos:OrderedCollection`` with members under ``skos:memberList``, an unordered one
    is ``skos:Collection`` with members under ``skos:member``. A collection holding no
    members contributes no membership row at all (FR-017) — the same "absent, not
    empty" rule T003's ``concept_property_rows`` already follows (FR-018).

    Membership is one row carrying every member, not one row per member (T028) — a
    four-member collection states ``skos:member`` once, with all four beside it. That
    row's ``entries`` key holds the list of ``{short_form, uri, href}`` dicts every
    other record-valued row would otherwise carry singly.
    """

    identifier_ids = count()

    def row(
        term: str, *, value=None, short_form=None, uri=None, href=None, entries=None
    ) -> dict:
        # term_uri (T031): see concept_property_rows.row() — same disclosure, same reason.
        return {
            "term": term,
            "term_uri": curie_uri(term),
            "value": value,
            "short_form": short_form,
            "uri": uri,
            "href": href,
            "entries": entries,
            # identifier_id (T029, corrected): see concept_property_rows.row() — same
            # disclosure, same reason. The membership row itself carries entries, not
            # its own uri, so it never claims one.
            "identifier_id": f"identifier-{next(identifier_ids)}" if uri else None,
        }

    def member_entry(member: Concept) -> dict:
        # D-015-02: Collection.members() (models.py, out of this feature's scope)
        # only select_relates "concept", not "concept__scheme", and every membership
        # is intra-vocabulary by construction (CollectionMember._reject_cross_scheme).
        # The collection's own already-loaded scheme is therefore assigned onto the
        # member before its uri is read, populating Django's FK cache without a
        # query — the same trick D-015-02 describes for collections()/members().
        member.scheme = collection.scheme
        return {
            "short_form": f"{collection.scheme.slug}:{member.slug}",
            "uri": member.uri,
            "href": reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": collection.scheme.slug, "concept_slug": member.slug},
            ),
            # identifier_id: shares identifier_ids with row() above, so a member's
            # hidden span id never collides with the vocabulary row's own.
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
    """A single concept's own page (015-read-single-record T000).

    Only the record resolution :class:`CollectionDetailView` also needs lands here: the
    vocabulary segment is resolved once, in ``setup()``, exactly as
    ``VocabularyDetailView.setup()`` already does for a vocabulary itself, then the slug
    lookup is retargeted to the *concept's* segment and scoped to that vocabulary — an
    unscoped lookup would 200 at an address whose vocabulary segment names nothing and
    raise ``MultipleObjectsReturned`` the moment two vocabularies share a concept slug
    (plan.md Key design decision #1).
    """

    model = Concept
    slug_url_kwarg = "concept_slug"
    template_name = "controlled_vocabularies/ui/concept_detail.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc

    def get_queryset(self):
        # select_related("scheme") joins the vocabulary row's own scheme lookup into
        # the object fetch; prefetch_related collapses what would otherwise be one
        # query per distinct .all() call site inside concept_property_rows()
        # (alt_labels, one per ConceptNote.Kind) into a single query each — the two
        # helpers that read a cached related set (plan.md Key design decision #7).
        # broader()/narrower()/related() build fresh querysets and are not
        # prefetchable (decisions.md D-015-02), so they are unaffected here.
        return (
            Concept.objects.filter(scheme=self.vocabulary)
            .select_related("scheme")
            .prefetch_related("labels", "concept_notes")
        )

    def get_breadcrumbs(self):
        # T025: PageObjectMixin's own default names the model's plural and links
        # nowhere ("Concepts", href ""), which reads as a trail to every concept
        # rather than the one vocabulary this page's concept belongs to. self.vocabulary
        # is already resolved in setup(), so this costs no extra query.
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
        # The reading language, falling back to the vocabulary's own default (FR-005,
        # decisions.md D6) — concept_property_rows applies the fallback per property
        # only because this view opts in by passing default_language explicitly.
        context = super().get_context_data(**kwargs)
        context["rows"] = concept_property_rows(
            self.object,
            get_language(),
            default_language=self.object.scheme.effective_default_language,
        )
        # T021, FR-014: the collections that gather this concept, never a row in
        # `rows` above — membership is a statement other records make about this
        # one, not a SKOS property this concept carries itself (decisions.md,
        # "Which collections a concept belongs to..."). `collections()` builds a
        # fresh queryset (plan.md Key design decision #7, decisions.md D-015-02),
        # so this is a genuine extra query, not one the existing prefetch collapses.
        context["concept_collections"] = self.object.collections()
        return context


class CollectionDetailView(MVPDetailView):
    """A single collection's own page (015-read-single-record T000). Same treatment as
    :class:`ConceptDetailView`, over :class:`Collection` instead.
    """

    model = Collection
    slug_url_kwarg = "collection_slug"
    template_name = "controlled_vocabularies/ui/collection_detail.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc

    def get_queryset(self):
        # select_related("scheme") joins the vocabulary row's own scheme lookup
        # into the object fetch (015-read-single-record T014, SC-006) — the same
        # collection.scheme collection_property_rows() reads for the vocabulary
        # row and for every member row's short-form prefix (D-015-02).
        return Collection.objects.filter(scheme=self.vocabulary).select_related(
            "scheme"
        )

    def get_breadcrumbs(self):
        # T025: same treatment as ConceptDetailView.get_breadcrumbs() — the upstream
        # default names the model's plural ("Collections") and links nowhere.
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
        context = super().get_context_data(**kwargs)
        context["rows"] = collection_property_rows(self.object)
        # T013, FR-017: no member row appears for an empty collection (its rows
        # loop simply has nothing to append), so "says it holds nothing" needs its
        # own flag rather than a template check for an absent row — computed from
        # the already-built rows, not a second .members() call.
        context["collection_has_members"] = any(
            row["term"] in (MEMBER_CURIE, MEMBER_LIST_CURIE) for row in context["rows"]
        )
        return context


class VocabularyDetailView(MVPListView):
    """A single vocabulary's own page: its description, provenance and the concepts it
    holds (014-look-inside-a-vocabulary, US-1).

    A list view over ``Concept``, not a detail view over ``ConceptScheme`` — plan.md Key
    design decision #1. django-mvp's ``MVPDetailView`` is deliberately empty below its
    heading (its own ADR 0001), so building on it would mean re-implementing search,
    pagination and the empty states ``MVPListView`` already supplies. The vocabulary
    itself is resolved once, in ``setup()``, and carried on ``self.vocabulary`` for every
    hook that needs it.
    """

    model = Concept
    template_name = "controlled_vocabularies/ui/conceptscheme_detail.html"
    list_item_template = "controlled_vocabularies/ui/concept_list_item.html"

    # T010: by the label actually shown, not the stored default-language one — Django
    # applies this innermost (D11), ahead of self.queryset's own annotation being
    # consulted by anything downstream. `pk` is not decoration: without a total order,
    # two identically labelled concepts could land on either of two pages, or on
    # neither, once pagination is in play (#140 makes the same point for vocabularies).
    ordering = [Lower("resolved_label"), "pk"]

    # The orderings a reader may choose, by the label actually shown rather than the stored
    # one — the same annotation the default `ordering` above uses, so a chosen sort and the
    # default agree about what a concept is called. The single-expression limitation and its
    # missing `pk` tiebreak are the list view's, restated: django-mvp#290, decisions.md D16.
    order_by = [
        ("label_asc", _("Label (A-Z)"), Lower("resolved_label")),
        ("label_desc", _("Label (Z-A)"), Lower("resolved_label").desc()),
    ]

    # django-mvp's SearchMixin reads ?q=, strips it, and applies case-insensitive
    # substring matching across these fields with OR semantics, joined with `.distinct()`
    # (T013, FR-008, FR-009, decisions.md D4/plan.md item 4). `label` is the preferred
    # label in the vocabulary's own default language; `labels__text` reaches every
    # ConceptLabel row in one traversal — preferred labels in other languages,
    # alternative labels, and hidden labels. Definitions and notes live on ConceptNote
    # and are deliberately absent, so they are never matched. A hidden label is matched
    # here and never displayed: display comes from `resolved_label`, which only ever
    # reads preferred labels.
    search_fields = ["label", "labels__text"]

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.vocabulary = ConceptScheme.objects.get(slug=kwargs["slug"])
        except ConceptScheme.DoesNotExist as exc:
            raise Http404(_("No vocabulary matches this address.")) from exc
        # US-2 T009, decisions.md D11: assigned to self.queryset here, never built by
        # annotating the result of super().get_queryset() — Django applies
        # self.ordering innermost, ahead of both django-mvp's search and order mixins'
        # own get_queryset() overrides, so an annotation added on the way out would not
        # exist yet when the ordering (T010) is applied. The active language is matched
        # exactly, not by base language (D11) — labels are stored under the site's own
        # configured languages, which is exactly what get_language() returns one of.
        preferred_in_active_language = ConceptLabel.objects.filter(
            concept=OuterRef("pk"),
            language=get_language(),
            kind=ConceptLabel.Kind.PREFERRED,
        ).values("text")[:1]
        # Every concept this vocabulary holds, and only this vocabulary's. No relation
        # is consulted, so the list is flat by construction — a concept three levels
        # down a broader/narrower chain is a plain sibling of one at the top, never
        # rendered nested beneath it (T008, FR-006, FR-012).
        # select_related("scheme") (015-read-single-record T019): the row partial
        # reverses its own link from `object.scheme.slug`, since it renders in an
        # isolated context holding only the object (`render_list_item` builds a fresh
        # context per row) and cannot reach this view's own `vocabulary` context
        # variable. Without the join, that read would cost one query per row, moving
        # the count the flat-query-count guarantee below asserts stays still.
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
        # Without this override the title reads as the concept model's plural, because
        # the view's `model` is `Concept` — the page describes the vocabulary, not concepts.
        return self.vocabulary.name

    def get_search_term(self):
        # Read and stripped exactly as django-mvp's own search mixin does it before
        # filtering (`mvp/views/list.py`), so "a search is in force" means the same
        # thing to the empty states and the "back to the whole vocabulary" link as it
        # does to the queryset (T015, #140's own `?q=%20%20` trap restated here).
        return self.request.GET.get("q", "").strip()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vocabulary"] = self.vocabulary
        context["search_term"] = self.get_search_term()
        # The stripped term, for the same reason the list of vocabularies does it: django-mvp
        # fills the box from the raw `?q=`, so a whitespace-only query would come back in the
        # box and the page would read as searched while filtering nothing (decisions.md D17).
        context["search_query"] = context["search_term"]
        # T019, decisions.md D5/D7: named and, where ordered, marked as such — never
        # rendered through django-mvp's list component (plan.md item 5), and nothing
        # here links to a collection (issue #142 owns its address).
        context["collections"] = self.vocabulary.collections.order_by(Lower("name"))
        return context

    def get_empty_state_heading(self):
        # T015, decisions.md D7: two distinct empty states, never one — a search
        # matching nothing says so and repeats the term; a genuinely empty vocabulary
        # keeps T011's own wording. Never mark_safe, never format_html.
        search_term = self.get_search_term()
        if search_term:
            return _("Nothing matches “%(term)s”") % {"term": search_term}
        return _("This vocabulary holds no concepts")

    def get_empty_state_message(self):
        if self.get_search_term():
            return _("Try a different search term.")
        return None
