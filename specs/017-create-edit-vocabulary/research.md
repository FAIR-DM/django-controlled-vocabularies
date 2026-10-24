# Research — FS-017 Create and edit a vocabulary

Against `origin/main` at `d60c18a`, with django-mvp 0.30.1 installed. The feature has no
`planning-notes.md`. Each item under "What the screens need" and "What the sketch faked" in
`sketch.md` is answered below.

## R1 — django-mvp's model form views carry the whole create, edit and delete flow

`mvp.views.MVPCreateView`, `MVPUpdateView` and `MVPDeleteView` (`mvp/views/edit.py`) provide the
page chrome, crispy rendering through django-mvp-forms, the success message, the redirect chain and,
for deletion, the protected-relation check. `MVPDeleteView.post()` collects the cascade before
deleting and re-renders the page with `is_protected` and `protected_objects` instead of letting
Django raise `ProtectedError`, so a forced submission deletes nothing (FR-015). The sketch already
subclasses all three, and the build keeps them.

The authorisation half is Django's `PermissionRequiredMixin`. With `raise_exception` left at its
default, it sends an anonymous user to `settings.LOGIN_URL` with `?next=` and refuses a signed-in
user without the permission with 403 (FR-004, `decisions.md` D1). The package adds no sign-in of its
own.

## R2 — An imported vocabulary is refused in `get_object()`

`static_uri` set is the signal the browsing pages already use for "imported" (014, Assumptions).
Raising `PermissionDenied` from `VocabularyUpdateView.get_object()` refuses every user on GET and
POST alike, before a form is built (FR-008). The vocabulary page hides the edit button on the same
condition.

## R3 — The default language: refuse a change in `clean`, not with a disabled field

A disabled Django field ignores submitted data and keeps the initial value. That silently drops a
change in the edge case where a concept was added between opening the form and saving it, where the
spec asks for a refusal with the reason. `ConceptScheme.save()` also raises `ValidationError` on that
change, which a form view would turn into a server error, because `form_valid()` calls `save()`
outside validation.

So the form validates it:

- `clean_default_language()` refuses a value that differs from the stored one when the vocabulary
  holds concepts, with code `language_fixed`.
- When the vocabulary holds concepts at render time, the widget is rendered with the HTML `disabled`
  attribute, so the browser submits nothing for it. An absent value keeps the stored language.

The sketch used `field.disabled = True` and is changed accordingly.

## R4 — A name's address is checked in `clean_name()`

`ConceptScheme.save()` refuses an empty slug and a slug collision with `ValidationError`, again
outside form validation. `clean_name()` derives the slug the way `save()` does
(`slugify(name, allow_unicode=True)`) and refuses an empty result (code `empty_slug`) and one taken
by another vocabulary (code `slug_taken`). `slug_is_manual` vocabularies keep their slug, so the check
is skipped for them, matching `save()`. The sketch already does this; codes are added.

## R5 — Who is using a vocabulary's concepts, by kind

`MVPDeleteView` hands the template `protected_objects`, the records whose `PROTECT` foreign key
blocked the cascade. For `ConceptField` that record is the consuming model's own row. For
`ConceptsField` it is a row of the generated through model (`fields.py`, the factory around line
455), whose `Meta.auto_created` is the consuming model. The delete page groups the protected records
by `record._meta.auto_created or type(record)` and counts distinct source records per group, so
`Dataset.keywords` reports "Datasets: 3", never "dataset-concept relationships: 7". This replaces the
sketch's `?preview=in-use` fake.

The test app (`tests/testapp`) already declares models with both fields, so the blocked state can be
tested against real records.

## R6 — Counts, not the cascade list

The spec asks for the number of concepts and collections (FR-014). `vocabulary.concepts.count()` and
`vocabulary.collections.count()` are two queries. `show_related_objects` stays off: the cascade list
would itemise every label, note and relation.

## R7 — The editing addresses sit behind a `-` segment

`/browse/-/new/`, `/browse/<vocabulary>/-/edit/` and `/browse/<vocabulary>/-/delete/`. A
vocabulary's own address is `/browse/<slug>/` and a concept's is `/browse/<slug>/<concept-slug>/`,
so `new`, `edit` or `delete` as plain segments would collide with a vocabulary or a concept of that
slug. `-` cannot be a slug: `slugify()` strips leading and trailing hyphens, and every slug the
package mints, from a label or from a published identifier (`exchange/skos.py`,
`identifier_slug_base`), goes through it. GitLab uses the same separator for the same reason. The
maintainer saw these addresses at the sketch gate and left the choice to the plan; it is kept. This
is a lasting rule about the package's address space, so it graduates to an ADR.

## R8 — crispy-forms becomes a declared dependency of the `ui` extra

The form's grouping is a crispy `Layout` with a `Fieldset`, the way django-mvp's own documentation
draws a form (`views.md`, "Three ways to change what a form looks like"). The package already imports
crispy indirectly through django-mvp, and the dependency check refuses a direct import of a
transitive dependency. django-filter was handled the same way in #202: it is declared in the `ui`
extra beside django-mvp, with django-mvp's own range. crispy-forms gets the same treatment:
`django-crispy-forms>=2.7,<3.0` (django-mvp 0.30 and 0.31 both require that range).

## R9 — The demo gains sign-in and the standard accounts

The package mounts no sign-in, so the demo mounts `django.contrib.auth.urls` and a login template,
and `seed_demo` creates the standard accounts with a `curator.user` holding the three vocabulary
permissions. A third, empty vocabulary ("Sample Types") lets the default language be changed in the
demo. The CI walk of the demo (`demo/smoke.py`) checks vocabulary counts and names, so it is checked
against the new seed.

## R10 — Documentation

A new how-to page, `docs/curating.md`, linked from `docs/index.md` under "Using the package": how a
curator creates, edits and deletes a vocabulary, which permission each needs, why an imported
vocabulary cannot be edited, and the URLs a project mounts. `docs/browsing.md` gets a line where it
says the pages are read-only. `CONTEXT.md` gains **Curator**. `CHANGELOG.md` gets an Added entry.

## What already exists

| Piece | Stopped at | Where |
|---|---|---|
| Create, edit and delete views | Installed package | `mvp.views.MVPCreateView`, `MVPUpdateView`, `MVPDeleteView` |
| Permission check and sign-in redirect | Django | `django.contrib.auth.mixins.PermissionRequiredMixin` |
| Refusing a protected deletion | Installed package | `MVPDeleteView.post()`, `_collect_deletion_data()` |
| The form | Django | `forms.ModelForm` over `ConceptScheme`, with crispy `Layout` (installed) |
| Slug derivation in the form | Django | `django.utils.text.slugify`, as `ConceptScheme.save()` uses |
| Language names | Django | `django.utils.translation.get_language_info`, as `VocabularyDetailView` uses |
| Date input | Browser | `<input type="date">` |
| Grouping protected records by consuming model | New code | a few lines in `VocabularyDeleteView.get_context_data()` |
| Templates for the form and the delete page | This repo and installed package | extend `form_view.html` and `delete_view.html` |
| Success messages | Installed package | `SuccessMessageMixin` through `MVPFormBase` |
| Demo sign-in | Django | `django.contrib.auth.urls`, `LoginView` |
