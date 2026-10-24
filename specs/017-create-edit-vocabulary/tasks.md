# Tasks: Create and edit a vocabulary

**Feature**: `017-create-edit-vocabulary` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md) · **Research**: [`research.md`](./research.md)

Every task is test-first: the test is written and seen to fail before the production change that
makes it pass. The sketch already wrote much of the production code, so "seen to fail" means running
the new test with the relevant hunk removed or reverted, then restoring it. Test scope per task is
one class or one file. The full suite runs once, at the end.

Tests follow `docs/contributing/standards/testing.md`: no assertions on wording, styling or icons;
validation errors asserted by field and code; flash messages by level; permissions, redirects and
what is saved always.

**Nothing in this feature adds a model, a field or a migration.**

---

## User Story 1 — A curator creates a vocabulary (P1, #212)

### T001 — Declare crispy-forms in the `ui` extra

**Files**: `pyproject.toml`, `uv.lock`

Add `django-crispy-forms>=2.7,<3.0; python_version >= '3.12'` to the `ui` extra beside django-filter,
with a one-line comment in the same style (plan D2). `uv lock`. Verified by the dependency check
(`uv run deptry .`) going from red to green with `controlled_vocabularies/ui/forms.py` present.

### T002 — The form accepts a name and the details, and refuses an unusable name

**Files**: `controlled_vocabularies/ui/forms.py`, `tests/test_ui/test_vocabulary_form.py`

Tests: a name alone is valid and saves a vocabulary with no `static_uri`. Every detail given is saved.
The default language offers blank plus the configured languages, and refuses one that is not
configured. A punctuation-only name is refused (`empty_slug`). A name whose slug another vocabulary
holds is refused (`slug_taken`), the other submitted values staying on the bound form. Saving an
existing vocabulary under its own name is not refused. The form has no slug, `slug_is_manual` or
`static_uri` field. Plan D1.

### T003 — Create view, route and permission

**Files**: `controlled_vocabularies/ui/views.py`, `controlled_vocabularies/ui/urls.py`,
`tests/test_ui/test_curation.py`

Tests (`TestVocabularyCreate`): with `add_conceptscheme`, GET is 200 and a valid POST creates the
vocabulary, redirects to its page and adds a success message. An invalid POST creates nothing. An
anonymous GET redirects to `settings.LOGIN_URL` with `next`. A signed-in user without the permission
gets 403 on GET and POST and nothing is created. Plan D3, D5.

### T004 — The list offers creation to a curator only

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_list.html`,
`tests/test_ui/test_curation.py`

Tests (`TestVocabularyListCreateAction`): the creation address appears on the list for a user with
`add_conceptscheme` and not for an anonymous user or a user without it. Plan D6.

### T005 — Demo sign-in, accounts and seed

**Files**: `demo/urls.py`, `demo/settings.py`, `demo/templates/registration/login.html`,
`demo/management/commands/seed_demo.py`, `demo/smoke.py` and its tests if they count vocabularies

Kept from the sketch (plan D7). Test: `seed_demo` creates the standard accounts, `curator.user`
holding exactly the three vocabulary permissions, and the three vocabularies. Bring any existing demo
test or smoke count in line.

### T006 — Documentation for creating

**Files**: `docs/curating.md` (new), `docs/index.md`, `CONTEXT.md`, `CHANGELOG.md`

The how-to page with a "Creating a vocabulary" section, the permissions table, and the routes a
project mounts. `CONTEXT.md` gains **Curator**. `CHANGELOG.md` Added entry and the crispy-forms line.

---

## User Story 2 — A curator edits a vocabulary held here (P1, #213)

### T007 — The default language is fixed once the vocabulary holds concepts

**Files**: `controlled_vocabularies/ui/forms.py`, `tests/test_ui/test_vocabulary_form.py`

Replace the sketch's `field.disabled = True` (plan D1, research R3). Tests: with concepts, the
widget renders `disabled`, a POST omitting the field keeps the stored language, and a POST with a
different language is refused (`language_fixed`) with nothing saved. Without concepts, a changed
language is saved.

### T008 — Edit view, route, permission and the imported refusal

**Files**: `controlled_vocabularies/ui/views.py`, `controlled_vocabularies/ui/urls.py`,
`tests/test_ui/test_curation.py`

Tests (`TestVocabularyUpdate`): with `change_conceptscheme`, GET on a vocabulary held here is 200 with
its current values. A POST changing the description saves it, redirects to the vocabulary's page and
adds a success message. A POST changing the name redirects to the new address, and the old address
is 404. An invalid POST re-renders with the cancel link at the stored address. An imported vocabulary
gets 403 on GET and POST for every user, superuser included, and is unchanged. Anonymous redirects to
sign in. Without the permission, 403. A vocabulary deleted after the form was opened gets 404 and no
vocabulary is created. The delete link is present only with `delete_conceptscheme`. Plan D3, D5.

### T009 — The vocabulary page offers edit and delete by permission

**Files**: `controlled_vocabularies/ui/templates/controlled_vocabularies/ui/conceptscheme_detail.html`,
`tests/test_ui/test_curation.py`

Tests (`TestVocabularyPageCuratorActions`): the edit address appears only with `change_conceptscheme`
on a vocabulary without `static_uri`. The delete address appears only with `delete_conceptscheme`,
on either kind. Neither appears for an anonymous user. Plan D6.

### T010 — Documentation for editing

**Files**: `docs/curating.md`, `docs/browsing.md`

"Editing a vocabulary": what can change, renaming moves the address, the fixed default language, and
why an imported vocabulary cannot be edited. In `docs/browsing.md`, point the read-only statements at
the curating page.

---

## User Story 3 — A curator deletes a vocabulary (P2, #214)

### T011 — Delete view, counts and permission

**Files**: `controlled_vocabularies/ui/views.py`, `controlled_vocabularies/ui/urls.py`,
`tests/test_ui/test_curation.py`

Remove the sketch's `?preview=in-use` branch (plan D3). Tests (`TestVocabularyDelete`): with
`delete_conceptscheme`, GET on a vocabulary holding concepts and a collection is 200 with
`concept_count` and `collection_count` matching. POST deletes the vocabulary, its concepts and its
collections, redirects to the list and adds a success message. An imported vocabulary can be deleted.
Anonymous redirects to sign in. Without the permission, 403 on GET and POST and nothing is deleted.
Back goes to a same-site `back` path, and an off-site or `//` value falls back to the vocabulary's page.

### T012 — A vocabulary in use is never deleted

**Files**: `controlled_vocabularies/ui/views.py`, `tests/test_ui/test_curation.py`

Plan D4, research R5. Tests (`TestVocabularyDeleteInUse`), using `tests/testapp` models: a concept
referenced by a `ConceptField` row, and one referenced by a `ConceptsField` through row. GET is 200
with `is_protected`, no form and `protected_kinds` naming each consuming model with its count of
distinct records (two through rows from one record count once). A forced POST deletes nothing.

### T013 — Documentation for deleting

**Files**: `docs/curating.md`, `CHANGELOG.md`

"Deleting a vocabulary": what goes with it, imported vocabularies included, and why one in use is
refused and what to do about it.
