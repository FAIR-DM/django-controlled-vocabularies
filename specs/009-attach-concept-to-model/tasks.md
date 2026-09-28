# Tasks — 009 Attach a concept from a chosen vocabulary to a model

Every task is test-first (Article I): the failing test comes before the code that satisfies it, in
the same task. Task ids are stable and never reused.

**No pre-existing test is modified.** This feature adds one method to `Concept` and otherwise adds
new modules, so the existing suite must pass untouched. A task that needs to edit an existing test
has got the change wrong.

**Tasks have no issues** — this file and `feature-state.json` are the whole task record.

**Sequencing.** Phase F blocks everything. After it, US-1 and US-2 are sequenced together because
both work on `fields.py`. US-3, US-4 and US-5 are independent of one another and of US-1/US-2 once
Phase F lands. US-6 is last because it documents what the others built.

## Phase F — Foundational (blocks every story)

- **T001** — `ConceptField` construction (FR-001, FR-002, FR-007, FR-010, `research.md` R1, R5).

  New module `controlled_vocabularies/fields.py`. `ConceptField(ForeignKey)` takes `vocabulary` as
  its first argument and fixes three things the consumer does not supply:
  `to="controlled_vocabularies.Concept"`, `on_delete=PROTECT`, and
  `limit_choices_to=Q(scheme__slug=vocabulary)`.

  **`to` is the string form, always, and this is not a detail.** A resolved model class in `to` is
  rejected outright by migration state — `ModelState` raises `ValueError: Model fields in
  "ModelState.fields" cannot refer to a model class`, because state has to be rebuildable without
  every referenced model already loaded. An ordinary `ForeignKey` never trips this, since its own
  `deconstruct()` stringifies a live-class `to` before anything rebuilds from it; this field strips
  `to` from `deconstruct()` entirely (T003), so `__init__` is the only place the string can come
  from. Doing it anywhere else — a `clone()` override, a special case for the autodetector — fixes
  one call site and leaves `migrate` and pytest-django's test-database build broken, which is
  exactly what the first attempt did. The string form also removes the `Concept` import from this
  module, and with it a circular-import risk.

  The `Q` is constructed, never evaluated, so nothing queries the database while the declaration is
  being read. That is FR-003's mechanism and it is asserted here rather than assumed, with
  `django.test.utils.CaptureQueriesContext` around the field's construction.

  Rejections, both at construction time:
  - `on_delete` passed by the consumer raises `TypeError` naming the reason. The guarantee in FR-007
    is not the consumer's to weaken, and refusing loudly is what keeps FR-010's "never silently
    override" true.
  - `vocabulary` absent or empty raises `TypeError`. An unconstrained field is a plain `ForeignKey`
    and offers none of this field's guarantees (FR-002).

  `error_messages["invalid"]` is overridden with a translatable message carrying a named placeholder
  for the vocabulary slug (Article XII). Django's default reads "concept instance with id 4 does not
  exist", which is wrong twice — the concept does exist, and the vocabulary is not named. `help_text`
  is set to a translatable default the consumer can override (Article XII makes it mandatory).

  **The placeholder needs a `validate()` override to have anything to interpolate.**
  `ForeignKey.validate()` builds the `ValidationError`'s `params` itself — `model`, `pk`, `field`,
  `value`, and nothing else (`django/db/models/fields/related.py`, verified against the installed
  Django 5.2.16). `ValidationError` defers `%`-substitution to iteration time
  (`message %= error.params` in `core/exceptions.py.__iter__`, which backs both `.messages` and
  `str()`), so a message carrying `%(vocabulary)s` constructs fine and raises `KeyError` the first
  time anything reads it — including T005's own assertion. So `ConceptField.validate()` calls
  `super().validate(...)` and catches the `code="invalid"` `ValidationError`, re-raising
  `ValidationError(self.error_messages["invalid"], code="invalid", params={"vocabulary": self.vocabulary})`.
  This is a message concern, not a second constraint mechanism — the refusal itself is still
  `limit_choices_to`.

  **T001 implements `validate()`; T005 proves it.** With a string `to`, `remote_field.model` only
  resolves when the field is attached to a model class (`RelatedField.contribute_to_class()` defers
  to `lazy_related_operation`), so an unbound field cannot run `validate()` at all — and no
  consuming model exists at this task. So T001's tests assert what an unbound field can:
  construction, both rejections, zero queries, and that `error_messages["invalid"]` carries the
  named placeholder. The behavioural assertion — raise, then *read* `.messages` and find the
  vocabulary named — is T005's, against a real test-app model, which is where the design review
  put it. Do not write a throwaway model in `tests/test_fields.py` to bring it forward.

- **T003** — `deconstruct()` (FR-001, `research.md` R2). *(Moved into Phase F from US-1 on
  2026-08-11 — see below. It was never a US-1 refinement; nothing that carries this field can
  migrate without it.)*

  `ForeignKey.deconstruct()` emits `to`, `on_delete` and `limit_choices_to`. All three are fixed by
  this field, and `limit_choices_to` is derived from `vocabulary`, so leaving them in would put a
  `Q` literal in every consumer's migration that duplicates the `vocabulary` string and drifts from
  it the moment either changes. `ConceptField.deconstruct()` deletes all three and adds `vocabulary`.

  **Why this is foundational and not US-1's.** `Field.clone()` rebuilds a field by calling
  `self.__class__(*args, **kwargs)` from its own `deconstruct()` output
  (`db/models/fields/__init__.py:666`), and `ModelState.from_model()` clones every local field
  (`db/migrations/state.py:807`). That runs on `makemigrations`, `makemigrations --check`, `migrate`
  and pytest-django's test-database build. Without this task, `deconstruct()` emits no `vocabulary`
  while `__init__` requires one and rejects `on_delete` — so every one of those commands raises
  `TypeError: Couldn't reconstruct field …` before writing anything, and T002's test app cannot
  produce an initial migration at all. Found by the Phase F Implementer, which reported T002 blocked
  rather than routing around the phase boundary; verified at both source lines.

  Test: a round trip. Deconstruct a field, rebuild it from the emitted path and kwargs, and assert
  the rebuilt field carries the same vocabulary, the same `limit_choices_to`, and `PROTECT`. Assert
  the emitted kwargs contain none of the three stripped names.

- **T002** — The consuming test app (FR-001, Article IV, testing standard §4).

  New `tests/testapp/`, added to `INSTALLED_APPS` in `tests/settings.py`. It holds the models this
  package's public API is exercised against, and it lives in `tests/` rather than in the package
  because shipping a consumer of your own public API inside the distribution is how a fixture
  becomes an accidental part of the release.

  Models: one carrying a required `ConceptField`, one carrying an optional one with a
  `related_name`, and one that already defines an attribute matching a name T011's contribution
  would generate — the collision guard needs a real model to be tested against, not a synthetic one.

  Its initial migration is generated and committed. Factories go in `tests/factories.py` beside the
  existing ones; the vocabulary fixtures — two schemes, each with concepts, one of them carrying
  labels in more than one language — go in `tests/conftest.py` so #87, #88 and #89 reach them
  without redefining them.

  Tests: the app migrates from zero, and `makemigrations --check` is clean.

## US-1 — A project attaches a concept with one declaration (#90, P1)

*(T003 moved to Phase F on 2026-08-11 — a model carrying `ConceptField` cannot migrate without it,
so it blocks T002 rather than building on it. US-1's story boundary is unchanged: the declaration
still works end-to-end here, and T004 is still what proves it.)*

- **T004** — Declaring, storing, and reading back (FR-001, FR-010).

  End-to-end against the test app. A concept from the named vocabulary assigned to a record survives
  a save and a reload. A record with nothing attached and an optional field validates and saves. The
  ordinary relation options behave as they do anywhere else: `related_name` produces the reverse
  accessor, `null`/`blank` behave, `verbose_name` and `help_text` are what was passed, and the FK's
  index is present (Article XIII, `research.md` R6).

  Test that `makemigrations --check` stays clean after the test app has migrated — the guard against
  T003 rotting.

## US-2 — Selections stay inside the named vocabulary (#91, P1)

- **T005** — Validation refuses a concept from another vocabulary (FR-005, `research.md` R1).

  No new *constraint* code — `ForeignKey.validate()` applies `limit_choices_to` before checking
  existence, so the refusal is already there. The message is the part that needs code, and it lands
  in T001's `validate()` override (without it, reading the raised error's `.messages` raises
  `KeyError: 'vocabulary'` rather than returning the text this task asserts on). What this task adds
  is the proof.

  Tests: `full_clean()` on a record holding a concept from the other vocabulary raises
  `ValidationError`; **reading** `.messages` (not merely catching the error) shows the message names
  the expected vocabulary — that read is the assertion the whole `validate()` override exists for,
  and it is this task's alone, because an unbound field cannot reach it. The message is the translatable
  one from T001 rather than Django's default. A concept from the correct vocabulary passes. A record
  with nothing attached and an optional field passes.

- **T006** — Form choices are limited (FR-006, `research.md` R1).

  Also no new code — `ForeignKey.formfield()` passes `limit_choices_to` through. The task is the
  assertion that it does, because FR-006 is a guarantee a consumer relies on and nothing in this
  package's own source states it.

  Tests: a `ModelForm` generated from the consuming model offers only the named vocabulary's
  concepts, and no concept of the other vocabulary appears. A submission carrying another
  vocabulary's concept is rejected rather than saved.

## US-3 — A concept in use cannot vanish (#92, P1)

- **T007** — The delete guard (FR-007, Article IX, `research.md` R5).

  No new code either — `PROTECT` was fixed in T001. This task is the guarantee's test, and it is
  worth its own task because the behaviour it asserts is the one nothing in the code states.

  Tests:
  - deleting a referenced concept raises `ProtectedError`, and both the concept and the record
    survive;
  - the same holds for `Concept.objects.filter(...).delete()`, because the protection lives in the
    relation rather than in model validation;
  - deleting the `ConceptScheme` holding a referenced concept raises `ProtectedError` and removes
    nothing — the cascade from scheme to concept meets the protection on the way down;
  - a concept no record references deletes normally;
  - deleting a consuming record leaves the concept in place.

## US-4 — A vocabulary that has not been imported yet (#93, P2)

- **T008** — The system check (FR-004, `research.md` R3).

  New module `controlled_vocabularies/checks.py`, registered **untagged** in the app config's
  `ready()`. Untagged is deliberate: `Tags.database` checks are filtered out unless `--database` is
  passed to `manage.py check`, which is exactly the command FR-004 exists to make useful.

  The check walks `apps.get_models()`, collects every declared `ConceptField`, and resolves the
  distinct vocabulary slugs in **one** query rather than one per field. Every field whose slug is
  absent yields a `Warning` naming the model, the field, and the slug, with a stable check ID.

  Tests: with the vocabulary absent, the check reports a warning naming the field and the slug; with
  it present, nothing; the reported object is a `Warning` and not an `Error`; and the whole check
  costs one query however many fields are declared.

- **T009** — The check survives a database it cannot ask (FR-003, FR-004, `research.md` R3).

  The check runs before `migrate`, so on a fresh install it runs against a database with no tables.
  A missing table is not evidence that a vocabulary is absent, so the check returns nothing rather
  than raising or reporting. `ProgrammingError`, `OperationalError` and an unreachable database are
  all `django.db.DatabaseError`, so one `except DatabaseError` covers every case FR-004 names.

  **This must be tested against a genuinely unmigrated connection, not a mocked one.** A mock of
  `DatabaseError` proves the `except` clause catches what it was written to catch and proves nothing
  about what the database actually raises. This is the defect most likely to survive into the merge
  gate, and it is called out in `plan.md` Risks for the same reason.

  Tests: `makemigrations` and `migrate` both succeed on an empty database with the vocabulary
  absent; the check against an unmigrated connection reports nothing; silencing the check ID through
  `SILENCED_SYSTEM_CHECKS` suppresses it; a form built from the consuming model offers no choices and
  does not raise.

## US-5 — The record reads back the label and the identifier (#94, P2)

- **T010** — `Concept.display_label()` (FR-008, `research.md` R4).

  A new method on `Concept`, beside `preferred_label()` and composed from it: the preferred label in
  the active language (`django.utils.translation.get_language()`), falling back to the scheme's
  effective default language when the concept carries none in the active one. A concept always has a
  preferred label in its scheme's default language, so the result is never empty for a concept that
  exists.

  It lives on `Concept` rather than on the field because the resolution is a property of a concept.
  #87 needs the identical thing per concept in a set, and so does any serializer or export reaching
  a concept another way.

  `preferred_label()` is **not** changed. Its `None` return is what makes "does this language have a
  label?" answerable, which import reporting and the future editor both need. Its existing tests must
  pass unmodified — that is the regression proof.

  Tests go in `tests/test_models.py` beside the existing label tests.

- **T011** — `get_<field>_label()` and `get_<field>_uri()` on the consuming model (FR-008, FR-009,
  `research.md` R4).

  `contribute_to_class` sets two methods on the consuming model, named after the field the way
  Django's own `get_FOO_display()` is. `get_<field>_label()` delegates to T010's method;
  `get_<field>_uri()` returns the concept's `uri` unchanged. Both return `None` when nothing is
  attached, rather than raising.

  The `setattr` is guarded: a model that already defines either name keeps its own, and is not
  silently overwritten. T002 built a model that does exactly that, so the guard is tested against a
  real collision.

  Tests: the label is the active language's when present and the vocabulary default's when not; the
  URI matches the concept's own; both return `None` on an empty field; the guard leaves a
  pre-existing definition alone.

## US-6 — Translatable messages, documentation, and reusable test material (#95, P3)

- **T012** — Vocabulary and translation (FR-011, FR-012, Articles VI and XII).

  Audit every string this feature puts in front of a person: the validation message and the
  `help_text` are wrapped with `gettext_lazy` and use named placeholders. The `on_delete` and
  `vocabulary` refusals from T001 are developer-facing diagnostics raised at import time and are
  exempt, which is recorded rather than left to inference.

  `CONTEXT.md` currently carries one row describing `ConceptField / ConceptsField` as a field
  "constrained to a scheme, with an autocomplete widget". That row is now half-wrong and half-early:
  this feature delivers the single-value constraint, `ConceptsField` is #87, and the autocomplete is
  #88. Reconcile it, and define the term the package now puts into a consuming project's code.

  Test: a standards test asserts no bare user-visible literal in `fields.py` or `checks.py`. Follow
  `tests/test_standards.py`'s AST-visitor shape, but **the visitor needs new sinks** — its existing
  ones (`CommandError(...)`, `.stdout`/`.stderr.write(...)`, `add_argument(help=...)`, a class-level
  `help = "..."`) match nothing a field or a check contains, so reused unmodified it reports zero
  regardless of what the new modules do. The sinks to recognise here:
  - `Field(help_text=..., verbose_name=...)` keyword-argument literals
  - `error_messages` dict values
  - bare strings passed to `ValidationError(...)`, `checks.Warning(...)` and `checks.Error(...)`

  Prove the test works by reinstating a bare literal in `fields.py` and confirming it goes red
  before wrapping it again.

- **T013** — README and CHANGELOG (FR-012, Article VI).

  README gains a section showing a field declaration, reading the label and the identifier back, and
  what happens when the named vocabulary has not been imported yet. It also states what
  `research.md` R7 found: `select_related("<field>__scheme")` and
  `prefetch_related("<field>__labels")` collapse the readback's queries. A consumer who does not know
  the storage layout — which is the premise of FR-008 — cannot work that out for themselves.

  CHANGELOG records the addition. Both are public markdown and go through the humanizer before they
  land (S7 does this for the whole feature).
