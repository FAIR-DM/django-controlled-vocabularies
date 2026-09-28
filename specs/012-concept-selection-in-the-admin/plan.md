# Implementation Plan: Concept selection inside the Django admin

**Branch**: `012-concept-selection-in-the-admin` | **Date**: 2026-08-13 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `specs/012-concept-selection-in-the-admin/spec.md`, research from [`research.md`](./research.md)

## Summary

The concept search control already reaches the Django admin unchanged: `ModelAdmin` builds a
consuming field through `db_field.formfield()`, which is our own override, so the widget and its
`model_field` binding arrive intact. Measured, not assumed (research R1).

What the admin then adds is the work. It replaces the widget with
`RelatedFieldWidgetWrapper` — the add, change, delete and view affordances FR-004 refuses. That is an
attribute assignment onto our form field after `formfield()` has returned, at
`django/contrib/admin/options.py:215`, so it is declined by the form field owning the attribute. No
Django code is patched and no project declares anything.

The second piece is inline rows. django-tomselect ships no admin integration and does not listen for
Django's `formset:added` event. Its MutationObserver fallback recovers a configuration by
normalising the row index in the element id, which cannot match the `__prefix__` of Django's
template row, so with `extra = 0` and no existing children a row added by "Add another" gets a bare
select. This package ships a small script that closes that gap.

Everything about searching, matching, display, paging and eligibility stays in the delivered
endpoint. No admin-specific view exists, and none is added.

## Technical Context

**Language/Version**: Python 3.14, Django 5.2.16

**Primary Dependencies**: `django-tomselect` 2026.6.2 (already a runtime dependency; no new one).
`django.contrib.admin` is a *conditional* dependency — never imported at module scope.

**Storage**: the package ships no model change, no field and no migration. The test application gains one parent model for the inline stories, with its own migration (task T008).

**Testing**: pytest + pytest-django, settings module `tests.settings`, consuming models in
`tests/testapp/models.py`.

**Target Platform**: any Django project consuming the package, with or without the admin installed.

**Project Type**: single installable Django application.

**Performance Goals**: an admin page must not grow with vocabulary size (FR-009, SC-006) — inherited
from the delivered control rather than newly built.

**Constraints**: no import of `django.contrib.admin` at startup (FR-006); no fourth wiring entry
(FR-002); an explicit `ModelAdmin` declaration always wins (FR-005).

**Scale/Scope**: five small source changes plus tests; no public Python API is added beyond the
behaviour of the two existing fields.

## Constitution Check

*Checked before Phase 0 and re-checked after this plan was written.*

| Article | Verdict |
|---|---|
| I — Test-First | Every task below is written test-first; the admin tests need new settings entries, which is task T001 so the failing tests can exist. |
| II — Simplicity | No new dependency, no new endpoint, no new model. The mechanism is one property setter and one script. The rejected alternatives (a `ModelAdmin` mixin the project must remember, patching `ModelAdmin.formfield_for_dbfield`) are each larger and each fail a requirement. The design review removed a second production change that had no requirement behind it (`decisions.md` D15). |
| III — Anti-Abstraction | No base class, no registry, no mixin exported for projects. The declining behaviour lives on the two existing form field classes. |
| IV — Integration-First | The acceptance path is a rendered admin page requested through the test client, not a unit call into `formfield_for_dbfield`. |
| V — Security & data-safety | Nothing new is interpolated into output; the shipped script is a static asset, not a template that renders model data. Eligibility still comes from the field declaration inside the delivered endpoint, untouched. The admin's own permissions are not weakened: declining the wrapper removes affordances, never grants one. |
| VI — Documentation | README section, `CONTEXT.md` update, CHANGELOG entry — story US-6, tasks T012–T014. |
| VII — Dependency discipline | No new runtime dependency. `django.contrib.admin` is added to the *test* settings only, and is resolved lazily at runtime. `deptry` must stay green. |
| XIV — Test structure | New modules mirror source: `tests/test_forms.py` (extended) for the form fields, `tests/test_admin.py` for the admin integration module, `tests/test_checks.py` (extended) for the no-admin proof. Existing consuming models and factories are reused. |
| XV — Cohesion | The declining behaviour is expressed as one mixin shared by the two form field classes, which is the framework's own grouping (a form field class), not an invented layer. |
| VIII — Dual compatibility contract | The Python API is unchanged. What changes is what a field renders as inside the admin, at `0.0.x` before first publish, so no deprecation window is owed. |
| XII — Internationalization | The one new user-visible string (the check message) is wrapped with named placeholders. |
| XIII — Data-model conventions | No change to the package's own models. The test application gains one model and one migration (T008); S5 consolidates only if a second appears. |

**No violations. Complexity Tracking is empty.**

## Project Structure

### Documentation (this feature)

```text
specs/012-concept-selection-in-the-admin/
├── spec.md
├── decisions.md
├── research.md          # Phase 0
├── plan.md              # this file
├── progress.md
├── feature-state.json
└── tasks.md             # Phase 2
```

### Source code

```text
controlled_vocabularies/
├── forms.py             # the two form field classes gain the declining behaviour
├── admin.py             # NEW — the lazy RelatedFieldWidgetWrapper lookup, nothing registered
└── static/
    └── controlled_vocabularies/
        └── js/
            └── concept-inline.js   # NEW — formset:added initialisation

tests/
├── settings.py          # gains django.contrib.admin and its prerequisites
├── settings_no_admin.py # NEW — the FR-006 proof, run out of process
├── testapp/
│   ├── models.py        # gains one parent model for the inline stories
│   ├── admin.py         # NEW — test-only ModelAdmin registrations
│   └── migrations/      # one migration for the new parent model
├── test_admin.py        # NEW — US-1..US-5 against rendered admin pages
├── test_forms.py        # extended — the declining behaviour at form-field level
└── test_checks.py       # extended — the no-admin subprocess proof
```

**Structure Decision.** `controlled_vocabularies/admin.py` holds the one function that resolves
`RelatedFieldWidgetWrapper`, and registers nothing. Two reasons, and the design review corrected
which one is load-bearing (`decisions.md` D10):

- It keeps an admin-only import out of `forms.py`, which otherwise has nothing to do with the admin,
  and gives `tests/test_admin.py` a source module to mirror per testing standard §4.
- Django's `AdminConfig.ready()` autodiscovers `admin` modules only when the admin is installed —
  but that is not what satisfies FR-006, because `forms.py` calls the lookup on every render and so
  imports the module regardless. **FR-006 is satisfied by the function importing
  `django.contrib.admin` only when it is among the installed applications**, and the test asserts
  `django.contrib.admin` is absent from `sys.modules`, not that this module is.

## Approach, story by story

### Foundational (before any story)

Admin tests cannot fail-then-pass until the admin exists in the test project. `django.contrib.admin`
needs `auth`, `contenttypes`, `sessions`, `messages` and `staticfiles`, the matching middleware, and
a `TEMPLATES` entry with the request, auth and messages context processors — its own system checks
(`admin.E4xx`) enforce this. One task, done first, with the smoke test proving `manage.py check`
stays clean.

### US-1 — the control renders on admin pages (P1)

Nothing to build. The work is the assertions: request the add page and the change page through the
test client as a staff user, confirm the rendered field is the concept control, that the page
carries no concept options, and that a POST saves. This story exists to pin behaviour that is
currently true by accident, so that the next two stories cannot quietly break it.

### US-2 — no add, change, delete or view affordance (P1)

`_DeclinesAdminRelatedWrapper`, a small mixin on `ConceptChoiceField` and `ConceptsChoiceField`:

- `widget` becomes a property. Its setter unwraps a `RelatedFieldWidgetWrapper` to the widget it
  wraps and stores that; every other value is stored as given.
- The wrapper class is resolved through `controlled_vocabularies.admin`, which returns `None` when
  `django.contrib.admin` is not installed, so the setter is a plain passthrough there.

Tests register `Concept` in a test admin site and sign in a superuser — the only configuration under
which the affordances would otherwise appear (measured in research R1) — and assert the rendered
page carries none of the four related-object links, for both fields, and that the control still
works.

### US-3 — inline rows (P2)

A parent model with an inline of a consuming model, registered both tabular and stacked, plus
`concept-inline.js` added to both widgets' media. The script listens for `formset:added`, and for
each `select[data-tomselect]` in the added row recovers the configuration registered against the
template row by substituting `__prefix__` for the row index in the element id, then calls
`window.djangoTomSelect.initialize`. It is a no-op on a page with no formsets and does not touch the
library's own initialisation paths.

Server-side tests assert the asset ships, that it is in the media of both widgets, that the
empty-form row renders a select carrying a registered configuration, and that a parent POSTed with a
new inline row saves the concept chosen in it. The browser click itself is a documented manual check
(`decisions.md` D12).

### US-4 — an explicit declaration wins (P2)

No production code. `raw_id_fields` skips the wrap in Django itself; `autocomplete_fields` and a
form-declared widget arrive as a `widget=` constructor argument, so the project's widget is what
renders — **and they are wrapped like any other field, so the declining setter does see them and
unwraps them.** That is FR-004 applying to whatever control renders, not an exception to FR-005:
the project gets the widget it asked for, without the related-object affordances. Read-only
presentation is Django's own and is outside FR-004 (`decisions.md` D14).

The story is four registrations against separate admin sites and the assertions that each renders
what it asked for, that the autocomplete registration also carries no related-object link, that a
valid concept still saves, that an ineligible one is still refused, and that `manage.py check`
reports nothing.

### US-5 — the admin stays optional (P2)

`tests/settings_no_admin.py` plus a subprocess `django-admin check`, reusing the
`_run_django_admin()` helper already in `tests/test_checks.py`. Plus a custom `AdminSite` registration
proving the behaviour is not bound to the default site, and an assertion that
`controlled_vocabularies.admin` registers nothing.

The false *Hold down "Control"* help text the admin appends to a many-to-many field is **not**
addressed here. It has no requirement behind it, and every mechanism for suppressing it costs more
than it returns (`decisions.md` D15). It is left as Django's own behaviour and carried to the retro
as a candidate follow-up.

### US-6 — documentation and strings (P3)

README section, `CONTEXT.md` entry, CHANGELOG. The README states the three unchanged wiring entries,
that registering a consuming model is all the admin needs, that concepts are chosen and not created
there, and how a project overrides the default.

## Risks

- **The declining setter is a seam onto Django's internals.** It depends on `options.py:193` being
  an attribute assignment. If a future Django built the wrapper inside `formfield_for_foreignkey`
  instead, the setter would stop firing and the affordances would come back silently. Mitigated by a
  test that asserts the *absence* of the four links from rendered output rather than the mechanism,
  so the failure surfaces as a red test on a Django upgrade rather than as behaviour drift.
- **The inline script's end-to-end behaviour is not machine-verified** (research R6). Recorded as a
  known gap, not implied coverage.
- **Adding the admin to the test settings widens the suite's surface.** Every existing test now runs
  with five more applications installed. The smoke test and full suite green at T001 is the check.
