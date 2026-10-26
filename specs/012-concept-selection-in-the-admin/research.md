# Research — 012 Concept selection inside the Django admin

Phase 0. Everything here was read from the installed source or measured by running it, not recalled.
Versions in the project environment: Django 5.2.16, django-tomselect 2026.6.2, Python 3.14.

## R1 — How the admin builds a form field, and where it takes the widget away

`ModelAdmin.formfield_for_dbfield` (`django/contrib/admin/options.py:162`) is the whole story for a
foreign key or many-to-many field:

1. `db_field.choices` truthy → `formfield_for_choice_field`, which never reaches the rest. Not our
   case; neither consumption field sets `choices`.
2. `formfield_overrides` for the field's exact class is merged into `kwargs` (`options.py:180`).
3. `formfield_for_foreignkey` / `formfield_for_manytomany` calls `db_field.formfield(**kwargs)`.
4. **`options.py:215` then replaces the widget unconditionally**, for every field not listed in
   `raw_id_fields`:
   `formfield.widget = RelatedFieldWidgetWrapper(formfield.widget, db_field.remote_field, self.admin_site, **wrapper_kwargs)`

Two consequences settle the design.

**Our `formfield()` survives, and so does `model_field`.** `ConceptFieldMixin.formfield()`
(`controlled_vocabularies/fields.py:118-143`) sets `model_field` unconditionally and `form_class`
by `setdefault`, and the admin reaches it through `db_field.formfield(**kwargs)` like any other
caller. Measured: with `Concept` registered in a probe admin site, the wrapper's inner widget is
`ConceptWidget`/`MultiConceptWidget` with `model_field` correctly bound. So nothing has to be done to
make the control *reachable* in the admin — that part is already true.

**There is no hook to decline the wrapper.** The wrap at `options.py:215` is not conditional on the
widget, the field class, or `formfield_overrides`. `raw_id_fields` is the only escape, and it is a
project-side declaration that replaces the control entirely. Everything else is wrapped, including
`autocomplete_fields` and a form-declared widget. The wrapper's own constructor
(`django/contrib/admin/widgets.py`) computes what it offers from arguments the `ModelAdmin` passes:

- `can_add_related` defaults to `admin_site.is_registered(rel.model)` when the model admin does not
  supply it, otherwise `related_modeladmin.has_add_permission(request)`;
- `can_change_related`, `can_delete_related`, `can_view_related` come from the matching permission
  methods, and are additionally forced off for a multi-value widget
  (`multiple = getattr(widget, "allow_multiple_selected", False)`);
- `can_delete_related` is also forced off when the relation cascades. Ours is `PROTECT`, so it is
  not forced off.

**Measured, with `Concept` registered and a superuser** (probe against `tests.testapp`):

| Field | Wrapped | add | change | delete | view |
|---|---|---|---|---|---|
| `Specimen.rock_type` (`ConceptField`) | yes | True | True | True | True |
| `Outcrop.minerals` (`MultiConceptField`) | yes | True | False | False | False |

This is the FR-004 problem in one table, and it confirms the specification's premise: nothing
renders today only because the package registers nothing in the admin. The moment R5 registers
`Concept`, a superuser sees all four on a consuming model's page.

## R2 — The mechanism: the form field declines the wrapper

`options.py:215` is an ordinary attribute assignment onto our own form field. A `widget` property
whose setter unwraps a `RelatedFieldWidgetWrapper` back to the widget it wraps is enough, and it is
local to this package: no Django code is patched, no project declares anything, and every other
assignment path is untouched.

Prototyped and measured on the same probe:

| Field | Widget after `formfield_for_dbfield` | Wrapped |
|---|---|---|
| `Specimen.rock_type` | `ConceptWidget` | no |
| `Outcrop.minerals` | `MultiConceptWidget` | no |

and a plain `ModelForm` outside the admin still gets `ConceptWidget` with `model_field` bound, so
nothing outside the admin changes.

Two constraints on how it is written:

- **It must not import `django.contrib.admin` at import time** (FR-006). The setter resolves
  `RelatedFieldWidgetWrapper` lazily, and only when `django.contrib.admin` is among the installed
  applications. A project without the admin never loads it and never pays for it.
- **It must not fight an explicit project declaration** (FR-005). It does not. `raw_id_fields` skips
  the wrap in Django itself. `autocomplete_fields` and a declared widget arrive as a `widget=`
  **constructor kwarg** rather than an attribute assignment, so the project's widget is what renders
  — and they are then wrapped like anything else, so the setter unwraps them too. That is FR-004
  applying to whatever control renders, not an exception to FR-005: the project gets the widget it
  asked for, without the related-object affordances.

## R3 — The other thing the admin adds to a many-to-many field

`formfield_for_manytomany` appends *Hold down "Control", or "Command" on a Mac, to select more than
one.* to `help_text` for any `SelectMultiple` that is not a `CheckboxSelectMultiple` or an
`AutocompleteSelectMultiple`. `TomSelectModelMultipleWidget` subclasses `forms.SelectMultiple`, so
it fires. Measured on `Outcrop.minerals`: the help text came back as
`"The minerals observed at this outcrop, if any. Hold down “Control”, or “Command” on a Mac, to
select more than one."`

The instruction is false under this control — there is nothing to hold Control on. **Nothing is
done about it in this feature** (`decisions.md` D15). It has no requirement behind it, and the design
review found that the obvious remedy does not even work: `options.py:337-341` reads
`form_field.help_text = format_lazy("{} {}", help_text, msg) if help_text else msg`, so with an
empty help text the admin's sentence *replaces* rather than appends, and a rule that ignores appends
cannot suppress it. The rule that would — freezing `help_text` after construction — silently
no-ops the ordinary `self.fields["minerals"].help_text = …` a consuming project writes in its own
`ModelForm.__init__`, which is a published-package regression bought for a requirement nobody made.

Also rejected: setting `allow_multiple_selected = False` on the widget. It would suppress the help
text, but `Select.get_context` uses the same flag to emit the `multiple` attribute on the rendered
element, so a real multi-select would stop being one.

Recorded and carried to the retro as a candidate follow-up issue.

## R4 — Inline rows, and why the library does not cover them

django-tomselect ships **no admin integration at all**: no `ModelAdmin` mixin, no admin widget, no
admin documentation, and its own example project registers models with a plain `ModelAdmin` that
does not use its widgets. Confirmed by grep over the installed distribution (zero hits for `admin`,
`RelatedFieldWidgetWrapper`, `formfield_for_dbfield`, `jQuery`) and against the upstream repository
(OmenApps/django-tomselect; the package moved from jacklinke).

Initialisation has two layers:

- each widget renders an inline `<script>` that calls `window.djangoTomSelect.initialize(element,
  config)` on `DOMContentLoaded` (`templates/django_tomselect/tomselect.html:683-688`);
- the first widget in a request also renders `tomselect_setup.html`, which defines
  `window.djangoTomSelect` and installs a `MutationObserver` on `document.body`
  (`tomselect_setup.html:496-521`).

Django's admin adds an inline row by cloning the empty-form template row in JavaScript
(`django/contrib/admin/static/admin/js/inlines.js:67`) and firing a bubbling `formset:added` event
(`inlines.js:91`). Two facts decide the work:

1. **The cloned row's inline script does not run.** jQuery marks scripts in a clone of an in-page
   element as already evaluated, and `domManip` skips them. So the per-widget initialiser never
   fires for a new row.
2. **The library does not listen for `formset:added`** — zero occurrences in the distribution. Its
   only path is the MutationObserver, which does see the new row, but then looks the configuration
   up by element id through `findSimilarConfig` (`tomselect_setup.html:265-291`). That function
   normalises `-<digits>-` to `-X-`. Django's template row carries `__prefix__`, not digits
   (`admin/edit_inline/stacked.html:19`), so the registered key normalises to itself and the new
   row's key never matches it. With `extra = 0` and no existing children, **no numbered row was
   ever rendered, so nothing matches and the new row silently gets a bare select.**

So this package supplies the missing piece: a small script that listens for `formset:added`, finds
`select[data-tomselect]` in the added row, recovers the configuration registered against the
template row by substituting `__prefix__` back into the id, and initialises. It is additive — it
does not replace or patch the library's own paths, and it does nothing on a page with no formsets.

Upstream is aware of the general problem: issue #13 ("Add support for formsets", closed) names
copying `formset.empty_form` and initialising the widgets in it, and #31 covers dependent fields in
formsets. Neither produced admin coverage.

## R5 — The related-object popup is broken under this control, independently of policy

Worth recording because it removes a counter-argument rather than supporting one. If the add
affordance did render, `dismissAddRelatedObjectPopup`
(`django/contrib/admin/static/admin/js/admin/RelatedObjectLookups.js:126-142`) appends an `<option>`
to the native `<select>` and fires a jQuery `change`. Tom Select hides that select and drives its
own DOM, and the plugin that would resynchronise it (`change_listener`) is not enabled — the
library's default plugin list is empty and the widget template never requests it. The concept would
save, and the visible control would never show it. So the affordances FR-004 removes are ones that
do not currently work anyway.

## R6 — Test environment

`tests/settings.py` today has no `django.contrib.admin`, no `sessions`, no `messages`, no
`staticfiles`, and a single middleware entry. The admin's own system checks (`admin.E4xx`) require
several of those, so admin tests need them present.

The two requirements pull in opposite directions: FR-001/003/004/005/007/008 need the admin
installed, FR-006 needs a project without it to be unaffected. Resolved by keeping one settings
module for the suite and proving the negative out of process:

- `tests/settings.py` **gains** the admin and its prerequisites, so the admin tests are ordinary
  tests;
- FR-006 is proven by a settings module with no admin, exercised through `django-admin check` in a
  subprocess. `tests/test_checks.py:34-42` already has `_run_django_admin()` for exactly this shape,
  so the idiom exists and is reused rather than invented.

Eleven consuming models already exist in `tests/testapp/models.py`, covering single-value,
multi-value, several vocabularies, and no vocabulary. No new consuming model is needed except a
parent for the inline stories.

**Known limit, recorded rather than solved:** the `formset:added` behaviour is browser behaviour,
and this package has no browser test harness. Adding one for one story is a large dependency
against Article VII. What is provable server-side — the script ships, it is in the widget's media,
the template row renders a registered configuration, the event name and id substitution are what
Django emits — is asserted; the end-to-end click is a documented manual check. Recorded in
`decisions.md` D12 so it is a known gap rather than an implied guarantee.

## R7 — Environment note, outside this feature

The project has 58 Poetry virtualenvs under `~/.cache/pypoetry/virtualenvs/`, one per worktree ever
created, and the currently activated one was missing `django-tomselect` until it was reinstalled.
Not this feature's work; worth cleaning up separately.
