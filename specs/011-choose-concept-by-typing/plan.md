# Implementation Plan — 011 Choose a concept by typing instead of scrolling

**Branch**: `011-choose-concept-by-typing` · **Spec**: `spec.md` · **Research**: `research.md` ·
**Decisions**: `decisions.md` · **Issue**: #88 · **Serves**: G2, G5 · **Roadmap**: R3

## Summary

Make both consumption fields render, by default, as a control a person types into. The vocabulary
never reaches the page: the control asks a search endpoint this package carries, the endpoint works
out for itself which concepts the declaring field allows, and it answers a bounded page at a time.

The search behaviour is adopted, not written. `research.md` evaluated three routes and lands on
**django-tomselect**, which is the maintainer's recommendation and also what the evidence supports:
one runtime dependency (`django>=4.2.29`, no transitive packages), MIT, Python 3.11–3.14, no jQuery
anywhere in its chain, bundled assets, and a pagination contract that already clamps page size
server-side. This package writes the parts that are specific to it — which concepts a declaration
allows, and how a concept is matched and displayed across three kinds of label — and inherits the
rest.

**Verified against the artefact, not the branch.** `research.md` read `main` on GitHub. Every API
fact this plan depends on was re-checked against the published wheel `django_tomselect-2026.6.2-py3-none-any.whl`,
because a plan built on a repository's default branch is a plan built on code nobody will install.
Findings that changed as a result are in `decisions.md` D7 to D11 and in Risks below.

**Design-reviewed, and one thing it found was fatal.** A single reviewer read this plan against the
spec, the wheel and the constitution before any story was implemented. It returned five findings, all
five confirmed against the wheel's source rather than accepted on assertion. The critical one is D12:
the first draft enforced the field's restriction only on the search request, which would have made
every legitimate form submission fail validation. D12 to D14 and the amendments to A5 to A9 are that
pass.

The shape of the work:

| What the spec asks | Where it comes from |
|---|---|
| Control is the default representation of both fields (FR-001) | `formfield()` on each model field, returning this package's form field (A3) |
| Package carries the endpoint, project chooses the address (FR-002) | this package's own `urls.py`, included once (A2) |
| Nothing of the vocabulary in the page (FR-003) | inherited — the widget renders one `<select>` and no options (A1) |
| Match across preferred, alternative and hidden labels (FR-004) | `search()` override, one `Q` over the label table plus the default-language column (A4) |
| Display under the preferred label, name the vocabulary (FR-005) | `virtual_fields` + `prepare_results()` over `display_label` (A5) |
| Restriction derived from the declaration, never from the request (FR-006) | two server-side paths: `hook_queryset()` on the endpoint for search, `get_queryset()` on the widget for form validation (A6) |
| Bounded, stable paging (FR-007) | inherited, with a total order and one override for the past-the-end case (A7) |
| Existing record shows what it holds (FR-008) | inherited, verified against the restricted queryset (A8) |
| Route missing is reported by the existing check (FR-010) | `checks.py`, widened (A9) |

## Technical Context

**Language/Version**: Python 3.11+ · **Framework**: Django 5.2 LTS and 6.0
**New runtime dependency**: `django-tomselect ^2026.6.2` — justified in `decisions.md` D7, declared
alongside `views.py`/`forms.py`, which are the first code to import it (Article VII).
**Testing**: pytest + pytest-django + factory_boy from `mvp-shared[test]`.
**Storage**: no model change. No migration in this package. The test app gains none.
**Target**: any Django project installing this package.

**What exists and is being used, not rebuilt:**

| Surface | Where | Used for |
|---|---|---|
| `ConceptFieldMixin` | `fields.py:29` | the shared `vocabulary` contract; the `formfield()` override lands here once, not twice |
| `ConceptField` / `ConceptsField` | `fields.py:146`, `fields.py` | the two declarations the endpoint resolves |
| `limit_choices_to` = `Q(scheme__slug__in=…)` | `fields.py:105` | **the restriction itself** — already declarative, already server-side, already the thing the form uses (A6) |
| `Concept.label` | `models.py:626` | the default-language preferred label, a column — one half of FR-004 |
| `ConceptLabel` (`concept.labels`) | `models.py` | language + kind + text — the other half of FR-004 |
| `Concept.display_label()` | `models.py:750` | FR-005, per result |
| `check_concept_field_vocabularies` | `checks.py:22` | FR-010, widened rather than joined by a second mechanism |
| `AutocompleteModelView` | `django_tomselect/autocompletes.py:141` | the endpoint's base — pagination, JSON shape, request parsing |
| `TomSelectModelChoiceField` / `…MultipleChoiceField` | `django_tomselect/forms.py:389`, `:401` | ordinary `ModelChoiceField` subclasses, returnable from `formfield()` |
| `get_autocomplete_params()` | `django_tomselect/widgets.py:244` | the documented hook that carries the field reference to the endpoint (A6) |

## Constitution Check

| Article | Bearing on this feature | Verdict |
|---|---|---|
| I — Test-First | Every task writes its test first. The two most likely to be asserted vacuously are FR-003 (must assert the *rendered* form carries no concept options at two vocabulary sizes, not that a widget class was chosen) and FR-006 (must assert against a real altered request, not that a helper returns a `Q`). | Pass, watched |
| II — Simplicity | Four overrides on one view, one `formfield()`, one `urls.py`, one widened check. No custom manager, no queryset class, no serializer, no template of our own. | Pass |
| III — Anti-Abstraction | The `formfield()` override goes on the existing mixin because both fields share the `vocabulary` contract it derives from. No new base class. | Pass |
| IV — Integration-First | Exercised through real `ModelForm`s built from the test app's existing consuming models and through real requests to the routed endpoint. | Pass |
| V — Security & data-safety | The whole of A6, plus the two allowlists closed explicitly (D8). The endpoint carries no permission rule by design (D3), which the README states rather than implies. | Pass |
| VI — Documentation | README gains all three wiring steps (D15), what the endpoint exposes, how to restrict it, and the browser requirement. `CONTEXT.md` gains the terms. CHANGELOG records the addition. | Pass |
| VII — Dependency discipline | One dependency, justified in D7 against the alternatives, declared alongside the code that imports it. It carries no transitive runtime packages, which is why deptry stays quiet. | Pass |
| VIII — Compatibility | `django-tomselect` declares `django>=4.2.29` and Python `>=3.11,<4.0`, classifying 5.2 and 6.0 — wider than this package's floor on both axes, so it constrains nothing this package promises. The public names added (`ConceptChoiceField`, `ConceptsChoiceField`, the URL name) enter the API contract. | Pass |
| IX — URI identity | The endpoint returns a concept's identifier and label. It creates nothing and changes nothing. | Pass |
| X — Stack & architecture | Models stay the source of truth. No RDF here. | Pass |
| XII — Internationalization | Every string the control, endpoint and check put in front of a person is wrapped, with named placeholders. Matching runs in the **active** language, which is what makes this article behavioural here rather than cosmetic. | Pass, watched |
| XIV — Test structure | New modules mirror the source tree: `tests/test_views.py`, `tests/test_forms.py`, `tests/test_urls.py`. Consuming models and factories are the shared ones FS-009 and FS-010 left. | Pass |
| XV — Cohesion | The view knows about concepts and declarations. It knows nothing about HTTP shapes beyond what it inherits, and the form field knows nothing about querysets. | Pass |

## Approach

### A1 — The rendered page carries no vocabulary (FR-003)

Inherited and asserted, not built. `TomSelectModelWidget` renders a single `<select>` carrying data
attributes and no `<option>` per eligible concept, so rendered size is independent of vocabulary
size. This is the feature's headline claim and the one most easily satisfied in appearance only, so
the test renders a real `ModelForm` against a vocabulary of a handful and again against one of
several thousand, and asserts the rendered output is the same length. Asserting "the widget is a
TomSelect widget" would pass while the page still grew.

### A2 — One URL configuration, at an address the project chooses (FR-002)

`controlled_vocabularies/urls.py`, new:

```python
app_name = "controlled_vocabularies"
urlpatterns = [
    path("concepts/", ConceptAutocompleteView.as_view(), name="concept-autocomplete")
]
```

The project writes `path("vocabularies/", include("controlled_vocabularies.urls"))` — prefix its
own. The widget resolves the *name*, never a path, so the prefix is honoured (`safe_reverse` in
`widgets.py:237`).

`research.md` flagged Req 1 as unmet by either candidate, on the grounds that a consuming project
must write the `path()` entry itself. That reads the requirement one layer out. The consumer of
`django-tomselect` here is **this package**, which is exactly the party that should own the
endpoint, and the wheel shipping no `urls.py` of its own is what leaves this package free to. The
requirement is met as written; the flag is resolved, not carried (D9).

### A3 — The control is the default, with nothing declared per field (FR-001)

`ConceptFieldMixin.formfield()` returns this package's form field, so a project's ordinary
`ModelForm` gets the control from the model declaration alone. Both model fields inherit it from
the one mixin. The form field classes are thin:

- `ConceptChoiceField(TomSelectModelChoiceField)` and `ConceptsChoiceField(TomSelectModelMultipleChoiceField)` —
  both are ordinary `ModelChoiceField` subclasses, so `formfield()` returning them is the standard
  Django pattern rather than anything the library has to permit.
- their widgets subclass `TomSelectModelWidget` / `TomSelectModelMultipleWidget` and override
  `get_autocomplete_params()` (A6).
- the config pins `css_framework` to the framework-free default, so this package imposes no
  Bootstrap on a project that uses none.

`formfield()` passes through everything Django gives it — `required`, `label`, `help_text`,
`queryset`, `limit_choices_to` — so FR-009's "every guarantee already made is unchanged" holds by
not intervening.

### A4 — Matched by any of its names (FR-004)

Override `search()` on the view. `search_lookups`, the inherited mechanism, expresses one flat list
of ORM lookups and cannot express "the active language's labels, of three kinds, or the
default-language column", so it is left empty and the method is replaced:

```python
Q(label__icontains=query)
| Q(labels__language=active, labels__kind__in=PREFERRED_ALTERNATIVE_HIDDEN, labels__text__icontains=query)
```

then `.distinct()`, which is what makes a concept matching on several of its labels appear once
(FR-004). `icontains` gives case-insensitivity portably and folds no accents, which is D4 stated in
code. The active language is `get_language()`, falling back to `settings.LANGUAGE_CODE` when
translation is inactive.

### A5 — Shown under one name, with its vocabulary (FR-005)

`value_fields = ["id"]`, `virtual_fields = ["display_label", "vocabulary"]`, and a `prepare_results()`
override that reads `Concept.display_label()` — which already resolves the active language and falls
back to the vocabulary's default — and the scheme's label. `hook_queryset()` carries
`select_related("scheme")` and `prefetch_related("labels")`, because `display_label()` walks
`self.labels.all()` and a bounded page would otherwise cost a query per row.

`hook_queryset()` rather than `get_queryset()`: the library documents it as the extension point run
before filtering, searching and ordering (`autocompletes.py:377`, called at `:392`), and overriding
`get_queryset()` puts this package in the position of re-chaining the base pipeline — allowlist
enforcement, `search()`, `order_queryset()` — correctly and forever. Same for A6.

The vocabulary is returned on every result rather than only when a field spans several. FR-005 makes
it conditional; always returning it is one behaviour instead of two, costs one already-selected
attribute, and is inside what FR-012 permits the endpoint to expose.

### A6 — The restriction is derived, never received (FR-006)

The load-bearing part of the feature. **The restriction is enforced twice, on two different paths,
because a search request and a form submission reach the server by different routes.** Design review
found the first draft of this section enforced it on the search path only, and in doing so broke
every legitimate submission — the correction is recorded as D12 and the two paths are now separate.

**Path one — searching.** Three pieces:

1. **The reference the control sends.** The widget overrides `get_autocomplete_params()` — a
   documented hook that reaches the rendered attributes and the browser plugin
   (`widgets.py:440` → `templates/django_tomselect/tomselect.html:193`) — and appends
   `field=<app_label>.<model>.<field_name>`. It is a *reference to a declaration*, never a
   restriction: nothing in it says which vocabulary, and altering it cannot widen anything.
2. **Resolution, in `hook_queryset()`.** Look the reference up through the app registry; require the
   resolved field to be an instance of this package's `ConceptFieldMixin`; apply
   `queryset.complex_filter(field.get_limit_choices_to())`. `complex_filter` is Django's own path
   for exactly this and handles the empty case, so a declaration naming no vocabulary makes every
   concept eligible — its meaning, not an exemption (FR-006).
3. **Refusal that discloses nothing.** A reference that fails to resolve, names a field that is not
   one of this package's, or is absent, returns `Concept.objects.none()` — an ordinary empty page,
   HTTP 200, identical in shape and status to a search that matched nothing. No exception escapes,
   so a missing model and an existing-but-wrong field are indistinguishable from outside.

**Path two — validating a submission.** The reference above is a GET parameter on the control's own
AJAX calls. It is not present when the form is posted, and no amount of care on the endpoint makes
it so. The library's field takes its validation queryset from `self.widget.get_queryset()`
(`forms.py:210-215`), which by default walks back to the endpoint through `LazyView` and an
*ambient* request (`lazy_utils.py:117`) — during a POST, that is the page's own submission, whose
`GET` is empty. Path one's fail-closed branch would then be the guaranteed state on every
submission, and `ModelChoiceField.to_python()` would raise `invalid_choice` for every value.

So this package's widget overrides `get_queryset()` to return
`Concept.objects.complex_filter(field.get_limit_choices_to())` directly, from the model field
instance `formfield()` already holds. No request is consulted, so nothing is request-derived here
either. This restores the behaviour Django's own `formfield()` gives an unmodified
`ModelChoiceField` — a value outside `limit_choices_to` is refused — rather than adding a rule, and
it makes FR-006 hold on the write path, which the search-only design never did.

The two paths derive the same restriction from the same declaration by the same call. They differ
only in how they find the declaration: path one resolves a reference, path two already has the field.

**Two request-controlled surfaces are closed explicitly** (`research.md`, confirmed in the wheel):
`allowed_filter_fields = []` and `allowed_ordering_fields = []`. Both default to `None`, which the
library treats as "validate that the field exists on the model" rather than "reject" — so by default
a hand-edited request can filter or order by any field on `Concept`. The values never leak, but
an unclosed filter is a boolean oracle over the model. The empty list is checked with `is not None`
in both places (`autocompletes.py:500`, `:696`), so `[]` genuinely blocks rather than falling back.

The test alters a real request, and the two surfaces refuse differently — a point the first draft of
this plan got wrong. A rejected `f=` empties the whole page: `apply_filters()` returns
`queryset.none()` (`autocompletes.py:597-603`) and runs *before* `search()` (`:392-396`), so nothing
survives. A rejected `ordering` leaves the results in the view's own order. Asserting "unchanged"
for both would fail on the first (D8).

### A7 — Bounded and stable (FR-007)

`page_size = 20`, and the inherited clamp at `MAX_PAGE_SIZE = 200` already refuses a request asking
for more. Stability needs a **total** order: `ordering = ("label", "pk")`, because `label` is unique
only within a vocabulary and a field naming none can span several. `pk` breaks the tie, so
successive pages neither repeat nor skip.

This is the first ordering path put on `Concept.label`, and Article XIII makes the indexing choice a
recorded one. It is recorded in D13: `label` gets no index in this feature, with the reason and the
condition that would change it.

One override. The inherited `paginate_queryset()` catches `EmptyPage` and returns **page 1**
(`autocompletes.py:743`), which would make a request past the end silently re-serve the beginning —
the spec's edge case says it returns nothing and says no more exist. The override is the empty-page
branch only; everything else is inherited.

### A8 — An existing record shows what it holds (FR-008)

Partly inherited, and one override is now **required rather than contingent**. The widget resolves
already-attached instances server-side to render them as selected, and it does so through
`self.get_queryset()` (`widgets.py:965`) — the very method A6 path two now narrows to the
declaration's restriction. So a concept whose vocabulary the declaration no longer names would be
dropped from the rendered control, and a person would save the emptiness back. A6's fix creates
this, so A6 pays for it: this package's widget overrides `_get_selected_options()` to resolve
already-attached instances against `Concept.objects.all()`.

The two paths are not in conflict once separated. What a record *already holds* is displayed
unrestricted, because the record holds it. What a submission may *newly contain* is validated
against the declaration. That is Django's own behaviour for a `ModelChoiceField` narrowed by
`limit_choices_to`, and FR-008 is about the first while FR-006 is about the second.

The other property still needs asserting: labels must come out as `display_label()` in the active
language rather than `str(obj)`.

### A9 — The missing route is reported at check time (FR-010, and the second wiring step)

Widen `check_concept_field_vocabularies`'s neighbour in `checks.py` with two warnings, both
database-free:

- the package's URL configuration is not included anywhere in the project — reverse the URL name
  and report what to add when it fails;
- `django_tomselect` is not in `INSTALLED_APPS`.

The second exists because the wheel ships its templates and static assets inside its own app
directory, so Django's app-directories template loader and static finder only see them when the app
is installed. **This is a second thing a project must do, and the spec promised one.** It is
recorded as D10, the spec text is amended rather than quietly stretched, and it is on the list for
the plan gate because it changes an acceptance scenario the maintainer approved. Both stay warnings,
matching the existing check: a project mid-setup is not broken.

**The check is not the only place a missing route surfaces.** US-4's independent test asks for a
message naming what is missing rather than an internal error, and a project that ignores the warning
reaches a render, where `get_autocomplete_url()` re-raises `NoReverseMatch` verbatim
(`widgets.py:239-241`). This package's widget catches it and raises `ImproperlyConfigured` naming
both wiring steps, so the two paths give the same answer (D14).

### A10 — Assets, strings, documentation (FR-011, FR-013, FR-014, FR-015)

Assets are the dependency's, reached through Django's ordinary form-media mechanism — this package
ships no JavaScript, no CSS and no template of its own, which is the cheapest way to satisfy FR-011
and the one with nothing to maintain. Strings are wrapped with named placeholders. README gains the
three wiring steps (D15), what the endpoint exposes, how a project restricts access to it, and the
JavaScript requirement. `CONTEXT.md` gains the terms. CHANGELOG records the addition, and the
dependency is declared alongside `views.py`.

## Risks

| # | Risk | Handling |
|---|---|---|
| R1 | The widget builds already-selected options through the restricted queryset, dropping a concept whose vocabulary the field no longer names (FR-008). | No longer a risk but a certainty, created by A6 path two: `_get_selected_options()` calls `self.get_queryset()`. The override is required work in T009, and T009 asserts it on a real record. |
| R2 | `.distinct()` over a join with `order_by("label", "pk")` is correct on PostgreSQL and SQLite but is the kind of thing that differs. | The paging test runs against a match set larger than one page and asserts two successive pages are disjoint and complete, on the suite's real database. |
| R3 | A second live session or a later Django release changes `get_autocomplete_params()`'s wiring, and the field reference silently stops being sent — the endpoint would then return *everything* the fallback allows. | The refusal is fail-closed: an absent reference returns no results, so a broken wiring produces an empty control rather than an unrestricted one. Asserted as its own case. |
| R4 | Single-maintainer dependency (`research.md` Req 8: one maintainer, 87 stars against DAL's 1,870). | Named in D7 with what it would cost to leave: this package's own code is four overrides and a `formfield()`, so the escape is the widget layer, not the feature. |
| R5 | `display_label()` per result reintroduces a query per row. | `prefetch_related("labels")` in `get_queryset()`, asserted with `assertNumQueries` over a full page rather than by inspection. |

## Complexity Tracking

**Why the endpoint is one view rather than one per field.** Both fields target `Concept`, and the
restriction arrives as a reference the view resolves. A view per declaration would put the
restriction in the URL configuration, which is where a project could edit it — the opposite of
FR-006 — and would need a route per consuming field.

**Why the reference is a plain dotted path and not a signed token.** Signing would make tampering
pointless rather than merely useless, but nothing is being protected: the reference carries no
restriction, and every failure path already returns the same empty page. A signature would add key
rotation, a longer URL and a second failure mode to explain, to guard a value whose alteration
already achieves nothing. Article II, and D11.

**Why `formfield()` lands on the mixin.** `ConceptFieldMixin` exists because the `vocabulary`
contract was previously restated in both fields and drifted. The default form representation is
derived from that same contract. Putting it anywhere else reopens the drift the mixin closed.

## Story → task map

| Story | Issue | Tasks |
|---|---|---|
| Phase F — dependency, endpoint skeleton, route | — | T001, T002 |
| US-1 A concept is chosen by typing | #116 | T003, T004 |
| US-2 Found by any of its names, shown by one | #117 | T005 |
| US-3 The results honour what the field allows | #118 | T006, T007 |
| US-4 One route, and nothing else to wire | #119 | T008 |
| US-5 A real vocabulary stays usable | #120 | T010 |
| US-6 An existing record shows what it holds | #121 | T009 |
| US-7 Strings, documentation, test material | #122 | T011 |
