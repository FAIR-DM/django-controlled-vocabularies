# Implementation Plan: Find a vocabulary

**Branch**: `013-find-a-vocabulary` | **Date**: 2026-08-19 | **Spec**: [`spec.md`](spec.md)

**Input**: Feature specification from `specs/013-find-a-vocabulary/spec.md`

## Summary

One page lists every vocabulary the site holds, searchable by name and description. The page is the
package's first human-facing HTML surface, so the plan is mostly about *where it lives*: a new inner
app, `controlled_vocabularies/ui/`, whose dependency on django-mvp is a packaging extra rather than a
runtime dependency, so a project consuming vocabularies without ever rendering them is unaffected.
django-mvp's `MVPListView` supplies search, pagination, the page shell and the empty state; this
feature supplies one view, one row partial, one page template, one route, and the tests and
documentation for them.

## Technical Context

**Language/Version**: Python 3.11 floor for the package; the ui extra requires 3.12 (django-mvp's
own floor), expressed as a dependency marker. CI runs 3.12 and 3.13.

**Primary Dependencies**: django-mvp `>=0.19,<1.0`, optional, in a new `ui` extra. No other new
dependency. Nothing is added to the hard dependency set.

**Storage**: none. Reads `ConceptScheme` and counts `Concept`; no model changes, no migration.

**Testing**: pytest + pytest-django, `tests/test_ui/` mirroring the new source modules, plus a
core-only settings module and a subprocess boot test proving the core still runs without the extra.

**Target Platform**: any Django project mounting the package's ui routes; also the package's own
test project.

**Project Type**: installable Django package (single project, library layout).

**Performance Goals**: query count per page independent of the number of vocabularies shown
(SC-005). Scale beyond tens of vocabularies is R7 and explicitly out of scope.

**Constraints**: no JavaScript requirement — the page works without it. No access rule of the
package's own. No link to a vocabulary's own page until #141 serves one.

**Scale/Scope**: three user stories, one new app, one view, two templates, one route, one extra,
and a demonstration project. The stories run **in sequence, not in parallel** — US-2 extends the
same view class and rewrites the same template block US-1 writes, and US-3 serves the finished page
and shares the README with both, so parallel worktrees would collide at convergence.

**Amendment, 2026-08-20 (re-gated):** US-3 adds a runnable demonstration project — `manage.py`, a
`demo/` project configured exactly as the README documents, a `seed_demo` command loading two
purpose-written SKOS files through the package's own importer, and an unattended check that serves
the page and reads it back. It exists because the first two stories are unverifiable by looking:
tests assert markup, and only a running page answers the question the feature was built to answer.
The demonstration is development surface, not published surface — it ships in the repository and not
in the wheel, so it adds no dependency a consumer carries.

## Constitution Check

| Article | Bearing on this feature | Verdict |
|---|---|---|
| I Test-First | Every task lands its test before its code; view behaviour is asserted through the real client. | Follows |
| II Simplicity | django-mvp supplies search, pagination, the shell and the empty-state hooks. The only thing built here that is not a template or a view attribute is the system check in R2 — justified below. | Follows, one entry in Complexity Tracking |
| III Anti-Abstraction | No base view class, no mixin, no registry. One concrete view. The "is it imported" test stays in the template rather than becoming a model property, because one caller is not a second use. | Follows |
| IV Integration-First | Acceptance runs through `client.get(reverse(...))` against rendered HTML, which is how a person touches this. | Follows |
| V Security & data-safety | Everything rendered goes through the template layer. The search term is a queryset `icontains` argument, never interpolated — the ORM parameterises it, which is also what makes `%` and `_` ordinary characters. The term is echoed back to the reader through the template's escaping. No auth, no uploads, no outbound fetch. | Follows |
| VI Documentation | README gains a section on the browsing page, how to install the extra and how to mount the routes; CHANGELOG gains the entry. No built docs site exists in this repo. Ships in this PR. | Follows |
| VII Dependency discipline | One new dependency, optional, declared alongside the code that imports it, with a `deptry` module-name map so the check passes. | Follows |
| VIII Dual compatibility contract | No URI is composed, published or changed. The data contract is untouched. | N/A |
| IX URI identity & data safety | Read-only feature; no writes, no migration. | N/A |
| X Stack & architecture norms | Django 5.2/6.0, Poetry, ruff. Models stay the source of truth; the page reads them. | Follows |
| XI RDF fidelity | Untouched. | N/A |
| XII Internationalization | Every string the page shows is `{% trans %}` in templates and `gettext_lazy` in Python, including both empty-state messages. SC-006 is a test. | Follows |
| XIII Data-model conventions | No field added, so no indexing decision. Ordering is `Lower("name")` on an unindexed column, which is correct at this scale and is R7's to revisit. | Follows |
| XIV Test structure | `tests/test_ui/` mirrors `controlled_vocabularies/ui/`, one class per subject, factories reused from `tests/factories.py`. Template and packaging tests have no source module to mirror; T001 declares those four files under `[tool.forge.conformance] non-mirror-paths`. | Follows |
| XV Cohesion | One view class holds the list behaviour; no free functions. | Follows |

## Project Structure

### Documentation (this feature)

```
specs/013-find-a-vocabulary/
├── spec.md
├── decisions.md
├── research.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```
controlled_vocabularies/
├── ui/                                  # new — the only place django-mvp is imported
│   ├── __init__.py                      # docstring only, no re-exports
│   ├── apps.py                          # ConceptVocabulariesUIConfig, label distinct from name
│   ├── checks.py                        # friendly failure when the extra is not installed
│   ├── urls.py                          # app_name, one route, nothing auto-mounted
│   ├── views.py                         # VocabularyListView
│   └── templates/controlled_vocabularies/ui/
│       ├── conceptscheme_list.html      # extends django-mvp's list_view.html
│       └── conceptscheme_list_item.html # the row
└── (everything else untouched)

tests/
├── settings.py                          # gains the ui stack
├── settings_core.py                     # new — core only, no django-mvp
├── urls.py                              # gains the ui routes under a prefix
├── urls_core.py                         # new — empty
└── test_ui/
    ├── __init__.py
    ├── test_apps.py
    ├── test_architecture.py             # core imports none of the ui stack (AST)
    ├── test_boot.py                     # core boots in a fresh subprocess
    ├── test_checks.py
    ├── test_packaging.py                # the extra is declared, and only there
    ├── test_templates.py
    ├── test_urls.py
    └── test_views.py
```

**Structure Decision**: inner app, not a second distribution. The alternative — a separate
`django-controlled-vocabularies-ui` package — costs a second release cadence and a version matrix
for a page. The extra gives the same isolation with one release. The isolation is not a convention
here but a tested property: three guard tests prove the core neither imports nor requires the UI
stack.

## Key design decisions

1. **`VocabularyListView(MVPListView)`** over `ConceptScheme`, with `search_fields = ["name",
   "description"]`, `ordering = [Lower("name"), "pk"]` as a class attribute, `get_queryset()`
   returning `.annotate(concept_count=Count("concepts"))`, and `list_item_template` naming the row
   partial. Page size is django-mvp's inherited default and is not restated. The ordering is a class
   attribute rather than an `.order_by()` call in `get_queryset()` because Django applies
   `self.ordering` innermost, before both django-mvp mixins — calling `.order_by()` in our own
   `get_queryset()` would apply it *after* the search mixin's `.distinct()`, which is the operand
   order upstream's own docstring says its mixin order exists to avoid.
   The two empty states are `get_empty_state_heading()` / `get_empty_state_message()` branching on
   `?q=`. Both return plain translatable text — never `mark_safe`, never `format_html`. They cannot
   carry a link: django-mvp's empty-state component renders both strings autoescaped with no slot,
   so markup in them would show as literal text, and marking them safe would emit the search term
   unescaped.
2. **The page template owns the actions block.** django-mvp renders search, sort, filter and create
   by default; this page wants search alone, and django-mvp's search input targets a form its filter
   action defines (research R4). The template overrides the block with a `GET` form of our own
   wrapping django-mvp's search action, our own `{% trans %}`d submit button (django-mvp's ships a
   hard-coded English label its component does not expose), and — when a search term is set — the
   link back to the unsearched list that FR-009 requires. Everything else is inherited;
   `{% block page.content %}` is not overridden.
3. **The row is a Cotton card partial** — name, description, concept count, and origin. Imported
   vocabularies show the publisher's identifier as text, never as a link. No element links to the
   vocabulary itself (FR-013).
4. **`app_name = "controlled_vocabularies_ui"`**, distinct from the core's
   `controlled_vocabularies` namespace, so both can be mounted in one project without either
   shadowing the other's reverses. Route name `vocabulary-list` at the empty path.
5. **A system check, not an import guard.** `ui/apps.py` `ready()` registers a check that reports
   an error naming the extra when `mvp` is not importable, so a misconfigured project learns at
   `manage.py check` rather than on its first request.

## Complexity Tracking

| Addition | Why it is not YAGNI |
|---|---|
| `ui/checks.py` — one function, one check | The failure it replaces is a raw `ModuleNotFoundError: mvp` raised from URL loading, which names neither the extra nor the app that needs it. The reference implementation lacks this and its own review flagged the gap. It is a function and a registration, not a layer. |
| Second settings module + subprocess boot test | The claim "the core does not require django-mvp" is otherwise untestable in a process that has already imported it. This is the same mechanism the repo already uses to prove the admin is optional. |
| A `demo/` project written out in full rather than importing the test settings | The demo's job is to be read as well as run: a reader comparing it against the README's instructions should find the same wiring twice, and a settings module that imports the tests' teaches nothing and drags test-only choices — an in-memory database, a fixed URI base — into the thing meant to look like a real project. |

## Risks

- **django-mvp's INSTALLED_APPS surface is wide** — cotton, icons, menus, crispy and its own app.
  A consuming project must install all of them, and the README has to say so exactly. Mitigation:
  the test project's settings are the working example, and the README quotes them.
- **Two upstream defects are worked around in our page template** — the search input targets a form
  only the filter action defines (research R4), and the search component's submit button carries a
  hard-coded English label it does not expose as a variable. Both workarounds will look redundant
  once django-mvp fixes them. Mitigation: one issue filed upstream covering both, and a comment in
  the template pointing at it.
- **Coverage floors** (project 90%, patch 85%) with a new app that is mostly templates. Mitigation:
  the view and check carry real tests; template behaviour is asserted through rendered HTML.
- **The demo's workflow file cannot be pushed by the bot** — the App holds no `workflows`
  permission, deliberately, so that an agent cannot rewrite the checks that gate its own work.
  Mitigation: the maintainer pushes that file himself; the story reports the constraint rather than
  routing around it. Every other file on the branch pushes normally.
- **A demo rots quietly.** Its whole value is being runnable, and nothing about a stale one looks
  wrong in a diff. Mitigation: the unattended walk (T017) is the demo's own test, and it asserts on
  a served response rather than on the code behind it.
