# Tasks: Concept selection inside the Django admin

**Feature**: `012-concept-selection-in-the-admin` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Every task is test-first per Article I: the test is written and seen to fail before the production
change that makes it pass. Test scope per task is one class or one file; the full suite runs once per
story, at the story's report.

`[P]` marks tasks that could run in parallel with their siblings. Phase 1 is sequential and blocks
everything.

## Phase 1 — Foundational

### T001 — The test project has an admin

**Files**: `tests/settings.py`, `tests/testapp/admin.py` (new), `tests/urls.py`

No admin test can fail-then-pass until the admin exists in the test project. `tests/settings.py`
currently installs only `contenttypes`, `auth`, `django_tomselect`, `controlled_vocabularies` and
`tests.testapp`, with a single middleware entry — so `django.contrib.admin`,
`django.contrib.sessions`, `django.contrib.messages` and `django.contrib.staticfiles` are all new,
as are `SessionMiddleware`, `AuthenticationMiddleware` and `MessageMiddleware`. Add those, plus a
`TEMPLATES` entry with the request, auth and messages context processors, and `STATIC_URL`. Mount the default admin site in
`tests/urls.py`. Create `tests/testapp/admin.py` registering `Specimen`, `Outcrop` and `RockSample`
with bare `ModelAdmin` classes — nothing declared about any field.

**Proves**: nothing on its own. **Verify**: `manage.py check` clean, and the full existing suite
green with five more applications installed. A red suite here means the wider surface broke
something, and that is this task's finding, not the next story's.

**Depends on**: nothing.

---

## Phase 2 — US-1: The admin page gets the same control, declaring nothing (P1, #125)

### T002 — The control renders on the add and change pages

**Files**: `tests/test_admin.py` (new)

Sign in a staff superuser, request the add page and the change page of a saved record for a model
declaring `ConceptField`, and assert the concept control is what rendered: the select carries the
`data-tomselect` marker, the page carries the widget's configuration script, and the field's
autocomplete reference (`field=testapp.specimen.rock_type`) is present. Repeat for `ConceptsField`.
Assert the change page shows the concept the record already holds under its preferred label.

**Covers**: FR-001, FR-002, SC-001, US-1 scenarios 1–3 and 6 — the bare `ModelAdmin` with only the three existing wiring entries is what demonstrates FR-002 and scenario 6.

### T003 — An admin page does not carry the vocabulary

**Files**: `tests/test_admin.py`

Render the add page against a vocabulary of five concepts and one of two thousand, and assert the
rendered length is identical. Mirror the shape `tests/test_forms.py::TestConceptFieldRenderingIsBoundedByVocabularySize`
already uses so the two read the same.

**Covers**: FR-009, SC-006, US-1 scenario 4.

### T004 — A page submitted from the admin saves, and the field's rules still bite

**Files**: `tests/test_admin.py`

POST the admin add form with an eligible concept and assert the record saves holding it. POST one
from another vocabulary and assert the form is invalid with the field's own message. Assert deleting
a referenced concept is still refused. Both fields.

**Covers**: FR-010, US-1 scenario 5.

---

## Phase 3 — US-2: Concepts are chosen here, never created (P1, #126)

### T005 — The four related-object affordances are absent

**Files**: `tests/test_admin.py`

Register `Concept` in a dedicated test admin site alongside the consuming models — this is the only
configuration in which the affordances appear at all, measured in `research.md` R1 — and sign in a
superuser holding every permission. Assert the rendered field carries no add, change, delete or view
related link: no `related-widget-wrapper-link`, no `add-related`, `change-related`,
`delete-related` or `view-related` anchor, for both fields. Note that
`RelatedFieldWidgetWrapper.__init__` mutates the wrapped widget's own `attrs` dict before the
setter unwraps it, so the rendered select still carries `data-context="available-source"`. That is
harmless and is not an affordance — assert on the links, not on the absence of that attribute. Assert the same with `Concept` not
registered. Assert the control itself still renders and still carries its autocomplete reference.

**Covers**: FR-004, US-2 scenarios 1–5, SC-002. **This test must fail before T006.**

### T006 — The form field declines the admin's wrapper

**Files**: `controlled_vocabularies/admin.py` (new), `controlled_vocabularies/forms.py`

`controlled_vocabularies/admin.py`: one function returning `RelatedFieldWidgetWrapper`, or `None`
when `django.contrib.admin` is not among the installed applications. It registers nothing and
imports the admin only inside that function.

`forms.py`: a small mixin applied to `ConceptChoiceField` and `ConceptsChoiceField` making `widget` a
property whose setter unwraps a `RelatedFieldWidgetWrapper` to the widget it holds and stores
everything else unchanged. Two mechanics to get right, both raised by the design review: the mixin
must come **before** the django-tomselect field class in the bases, or the inherited class-level
`widget` attribute shadows the property; and the getter must tolerate being read before anything has
been stored, because `django/forms/fields.py:146` evaluates `widget = widget or self.widget` during
`Field.__init__`. Per Article XIV the behaviour is one named mixin shared by both classes,
not duplicated logic; per Article III it stays a mixin on the existing classes and nothing is
exported for a project to use.

**Covers**: FR-004. **Verify**: T005 green, and `tests/test_forms.py` still green — the non-admin
path must be untouched.

### T007 — The declining behaviour is asserted at form-field level too

**Files**: `tests/test_forms.py`

The page-level assertions in T005 prove the outcome; this proves the seam. Assign a
`RelatedFieldWidgetWrapper` to a constructed form field's `widget` and assert the field holds the
inner widget with its `model_field` binding intact. Assign an ordinary widget and assert it is held
as given. Both form field classes.

**Covers**: FR-004, FR-005.

---

## Phase 4 — US-3: Inline rows, including the ones added on the page (P2, #127)

### T008 — A parent model with inlines

**Files**: `tests/testapp/models.py`, `tests/testapp/admin.py`, `tests/testapp/migrations/0004_*.py`

One parent model whose children are an existing consuming model, registered once as a
`TabularInline` and once as a `StackedInline` on separate admin sites, one with `extra = 1` and one
with `extra = 0` — the second is the configuration the library fails on (`research.md` R4). Every new
model field carries `help_text`, `verbose_name` and `gettext_lazy` per the org standard.

**Covers**: infrastructure for T009–T011.

### T009 — Saved inline rows carry the control

**Files**: `tests/test_admin.py`

Request the parent's change page with two saved children and assert each row's field rendered as the
control, showing its own concept. Assert a row whose field declares a different vocabulary carries
its own autocomplete reference and not the parent's.

**Covers**: FR-003, US-3 scenarios 1 and 4.

### T010 — The empty-form row is initialisable, and the script ships

**Files**: `controlled_vocabularies/static/controlled_vocabularies/js/concept-inline.js` (new),
`controlled_vocabularies/forms.py`, `tests/test_admin.py`, `tests/test_forms.py`

The script listens for `formset:added`, and for each `select[data-tomselect]` in the added row
recovers the configuration registered against the template row by substituting `__prefix__` for the
row index in the element id, then calls `window.djangoTomSelect.initialize`. It does nothing when
the event never fires, and it does not replace or patch the library's own paths.

Add it to both widgets' `Media`.

Assert server-side: the asset is in both widgets' media; the rendered empty-form row carries a
select with `data-tomselect` and a registered configuration whose id contains `__prefix__`; the id
substitution the script performs matches the identifier Django's `inlines.js` produces for a new
row. Write the manual check into `decisions.md` D12's entry rather than claiming the click is
covered.

**Covers**: FR-003, US-3 scenarios 2 and 5.

### T011 — A parent saved with a new inline row keeps its concept

**Files**: `tests/test_admin.py`

POST the parent's change form with an extra formset row carrying a concept, and assert the child is
created holding it. This is the server half of the "Add another" journey and it does not depend on
the browser.

**Covers**: FR-003, US-3 scenario 3, SC-003.

---

## Phase 5 — US-4: A project's own choice wins (P2, #128)

### T012 — [P] Three explicit declarations each render what they asked for

**Files**: `tests/testapp/admin.py`, `tests/test_admin.py`

Register the same consuming model on three separate admin sites: one naming the field in
`autocomplete_fields`, one in `raw_id_fields`, one whose form declares its own widget. Assert each
renders what it declared and not the concept control, that a valid concept still saves through each,
that an ineligible one is still refused, and that `manage.py check` reports nothing.

With `Concept` registered on the site under test, also assert the `autocomplete_fields` and
declared-widget registrations carry no add, change, delete or view related link. Both are wrapped by
Django like any other field, so FR-004 applies to them too — only `raw_id_fields` skips the wrap,
and it renders no control this feature owns.

**Covers**: FR-005, US-4 scenarios 1–5, SC-004.

### T013 — [P] Read-only presentation renders no control

**Files**: `tests/testapp/admin.py`, `tests/test_admin.py`

A `ModelAdmin` listing the field in `readonly_fields`, and a staff user holding view permission but
not change permission. Assert both render the concept's preferred label and no control.

Register `Concept` on the admin site under test, as T005 does, and pin what Django then renders:
a single-value read-only relation carries a link to the concept's own admin change page, and a
read-only many-to-many renders plain text. This is FR-008 and `decisions.md` D14, not a violation of
FR-004 — the test exists so that the boundary is asserted rather than assumed, and so a future
change to it is visible.

**Covers**: FR-008, US-4 scenarios 6 and 7.

---

## Phase 6 — US-5: The admin stays optional (P2, #129)

### T014 — [P] A project without the admin is unaffected

**Files**: `tests/settings_no_admin.py` (new), `tests/test_checks.py`

A settings module with no `django.contrib.admin`, exercised through `django-admin check` in a
subprocess. Assert the check output is clean and carries none of this package's warnings beyond what
it reports today.

Assert **`"django.contrib.admin" not in sys.modules`** after rendering a form over a consuming model
under that configuration. That is what FR-006 requires. Asserting that
`controlled_vocabularies.admin` is unimported would prove nothing: `forms.py` calls its lookup on
every render, so it is imported either way (`decisions.md` D10). Also assert the module registers
nothing when the admin *is* installed.

`_run_django_admin()` in `tests/test_checks.py:34-42` hardcodes `DJANGO_SETTINGS_MODULE`, so it
gains a settings parameter defaulting to today's value. That is a modification to a pre-existing
test helper: record it as a one-line `decisions.md` entry when the task runs, per Article I.

**Covers**: FR-006, US-5 scenarios 1 and 2, SC-005.

### T015 — [P] A custom admin site gets the same behaviour

**Files**: `tests/test_admin.py`

Register a consuming model on a custom `AdminSite` and assert the control renders, works, and
carries no related-object affordance. Assert a model registered on both the default site and a
custom one gets it on both.

**Covers**: FR-007, US-5 scenarios 3 and 4.

### T016 — ~~The false multi-select instruction is not appended~~ *(dropped at the design review)*

Dropped before implementation, per `decisions.md` D15. The admin appends *Hold down "Control"…* to a
many-to-many field's help text, and it is false under this control — but no requirement asks for it
to be removed, and neither mechanism for removing it works without cost. Left as Django's behaviour
and carried to the retro as a candidate follow-up issue.

---

## Phase 7 — US-6: Documented, translatable, and tested where it belongs (P3, #130)

### T017 — README, CONTEXT.md and CHANGELOG

**Files**: `README.md`, `CONTEXT.md`, `CHANGELOG.md`

The README gains an admin section: registering a consuming model is all it takes, the wiring is the
same three entries the forms feature already asks for, concepts are chosen on these pages and never
created, and how a project overrides the default with `autocomplete_fields`, `raw_id_fields`, its own
widget or `readonly_fields`. `CONTEXT.md`'s concept search control entry gains the admin. The
CHANGELOG records the addition. All three are public markdown and get the humanizer pass at S7.

**Covers**: FR-012, US-6 scenarios 1, 4 and 5.

### T018 — Strings and test structure

**Files**: `tests/test_admin.py`, source as needed

Assert every user-visible string this feature added is wrapped for translation with named
placeholders, and that the new test modules mirror the source tree and reuse the shared consuming
models and factories rather than defining new ones.

**Covers**: FR-011, US-6 scenarios 2 and 3.

---

## Dependency order

```
T001
 └── US-1 (T002 → T003 → T004)
      └── US-2 (T005 → T006 → T007)
           └── US-3 (T008 → T009 → T010 → T011)
                └── US-4 (T012, T013)
                     └── US-5 (T014, T015)
                          └── US-6 (T017, T018)
```

**The stories are dispatched sequentially onto the feature branch, not into parallel worktrees**
(`decisions.md` D16). They share four files, and only one of those collisions was recorded before
the design review:

| File | Touched by |
|---|---|
| `tests/test_admin.py` | every story — T002–T005, T009–T011, T012–T013, T015, T018 |
| `controlled_vocabularies/forms.py` | T006 (US-2), T010 (US-3) |
| `tests/test_forms.py` | T007 (US-2), T010 (US-3) |
| `tests/testapp/admin.py` | T001 (foundational), T008 (US-3), T012 and T013 (US-4) |

The `[P]` marks inside US-4 and US-5 mean the tasks within that story are order-independent, not
that the stories fan out.

## Verification per story

`kit/forge verify` at each story's report, plus `kit/forge tamper-check` against the story's base.
The full suite runs once per story, not once per task.

FR-013 (no undeclared runtime dependency, dependency checks green) is discharged by the `deptry` step
inside `kit/forge verify` rather than by a task of its own — this feature adds no dependency, so the
requirement is a standing check rather than work.
