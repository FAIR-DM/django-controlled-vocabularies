# Implementation Plan: Create and edit a vocabulary

**Feature**: `017-create-edit-vocabulary` · **Spec**: [`spec.md`](./spec.md) · **Research**:
[`research.md`](./research.md) · **Sketch**: [`sketch.md`](./sketch.md)

## Summary

Three pages in the opt-in browsing front end (`controlled_vocabularies.ui`): create, edit and delete a
vocabulary, built on django-mvp's model form views and guarded by Django's model permissions. The
maintainer approved the sketched pages, so their templates, markup and copy are kept. The views and
the form behind them are rebuilt test-first. Every test is seen to fail before the code that makes
it pass, which for code the sketch already wrote means the test runs red against the code with the
relevant hunk removed.

Nothing here adds a model, a field or a migration.

## Technical Context

- Python 3.12+, Django 5.2+, django-mvp `>=0.30.1,<0.31` (moving to 0.31 in a separate pull request,
  which this branch takes once merged), django-mvp-forms with the `daisyui` crispy pack.
- Tests: pytest with pytest-django, `tests/settings.py`, the ui routes mounted at `/vocabularies/`
  (`tests/urls.py`). Consuming models with both concept fields live in `tests/testapp/models.py`.
- Verify: `uv run pre-commit run --all-files` and `uv run pytest`.

## Constitution Check

- Article I (test first): every task names its test and the hunk it runs red against.
- Untrusted input: names and publication details are model data rendered through Django's
  autoescaping. The `back` parameter on the delete page is checked with
  `url_has_allowed_host_and_scheme`. The `next` parameter is django-mvp's own, open-redirect safe.
- Translatable strings: every string the pages show goes through `gettext_lazy`.
- The admin stays optional (ADR 0013): nothing imports `django.contrib.admin`.
- No new model, field or migration.

## Project Structure

```text
controlled_vocabularies/ui/
├── forms.py                      # VocabularyForm (kept from the sketch, changed per D1–D2 below)
├── views.py                      # VocabularyCreateView, VocabularyUpdateView, VocabularyDeleteView
├── urls.py                       # the three routes behind "-"
└── templates/controlled_vocabularies/ui/
    ├── conceptscheme_form.html           # kept
    ├── conceptscheme_confirm_delete.html # kept
    ├── conceptscheme_list.html           # "New vocabulary" action, kept
    └── conceptscheme_detail.html         # Edit and Delete actions, kept
tests/test_ui/
├── test_views.py                 # new classes for the three views and the page actions
├── test_forms.py                 # new: the form
└── test_architecture.py          # one more import scan (no admin)
tests/conftest.py                 # curator fixtures
docs/curating.md                  # new how-to page
docs/adr/NNNN-…                   # the "-" segment, graduated at converge
demo/                             # sign-in, accounts, a third vocabulary
```

## Design

### D1 — The form

`VocabularyForm` (`controlled_vocabularies/ui/forms.py`), a `ModelForm` over the name, description,
default language and the five publication details. Never the slug, `slug_is_manual` or `static_uri`
(FR-009).

- `default_language` is a `ChoiceField`: a blank "site default" choice labelled with
  `language_name(settings.LANGUAGE_CODE)`, then `[(code, language_name(code)) for code, _ in
  settings.LANGUAGES]`. `language_name` is the existing helper in `controlled_vocabularies/ui/filters.py`,
  which already falls back for a code Django does not know. The sketch's `language_choices()` is deleted.
- `clean_name()` strips the name, refuses an empty slug (`code="empty_slug"`) and a slug another
  vocabulary holds (`code="slug_taken"`), skipping both for a `slug_is_manual` vocabulary (research
  R4).
- **Changed from the sketch:** the default language is not a Django `disabled` field. When the bound
  instance holds concepts, the widget gets the HTML `disabled` attribute and the field's help text says
  why. `clean_default_language()` returns the stored value when the field is absent from the submitted data
  (`widget.value_omitted_from_data`), not merely blank, so choosing the blank site default still
  saves `""`. It refuses a
  submitted value that differs from the stored one while the vocabulary holds concepts
  (`code="language_fixed"`). Research R3.
- The crispy `Layout` keeps the approved grouping: name, description and default language untitled,
  then a "Publication details" `Fieldset`.

### D2 — Dependencies

`django-crispy-forms>=2.7,<3.0; python_version >= '3.12'` is added to the `ui` extra in
`pyproject.toml`, beside django-filter and for the same reason (research R8), and `uv.lock` is
refreshed. The dependency check then passes.

### D3 — The views

All three in `controlled_vocabularies/ui/views.py`, each `PermissionRequiredMixin` first:

| View | Permission | Notes |
|---|---|---|
| `VocabularyCreateView(MVPCreateView)` | `add_conceptscheme` | lands on the new vocabulary's page with a success message |
| `VocabularyUpdateView(MVPUpdateView)` | `change_conceptscheme` | `get_object()` raises `PermissionDenied` for a vocabulary with `static_uri` (FR-008). Lands on the vocabulary's page at its current address. Cancel and the breadcrumb use `self.object.slug`: the slug only changes inside `save()`, so no re-query is needed. Offers Delete only to a user with `delete_conceptscheme` |
| `VocabularyDeleteView(MVPDeleteView)` | `delete_conceptscheme` | any vocabulary. Context adds `concept_count`, `collection_count` and `protected_kinds` (D4). Back goes to `back` when `url_has_allowed_host_and_scheme(back, {request.get_host()}, require_https=request.is_secure())` accepts it, as django-mvp's own `get_back_url()` checks, else the vocabulary's page. Lands on the list |

The sketch's views are kept in shape. **Removed from the sketch:** the `?preview=in-use` branch in
`VocabularyDeleteView.get_context_data()`.

A stale edit form whose vocabulary was deleted meanwhile gets 404 from `get_object()`. It never
creates a vocabulary (spec, Edge Cases).

### D4 — Who is using the concepts

`protected_kinds` is a list of `(label, count)` pairs, sorted by label: each protected record is
grouped under `record._meta.auto_created or type(record)` (the consuming model, for a `ConceptsField`
through row as well as a `ConceptField` row), labelled with that model's capitalised
`verbose_name_plural`, and counted by distinct source record (research R5). For a `ConceptField` kind, the distinct pks of the
records already in hand. For a through-model kind, one query:
`through.objects.filter(pk__in=<protected pks>).values(<fk to the consumer>).distinct().count()`,
because the collector loads through rows with their pk only.

### D5 — Routes

In `controlled_vocabularies/ui/urls.py`, before the vocabulary and concept routes:
`-/new/` → `vocabulary-create`, `<str:slug>/-/edit/` → `vocabulary-update`,
`<str:slug>/-/delete/` → `vocabulary-delete` (research R7).

### D6 — The browsing pages

The list of vocabularies shows "New vocabulary" only with `add_conceptscheme`. A vocabulary's page
shows Edit only with `change_conceptscheme` and no `static_uri`, and Delete only with
`delete_conceptscheme` (FR-017, FR-018). Kept from the sketch.

### D7 — Demo

Kept from the sketch: `django.contrib.auth.urls` under `/accounts/`, `demo/templates/registration/login.html`,
`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`, and `seed_demo` creating "Sample Types" and the standard
accounts with `curator.user`. `demo/smoke.py` and its tests are brought in line with three seeded
vocabularies wherever they count them.

### D8 — Documentation

`docs/curating.md` (how-to), linked from `docs/index.md`. `docs/browsing.md`: where it calls the pages
read-only, point to the curating page. `CONTEXT.md`: **Curator**. `CHANGELOG.md`: Added entry, and the
`ui` extra's new crispy-forms requirement.

## Story sequencing

One implementer builds the three stories in order in the feature's worktree, because they share
`views.py`, `urls.py` and the documentation page: US1 (form, create, routes, list action, dependency,
demo), then US2 (edit, vocabulary page actions), then US3 (delete).

## Complexity Tracking

None. Every piece is a subclass or a configuration of what django-mvp and Django already provide,
apart from the few lines grouping protected records (D4).
