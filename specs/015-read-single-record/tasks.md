# Tasks: Read a single record

**Feature**: `015-read-single-record` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Every task is test-first per Article I: the test is written and seen to fail before the production
change that makes it pass. Test scope per task is one class or one file; the full suite runs once per
story, at the story's report.

`[P]` marks tasks that could run in parallel with their siblings.

**Nothing in this feature changes a model, adds a migration, or touches
`controlled_vocabularies/ui/checks.py`.** A task that finds itself editing
`controlled_vocabularies/models.py` has gone wrong. The one core change is in `exchange/`, is a move
plus two derived constants and one written-out one, and is T001.

**A record's address is never built by hand.** In-site links use `{% url %}` against the
`controlled_vocabularies_ui` namespace. `local_url` is an identifier, not a route. The existing
template test forbids it, but only in the one file it names; T023 widens that guard to every
template carrying an in-site link.

---

## Foundational — no story is dispatched until every task here is green

### T000 — The two addresses resolve, and each finds its record

**Files**: `controlled_vocabularies/ui/urls.py`, `controlled_vocabularies/ui/views.py`,
`tests/test_ui/test_urls.py`

The two `path()` declarations exactly as plan.md §2 gives them, the collection route first:

```python
(
    path(
        "<str:slug>/collection/<str:collection_slug>/",
        CollectionDetailView.as_view(),
        name="collection-detail",
    ),
)
(
    path(
        "<str:slug>/<str:concept_slug>/",
        ConceptDetailView.as_view(),
        name="concept-detail",
    ),
)
```

`<str:…>` and not `<slug:…>`, for the reason the vocabulary route already documents: the models
slugify with `allow_unicode=True` and Django's converter is ASCII-only.

The two view classes come with the routes, carrying **only the record resolution both pages share**.
`SingleObjectMixin`'s default `slug_url_kwarg` is `"slug"`, which on these routes is the
*vocabulary's* segment, so left alone each view filters records by the vocabulary's slug and 404s on
every real address. Retargeting `slug_url_kwarg` alone is not enough either: `Concept.slug` is unique
only per scheme and `Collection.slug` likewise, so an unscoped lookup serves 200 at an address whose
vocabulary segment names nothing and raises `MultipleObjectsReturned` when two vocabularies share a
record slug. Each view therefore resolves the vocabulary from the first segment in `setup()`, raising
`Http404` when it names nothing — the shape `VocabularyDetailView.setup()` already uses — retargets
`slug_url_kwarg` to `concept_slug` / `collection_slug`, and scopes `get_queryset()` to the resolved
vocabulary. Nothing else: no template, no context, no rows.

**This is foundational because T003 depends on it.** T003 returns each record-valued row's in-site
address, which it must reverse through this namespace; without these names it raises
`NoReverseMatch`. The pages themselves, their 404 assertions and the read-only assertion stay with
T004 and T011.

**Proves**: the addressing and resolution FR-001 and FR-002 depend on.
**Verify**: each name reverses to the address `local_url` composes for the same record, including one
slugged in a non-Latin script; a record slug held by two vocabularies resolves to the one named in
the address.
**Depends on**: nothing.

### T001 — A stored kind knows the SKOS property it fills

**Files**: `controlled_vocabularies/exchange/mapping.py`, `controlled_vocabularies/exchange/skos.py`,
`tests/test_exchange/test_mapping.py` (new), `tests/test_exchange/test_skos.py`

Move `skos_curie` from `SkosGraph` in `skos.py` into `mapping.py` as a module-level function, and
update its two callers in `skos.py`. It depends only on the SKOS namespace, which lives in
`mapping.py` already, and `skos.py` imports `mapping.py`, so the dependency runs the right way.

**Give `skos_curie` a namespace guard.** It slices the SKOS namespace off by length with no check, so
`skos_curie(rdflib.RDF.type)` returns the mangled `"skos:tax-ns#type"` instead of failing. It must
refuse a predicate outside the SKOS namespace. Its docstring scoped it to report display, which is
why this has not mattered; keying a page's rows on it makes it matter.

Add `LABEL_CURIES` and `NOTE_CURIES`, each **derived by inverting the existing forward table and
applying `skos_curie`** — never hand-written. A predicate added to `LABEL_PREDICATES` or
`NOTE_PREDICATES` must therefore appear in the inverse with no second edit.

**Add the terms no forward table holds**, written out as a module-level constant because they invert
nothing that exists: the relation terms (`skos:broader`, `skos:narrower`, `skos:related`), the
vocabulary term (`skos:inScheme`), the membership terms (`skos:member`, `skos:memberList`), and the
type term `rdf:type` with its values `skos:Concept`, `skos:Collection` and `skos:OrderedCollection`.
Without these, FR-010 to FR-013 have nothing to key a row on.

**Two assertions, and neither borrows the implementation.** Assert the derived tables against
hand-written expected CURIEs, the shape D48 already established for these exact predicates in
`tests/test_exchange/test_skos.py` — restating the expectation rather than recomputing it, which
would compare the implementation to itself and pass for any behaviour. Separately assert that every
key of `LABEL_PREDICATES` and `NOTE_PREDICATES` appears in its inverse, which is the no-second-edit
property, and is not tautological because it compares two different structures.

`tests/test_exchange/test_mapping.py` is new and mirrors a source module, so it needs no
conformance declaration.

**Proves**: FR-003 (the keying the rows depend on).
**Verify**: the exchange suite passes unchanged apart from the two updated call sites; the derived
tables match the hand-written expectations; `skos_curie` raises on a non-SKOS predicate.
**Depends on**: nothing.

### T002 — One component renders a term and its value

**Files**: `controlled_vocabularies/ui/templates/cotton/controlled_vocabularies/property_row.html`
(new), `tests/test_ui/test_templates.py`

A component taking a term, a value, and optionally a record's short form, canonical identifier and
in-site address. It renders a `<dt>`/`<dd>` pair; a caller wraps a run of them in a `<dl>`.

**Namespacing is load-bearing.** The path puts it at `<c-controlled_vocabularies.property_row />`.
A component at `cotton/data_field.html` in this package would silently shadow django-mvp's for every
project that installs both, because the two directories sit on one loader path.

**It composes django-mvp's own components and uses no class this package invents.** This package
ships no stylesheet and django-mvp's is prebuilt from django-mvp's own templates, so an invented
utility class is absent from the built CSS and does nothing at all, silently. Assert this: every
class the component names is present in the shipped stylesheet. Pick a control class the build has
no other reason to emit, so a passing assertion means something.

**Proves**: FR-016.
**Verify**: the component renders both shapes in isolation through `render_to_string`; the class
assertion passes; no `<dt>` or `<dd>` is written by hand anywhere else in this feature.
**Depends on**: nothing.

### T003 — The rows a record contributes, in a fixed order

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

The shared row-building both pages use: given a record and the reading language, return an ordered
list of rows, each carrying its term (a CURIE from T001), its value, and — where the value is a
record — that record's short form `{scheme.slug}:{record.slug}`, its `uri`, and its in-site address.

**The order is fixed here and not in a template**, so the page reads the same way every time: type,
preferred label, alternative labels, notes in the order `ConceptNote.Kind` declares them, relations,
then the vocabulary. A property with no value in the available languages **contributes no row**, so
no template ever needs emptiness logic.

Hidden labels are never a row (FR-004). Assert that with a concept that has one.

**Proves**: FR-003, FR-004, FR-006, FR-018.
**Verify**: unit tests over the returned rows for a richly populated concept, a bare one, and one
carrying a hidden label.
**Depends on**: T000, T001.

---

## Story US-1 — Open a concept and read what it holds (P1)

### T004 — A concept's address serves a read-only page

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

`ConceptDetailView` gains its page: the template it renders and the context it builds. Its route and
its record resolution came with T000; this task asserts the behaviour they produce.

404 for a concept slug naming nothing, **and equally for a vocabulary segment naming nothing**
(FR-001). A concept whose slug exists in a different vocabulary is not found here — assert it with
two vocabularies each holding that slug, so the assertion covers the multiple-match case too.

The page is read-only. **The test asserts on the rendered page that no editing control appears**: the
upstream directory already resolves empty because every `show_<action>_action` defaults to `False`,
so the assertion exists to catch that default flipping, not to verify an override.

**Proves**: FR-001, FR-009 · SC-001 · US-1 scenario 5.
**Verify**: anonymous request to a real concept returns 200; both flavours of unknown address
return 404; a concept slug shared by two vocabularies resolves to the right one; no edit or delete
affordance in the markup.
**Depends on**: T003.

### T005 — Everything recorded appears, keyed by its property

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_detail.html`
(new), `tests/test_ui/test_views.py`

The page renders the rows from T003 inside one `<dl>`, through the T002 component. A concept with a
preferred label, alternative labels, a definition and a scope note shows each on its own row under
the SKOS property it was recorded under. No hidden label appears anywhere in the markup.

**Proves**: FR-003, FR-004 · SC-001, SC-002 · US-1 scenarios 1, 2.
**Verify**: parse the page and assert term/value pairs by their CURIE; assert the hidden label's text
is absent from the whole response.
**Depends on**: T004.

### T006 — A value is shown in the language being read

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

The reading language, falling back to the vocabulary's own default — the rule
`Concept.display_label()` already implements, applied to notes and alternative labels as well as to
the preferred label. One language, never every language a value was recorded in.

**Proves**: FR-005 · US-1 scenario 3.
**Verify**: a concept with German and English values renders the German ones under a German reading
language, and a concept with no German value falls back to its vocabulary's default rather than
rendering nothing.
**Depends on**: T005.

### T007 — Type and identifier

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_detail.html`,
`tests/test_ui/test_views.py`

A row saying what kind of thing the record is, keyed by the RDF type property, and the record's own
identifier shown as a link — the treatment the vocabulary page already gives a vocabulary's.

**Proves**: FR-008, FR-012.
**Verify**: both rows present; **the type row's key is the literal `rdf:type`**, not a CURIE the SKOS
formatter mangled out of it; the identifier is an anchor whose destination is the record's `uri`; an
imported concept shows its publisher's identifier.
**Depends on**: T005.

### T008 — An unfilled property produces no row [P]

**Files**: `tests/test_ui/test_views.py`

A concept carrying nothing beyond its label shows its label, its type, its identifier and its
vocabulary, and shows no row for any property it does not carry — not an empty one, not one reading
as absent.

**Proves**: FR-018 · US-1 scenario 4.
**Verify**: count the rows on a bare concept's page and name them.
**Depends on**: T005.

### T009 — The page's query count does not grow with what it shows [P]

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

`select_related("scheme")` and one `prefetch_related` over `labels` and `concept_notes` — the two
helpers that read a cached related set.

**The relation helpers are not prefetchable.** `broader()`, `narrower()`, `related()` and
`collections()` build fresh querysets, so a prefetch of the relation paths is inert. Chain
`.select_related("scheme")` on the queryset each helper returns, because the related concept's scheme
slug prefixes its short form and reading it per row is one query per related record. `collections()`
returns a list, and every membership is intra-vocabulary by construction, so its prefix comes from
the concept's own already-loaded scheme.

**Proves**: SC-006.
**Verify**: establish the count with `CaptureQueriesContext`, then assert it with
`django_assert_num_queries` and show it unmoved when the concept gains labels, notes, relations and
memberships.
**Depends on**: T005.

### T010 — The README documents the concept page

**Files**: `README.md`

A section covering what the page shows, how it is reached, and the view that serves it, in the shape
the vocabulary sections already use. Every public name the story introduces is quoted.

**Proves**: Article VI.
**Verify**: the documented reverse names and view names exist; the documented behaviour matches the
tests.
**Depends on**: T009.

---

## Story US-2 — Open a collection and see what it holds (P2)

### T011 — A collection's address serves a page

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

`CollectionDetailView` gains its page, declared before the concept route by T000. Same read-only
treatment and the same two flavours of 404 as T004, over the resolution T000 already built.

Assert that a concept and a collection sharing one slug inside one vocabulary are both reachable —
the disjointness the address segment exists for.

**Proves**: FR-002, FR-009 · Edge case 2.
**Verify**: 200 on a real collection; 404 on both flavours of unknown; the shared-slug pair both
serve, at different addresses.
**Depends on**: T003.

### T012 — Name, type and members

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/collection_detail.html`
(new), `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

The same definition list: the collection's name, its identifier as a link, a type row distinguishing
an ordered collection from an unordered one, and its members under the membership property matching
its kind. An ordered collection's members appear in the sequence their positions record.

**Proves**: FR-008, FR-012, FR-013 · SC-005 · US-2 scenarios 1, 2.
**Verify**: an unordered collection and an ordered one render different type rows and different
membership properties; the ordered one's members are in position order, asserted against a
deliberately non-alphabetical sequence so the assertion cannot pass by accident.
**Depends on**: T011.

### T013 — A collection holding nothing says so [P]

**Files**: `tests/test_ui/test_views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/collection_detail.html`

Distinct wording, and no empty membership row.

**Proves**: FR-017 · US-2 scenario 3.
**Verify**: the page renders, says the collection holds nothing, and carries no membership row.
**Depends on**: T012.

### T014 — The collection page's query count is flat [P]

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

As T009, for members. `Collection.members()` builds `self.memberships.select_related("concept")` —
note `"concept"`, not `"concept__scheme"` — so it needs widening, or the prefix read costs one query
per member.

**Proves**: SC-006.
**Verify**: the count does not move as members are added.
**Depends on**: T012.

### T015 — The README documents the collection page

**Files**: `README.md`

**Depends on**: T014.

---

## Story US-3 — Follow a record to the records around it (P2)

### T016 — A record-valued row carries a short form, an identifier and a link

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/cotton/controlled_vocabularies/property_row.html`,
`tests/test_ui/test_views.py`

The short form is `{scheme.slug}:{record.slug}`. The link goes to that record's page **on this
site**, reversed through the app's namespace. The canonical identifier is the record's `uri`, which
for an imported record is its publisher's.

**The identifier must be reachable without a pointer** (FR-007). A `title` attribute alone does not
satisfy that — it is invisible to a keyboard user and unreliable for a screen reader. Carry it in
the markup as text associated with the link. The test asserts the reader-facing outcome: the
identifier is present in the response and associated with its link, without relying on hover.

**Proves**: FR-006, FR-007 · SC-003 · US-3 scenarios 3, 4.
**Verify**: a concept in an imported vocabulary shows the publisher's identifier while its link
resolves to this site's page for it; the identifier is in the markup, not only in an attribute a
pointer reveals.
**Depends on**: T005, T012.

### T017 — Broader, narrower and related

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

Each as its own row keyed by the SKOS property naming the relation. **Narrower is derived** — only
the broader direction is stored — so assert it from a concept that is the broader of two others.

**Proves**: FR-010 · SC-003 · US-3 scenarios 1, 2.
**Verify**: use the existing relation graph builder; follow a broader link and arrive at that
concept's page.
**Depends on**: T016.

### T018 — The vocabulary a record belongs to, and no further step [P]

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

A row for the vocabulary, keyed by its SKOS property and linking to its page. **No ancestor chain**:
a concept three levels down shows its immediate broader concept and nothing above it.

**Proves**: FR-011.
**Verify**: build a three-level chain and assert the middle concept's page names only its immediate
neighbours.
**Depends on**: T017.

---

## Story US-4 — Reach a record from the vocabulary that holds it (P2)

### T019 — A vocabulary's concepts link to their pages

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_list_item.html`,
`tests/test_ui/test_views.py`, `tests/test_ui/test_templates.py`

The row partial becomes a link, and the comment naming this issue as the owner of the address comes
out. A narrowed list links its results the same way.

**Proves**: FR-015 · SC-004 · US-4 scenarios 1, 3.
**Verify**: follow an entry from the vocabulary page and from a search result, and arrive at the
right concept.
**Depends on**: T004.

### T020 — A vocabulary's collections link to their pages

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_detail.html`,
`tests/test_ui/test_views.py`

Same, for the collections section, and its comment comes out too.

**Proves**: FR-015 · SC-004 · US-4 scenario 2.
**Verify**: follow a collection entry and arrive at the right collection.
**Depends on**: T011.

---

## Story US-5 — See which collections a concept belongs to (P3)

### T021 — The membership section

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_detail.html`,
`tests/test_ui/test_views.py`

Below the definition list and outside it, under a heading in plain language rather than a CURIE,
because SKOS has a property pointing from a collection to its concepts and no inverse of it. Each
collection links to its page.

**Proves**: FR-014 · US-5 scenario 1.
**Verify**: a concept gathered by two collections names both, outside the `<dl>`, each linking
correctly.
**Depends on**: T012, T016.

### T022 — No section when no collection gathers it [P]

**Files**: `tests/test_ui/test_views.py`

Absent, not empty.

**Proves**: FR-014 · US-5 scenario 2.
**Verify**: the heading does not appear at all.
**Depends on**: T021.

---

## Closing — the guarantees no single story owns, then the demo

Both tasks here run after US-5, in the order given.

### T023 — Translation, escaping, and the links that cannot exist

**Files**: `tests/test_ui/test_views.py`, `tests/test_ui/test_templates.py`

Four requirements that hold across both pages and belong to no one story, asserted once here rather
than assumed everywhere.

- **Every user-visible string these pages show is translatable** (FR-019). A CURIE is not a
  user-visible string — it is a SKOS identifier and stays untranslated. The existing template scan
  already globs every template under the templates root, so it covers the new templates the moment
  they exist and needs no widening. **Scope this bullet to the Python-side strings the views
  introduce**, which that scan does not reach.
- **The in-site-link guard covers the templates this feature adds** (FR-006). Today
  `ROW_TEMPLATE_PATH` names one file, so no template added here is in its scope. Turn it into the
  list of templates that carry an in-site link — the two existing row partials plus
  `property_row.html` — and parametrise the existing assertions over it.
- **Values reach the reader escaped** (FR-021). A concept whose label, note or publisher-supplied
  identifier contains markup renders it as text. Nothing is marked safe, and a publisher-supplied
  identifier reaches an attribute only as a link's destination.
- **No cross-vocabulary link appears** (FR-020). Nothing stores a concept's exact or close matches,
  so no row can carry one. Assert it against a concept imported from a file that offered them, so
  the assertion is about the shipped behaviour rather than about an empty database.

**Proves**: FR-019, FR-020, FR-021 · SC-007.
**Verify**: the assertions above pass; the escaping test fails if `|safe` is introduced anywhere in
either template; the widened link guard fails if `local_url` is reintroduced in any listed template.
**Depends on**: T012, T017, T022.

### T024 — The demo reaches the new pages, and the changelog records them

**Files**: `README.md`, `CHANGELOG.md`, `demo/seed/research_methods.ttl`, `demo/` as needed

The demo walkthrough seeds two vocabularies and one collection of each kind. **It seeds no relation
and one language** — checked, not assumed: neither seed file carries `skos:broader` or
`skos:related`, and every literal in both is tagged `@en`. So extending the seed is a step of this
task, not something its verification can take for granted.

- Extend `demo/seed/research_methods.ttl` with a broader/narrower pair, a related pair, and a note in
  a second language.
- Extend the documented walk so it ends on a concept's page and a collection's page.
- Confirm the walk exercises what the pages show: a relation, a collection membership, and a value
  falling back across languages.
- Changelog entry per the quality bar.

Three documentation debts fall due here too. The documentation check only runs when it is given a
base ref to diff against, which the per-story verifications did not pass, so it stayed silent from
T001 on and all three surfaced at once at US-5's convergence.

- **The concept page section does not mention the membership section T021 added.** It documents
  every row of the definition list and stops. Say that the collections gathering a concept are named
  below the list rather than in it, why the heading is plain language where every row is keyed by a
  SKOS property, and that a concept no collection gathers shows no such section.
- **Three public names this feature added are documented nowhere**: `skos_curie` in
  `controlled_vocabularies.exchange.mapping`, and `concept_property_rows` and
  `collection_property_rows` in `controlled_vocabularies.ui.views`. Each is the seam a consumer
  reaches for when building their own page or their own rendering of a report, so each belongs where
  that consumer is already reading — the two row builders in the page sections that name the view
  they serve, `skos_curie` where the README first explains what a short form is. A docstring is not
  documentation and neither is a changelog entry.
- **Nothing this feature added may be left undocumented.** Run the check rather than reasoning about
  which names it will flag.

**Proves**: Article VI, SC-008.
**Verify**: run the documented commands from a clean database and walk the documented path;
`forge verify --base main --steps docs` exits green.
**Depends on**: T023.

## Reader-reported corrections — six defects found reading the shipped pages

Raised by the maintainer after walking a vocabulary's page through to a concept's and a
collection's. Each is a mismatch between what the specification says and what the pages do, not a
change of intent, so each is corrected here rather than re-specified.

### T025 — A detail page's breadcrumb trail names its own vocabulary

A vocabulary's page shows "Home > DCMI Type Vocabulary". Both record pages showed the upstream
default instead — the model's plural, linking nowhere. Both now show home, the vocabulary holding
the record, and the record itself, unlinked as the page the reader is already on.

**Proves**: FR-002.
**Verify**: the trail's texts and hrefs, on both pages.

### T026 — The record's own identifier leads the page

It sat at the foot, beneath everything the record says about itself. A reader citing the record
should not have to scroll past the whole definition list to reach it, so it now sits directly
beneath the title. Still not a row of the list: the fixed row order names only SKOS statements the
record makes about itself.

**Proves**: FR-008.
**Verify**: the identifier's position precedes the definition list's, on both pages.

### T027 — The membership section names its direction, and its entries underline on hover

"Collections" reads as collections belonging to the concept, the inverse of what the section says.
It is now "Member of". Both this section's entries and the vocabulary page's collection entries
were bare anchors carrying no class at all; both now compose django-mvp's own link component with
its hover variant.

**Proves**: FR-014.
**Verify**: the heading's text, and the hover class on every entry of both sections.

### T028 — A collection's members are one group, not one row each

A four-member collection stated `skos:memberList` four times, once per member. The property is
stated once now, with every member listed beneath it, the same shape the membership section uses. A
collection holding no members still contributes no row at all.

**Proves**: FR-012, FR-013, FR-017.
**Verify**: exactly one membership term on the page, carrying every member.

### T029 — A short form discloses its identifier on hover, not underneath it

The canonical identifier was printed as text beside the short form. The specification asks for it on
hover. A `.tooltip` span now *wraps* each link, carrying the identifier as its `data-tip`, and the
link names a visually-hidden `.sr-only` span holding the same value through `aria-describedby`.

Two corrections to the first attempt, both load-bearing. The class belongs on a wrapper rather than
on the anchor: daisyUI's reveal rule is `:has(:focus-visible)`, which matches a focused *descendant*,
so an anchor carrying the class never matched its own focus and the keyboard reveal silently never
fired. And the accessible description is `aria-describedby`, not `title`: where both are present the
former wins, and whether a screen reader announces `title` at all is a per-user setting. `aria-label`
is not used — it would replace the link's accessible name, the short form, rather than add to it.

The caller generates one `identifier_id` per record-valued row, so the hidden spans stay distinct on
a page showing several.

**Proves**: FR-006, FR-007.
**Verify**: the identifier is absent from the row's visible text, present in the wrapper's `data-tip`
and in the hidden span the link describes itself by, and absent from any `title` attribute; two
related records on one page have distinct hidden-span ids.

### T030 — Reconcile the tests these changes invalidate

Three tests pin the behaviour T029 reverses, and two pin T028's one-row-per-member shape. Each is
evidence about intent, so each is amended in place to assert the new guarantee rather than deleted.
A new case proves a publisher-supplied identifier is escaped both in the wrapper's `data-tip` and in
the hidden span's text.

**Proves**: Article IV.
**Verify**: no test is removed, and the suite is green.

### T031 — A row's term discloses the URI its CURIE abbreviates

The fifth point again, on the term side: hovering a row's term showed nothing. A CURIE abbreviates
a URI wherever it appears, so a term now carries the same disclosure a short form does, through
`curie_uri()`, which expands a prefixed name against the namespaces the package declares and
refuses one it does not. The term is wrapped in `<abbr>` — a CURIE is an abbreviation, and the
element makes a screen reader announce the expansion where a pointer-only tooltip cannot reach.

**Proves**: FR-007.
**Verify**: every term on both pages carries the URI its CURIE expands to, and no page prints it.
