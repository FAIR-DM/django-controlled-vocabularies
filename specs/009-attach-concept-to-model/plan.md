# Implementation Plan — 009 Attach a concept from a chosen vocabulary to a model

**Branch**: `009-attach-concept-to-model` · **Spec**: [`spec.md`](spec.md) · **Research**: [`research.md`](research.md) · **Decisions**: [`decisions.md`](decisions.md)

## Summary

A `ForeignKey` subclass, `ConceptField`, that a consuming project declares on its own model naming
one vocabulary by slug. Almost everything the spec asks for falls out of `limit_choices_to` set to a
`Q` object: it restricts the choices a form offers and it is applied by `ForeignKey.validate()`, so
FR-005 and FR-006 are one mechanism rather than two, and a `Q` is lazy so FR-003's no-query-at-import
rule holds without effort (`research.md` R1). `on_delete` is fixed at `PROTECT`, which Article IX
already requires and which the relation enforces against bulk deletes and cascades alike.

The work that is genuinely new is at the edges:

- `deconstruct()` has to strip three inherited kwargs so migrations record the `vocabulary` string
  the consumer wrote rather than a duplicated `Q` literal (`research.md` R2);
- an app-level system check that reports a named vocabulary missing from the database, as a warning,
  surviving a database with no tables (`research.md` R3);
- a label resolution that falls back from the active language to the vocabulary's default, which
  belongs on `Concept` because #87 and every serializer need the same thing (`research.md` R4).

No new runtime dependency. One migration, in the test app only — the package itself gains no model
change, because the field is something consumers declare rather than something this package stores.

## Technical Context

**Language/Version**: Python 3.11+ · **Framework**: Django 5.2 LTS and 6.0
**Runtime dependencies**: unchanged — `django`, `rdflib`, `defusedxml`. Article VII needs no new
justification.
**Testing**: pytest + pytest-django + factory_boy from `mvp-shared[test]`.
**Storage**: no change to this package's models beyond one added method. The consuming test model
lives in the test app and carries the only new migration.
**Target**: any Django project installing this package.

**What exists and is being used, not rebuilt:**

| Surface | Where | Used for |
|---|---|---|
| `Concept` | `models.py:612` | the relation target |
| `Concept.preferred_label(language=None)` | `models.py:731` | the per-language read `display_label()` composes |
| `Concept.uri` | `models.py:314` (inherited) | FR-009, returned unchanged |
| `ConceptScheme.slug` (unique app-wide) | `models.py:453` | the declaration key |
| `ConceptScheme.effective_default_language` | `models.py:513` | the fallback language |
| `ForeignKey.validate()` / `formfield()` | Django | FR-005 and FR-006, via `limit_choices_to` |

## Constitution Check

| Article | Bearing on this feature | Verdict |
|---|---|---|
| I — Test-First | Every task writes its test first. The check's unmigrated-database path is the one most likely to be asserted with a mock instead of the real condition, and must not be. | Pass, watched |
| II — Simplicity | The whole constraint is one `Q`. No custom manager, queryset, descriptor, or form field. | Pass |
| III — Anti-Abstraction | The rejected alternatives in `research.md` are all abstractions this refuses. `ConceptField` is a `ForeignKey` that fills in three arguments. | Pass |
| IV — Integration-First | The field is the package's public integration surface, exercised through a real consuming model in the test app rather than in isolation. | Pass |
| V — Security & data-safety | `PROTECT` is the data-safety mechanism, and it is the point of US-3. | Pass |
| VI — Documentation | README gains the declaration, the readback, the missing-vocabulary behaviour, and the `select_related`/`prefetch_related` note from `research.md` R7. | Pass |
| VII — Dependency discipline | Nothing added. | Pass |
| IX — URI identity & downstream-data safety | `on_delete=PROTECT` is this article's clause, implemented here for the first time. The article's per-concept lifecycle sentence is superseded and is R4's to reconcile (`decisions.md` D6). | Pass |
| X — Stack & architecture norms | Models stay the source of truth. Nothing here touches RDF. | Pass |
| XII — Internationalization | `help_text` on the field, translatable validation message with a named placeholder. The `on_delete` refusal is a developer diagnostic and is exempt. | Pass |
| XIII — Data-model conventions | The FK index is kept, deliberately, and recorded (`research.md` R6). Migrations consolidated at S5. | Pass |
| XIV — Test structure | Test modules mirror the source tree; the consuming model and its factory are shared fixtures, not per-test definitions. | Pass |

No violations. Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/009-attach-concept-to-model/
├── spec.md
├── plan.md
├── research.md
├── decisions.md
└── tasks.md
```

No `data-model.md`: this feature adds no model to the package. No `contracts/`: the contract is the
field's own signature, and it is documented in the README.

### Source code

```text
controlled_vocabularies/
├── fields.py          # NEW — ConceptField
├── checks.py          # NEW — the missing-vocabulary system check
├── models.py          # + Concept.display_label()
└── apps.py            # + register the check in ready()

tests/
├── test_fields.py     # NEW — declaration, constraint, deconstruct, readback, delete guard
├── test_checks.py     # NEW — the system check, including the unmigrated-database path
├── test_models.py     # + Concept.display_label()
├── factories.py       # + a factory for the consuming test model
├── conftest.py        # + fixtures shared with #87, #88, #89
└── testapp/           # NEW — the consuming model and its migration
```

**Structure Decision.** `fields.py` and `checks.py` are new top-level modules in the package, matching
the flat layout the package already uses for `conf.py` and `models.py`. The consuming model has to
live somewhere Django can migrate, and it must not be in the package itself — shipping a consumer of
your own public API as a model is how a test fixture becomes an unintended part of the distribution.
So it goes in a `tests/testapp/` app added to the test settings' `INSTALLED_APPS`.

## Approach

**Phase F — foundational, sequential, blocks everything.** The consuming test app has to exist before
any story can be tested against a real model. It carries T001, T003 and T002, in that order: the
field, then `deconstruct()`, then the test app. `deconstruct()` moved here from US-1 on 2026-08-11
because `ModelState.from_model()` clones every field through `deconstruct()`, so no model carrying
`ConceptField` can migrate — or even build a test database — until it exists.

**Then the stories.** US-1 and US-2 are close to the same code and are sequenced together. US-6 is
last because it documents what the others built.

**Dispatch order is constrained by shared files, not only by logic.** Each story runs in its own
worktree, so two stories writing the same module collide at convergence. `fields.py` is written by
T001 (Phase F), T003 (US-1) and T011 (US-5); `tests/test_fields.py` is written by T001, T003,
T005/T006, T007 and T011. So:

- **US-1/US-2, then US-3, then US-5 run in sequence.** All three add cases to
  `tests/test_fields.py`, and US-5 also edits `fields.py`. They are logically independent of one
  another; the constraint is the file, and two worktrees appending to the end of the same file
  conflict on merge regardless. (US-1 is now T004 alone; T003 moved to Phase F.)
- **US-4 is the only genuinely parallel story.** It writes `checks.py` and `tests/test_checks.py`,
  which no other story touches, so it can run alongside any of the above.

The one sequencing constraint worth naming: **US-5 depends on `Concept.display_label()`, which is a
change to this package's model rather than to the field.** It is not a dependency of US-1 through
US-4, so it neither blocks nor is blocked by them.

## Risks

| Risk | Handling |
|---|---|
| The system check is tested against a mocked database error rather than a real unmigrated connection, so it passes while the real path raises. | Named in the task brief as a required test condition, and re-checked at S6 against the diff. This is the single most likely defect in the feature. |
| `deconstruct()` drifts from `__init__` as arguments are added, and nothing notices until a consumer's migration breaks. | A round-trip test — deconstruct, rebuild from the emitted kwargs, assert equivalence — plus `makemigrations --check` in the test app. |
| The `get_<field>_…()` names collide with something a consuming model already defines. | `setattr` is guarded, and the guard has its own test. |
| Vocabulary membership is enforced only at validation, so a reviewer reads it as a hole. | Stated in `spec.md` Assumptions and `decisions.md` D4 before review, not after. |
