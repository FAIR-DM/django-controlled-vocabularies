# Decisions — 012 Concept selection inside the Django admin

Rationale too long to sit inside `spec.md`, plus every ambiguity resolved without asking the
maintainer. Each entry records what was unclear, what was chosen, and why the choice is defensible.
Decisions taken *with* the maintainer live in `spec.md` under `## Clarifications`.

## D1 — The related-object affordances are refused, not merely absent
**Ambiguous**: Django's admin wraps a foreign-key or many-to-many field in a wrapper that offers to
add, change, delete and view the related record. It renders those buttons only when the related
model is registered in the admin and the person holds the matching permission, so today the
question is invisible: this package registers nothing, and the buttons never appear. It would have
been possible to write the specification to describe today's behaviour and say nothing.

**Chosen**: the specification requires the affordances to be absent *whatever* is registered, and
tests must prove it with the concept model registered and a superuser signed in.

**Why defensible**: the curator interface (R5) is an Essential goal in the same milestone. When it
registers the concept model, every consuming project's data-entry page would grow a "create a
concept" button, with no code changed anywhere and nobody looking. A requirement that only holds
because a precondition happens to be false is not a requirement, and the failure would arrive
inside an unrelated feature. This is the FR-004 / User Story 2 pair.

**ADR:** docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md — the standing rule and its mechanism.

## D2 — The scope of "selection-only" covers all four affordances
**Ambiguous**: the maintainer's decision named creating a concept. The wrapper offers four things.

**Chosen**: none of the four render.

**Why defensible**: delete is strictly worse than add — removing a shared concept from the page of
a record that merely references it damages every other record using it, and the package's own
delete protection exists precisely because that must not be easy. Change has the same shape one
step down: editing a shared label from a data-entry form is authoring. View is the only benign one,
and it is refused for a different reason rather than a safety one: it opens the admin's own change
form for the concept, which is R5's to design and does not exist, and reading a concept's
definition is what the browsing interface in R6 is for. Shipping three of four and leaving one
pointing at a page that does not exist yet would be worse than a clean rule.

**ADR:** none — the scope of the rule graduated in docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md, recorded there rather than as a second ADR.

## D3 — An explicit `ModelAdmin` declaration wins silently
**Ambiguous**: a project naming the field in `autocomplete_fields` gets the admin's own autocomplete
instead of this package's control. That could be treated as a mistake worth reporting — the project
is passing up the feature — or as an instruction.

**Chosen**: an instruction. It wins, and nothing is reported.

**Why defensible**: Article II. A default that cannot be escaped is not a default, and a project
adopting the package should never have to audit its existing `ModelAdmin` classes first. The admin's
own autocomplete is a legitimate thing to want, and a warning that fired on a correct configuration
would be noise in `manage.py check` — the same channel the package uses for the three wiring
entries that genuinely are missing when it reports them. Diluting that channel costs more than the
warning could return.

**ADR:** docs/adr/0012-an-explicit-declaration-wins-and-nothing-is-reported.md

## D4 — Inline rows added in the browser are in scope
**Ambiguous**: the issue says "admin add and change pages". An inline row created by clicking "Add
another" is neither, strictly — it is a copy of a hidden template row, made in the browser after
the page was delivered.

**Chosen**: in scope, and called out as a requirement of its own (FR-003).

**Why defensible**: excluding it produces a feature that demonstrates correctly and fails in use.
The rows rendered with the page are the records that already exist; the row someone adds is the one
they are entering. A control that initialises only at page load leaves an inert box in exactly the
place the person is working, and this is the single most common way a search-as-you-type control
integrated into the admin goes wrong. Naming it in the specification makes it a tested behaviour
rather than a discovered defect.

**ADR:** none — a scope call for this feature's user stories; nothing downstream inherits it.

## D5 — The admin remains an optional dependency
**Ambiguous**: whether the package may now assume `django.contrib.admin` is installed.

**Chosen**: it may not. Nothing added by this feature may be imported at startup in a way that
requires the admin, no check may report on it in a project that does not have it, and the behaviour
must equally reach a project running its own `AdminSite`.

**Why defensible**: the consumption fields are for any Django project, and the admin is an optional
application in Django's own layering. A package that made it mandatory would break projects that
never asked for the feature, at startup rather than on a page. The custom-site half is the same
argument in the other direction: a feature wired only to `django.contrib.admin.site` would appear
to work in the test project and silently do nothing in a project that runs its own site, which is
common in exactly the research-infrastructure projects this package targets.

**ADR:** docs/adr/0013-the-django-admin-stays-an-optional-dependency.md

## D6 — Read-only presentation renders no control
**Ambiguous**: what a field in the admin's read-only list, or a page a person may view but not
change, should show.

**Chosen**: the concept's preferred label, no control.

**Why defensible**: it is what read-only means, and the alternative — a disabled control — invites
a person to type into something that cannot accept a change. The label is also the correct value to
show, because the field's readback is already part of the delivered contract.

**ADR:** none — a boundary of docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md, stated in that ADR's Decision.

## D7 — The changelist is excluded
**Ambiguous**: whether searching or filtering a consuming model's admin list page by concept
belongs here.

**Chosen**: no. The specification says so explicitly rather than leaving it unstated.

**Why defensible**: the issue names the add and change pages. A filter sidebar over a vocabulary of
tens of thousands of concepts is the same problem this feature exists to solve, one page along, and
it would need its own decisions about what a filter offers before anything is typed. Leaving it
unstated would have invited it into the implementation as an obvious extra.

**ADR:** none — a scope boundary of this feature; the changelist is a later question, not a standing constraint.

## D8 — No admin-specific endpoint, and no second copy of the search rules
**Ambiguous**: the admin could plausibly have justified its own search view, closer to the admin's
own autocomplete conventions.

**Chosen**: it reuses the delivered endpoint unchanged.

**Why defensible**: Article III. Every rule about what a typed string matches, what a result shows,
how results are bounded and where the restriction comes from was settled in #88 and is enforced in
one place. A second endpoint would be a second copy of the security-relevant rule that the
restriction is derived from the field declaration rather than taken from the request, which is the
rule Article V cares about most here. One endpoint, one place to get that right.

**ADR:** none — reuses the endpoint and the restriction-derivation rule already recorded in docs/adr/0010-a-restriction-is-derived-on-every-path-not-carried-on-one.md; this feature added no new stance.

## D9 — The form field declines the admin's wrapper, rather than a project applying a mixin
**Ambiguous**: FR-004 says a consuming model registered with a `ModelAdmin` that declares nothing
gets no related-object affordances. Django wraps every foreign key and many-to-many field in
`RelatedFieldWidgetWrapper` at `django/contrib/admin/options.py:193`, unconditionally, and offers no
hook to decline it. Three ways out were considered.

**Chosen**: the form field owns its `widget` attribute, so its setter unwraps a
`RelatedFieldWidgetWrapper` back to the widget inside it. Prototyped and measured before this plan
was written (`research.md` R2): both fields come back unwrapped through the admin, and a plain
`ModelForm` outside the admin is unchanged.

**Why defensible**: it satisfies the requirement with no project action, no patch to Django, and no
new public surface. The alternatives each fail something:

- *A `ModelAdmin` mixin the project applies.* Contradicts FR-001, and its failure mode is silence —
  a project that forgets it gets the affordances back with nothing to notice.
- *Replacing `ModelAdmin.formfield_for_dbfield` at app-ready.* A monkey patch on a core Django
  method, affecting every field on every model in the project, to change the behaviour of two. Fails
  Article II and Article III, and a library that does this is a poor citizen in someone else's
  project.

The cost is honest and recorded in `plan.md` Risks: the setter depends on Django assigning to that
attribute. The tests assert the absence of the four links in rendered output rather than the
mechanism, so a future Django that built the wrapper differently fails a test rather than drifting.

**ADR:** docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md — the mechanism half of that decision.

## D10 — The conditional admin import lives in `controlled_vocabularies/admin.py`
**Ambiguous**: FR-006 forbids importing `django.contrib.admin` at startup, but the setter in D9 has
to know what a `RelatedFieldWidgetWrapper` is.

**Chosen**: a module named `admin.py` holding one lookup function that resolves the class lazily and
returns `None` when the admin is not installed. It registers nothing.

**Why defensible**: it keeps an admin-only import out of `forms.py`, which otherwise has nothing to
do with the admin, and it gives `tests/test_admin.py` a source module to mirror under testing standard §4.

*Corrected at the design review (DR-005).* The original rationale claimed that Django's
`AdminConfig.ready()` autodiscovery is what makes the module conditional. It is not: `forms.py`
calls the lookup on every render, so any project rendering a concept field imports this module
whether or not the admin is installed. **FR-006 is satisfied by the function importing
`django.contrib.admin` only when it is among the installed applications**, and the test asserts
`django.contrib.admin` is absent from `sys.modules` rather than that this module is. The module is
still the right home; the reason was wrong.

**ADR:** none — module placement in service of 0011-a-concept-is-chosen-in-the-admin-never-created-there and docs/adr/0013-the-django-admin-stays-an-optional-dependency.md; the constraint lives in the ADR, not the file it happens to sit in.

## D11 — ~~The many-to-many field ignores the admin's appended help text~~ *(superseded by D15)*
**Ambiguous**: `formfield_for_manytomany` appends *Hold down "Control", or "Command" on a Mac, to
select more than one.* to the help text of any `SelectMultiple`. Measured on `Outcrop.minerals`
(`research.md` R3). The instruction is false under this control.

**Chosen**: the multi-value form field keeps the help text it was constructed with and ignores a
value that merely appends to it.

**Superseded by D15 at the design review, before anything was built.** The rule stated here cannot
deliver the behaviour, and the rule that could is worse than the problem. The text is kept as the
record of what was considered.

**Why it looked defensible**: it is the same shape as D9 — the admin mutates an attribute after
`formfield()` returns, and the field owns the attribute. Matching the appended sentence is not needed, and would
be fragile because the string is translated. Rejected: setting `allow_multiple_selected = False` on
the widget, which would suppress the message but also stop `Select.get_context` emitting the
`multiple` attribute, so a real multi-select would stop being one.

**ADR:** none — struck within the feature and never implemented; there is no decision left to abide by.

## D12 — The inline script's browser behaviour is a documented manual check, not a test
**Ambiguous**: US-3 requires a row added by "Add another" to carry a working control. That is
browser behaviour, and this package has no browser test harness.

**Chosen**: assert everything provable server-side — the asset ships, both widgets carry it in their
media, the empty-form row renders a select with a registered configuration, the event name and the
id substitution match what Django emits, and a parent POSTed with a new inline row saves its
concept. The click itself is a manual check, written down as one.

**Why defensible**: adding Playwright or Selenium to a Django library for one story is a
runtime-scale dependency against Article VII, and a browser suite is infrastructure that then has to
be maintained and run in CI for every future feature. Recording the gap is honest; claiming coverage
that does not exist is the failure this avoids. If a second browser-dependent story arrives, the
harness becomes justified and this decision is the evidence for it.

**Manual check (T010)**: in a project with the admin installed and a `ModelAdmin` carrying a
`ConceptField`- or `ConceptsField`-consuming inline (`TabularInline` or `StackedInline`), on the
parent's change page:

1. Click "Add another" below the inline. The new row must render as the search-as-you-type control
   — a text box you can type into and pick a result from — not a bare `<select>` listing every row
   in the vocabulary (the failure `research.md` R4 describes: the browser JS never initialises the
   clone).
2. Type into it and confirm results arrive from the autocomplete endpoint (network tab: a request to
   the field's own autocomplete URL, not a 404 or no request at all), restricted to the row's own
   declared vocabulary.
3. Pick a result, save the parent, and confirm the row persists holding it (the server-side half —
   T011 — proves the save always works; this step proves the browser-added row actually reaches the
   POST with the right value, not just that the control renders).
4. Repeat against an inline whose formset starts with **no saved rows** (`extra = 0`, no existing
   children) — the exact configuration `research.md` R4 measured the library's own fallback failing
   on. The first row added on the page must behave identically to step 1.
5. Confirm no error appears in the browser console on either add, and that adding a second row after
   the first works the same way (the template row `concept-inline.js` reads from is never consumed —
   it stays available for every subsequent "Add another" click).

A failure at step 1 or 4 with no console error most likely means `concept-inline.js` isn't loading —
check the rendered page's `<head>` for a `<script>` tag referencing it (declared on both widgets'
`Media`, T010) before assuming the listener itself is wrong.

**ADR:** none — a test-coverage boundary local to this feature, recorded in plan.md Risks.

## D13 — The test project gains the admin, and the no-admin case is proven out of process
**Ambiguous**: FR-001 through FR-008 need `django.contrib.admin` installed in the test project, and
FR-006 needs a project without it to be unaffected. One settings module cannot be both.

**Chosen**: `tests/settings.py` gains the admin and the five applications and middleware its own
system checks require. FR-006 is proven by `tests/settings_no_admin.py` exercised through
`django-admin check` in a subprocess.

**Why defensible**: `tests/test_checks.py` already runs `django-admin` in a subprocess for exactly
this shape of assertion, so the idiom is the repo's own rather than invented for this feature. The
alternative — running the whole suite twice under two settings modules — doubles CI time to prove
one negative.

**ADR:** none — test-harness structure serving docs/adr/0013-the-django-admin-stays-an-optional-dependency.md.

## D14 — FR-004 is scoped to the editable control, not to read-only presentation
**Raised by**: the design review, finding DR-001, verified against Django 5.2.16 before it was
acted on.

**The problem**: FR-004 as gated said no add, change, delete or view affordance "whether or not the
package's own models are registered in the admin and whatever permissions the person holds". A field
the admin renders read-only is excluded from the form, so no form field and no widget is built for
it and the D9 setter never runs. `AdminReadonlyField.contents()`
(`django/contrib/admin/helpers.py:294-298`) routes a read-only single-value relation through
`get_admin_url` (`helpers.py:251-264`), which reverses `admin:<app>_<model>_change` and returns a
link, falling back to plain text only while the model is unregistered. No package can decline that.
Left unnoticed, the requirement would have passed its tests today and started rendering a link the
moment R5 registers `Concept` — precisely the latent activation D1 exists to forbid.

**Chosen**: amend FR-004 to govern the control, and state in FR-008 that read-only presentation is
Django's own, including the link it renders once the model is registered. A read-only many-to-many
field is unaffected either way: `helpers.py:293` renders it as `", ".join(map(str, value.all()))`,
with no link.

**Why defensible**: "selection-only" was a decision about what a person entering a record can do to
the vocabulary from that page. A read-only field offers no selection at all, and following a link to
a concept's own admin page is not authoring one from a data-entry form — what happens on that page
is governed by the concept permissions the project grants. The alternative readings were both worse:
leaving FR-004 as written makes it a requirement no implementation can satisfy, and suppressing the
link would mean overriding admin internals for every consuming project to remove a read-only
hyperlink.

**Status**: this narrows a requirement the maintainer approved, so it is raised explicitly in the
plan notification rather than absorbed quietly, and it is called out again at the merge gate.

**ADR:** none — a boundary of docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md, stated in that ADR's Decision.

## D15 — The admin's false multi-select instruction is left alone
**Raised by**: the design review, finding DR-002.

**The problem**: `formfield_for_manytomany` appends *Hold down "Control", or "Command" on a Mac, to
select more than one.* to a many-to-many field's help text. It is false under this control. D11
planned to suppress it. Two things are wrong with that. No FR or SC asks for it — FR-010's
enumerated guarantees are the vocabulary constraint, the delete protection, the required rule and
the readback, none of which is help text. And the rule cannot work: `options.py:337-341` *replaces*
rather than appends when the field has no help text of its own, so ignoring appends leaves the
sentence in place; the rule that would catch both — freezing `help_text` after construction — also
silently ignores the ordinary `self.fields[…].help_text = …` a consuming project writes in its own
`ModelForm.__init__`.

**Chosen**: drop the production change and the task. The sentence stays, as Django's behaviour
rather than this package's.

**Why defensible**: it is a cosmetic defect with no requirement behind it, and every mechanism for
removing it costs a real guarantee or does not work. Dropping it also removes the only reason two
stories had to edit `forms.py`, which is why the design review's own asymmetric bar treats
work-removing findings as cheap. Carried to the retro as a candidate follow-up issue, where it can
be judged on its own rather than smuggled into a feature about affordances.

**ADR:** none — a dropped task carried as a retro follow-up, not a standing rule.

## D16 — Stories are dispatched sequentially onto the feature branch
**Raised by**: the design review, finding DR-003.

**The problem**: the task list had six stories and four shared files. `tests/test_admin.py` is
touched by every story, `controlled_vocabularies/forms.py` by two, `tests/test_forms.py` by two, and
`tests/testapp/admin.py` by three. The dependency section recorded one of those collisions and then
declared the rest independent.

**Chosen**: the stories run sequentially onto the feature branch, not in parallel worktrees, and the
full collision list is written into `tasks.md` so the ordering is a stated constraint rather than an
accident.

**Why defensible**: parallel fan-out is a phase-2 capability and this feature does not need it. Four
worktrees each creating their own version of a test module that does not exist at the base is a
four-way conflict at convergence, which costs more than the wall-clock it would have saved.

**ADR:** none — a run-process choice; nothing in the codebase inherits it.

## D17 — One pre-existing test modified: the middleware check no longer empties `MIDDLEWARE`
**Article I requires this to be recorded before the change stands.**

`tests/test_checks.py::TestTheMiddlewareCheckReachesManageCheck::test_the_missing_middleware_is_reported_by_manage_check`
ran `call_command("check")` under `override_settings(MIDDLEWARE=[])`. Once T001 installed
`django.contrib.admin`, an empty middleware list trips the admin's own `admin.E4xx` checks and the
command raises before the assertion is reached.

**Changed to** dropping only `django_tomselect.middleware.TomSelectMiddleware` from the configured
list, leaving the rest in place.

**Why this is not weakening the test**: its stated subject is that `controlled_vocabularies.W004`
is registered and reaches `manage.py check`. Removing exactly the middleware the check is about
proves that more precisely than emptying the list did — the old form could have passed for reasons
other than the one it names. Nothing about the assertion changed, and the test fails if the check is
unregistered or stops firing.

**Not changed**: the sibling tests that call `check_tomselect_middleware_installed()` directly under
`MIDDLEWARE=[]`. They never reach the admin's checks, so they still exercise the empty case.

**ADR:** none — narrowing one test fixture, local to this feature.

## D18 — T001 was implemented by the orchestrator rather than dispatched
Foundational, not a story: settings entries, a URL mount and three bare `ModelAdmin` registrations,
with no design content and nothing for an Implementer to decide. The pipeline allows direct
implementation for work of this shape provided the reason is recorded, and this is the record. Every
story from US-1 onward is dispatched.

**ADR:** none — a run-process choice; nothing in the codebase inherits it.

## D19 — T004's refusal tests assert on the errored field, not on message text
**Decision**: `tests/test_admin.py::TestAdminSubmissionSavesAndFieldRulesStillBite`'s two
foreign-vocabulary tests assert `'id="id_rock_type_error"' in content` / `'id="id_minerals_error"'
in content`, not any particular error string.

**Why**: a first draft asserted `"is not a valid concept" in content` — the wording of
`ConceptField.validate()`'s model-level custom message (`fields.py:215`). Run against the real
admin POST, it failed: the actual rendered text is Django's own generic `ModelChoiceField` message,
"Select a valid choice. That choice is not one of the available choices." The refusal happens at
the form field's own level first — the widget's `get_queryset()` is already narrowed to the
declared vocabulary (the same mechanism `tests/test_forms.py::TestConceptFieldSubmissionSurvives`
proves is what lets a *legitimate* concept survive), so `ModelChoiceField.clean()` rejects the
foreign pk before `Model.full_clean()` and the field's own custom message are ever reached. This
matches the existing suite's own restraint: `test_forms.py`'s equivalent tests assert
`"mineral" in form.errors`, never the message text, for the same reason.

**Revisit if**: a future story moves the restriction from the widget's queryset to model-level
validation only (so the custom message becomes reachable from a form submission) — then these
tests' assertions should tighten to match, per `craft-tdd`'s "assert outcomes" rule.

**ADR:** none — a test-authoring detail sealed inside two test functions.

## D20 — `# type: ignore[misc]` on both field classes, not a restructure
**Decision**: `ConceptChoiceField` and `ConceptsChoiceField` each carry `# type: ignore[misc]`
on their class line, immediately after adding `_DeclinesAdminRelatedWrapper` as their first
base (T006).

**Why**: mypy validates the full inherited MRO whenever a class lists more than one explicit
base, and doing so here surfaces a pre-existing conflict between `django_tomselect`'s own
`BaseTomSelectModelMixin` and Django's `ModelChoiceField` over `queryset`/`to_field_name` — a
third-party inconsistency with nothing to do with this mixin, invisible before this task only
because both field classes previously listed a single base (`TomSelectModelChoiceField`), which
never triggers the check. Confirmed by reverting the mixin and re-running mypy: the errors
disappear with it, on the unmodified base branch.

**Revisit if**: `django_tomselect` fixes the underlying conflict upstream, or mypy's own
handling of transitively-inherited base conflicts changes — either would make the ignore
comments stale, and `mypy --warn-unused-ignores` would then flag them.

**ADR:** none — a local annotation working around a third-party type conflict.

## D21 — US-3's inline registrations and factory live outside `tasks.md`'s file list (T008)
**Decision**: `Locality` (the parent model, with its own `ConceptField`) and the `locality`
foreign key on `Specimen` are declared in `tests/testapp/models.py` as `tasks.md` T008 names, but
the `TabularInline`/`StackedInline` registrations are on dedicated sites in `tests/test_admin.py`,
not in `tests/testapp/admin.py`. `LocalityFactory` was added to `tests/factories.py`, a file
`tasks.md` T008 and the task brief's `test_project_ownership` note both omit.

**Why**: `tests/testapp/admin.py`'s own module docstring states the project's convention — bare
registrations only; anything that declares something (an inline is a declaration) belongs on its
own site in `tests/test_admin.py`, the pattern every prior story (`concept_registered_admin_site`,
`bare_admin_site`) already follows. The task brief's own context named this explicitly and asked
for the departure to be recorded here. `LocalityFactory` follows `craft-tdd`'s one-factory-per-model
structure rule (constitution Article X) — every other model `tests/testapp/models.py` carries has
one in `tests/factories.py`, and `Locality` is exercised by `pytest.mark.django_db` tests that need
a saved instance the same way.

Also decided here: `Locality` carries its own `ConceptField` (`primary_mineral`, vocabulary
`"mineral"`, distinct from `Specimen.rock_type`'s `"rock-type"`) — not required by T008's acceptance
text alone, but by `spec.md` US-3 scenario 4 ("an inline row whose field declares a different
vocabulary **from the parent form's field**"), which presupposes the parent form has a field of its
own to contrast against. Without it, T009's second test would have nothing to prove.

**Revisit if**: a future story needs `Locality` registered on the default site for some other
reason — at that point a bare registration belongs in `tests/testapp/admin.py` alongside
`Specimen`/`Outcrop`/`RockSample`, unrelated to this decision.

**ADR:** none — test-file placement, local to this feature.

## D22 — US-4's registrations also live outside `tasks.md`'s file list (T012, T013)
**Decision**: `tasks.md` names `tests/testapp/admin.py` as a file T012 and T013 touch. Neither
task does: every registration each declares — `autocomplete_fields`, `raw_id_fields`, a
form-declared widget, `readonly_fields` — is exactly the kind of declaration
`tests/testapp/admin.py`'s own module docstring reserves for a dedicated site in
`tests/test_admin.py`. All eight new `ModelAdmin`/`ModelForm` classes and the four fixtures both
tasks add (`autocomplete_site`, `raw_id_site`, `declared_widget_site`, `readonly_concept_site`)
live there instead, alongside the equivalent US-1/US-2/US-3 sites already following the same
convention.

**Why**: this is the same departure D21 recorded for T008 — the task brief's own
`test_project_ownership` context named it explicitly for this story too and asked for it to be
recorded here rather than reasoned through silently. `tests/testapp/admin.py` stays exactly what
its docstring says it is: three bare registrations proving the default needs nothing declared.

**Revisit if**: a future story needs one of these declarations available to tests outside
`tests/test_admin.py` — at that point it moves to `tests/testapp/admin.py`, unrelated to this
decision.

**ADR:** none — test-file placement, local to this feature.

## D24 — T017's README assertion lives in `tests/test_standards.py`, not `tests/test_admin.py`
**Decision**: `tasks.md` names `README.md`, `CONTEXT.md` and `CHANGELOG.md` as T017's files. This
story adds one more: a `TestReadmeDocumentsTheAdminSection` class in `tests/test_standards.py`,
checking the shipped README states the four things spec.md's US-6 scenario 1 names.

**Why**: `tests/test_standards.py` already carries `TestReadmeDocumentsTheConceptSearchControlsWiring`
(#88's T011) — the identical technique, for the sibling documentation-only story one feature back:
read the shipped README rather than trust a docs-writing pass to have said everything the
acceptance scenario names. Putting the new class beside it keeps every README-content assertion in
one place and follows the established convention exactly rather than inventing a second one in
`test_admin.py`, which has no other README-reading test.

**Revisit if**: a future feature's documentation assertions grow numerous enough that
`tests/test_standards.py` stops being one module's worth of "does the package meet its written
standards" — at that point a dedicated `tests/test_docs.py` is the fix, unrelated to this decision.

**ADR:** none — test-file placement, local to this feature.

## D25 — T018's translation-status guard extends the existing sweep; the JS file gets no sweep at all
**Decision**: `tasks.md` names `tests/test_admin.py` (plus source "as needed") for T018's
translation-status half. This story instead adds `admin_module` (`controlled_vocabularies.admin`)
to `tests/test_standards.py`'s `_FIELDS_CHECKS_MODULES` list, so
`TestFieldsChecksI18nSweep::test_module_carries_no_bare_user_visible_literal` now runs against it
alongside `fields.py`, `checks.py`, `forms.py` and `views.py`. No new visitor, no new test class,
and no change to `controlled_vocabularies/admin.py` itself. `concept-inline.js` — the third file
this feature added — gets no automated sweep of any kind, Python or otherwise.

**Why**: enumeration first. `git diff main..HEAD -- controlled_vocabularies/` is the whole surface
this feature added: `admin.py`, `forms.py`, and `concept-inline.js`. `forms.py`'s addition
(`_DeclinesAdminRelatedWrapper`) is already covered — it's one of the four modules
`_FIELDS_CHECKS_MODULES` already swept before this story. `admin.py` was the one gap: a module this
feature added that no sweep reached. `_FieldsChecksI18nVisitor` already recognises the sinks a
module like this could carry (`ValidationError`, `ImproperlyConfigured`, `checks.Warning`/`Error`,
`help_text=`/`verbose_name=`), so extending the parametrize list is the whole fix — duplicating a
second visitor in `test_admin.py` would check the same thing twice by two different mechanisms for
no gain, and this file is already the established home for exactly this question (D24 makes the
identical case for the README assertion). Proved as a real gate before trusting it: with a bare
`error_messages = {"invalid": "boom"}` temporarily spliced into `admin.py` (never committed — `git
diff --stat controlled_vocabularies/` shows nothing after reverting),
`test_module_carries_no_bare_user_visible_literal[controlled_vocabularies.admin]` failed, reporting
`['boom']`; reverted, and the whole `TestFieldsChecksI18nSweep` class passed again, five modules.

`concept-inline.js` carries no equivalent sweep because Article XII's own text (`memory/
constitution.md`) scopes the internationalization requirement to Python (models, forms, views,
admin, validators) and templates (`{% trans %}`/`{% blocktranslate %}`); it says nothing about
JavaScript, and no other feature in this repository's history has swept a JS file either. Read in
full and enumerated by hand: every string literal in it is `'use strict'`, the `-__prefix__-` regex
substitution, the `select[data-tomselect]` CSS selector, or the `formset:added` DOM event name — no
`textContent`/`innerHTML` assignment, no `alert`, nothing a person reads. FR-011 is therefore
satisfied by this file having nothing to wrap, stated here as the enumeration rather than asserted
by a mechanism built to check for something that isn't there.

**Revisit if**: a future feature ships a JavaScript file that does put text in front of a person —
at that point it needs its own translation mechanism and its own test, not a retrofit of the Python
AST sweep this decision extends.

**ADR:** none — test-harness placement; the translatability rule itself is constitution Article XII, not a decision of this feature.

## D23 — T014's `_run_django_admin` gains a `settings` parameter, and one file joins its list
**Decision**: `tests/test_checks.py:_run_django_admin()` gains a `settings: str = "tests.settings"`
keyword parameter, threaded into `DJANGO_SETTINGS_MODULE`. Every pre-existing call site is
unaffected — the default reproduces exactly what the hardcoded value did. `tasks.md` T014 named this
change explicitly and asked for it to be recorded here (constitution Article I); the task brief's
own `the_subprocess_helper` note repeats the same instruction.

A second file joins T014's list beyond the two `tasks.md` names (`tests/settings_no_admin.py`,
`tests/test_checks.py`): `tests/urls_no_admin.py`. `tests/settings.py`'s `ROOT_URLCONF` points at
`tests.urls`, which mounts `admin.site.urls` unconditionally — reusing it for the no-admin settings
module resolves that path lazily but still walks it while building `URLResolver.app_dict`, which
constructs `AdminSite`'s default site and imports `django.contrib.admin` regardless of which route is
being reversed. That would fail the FR-006 proof for a reason having nothing to do with the feature.
`tests/urls_no_admin.py` mounts only `controlled_vocabularies.urls` — what a project without the
admin actually has mounted — and `tests/settings_no_admin.py`'s `ROOT_URLCONF` names it instead.

**Why defensible**: both changes are the minimum needed to make the acceptance-named files work at
all; neither widens what T014 proves. The `settings` parameter is additive and backward-compatible
(a `str` default, not a behavior change for any existing caller). The extra urlconf module is a test
fixture, not production code, and follows the same convention `tests/urls.py`'s own docstring already
states — the admin mounted only where a project would actually mount it.

**Revisit if**: a later story needs the no-admin urlconf to carry more than the one route — at that
point `tests/urls_no_admin.py` grows with it, unrelated to this decision.

**ADR:** none — a test-helper signature, backward-compatible and local.

## D26 — the CHANGELOG's override sentence excludes `readonly_fields` from the no-affordance claim
**Decision**: T017's CHANGELOG entry originally read "`autocomplete_fields`, `raw_id_fields`, a
form's own declared widget, and `readonly_fields` still work as they would for any other related
field, each keeping the same no-affordance and validation guarantees." Corrected at the humanizer
pass to attribute those guarantees to the first three only.

**Why**: the sentence contradicted FR-008 and the README's own read-only paragraph. Django renders
a read-only single-value relation as a link to that record's admin change page
(`django/contrib/admin/helpers.py`, `AdminReadonlyField`), which this package neither adds nor
suppresses — so a read-only concept field does carry a view affordance of a kind. A read-only field
is also excluded from the form entirely, so it is not validated at all and "the same validation
guarantees" is wrong for it too. The README already stated both facts correctly; only the CHANGELOG
generalised past them.

**Revisit if**: R5 registers `Concept` behind a curator-only permission and the read-only link
becomes reachable in a way that warrants documenting on its own.

**ADR:** none — a documentation correction restoring what docs/adr/0011-a-concept-is-chosen-in-the-admin-never-created-there.md and docs/adr/0012-an-explicit-declaration-wins-and-nothing-is-reported.md already state.

## D27 — an added inline row discards the control markup its clone brought with it
**Raised by**: the code review, finding ADMIN-002 — `concept-inline.js` shipped with no executed
verification of any kind, and D12's manual check had never been run. Running it found this.

**The problem**: the empty-form template row is initialised on page load like every other row, so
its rendered `.ts-wrapper` — the visible search control — is part of what Django's `inlines.js`
clones, and Django then rewrites `__prefix__` to the new row number inside it. The added row
therefore arrives already carrying an inert copy of the control, complete with duplicate element
ids, before this script initialises the real one. Measured against Django 5.2.16 and
django_tomselect 2026.6.2: two `.ts-wrapper` elements in the new row's cell, both visible, both
holding an input with `id="id_specimens-1-rock_type-ts-control"`. `initialize`'s own destroy step
does not reach the copy, because there is no TomSelect instance behind it — it is markup only.

**Chosen**: before initialising, remove every `.ts-wrapper` that is a sibling of the select and is
not the wrapper of a live instance, then initialise as before.

**Why defensible**: the clone is markup with no owner, and the row is new, so nothing can be
depending on it. Guarding on the live instance's own wrapper keeps the function correct if
django_tomselect's `MutationObserver` fallback reaches the row first — that wrapper is left alone
and `initialize` destroys it through the library's own path.

**Not tested**: the fault and the fix are both invisible to a server-side test — the double control
exists only in the cloned DOM. D12's boundary is unchanged, and this is the second thing that
boundary has cost. Recorded in the retro as evidence toward a browser harness.

**ADR:** none — an implementation detail of FR-003, inside a decision (D12) that already stands.

## D24 — Underscore-prefixed class names dropped, on the maintainer's instruction

**Raised by**: Sam, at the merge gate, reviewing PR #131: "the use of underscores to denote
'private' classes ... is ugly and unpythonic. Please rename these without the underscore."

**Changed**: every underscore-prefixed *class* in the files this pull request touches.

| Was | Now |
|---|---|
| `_ConceptWidgetValidationMixin` | `ConceptWidgetValidationMixin` |
| `_ConceptWidgetReferenceMixin` | `ConceptWidgetReferenceMixin` |
| `_ConceptWidgetRouteMixin` | `ConceptWidgetRouteMixin` |
| `_ConceptWidgetDisplayMixin` | `ConceptWidgetDisplayMixin` |
| `_DeclinesAdminRelatedWrapper` | `DeclinesAdminRelatedWrapperMixin` |
| the twelve test-only helper classes in `tests/test_admin.py` and `tests/test_checks.py` | the same names without the underscore |

The new mixin also gained the `Mixin` suffix its four siblings in the same module already carry —
consistency inside the file, not an extra change of direction.

**Scope**: classes only, and only in files this pull request already touches. Module-level *functions*
keep their underscore (`_config`, `_echoed_uri`, `_prepare_static_uri` and the rest), which is
ordinary Python and was not what the instruction was about. Underscore-prefixed classes elsewhere in
the package — `_DryRun`, `_Fetched`, `_FatalIdentity`, `_DoNothingContentHandler`,
`_ConceptReferenceResolverMixin`, and the two AST visitors in `tests/test_standards.py` — are
untouched here, because renaming them would pull four modules this feature never opened into its
diff. Worth doing as its own small change.

**Consequence worth naming**: the four widget mixins were module-private and are now part of
`controlled_vocabularies.forms`'s public surface. That is consistent with Article XIV, which treats a
class as the extension point a consumer subclasses, and the package is at `0.0.x` before its first
publish, so no compatibility window is owed.

**Verified**: `forge verify` green — conformance, lint, typecheck, 1353 tests, build.
