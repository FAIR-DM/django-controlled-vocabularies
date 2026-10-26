# Implementation Plan: Read a single record

**Branch**: `015-read-single-record` · **Spec**: [`spec.md`](./spec.md) · **Decisions**: [`decisions.md`](./decisions.md)

**Input**: Feature specification for issue #142, approved at the specification gate on 2026-08-24.

## Summary

Two new pages in the browsing front end `controlled_vocabularies/ui/` that #140 created and #141
extended: one for a concept, one for a collection. Each is a definition list of everything the
database records about that record, keyed by the SKOS property the value was recorded under. The
work reuses what the two previous slices built — the app, its namespace, the reading-language rule,
the identifier-link treatment — and adds one genuinely new thing, a reusable component for a
term-and-value pair, because nothing upstream renders a definition list.

Nothing in the core package changes except one small addition to the predicate tables: the
existing tables map a SKOS predicate to a stored kind, and these pages need the inverse.

## Technical Context

- **Language / framework**: Python 3.11+, Django 5.2 and 6.0, as the dual-compatibility contract
  requires.
- **Front end**: the `ui` extra — `django-mvp` 0.19.2 and, through it, `django_cotton`. No new
  dependency.
- **Existing surface reused**: `controlled_vocabularies.ui.urls` (namespace
  `controlled_vocabularies_ui`), `Concept.display_label()`, `Concept.preferred_label()`,
  `alt_labels()`, `definition()`, `notes()`, `broader()`, `narrower()`, `related()`,
  `collections()`, `Collection.members()`, and `StaticUriModel.uri` / `local_url`.
- **Storage**: no model changes, no migration. Every value these pages show is already stored.
- **Testing**: pytest with `pytest-django`, `factory_boy`, `django_assert_num_queries`,
  BeautifulSoup for markup assertions — the toolchain the two previous slices already use.
- **Scale**: the vocabulary pages defer scale to R7 and these pages do the same. What they do not
  defer is query-count flatness, which is a correctness property here rather than a performance one.

## Constitution Check

| Article | How this feature satisfies it |
|---|---|
| I — Test-First | Every task writes its test before its implementation; the acceptance scenarios in `spec.md` are the source of the test names. |
| II — Simplicity | One view per page, one template per page, one component. The inverse predicate table is added because a page now reads it, not ahead of need. |
| III — Anti-Abstraction | No registry, no resolver class, no renderer abstraction. A view method builds a list of rows and the template renders them. |
| IV — Integration-First | The routes mirror the addresses the models already compose, so the feature integrates with identity rather than inventing a parallel address space. |
| V — Security & data-safety | Every value reaches the page through the template layer's escaping, nothing is marked safe, and a publisher-supplied identifier reaches an attribute only as a link destination (FR-021). |
| VI — Documentation | The README gains a section for the record pages and the demo walkthrough is extended to reach them, in this PR. |
| VII — Dependency discipline | No new dependency. `rdflib` is already a core runtime dependency, so reading the predicate tables from the browsing app adds nothing to the install. |
| IX — URI identity | The addresses served are exactly the ones `local_url` composes. This feature reads that composition and never redefines it. |
| X — Stack & architecture | The browsing app stays behind the `ui` extra; no core module imports it. The architecture test already enforces this. |
| XI — RDF fidelity | Not engaged. These pages read stored values and serialise no RDF; the CURIEs they key rows on name the properties the values were recorded under. |
| XII — Internationalization | Every user-visible string is wrapped, in Python and in templates. A CURIE is not a user-visible string — it is a SKOS identifier and stays untranslated. |
| XIII — Data-model conventions | No model fields added, so no indexing decision is owed. The reads these pages perform run against indexes that already exist. |
| XIV — Test structure | New tests land in `tests/test_ui/test_views.py` and `tests/test_ui/test_templates.py` as new `Test<Subject>` classes, mirroring the source. No new factory is needed. |
| XV — Cohesion | Row-building lives on the view, which is what Django owns; the language rule stays on the model, where it already is. |

No violation to record. No entry in Complexity Tracking.

## Key design decisions

### 1. These are detail views, not list views

The vocabulary page is a list view over concepts because it genuinely lists something and needed
search, pagination and empty states. A record's page lists nothing that is paginated and searches
nothing, so it is a `DetailView`. The upstream `MVPDetailView` supplies the page chrome and leaves
`{% block page.content %}` empty, which is exactly what a page writing its own body wants.

Its `directory = ["update", "delete"]` names two actions, but every `show_<action>_action` on the
base class defaults to `False` and `resolve_crud_url` drops an action whose flag is falsy before it
reverses anything, so `get_directory()` already returns nothing until a view opts in. **No
`directory` override is needed and none is added.** What is worth keeping is the check itself: the
first task asserts on the rendered page that no editing control appears, because that is what would
catch a default flipping in a 0.x dependency.

**How each view finds its record.** `SingleObjectMixin.get_object` reads
`self.kwargs[self.slug_url_kwarg]`, whose default is `"slug"` — which here is the *vocabulary's*
segment, not the record's. Left alone, every concept page would filter concepts by the vocabulary's
slug and 404. Retargeting `slug_url_kwarg` alone is not enough either: `Concept.slug` is unique only
per scheme (`unique_concept_slug_per_scheme`) and `Collection.slug` likewise, so an unscoped lookup
serves 200 at an address whose vocabulary segment names nothing — which FR-001 forbids — and raises
`MultipleObjectsReturned` the moment two vocabularies share a record slug, which the models permit.

Both views therefore do what `VocabularyDetailView.setup()` (`ui/views.py:186-191`) already does:
resolve the vocabulary from the first path segment, raising `Http404` when it names nothing, then set
`slug_url_kwarg` to `concept_slug` / `collection_slug` and override `get_queryset()` to filter on the
resolved vocabulary. An unknown vocabulary segment and an unknown record segment then both 404
indistinguishably, and a slug shared across vocabularies resolves to exactly one record.

### 2. The routes mirror the addresses the models already compose

`Concept.local_url` is `{scheme.local_url}/{slug}` and `Collection.local_url` is
`{scheme.local_url}/collection/{slug}`. The routes are therefore:

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

`<str:…>` rather than `<slug:…>` for the same reason the vocabulary route uses it: the models
slugify with `allow_unicode=True` and Django's slug converter matches ASCII only. The collection
route is declared first because it is the more specific pattern; the two cannot in fact collide,
since one has three segments and the other two, but declaring the specific one first is the habit
that stays correct when a third shape arrives.

The existing system check `controlled_vocabularies.ui.W001` compares the mount path against the
configured base address. It checks the vocabulary route, and every address in this feature is
composed beneath that same mount, so it already covers them. **No new check** — a second check
asserting the same mount would be duplicate work with a second thing to keep in step.

### 3. One inverse predicate table, in the module that owns the forward one

`exchange/mapping.py` maps a SKOS predicate to a stored kind, for import. These pages need the
opposite: given a stored kind, the CURIE to key its row on. The inverse is **derived from the
existing tables rather than hand-written**, so the two cannot drift:

- `skos_curie()` moves from `SkosGraph` in `exchange/skos.py` into `exchange/mapping.py`, where the
  namespace it depends on already lives. It is a namespace concern, not a graph concern, and
  `skos.py` imports `mapping.py` already, so the dependency runs the right way. Its two existing
  callers in `skos.py` are updated. The move also keeps the browsing app from importing a
  2000-line importer for a two-line formatter; `SkosGraph` is not exported from
  `exchange/__init__.py`, so no public surface changes.
- **`skos_curie` gains a namespace guard.** It slices the SKOS namespace off by length with no check,
  so `skos_curie(rdflib.RDF.type)` returns the mangled `"skos:tax-ns#type"` rather than failing. Its
  docstring scoped it to report display, which is why that has not mattered; keying a page's rows on
  it makes it matter. It must refuse a predicate outside the SKOS namespace.
- `mapping.py` gains `LABEL_CURIES` and `NOTE_CURIES`, each built by inverting the existing dict and
  applying `skos_curie`. Adding a predicate to the forward table therefore adds it to both pages
  with no second edit.
- **The terms no forward table holds are written out.** The relation terms (`skos:broader`,
  `skos:narrower`, `skos:related`), the vocabulary term (`skos:inScheme`), the membership terms
  (`skos:member`, `skos:memberList`) and the type term and its values (`rdf:type` →
  `skos:Concept` / `skos:Collection` / `skos:OrderedCollection`) invert nothing that exists, so they
  are a small module-level constant in `mapping.py` rather than a derivation. The type term is not in
  the SKOS namespace at all, which is the guard above earning its place.

This is a move plus two derived constants and one written-out one — no new concept, and the module
docstring's rule about growing one predicate at a time is honoured, because the derived entries are
the ones already there.

### 4. A row is built in Python, rendered by one component

The view builds an ordered list of rows, each a term (the CURIE), a value, and, when the value is a
record, that record's short form, its canonical identifier and its address on this site. The
template loops that list through one component. **The row order is fixed in the view**, so the page
reads the same way every time and a reader learns where to look: type, preferred label, alternative
labels, notes in the order the note kinds are declared, then the relations, then the vocabulary.

A property carrying no value in the available languages contributes no row (FR-018) — the view
simply does not append it, so the template needs no emptiness logic.

### 5. The component is this package's own, and namespaced

`django-mvp` ships `data_field`, which renders a heading and a paragraph. A definition list needs
`<dt>` and `<dd>` inside a `<dl>`, so there is nothing to reuse.

The component lands at `controlled_vocabularies/ui/templates/cotton/controlled_vocabularies/property_row.html`
and is used as `<c-controlled_vocabularies.property_row />`. **The namespacing is load-bearing**: a
component at `cotton/data_field.html` in this package would silently shadow django-mvp's for the
whole project, since both directories are on the same loader path.

**The styling constraint that decides its markup:** this package ships no stylesheet, and
django-mvp's is prebuilt from django-mvp's own templates, so any utility class this package invents
is absent from the built CSS and does nothing. The component therefore composes django-mvp's own
components and uses only classes that build already emits. A task asserts this by checking the
classes the component names against the shipped stylesheet, so the constraint is enforced rather
than remembered.

### 6. The short form and its identifier

A record's short form is `{scheme.slug}:{record.slug}`, built in the view. Its canonical identifier
is `record.uri`, which is the publisher's where one assigned it and this site's composed address
otherwise. Its link is `{% url %}` against this app's namespace — **never `local_url`**, which is an
identifier and not a route. The existing template test forbids it, but is hardcoded to one file,
so the closing phase widens it to every template that carries an in-site link.

The identifier must be reachable without a pointer (FR-007). A `title` attribute alone does not
satisfy that: it is invisible to a keyboard user and unreliable for a screen reader. The row
therefore carries the identifier in the markup as text associated with the link, visually
secondary, so every reader reaches it by the same means. This is one of the two places where the
plan makes a call the specification deliberately left open, and the acceptance test asserts the
reader-facing outcome rather than the mechanism.

### 7. Query counts are asserted, not hoped for

A record's page reads labels, notes, both relation directions and collection memberships. **Only the
label and note helpers read a cached related set.** `preferred_label()`, `alt_labels()`,
`definition()` and `notes()` iterate `self.labels.all()` / `self.concept_notes.all()`, so one
`prefetch_related` collapses them:

```python
Concept.objects.select_related("scheme").prefetch_related("labels", "concept_notes")
```

`broader()`, `narrower()`, `related()` and `collections()` build fresh querysets
(`Concept.objects.filter(…)`, `Collection.objects.filter(…)`), as does `Collection.members()`. A
fresh queryset bypasses the prefetch cache entirely, so **prefetching the relation paths would be
inert** and is not done. Each record-valued read instead chains `.select_related("scheme")` on the
queryset the helper returns, because the related record's scheme slug is what prefixes its short form
(FR-006) and reading `concept.scheme` per row is one query per related record — precisely what SC-006
forbids.

`collections()` and `members()` return lists rather than querysets. For those the view takes the
prefix from the record's own already-`select_related`ed scheme, which is valid without a second
mechanism: `ConceptRelation._reject_cross_scheme` and `CollectionMember._reject_cross_scheme` make
every relation and every membership intra-vocabulary by construction.

Each page gets a `django_assert_num_queries` test whose count does not move when the number of
labels, notes, relations or members grows — the SC-006 guarantee.

### 8. The links the previous slices deferred

`concept_list_item.html` and the collections list in `conceptscheme_detail.html` both carry a
comment naming this issue as the owner of the address they could not link to. Both become links, and
the comments come out. This is US-4 and it is deliberately last of the P2 stories: it is small, and
it is the one story that cannot be tested until the pages it links to exist.

## Story sequence and structure

Foundational work first, sequential, because every story renders through it:

**Foundational** — the routes, the inverse predicate table, the component, and the row-building the
two views share. No story is dispatched until this is green.

| Order | Story | Depends on |
|---|---|---|
| 1 | US-1 concept page (P1) | foundational |
| 2 | US-2 collection page (P2) | foundational |
| 3 | US-3 links between records (P2) | US-1, US-2 |
| 4 | US-4 links from the vocabulary page (P2) | US-1, US-2 |
| 5 | US-5 collection membership section (P3) | US-1, US-2 |
| 6 | Closing — the guarantees no single story owns, then the demo and changelog | US-5 |

US-3, US-4 and US-5 are independent of one another and could run in parallel. Phase 1 of the
delivery model allows one worktree at a time, so they run in the order above.

The closing phase is a phase rather than a story because its two tasks assert properties that hold
across both pages and belong to no one story. Without it they would sit in no worktree and never be
dispatched.

## Files this feature touches

**Added**

- `controlled_vocabularies/ui/templates/cotton/controlled_vocabularies/property_row.html`
- `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_detail.html`
- `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/collection_detail.html`

**Changed**

- `controlled_vocabularies/ui/views.py` — two view classes and the row-building they share.
- `controlled_vocabularies/ui/urls.py` — two routes.
- `controlled_vocabularies/exchange/mapping.py` — `skos_curie` moves in; two derived tables.
- `controlled_vocabularies/exchange/skos.py` — its two `skos_curie` callers.
- `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/concept_list_item.html` — links.
- `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_detail.html` — links.
- `tests/test_ui/test_views.py`, `tests/test_ui/test_templates.py`, `tests/test_ui/test_urls.py`,
  `tests/test_exchange/test_skos.py`, and `tests/test_exchange/test_mapping.py` (new)
- `demo/seed/research_methods.ttl` — a relation and a second-language note, so the walkthrough
  exercises what the pages show. The seed carries neither today.
- `README.md` — a section for the record pages, and the demo walkthrough extended to reach them.
- `CHANGELOG.md`

**Not touched**: `controlled_vocabularies/models.py`, migrations, `controlled_vocabularies/ui/checks.py`.

## Risks

1. **`MVPDetailView`'s chrome may render an editing affordance this package cannot serve.** It does
   not today — every `show_<action>_action` defaults to `False`, so the directory resolves empty —
   but that is an upstream default in a 0.x dependency and could flip. Mitigation: the first
   foundational task asserts on the rendered page that no editing control appears, so a flip surfaces
   as a red test rather than as an unserveable button.
2. **A component whose classes the built stylesheet does not carry renders unstyled and nothing goes
   red.** This has caught this project before. Mitigation: the component composes django-mvp's own
   components, and a test checks its classes against the shipped stylesheet.
3. **Moving `skos_curie` touches the import path**, which is well covered but is not this feature's
   subject. Mitigation: it is a move with no behaviour change, both callers are updated in the same
   task, and the existing exchange tests must stay green without modification — which the tamper
   guard independently enforces.
4. **A concept in a vocabulary whose slug is long or non-Latin produces an unlovely short form.**
   Accepted: the short form is derived from data the site already owns, and the canonical identifier
   is always present beside it.
