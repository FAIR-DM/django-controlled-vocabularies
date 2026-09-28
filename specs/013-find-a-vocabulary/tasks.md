# Tasks: Find a vocabulary

**Feature**: `013-find-a-vocabulary` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Every task is test-first per Article I: the test is written and seen to fail before the production
change that makes it pass. Test scope per task is one class or one file; the full suite runs once per
story, at the story's report.

`[P]` marks tasks that could run in parallel with their siblings. Phase 1 is sequential and blocks
everything.

## Phase 1 — Foundational

### T001 — The ui extra exists and CI installs it

**Files**: `pyproject.toml`, `poetry.lock`, `.github/workflows/tests.yml`

Declare `django-mvp` as an **optional** dependency pinned `>=0.19,<1.0` with a
`python = ">=3.12"` marker, and add a `[tool.poetry.extras] ui = ["django-mvp"]` entry. django-mvp's
own floor is 3.12 while this package's is 3.11, so the marker makes the extra unavailable there
rather than an error. Add `[tool.deptry.package_module_name_map] django-mvp = "mvp"` — without it
deptry looks for a module named `django_mvp` and reports every ui import as missing. Regenerate the
lock. Change the tests workflow's `poetry-install-args` from `''` to `'--extras ui'`, and add
`controlled_vocabularies/ui/**` to nothing — the workflow's push path filter already covers
`controlled_vocabularies/**`.

Also declare the four test modules that mirror no source module, or the conformance check reads them
as testing standard §4 violations once T004 and T009 land:

```toml
[tool.forge.conformance]
non-mirror-paths = [
    "tests/test_ui/test_architecture.py",
    "tests/test_ui/test_boot.py",
    "tests/test_ui/test_packaging.py",
    "tests/test_ui/test_templates.py",
]
```

Name the four files, not the `tests/test_ui/` prefix — the rest of that directory does mirror
modules and must stay checked.

**Proves**: nothing on its own. **Verify**: `poetry install --extras ui` succeeds, `poetry check`
clean, `deptry` clean, the existing suite green.

**Depends on**: nothing.

---

### T002 — The ui app exists and registers

**Files**: `controlled_vocabularies/ui/__init__.py`, `controlled_vocabularies/ui/apps.py`,
`tests/test_ui/__init__.py`, `tests/test_ui/test_apps.py`

`__init__.py` is a module docstring and nothing else — it is imported in the app registry's first
phase, so a re-export reaching `views.py` would touch models and raise `AppRegistryNotReady` at
`django.setup()`. `apps.py` declares the config with `name = "controlled_vocabularies.ui"` and
`label = "controlled_vocabularies_ui"`; the label must differ from the core app's or the registry
refuses both.

Test, in `TestUIAppConfig`: the app registers alongside the core app without raising (a subprocess
with an inline `settings.configure`, per the repo's existing out-of-process precedent in
`tests/settings_no_admin.py`), the config's label is the distinct one, and `__init__.py` parses to
exactly one statement whose value is a string constant.

**Proves**: the app loads and stays inert at import time. **Verify**: `pytest tests/test_ui/test_apps.py`.

**Depends on**: T001.

---

### T003 — The test project can render the ui, and can still boot without it

**Files**: `tests/settings.py`, `tests/settings_core.py` (new), `tests/urls.py`,
`tests/urls_core.py` (new)

`tests/settings_core.py` holds what the package needs on its own — the current contents of
`tests/settings.py`, with `ROOT_URLCONF = "tests.urls_core"` pointing at an empty urlconf.
`tests/settings.py` becomes a star-import of it plus the ui stack: `django_cotton`, `easy_icons`,
`flex_menu`, `crispy_forms`, `crispy_tailwind`, `mvp` and `controlled_vocabularies.ui` in
`INSTALLED_APPS`, django-mvp's context processor appended to `TEMPLATES`, and the
`CRISPY_TEMPLATE_PACK`, `CRISPY_ALLOWED_TEMPLATE_PACKS`, `EASY_ICONS` and `FLEX_MENUS` settings
django-mvp expects.
`django-literature`'s `tests/settings.py` is the working list — copy it, do not invent it, but
**filter the copy to django-mvp's own declared dependencies**. In particular it installs
`django_tables2`, which django-mvp does not depend on (it is a guarded optional integration there)
and `--extras ui` does not install; this page is a card grid, not a table, and because
`tests/settings.py` is the settings module for the whole repo, naming an uninstalled app there
fails collection of every test in the suite, not only these. `SITE_ID` goes the same way —
django-mvp uses no `django.contrib.sites`, so the setting is inert.
`tests/urls.py` mounts `controlled_vocabularies.ui.urls` under a non-empty prefix of the test
project's choosing, so a hard-coded path in a view is caught rather than accidentally matching.

**Proves**: nothing on its own. **Verify**: existing suite green under the widened settings;
`manage.py check` clean under both settings modules.

**Depends on**: T002.

---

### T004 — The core neither imports nor requires the ui stack

**Files**: `tests/test_ui/test_architecture.py` (new), `tests/test_ui/test_boot.py` (new),
`tests/test_ui/test_packaging.py` (new)

Three independent proofs, each of which fails for a different mistake:

- **Architecture**: parse every `controlled_vocabularies/**/*.py` outside `ui/` with `ast` and
  assert none imports `mvp`, `django_cotton`, `crispy_forms`, `easy_icons`, `flex_menu` or
  `controlled_vocabularies.ui`. Parsed, not grepped, so a mention in a docstring cannot fail it.
- **Boot**: in a fresh subprocess forcing `DJANGO_SETTINGS_MODULE=tests.settings_core` inside the
  script (pytest-django exports the other one), run `django.setup()` and `call_command("check")`,
  import every core module, then assert `"controlled_vocabularies.ui" not in sys.modules`.
- **Packaging**: parse `pyproject.toml` with `tomllib` and assert django-mvp is optional, is listed
  in the `ui` extra, and appears in no other extra and no dependency group.

**Proves**: the isolation the whole structure rests on is a property, not a convention.
**Verify**: `pytest tests/test_ui/test_architecture.py tests/test_ui/test_boot.py tests/test_ui/test_packaging.py`.

**Depends on**: T003.

---

### T005 — A project that forgets the extra is told so

**Files**: `controlled_vocabularies/ui/checks.py` (new), `controlled_vocabularies/ui/apps.py`,
`tests/test_ui/test_checks.py` (new)

Register a system check from the ui config's `ready()` that reports an error when `mvp` cannot be
imported, naming both the extra to install and the app that requires it. Without it the first
symptom is `ModuleNotFoundError: mvp` raised from URL loading, which names neither.

Test: with `mvp` importable the check returns nothing; with the import made to fail, it returns one
error carrying the package extra in its message and a stable id.

**Proves**: FR-012's neighbour — the app fails legibly when its dependency is absent.
**Verify**: `pytest tests/test_ui/test_checks.py`.

**Depends on**: T002.

---

## Phase 2 — US-1: See every vocabulary the site holds (P1, #143)

### T006 — The page exists at a name, and lists every vocabulary once

**Files**: `controlled_vocabularies/ui/urls.py` (new), `controlled_vocabularies/ui/views.py` (new),
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list.html` (new),
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list_item.html` (new),
`tests/test_ui/test_urls.py` (new), `tests/test_ui/test_views.py` (new)

`urls.py` declares `app_name = "controlled_vocabularies_ui"` — distinct from the core's namespace so
both can be mounted in one project — and one route at the empty path named `vocabulary-list`,
importing views relatively. `views.py` holds `VocabularyListView(MVPListView)` over `ConceptScheme`
with `list_item_template` naming the row partial and `template_name` naming the page template. The
page template extends django-mvp's `list_view.html` and, for now, overrides `{% block page.actions %}`
to render nothing — the default block renders search, sort, filter and create, none of which this
story has. The row partial renders the vocabulary's name and description.

Test, in `TestVocabularyList`: reverse the route by name (never by path) and request it; every
vocabulary in the database appears exactly once; a vocabulary added afterwards appears on the next
request; the page renders no sort, filter or create control.

**Proves**: FR-001, FR-012, and the first acceptance scenario of User Story 1.
**Verify**: `pytest tests/test_ui/test_urls.py tests/test_ui/test_views.py`.

**Depends on**: T005.

---

### T007 — An entry shows its description, its size, and where it came from

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list_item.html`,
`tests/test_ui/test_views.py`

`get_queryset()` annotates `concept_count=Count("concepts")`. The row renders the description, the
count, and the origin: a vocabulary whose `static_uri` is set is shown as imported and shows that
identifier as **text**, never as a link — an identifier is not always a resolvable address; one with
no `static_uri` is shown as held here and shows no identifier.

Test, in `TestVocabularyListEntry`: an imported vocabulary's entry carries its publisher identifier
and the imported wording; a locally authored one carries neither; a vocabulary with three concepts
reports three; one with none still appears and reports none rather than an empty space; a
vocabulary with no description renders without a stray label or punctuation.

**Proves**: FR-002, FR-003, and User Story 1 scenarios 2 to 5.
**Verify**: `pytest tests/test_ui/test_views.py -k Entry`.

**Depends on**: T006.

---

### T008 — The order is alphabetical, stable, and costs a flat number of queries

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_views.py`

Set `ordering = [Lower("name"), "pk"]` as a **class attribute**, not an `.order_by()` call inside
`get_queryset()`. Django applies `self.ordering` innermost, ahead of both django-mvp mixins; ordering
from our own `get_queryset()` would land after the search mixin's `.distinct()`, which is the operand
order upstream's docstring says its mixin order exists to avoid, and this repo's SQLite-only suite
could not catch the consequence. The `Count("concepts")` annotation stays in `get_queryset()`.

The `pk` tiebreaker is not decoration: an order without a total order lets a row appear on two pages
or on neither once pagination is in play. Page size is django-mvp's inherited default — do not
restate it.

Test, in `TestVocabularyListOrdering`: vocabularies whose names differ only in case sort as a reader
would expect and not as byte order would; two requests return the same sequence; two vocabularies
sharing a name still produce a deterministic order; and `django_assert_num_queries` shows the same
query count for a page of three vocabularies as for a page of thirty — which is SC-005 as a test
rather than a claim.

**Proves**: FR-004, SC-005, User Story 1 scenario 6.
**Verify**: `pytest tests/test_ui/test_views.py -k Ordering`.

**Depends on**: T007.

---

### T009 — An empty site says so, and nothing links anywhere

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list_item.html`,
`tests/test_ui/test_views.py`, `tests/test_ui/test_templates.py` (new)

Override `get_empty_state_heading()` and `get_empty_state_message()` to say the site holds no
vocabularies. Both strings are translatable, as is every string in the templates.

Test: a database with no vocabularies returns 200 and the empty wording. In `test_templates.py`,
read the row partial's source and assert it contains no `{% url %}` tag and no `local_url`
reference, and assert the rendered page contains no anchor whose href is a vocabulary's own
address — FR-013 stated two ways, because the template can regain a link without the view changing.
Also scan every shipped template for reader-visible text outside a translation tag.

**Proves**: FR-011, FR-013, SC-006, User Story 1 scenario 7.
**Verify**: `pytest tests/test_ui/test_views.py tests/test_ui/test_templates.py`.

**Depends on**: T008.

---

### T010 — The page is documented

**Files**: `README.md`, `CHANGELOG.md`

A section covering what the page is, installing the extra (`pip install
django-controlled-vocabularies[ui]`), the applications a project adds to `INSTALLED_APPS` — the ui
app and django-mvp's own stack, quoted from the test project's settings so the list is one that
demonstrably works — mounting the routes with `include`, and reversing the route by name. State
plainly that entries do not yet link to a vocabulary, and why. CHANGELOG entry under Unreleased.

**Proves**: Article VI. **Verify**: the README's own instructions followed against the test project
produce the page.

**Depends on**: T009.

---

## Phase 3 — US-2: Narrow the list to the one you are after (P2, #144)

**This phase starts only after US-1 has landed.** The two stories are not independent: they edit the
same view module, the same page template and the same test module, and T011 rewrites the actions
block T006 writes. Dispatch them in sequence, in one checkout — not into parallel worktrees.

### T011 — A search narrows the list by name and by description

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list.html`,
`tests/test_ui/test_views.py`

Set `search_fields = ["name", "description"]`; django-mvp's mixin reads `?q=`, strips it and applies
case-insensitive substring matching across those fields. Replace the page template's empty actions
block with a `GET` form of our own wrapping django-mvp's search action — the shipped search input
targets a form defined by the *filter* action, so rendering search alone yields a box that submits
nothing (research R4). Render the submit button in our own template as `{% trans "Search" %}` rather
than relying on django-mvp's, whose label is a hard-coded English literal the component exposes no
variable for. Leave a comment naming the upstream issue covering both.

Test, in `TestVocabularySearch`: a word from a name narrows to that vocabulary; a word appearing only
in a description does too; matching ignores case; a term containing `%`, `_` or a quote is looked for
literally and matches nothing rather than everything; a non-Latin term matches its vocabulary. Assert
the rendered page carries the search input and no sort or filter control, and that submitting the
form reaches the view with `?q=` set — the defect being worked around is silent otherwise.

**Proves**: FR-006, SC-006, User Story 2 scenarios 1 to 3 and 7.
**Verify**: `pytest tests/test_ui/test_views.py -k Search`.

**Depends on**: T009.

---

### T012 — A search survives being linked to, and being paged through

**Files**: `tests/test_ui/test_views.py`

No production change is expected: django-mvp builds pagination links with Django's `querystring`
tag, which keeps every parameter but the page. This task proves that rather than assuming it —
the reference package carries a strict xfail for the opposite behaviour on an older version.

Test: requesting the page with `?q=` returns the narrowed set, and requesting the same address again
returns the same set in the same order; with more vocabularies than fit a page, following the
rendered link to page two — read out of the markup, never constructed by hand — keeps the search
applied; and the second page's results are a continuation of the same narrowed set rather than of
the full one.

**Proves**: FR-007, FR-008, FR-010, User Story 2 scenarios 5 and 6.
**Verify**: `pytest tests/test_ui/test_views.py -k Search`.

**Depends on**: T011.

---

### T013 — A search matching nothing says so, in its own words

**Files**: `controlled_vocabularies/ui/views.py`,
`controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list.html`,
`tests/test_ui/test_views.py`

Branch both empty-state methods on whether a search term was given: with one, say nothing matched and
repeat the term; without one, keep T009's wording. A mistyped word is invisible once the search box
is the only record of it, and telling someone whose search missed that the site is empty is a false
statement the page has the information to avoid. The echoed term is escaped by the template layer.

**The way back to the full list is a link in the actions block T011 owns**, not markup inside the
message. django-mvp's empty-state component renders heading and message as autoescaped strings with
no slot and no block, so an anchor in the message would render as literal text — and the obvious
repair, `mark_safe` over a string that also carries the search term, would emit an attacker-supplied
term unescaped. Both methods return plain translatable text; neither uses `mark_safe` or
`format_html`. Do not override `{% block page.content %}`.

Test: a search matching nothing returns 200 with the no-match wording, the term echoed, and a link
to the unsearched page; an empty database with no search keeps T009's wording, and shows no such
link; the two messages are different strings; and a term containing markup is escaped in the
response — assert on the escaped form, since a message rendered through `mark_safe` would pass a
substring check for the raw term.

**Proves**: FR-009, FR-011, User Story 2 scenario 4.
**Verify**: `pytest tests/test_ui/test_views.py -k Search`.

**Depends on**: T012.

---

### T014 — Search is documented

**Files**: `README.md`, `CHANGELOG.md`

Extend the browsing section: what the search covers (names and descriptions, not concepts), that
it travels in the address so a narrowed list can be shared, and that there is no filtering. Say
that a second word **widens** rather than narrows — matching is OR across every word and both
fields — because the opposite is what a reader assumes. Say what it does not do — finding a concept
without knowing its vocabulary — so a reader is not left inferring it.

**Proves**: Article VI. **Verify**: the documented behaviour matches the tests.

**Depends on**: T013.

---

## Phase 4 — US-3: Run the page and look at it (P1, #146)

*Added 2026-08-20 by amendment, re-gated with the maintainer. Runs after US-2 has merged: both
touch the README, and the demo has to serve the finished page rather than half of it.*

### T015 — The demo project runs

**Files**: `manage.py` (new), `demo/__init__.py` (new), `demo/settings.py` (new),
`demo/urls.py` (new), `tests/test_demo/__init__.py` (new), `tests/test_demo/test_demo.py` (new),
`pyproject.toml`

The repository has no `manage.py` and no project of its own — the test suite has always been the
only thing that boots Django. Add both. `demo/settings.py` is the configuration the README already
documents, written out in full rather than imported from the tests: a reader comparing the two
should find them the same wiring, and a demo that imports test settings teaches nobody anything.
`DEBUG = True`, a local SQLite file, and a throwaway secret written in the file — with a `ruff`
per-file ignore for the hard-coded-secret rule, since the alternative is a demo that will not start
until someone exports an environment variable.

`demo/urls.py` mounts the browsing routes, the admin (so a vocabulary can be added by hand and seen
to appear), and a root route **named `home`** redirecting to the list. The name is not decoration:
django-mvp's footer menu reverses `home` on every page, so without it every render logs a reversal
failure and the demo's root address — the first thing anyone tries — is a 404.

Declare `tests/test_demo/` as a directory prefix under `[tool.forge.conformance] non-mirror-paths`:
its subject is a project, not a module.

Test, in `TestDemoProject`: the demo settings module boots in a subprocess and `manage.py check`
is clean under it; the list route reverses under the demo's own urlconf; the root address redirects
to it; `DEBUG` is on and the database is a local file, so nobody mistakes it for a deployment
template.

**Proves**: FR-014, FR-015, FR-018, User Story 3 scenarios 1 and 4.
**Verify**: `pytest tests/test_demo/ -q`, then by hand: `python manage.py migrate` and
`python manage.py runserver`.

**Depends on**: T014.

---

### T016 — Seeding is one command, and repeatable

**Files**: `demo/seed/*.ttl` (new), `demo/management/__init__.py` (new),
`demo/management/commands/__init__.py` (new), `demo/management/commands/seed_demo.py` (new),
`tests/test_demo/test_seed.py` (new)

Two small SKOS files written for this purpose and shipped under `demo/seed/` — **not** reused from
`tests/fixtures/`, which is test data whose shape changes when a test needs it to. One carries
static URIs from an external publisher, so it lands as an imported vocabulary; one carries none, so
it lands as authored here. Between them the demo shows both kinds of entry, which is the difference
the list is claiming to make visible.

`seed_demo` clears the vocabularies it manages and loads both files through the package's own
import path — the demo exercises the same code a real project would, never a fixture loaded behind
it. Destructive and idempotent by design, and it says so when it runs.

Test, in `TestSeedDemo`: after one run both vocabularies exist with their concepts; after a second
run the counts are identical; a vocabulary added by hand between runs is gone afterwards; one
vocabulary reads as imported and the other as authored here.

**Proves**: FR-016, User Story 3 scenarios 2 and 3.
**Verify**: `pytest tests/test_demo/test_seed.py -q`.

**Depends on**: T015.

---

### T017 — The walk runs unattended

**Files**: `demo/smoke.py` (new), `.github/workflows/demo.yml` (new), `tests/test_demo/test_smoke.py` (new)

A script that does what a person would: migrate a throwaway database, seed it, start the server,
request the list, and assert on what comes back — that both seeded vocabularies are named, that a
search narrows to one of them, and that the page carries the concept counts. It asserts on the
served response, never on the code that produced it, because the failure it exists to catch is the
one every unit test passes through: a template that renders in a test client and not in a browser.

`.github/workflows/demo.yml` runs it on pull requests and on pushes to the default branch, with no
paths filter on the pull-request trigger — a path-filtered required check never reports on an
out-of-scope pull request and blocks the merge, which the repository's other workflows already
explain. Read-only `contents` permission, no secrets: it installs from the public index and asserts
locally. Model it on `django-literature`'s `demo.yml`.

**The maintainer pushes this file.** The bot identity has no `workflows` permission, by design, so
this task's branch cannot be pushed by the usual route — flag it at the story report rather than
working around it.

Test, in `TestDemoSmoke`: the script's assertions are exercised against a served page in-process, so
a broken assertion fails here rather than only in CI.

**Proves**: FR-017, User Story 3 scenario 5.
**Verify**: `pytest tests/test_demo/test_smoke.py -q`, and `python -m demo.smoke` end to end.

**Depends on**: T016.

---

### T018 — The demo is documented

**Files**: `README.md`, `CHANGELOG.md`

A "Try it" section: the three commands in order, the address they lead to, what the seeded content
holds, that seeding is destructive and idempotent, and — plainly — that this is not a production
configuration. Keep it beside the browsing section it demonstrates, not in a separate part of the
file.

**Proves**: Article VI, FR-015, FR-018. **Verify**: follow the section from a clean checkout and get
the page.

**Depends on**: T017.

---

## Out of scope, deliberately

- Any link into a vocabulary — #141.
- Searching concepts across vocabularies — no roadmap item covers it; raised at the spec gate.
- Filtering by any axis, including tags, which do not exist.
- Anything about performance beyond a flat query count — R7.
