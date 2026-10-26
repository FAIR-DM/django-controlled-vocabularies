# Implementation Plan — 010 Attach several concepts from a chosen vocabulary to a model

**Branch**: `010-attach-several-concepts` · **Spec**: `spec.md` · **Research**: `research.md` ·
**Decisions**: `decisions.md` · **Issue**: #87 · **Serves**: G2 · **Roadmap**: R3

## Summary

Ship `MultiConceptField`, a `ManyToManyField` subclass a consuming project declares on its own model,
naming by slug the vocabulary its concepts come from — one, several, or none. It fixes what the
consumer does not supply — the target, the membership model, and the choice restriction — and adds
the two guarantees a many-valued relation does not provide on its own.

*Refined 2026-08-12 (spec `## Clarifications`, `decisions.md` D9): naming a vocabulary became
optional, so a project can carry a keywords field drawing on several imported vocabularies or on all
of them. Propagated through Approach 1, 4 and 7, and through `tasks.md` T001, T002, T005, T006, T010
and the new T012.*

The shape of the work is set by `research.md`, and it is not the shape FS-009 had. The single-value
field was a `ForeignKey` that filled in three arguments and got its constraint, its validation and
its delete protection from Django. Here, of those three, only the form restriction is inherited:

| What the spec asks | FS-009 got it from | Here it comes from |
|---|---|---|
| Form offers only the vocabulary's concepts (FR-006) | `limit_choices_to` | `limit_choices_to`, unchanged (R1) |
| Foreign concept refused (FR-005) | `ForeignKey.validate()` | an `m2m_changed` `pre_add` receiver (R1, R2, R3) |
| Referenced concept cannot be deleted (FR-007) | `on_delete=PROTECT` on the field | a generated through model whose target foreign key is `PROTECT` (R4, R6) |
| Required means a value (FR-010) | `null=False` at the column | `blank=False` for the form, plus a pk-guarded check installed on `full_clean` (R2, R5) |
| Label and URI readback (FR-008/009) | two contributed accessors | two contributed accessors, returning one value per attached concept |
| Missing vocabulary reported (FR-004) | `checks.py` | the same check, widened to both field types |

Three of those five rows are new mechanisms rather than new arguments, which is what makes this
feature larger than its issue text suggests.

## Technical Context

**Language/Version**: Python 3.11+ · **Framework**: Django 5.2 LTS and 6.0
**Runtime dependencies**: unchanged — `django`, `rdflib`, `defusedxml`. Article VII needs no new
justification.
**Testing**: pytest + pytest-django + factory_boy from `mvp-shared[test]`.
**Storage**: no change to this package's own models. The membership table belongs to the consuming
model and is generated per declaration; the test app carries the only new migration.
**Target**: any Django project installing this package.

**What exists and is being used, not rebuilt:**

| Surface | Where | Used for |
|---|---|---|
| `ConceptField` | `fields.py:17` | the precedent for `__init__`/`deconstruct`/accessor shape — not a base class (see Complexity Tracking) |
| `Concept` | `models.py:613` | the relation target |
| `Concept.display_label()` | `models.py:750` | FR-008, per attached concept |
| `Concept.uri` | `models.py:315` (inherited) | FR-009, returned unchanged |
| `ConceptScheme.slug` (unique app-wide) | `models.py:453` | the declaration key |
| `check_concept_field_vocabularies` | `checks.py:20` | FR-004, widened to both field types |
| `create_many_to_many_intermediary_model` | Django `related.py:1308` | the pattern the through generation follows |
| `tests/testapp/models.py` | test app | consuming models, extended rather than replaced |

## Constitution Check

| Article | Bearing on this feature | Verdict |
|---|---|---|
| I — Test-First | Every task writes its test first. The two most likely to be asserted against a mock instead of the real condition are the delete protection (must be a real `ProtectedError` from a real delete, both single and queryset) and the fast-path hazard in R6 (must assert a foreign concept is refused through `.add()` on a live model, not that a receiver function returns something). | Pass, watched |
| II — Simplicity | Three mechanisms, each the smallest thing that satisfies its requirement: one `Q`, one signal receiver, one copied-and-changed model factory. No custom manager, queryset, or form field. | Pass |
| III — Anti-Abstraction | No shared base class between the two fields. See Complexity Tracking — this is the feature's main design judgement and it resolves against extraction. | Pass |
| IV — Integration-First | The field is the package's public integration surface, exercised through real consuming models in the test app, including one carrying both field types against the same vocabulary. | Pass |
| V — Security & data-safety | The delete guard is the data-safety mechanism. Its boundary is stated honestly in the README: it is enforced by Django's collector, not by a database constraint, because Django emits no `ON DELETE` clause for any relation (R6). | Pass |
| VI — Documentation | README gains the multiple-value declaration, the readback, what required and optional mean, and the query-cost note. `CONTEXT.md` gains the term. CHANGELOG records the addition. | Pass |
| VII — Dependency discipline | Nothing added. | Pass |
| VIII — Compatibility | The article already names `MultiConceptField` as part of the Python API contract, so the name is fixed by the constitution rather than chosen here. | Pass |
| IX — URI identity & downstream-data safety | The article's `on_delete=PROTECT` clause is honoured through the generated through model, which is the only place a many-valued relation can carry it. | Pass |
| X — Stack & architecture norms | Models stay the source of truth. Nothing here touches RDF. | Pass |
| XII — Internationalization | `help_text` on the field, translatable validation messages with named placeholders. The `TypeError`s refusing fixed kwargs are developer diagnostics and are exempt. | Pass |
| XIII — Data-model conventions | Indexing recorded in `research.md` R7: the membership table's two foreign keys carry Django's automatic indexes and the pair carries the join's uniqueness constraint; nothing is added. Migrations consolidated at S5. | Pass |
| XIV — Test structure | `tests/test_fields.py` gains classes for the new field; the consuming models and fixtures are extended, not duplicated. | Pass |
| XV — Cohesion | The field class holds the behaviour. The one module-level function is the through-model factory, which mirrors Django's own and is called from exactly one place. | Pass |

No violations.

## Project Structure

### Documentation (this feature)

```text
specs/010-attach-several-concepts/
├── spec.md
├── decisions.md
├── research.md
├── plan.md
└── tasks.md
```

### Source code

```text
controlled_vocabularies/
├── fields.py          # MultiConceptField added alongside ConceptField
└── checks.py          # widened to both field types

tests/
├── test_fields.py     # new classes for MultiConceptField
├── conftest.py        # fixtures extended
├── factories.py       # unchanged
└── testapp/
    ├── models.py      # consuming models extended
    └── migrations/    # one new migration
```

## Approach

**1. The field, and what it fixes.** *(Propagated 2026-08-12 from the spec refinement, D9.)*
`MultiConceptField(ManyToManyField)` takes an **optional** `vocabulary` and fixes three things the
consumer may not supply: `to="controlled_vocabularies.Concept"`, `limit_choices_to`, and `through`.

`vocabulary` accepts three shapes, normalised once in `__init__` to a tuple of slugs:

| Declaration | Normalised | `limit_choices_to` |
|---|---|---|
| `vocabulary="rock-type"` | `("rock-type",)` | `Q(scheme__slug__in=("rock-type",))` |
| `vocabulary=["gcmd", "agu-index"]` | `("gcmd", "agu-index")` | `Q(scheme__slug__in=(…))` |
| omitted | `()` | not set at all |

One code path, not three: a single slug is a one-element tuple, so `__in` covers both the one-and
several cases and there is no separate branch to test or to get wrong. Duplicates collapse and order
does not matter, because a set of slugs is what the restriction means. The empty tuple is the only
genuine branch, and it is an absence — no `limit_choices_to`, no receiver, no check entry — rather
than a second mechanism.

`to` and `limit_choices_to` are overwritten; `through` is refused outright with a `TypeError`,
because a consumer-supplied membership model would silently drop the delete guarantee — the same
reasoning that makes `on_delete` non-overridable on `ConceptField`. `to` stays the *string* form,
never the imported class, for the migration-state reason recorded in `ConceptField`'s docstring.

**A field naming no vocabulary is not a degenerate case to tolerate; it is a supported shape.** It
keeps the delete protection, the readback and the required-set rule, and it gives up only the
restriction. What matters for the code is that every mechanism below asks "did this declaration name
any vocabulary?" and does nothing rather than something weaker when the answer is no.

**2. Deconstruction.** `deconstruct()` strips `to` and `limit_choices_to` and records `vocabulary`.
Both are emitted by Django and both would be passed back to `__init__` by `Field.clone()`, which runs
on every `makemigrations`, `makemigrations --check`, `migrate` and test-database build. `through` is
never emitted, because the generated model is marked auto-created (R6). A kwarg stripped without a
recorded replacement is worse than one left in — migration state and field definition diverge with no
error — so `vocabulary` carries the whole declaration.

**3. The through model.** `contribute_to_class` skips `ManyToManyField`'s own through generation and
substitutes one whose foreign key to `Concept` is `PROTECT` rather than `CASCADE`, following
Django's `create_many_to_many_intermediary_model` exactly otherwise — same naming, same
`unique_together`, same hidden reverse accessors, and critically the same `Meta.auto_created` set to
the owning model class, which is what keeps the model out of migration state and out of
`deconstruct()` while still having its table created and dropped with the owner (R6).

**Skipping means skipping the method, not undoing its effect.** `ManyToManyField.contribute_to_class`
generates and registers the CASCADE through model inside its own body, after its `super()` call and
before returning, so there is no seam an ordinary `super().contribute_to_class(...)` leaves open. Call
it and then generate a second model of the same name and Django's app registry warns
`Model … was already registered` on every consuming declaration. The way through is
`super(ManyToManyField, self).contribute_to_class(cls, name, **kwargs)`, which enters the MRO one
class higher and attaches the field without generating anything. That skip has a price: the
symmetrical and hidden `related_name` rewriting at the top of `ManyToManyField.contribute_to_class`
is skipped with it, and the hidden branch is live here — FR-011 accepts `related_name="+"`, and
without the rewrite two such fields on one model clash. Replicate that branch before the `super()`
call. The symmetrical branch is dead for this field, because the target is always `Concept` and never
the owner, so replicating it would be writing code for a state that cannot occur.

**4. The vocabulary check on the write path.** In the same `contribute_to_class`, connect an
`m2m_changed` receiver to the through model just generated — **only when the declaration named at
least one vocabulary.** A field naming none has nothing to enforce, and not connecting a receiver is
better than connecting one that returns immediately: Django's fast path is then available and the
field costs exactly what a stock relation costs (R6). On `pre_add` the receiver resolves the incoming
primary keys in one query and raises `ValidationError` naming the expected vocabularies if any
concept falls outside them, which aborts the whole write before a row is inserted (FR-005). **Connecting the
receiver here, rather than in `AppConfig.ready()` or on import of some other module, is
load-bearing:** R6 found that a truthy `auto_created` re-enables Django's `bulk_create` fast path,
which skips `m2m_changed` entirely when no receiver is connected for that through model. Binding the
receiver at the moment the through model is created means a declaration cannot exist without its own
guard, so there is no window in which writes go unchecked.

**5. Required means at least one.** `blank=False` gives the form half for nothing (R5). The model
half has no hook — `full_clean()` never looks at a many-valued relation (R2) — so the field installs
one on the consuming model class, once per class, delegating to the original `full_clean`. Three
constraints on that installation, the first from FR-010 and the other two from R5 and the probe
output:

- **It checks every required `MultiConceptField` on the class, not the one that installed it.** The
  installation happens once per class, so a wrapper closing over the field instance that triggered it
  would leave a second required `MultiConceptField` on the same model unenforced, silently and with
  nothing failing. The wrapper resolves the class's required `MultiConceptField`s from
  `cls._meta.get_fields()` when it runs, and FR-010 applies to each of them.

- **It must skip an unsaved record.** Touching the relation descriptor on an instance with no primary
  key raises `ValueError`, and `full_clean` does not catch `ValueError`, so an unguarded check turns
  an ordinary `ModelForm.is_valid()` on a new object into a crash. It also *has* to skip it on the
  merits: a record is saved before its memberships can be written, so an empty set on an unsaved
  record is the correct intermediate state of every legitimate creation (D3).
- **It must not swallow the other errors.** The original `full_clean` raises before the added check
  runs, so the check has to catch that `ValidationError`, merge its own message into the error
  dictionary under the field's name, and re-raise the whole thing. A record with a bad character
  field and an empty required set must report both.

**6. Readback.** `contribute_to_class` adds `get_<name>_labels()` and `get_<name>_uris()`, plural,
each returning one entry per attached concept — labels through `Concept.display_label()`, which
already resolves the active language and falls back to the vocabulary's default. Both return an
empty result rather than raising when the record holds nothing. The existing collision guard applies:
a model that already defines either name keeps its own.

**7. The system check.** `checks.py` currently filters `isinstance(field, ConceptField)` over
`model._meta.get_fields()`. Widen the filter to both field types and keep everything else — the same
warning id, the same single query for the distinct slugs, the same silence on a `DatabaseError`. The
existing tests continue to cover the single-value case.

Two things the refinement changes here. A `MultiConceptField` contributes **each** of the slugs it names
to the distinct set, not one, and a field naming none contributes nothing and can never be warned
about (FR-004). A field naming three vocabularies of which one is absent warns about that one and
stays quiet about the other two, so the warning names the missing slug rather than the field's whole
declaration.

**8. Documentation.** README, `CONTEXT.md` and CHANGELOG per Articles VI and XII. The README states
the delete guarantee's real boundary rather than overstating it: it holds for anything going through
the ORM, including a bulk queryset delete, and not for SQL issued outside Django.

## Complexity Tracking

One judgement, which `decisions.md` D6 deliberately left to this stage: **do the two fields share an
implementation?**

They do not, and the reason is that the overlap is smaller than it looks. Reading the two side by
side, every mechanism differs — `ForeignKey` against `ManyToManyField`, `validate()` against a
signal receiver, an inherited `PROTECT` against a generated through model, a column's `null=False`
against an installed validation hook. What genuinely repeats is the `vocabulary` kwarg being stored
and stripped, which is about six lines, and the shape of the two contributed accessors.

Article III asks for a present, concrete second use before an abstraction, and this is that second
use — so the question is fairly put. The answer is that a shared base holding six lines of kwarg
handling would have to be a `Field` subclass sitting above two classes with different parents, which
is not a base class so much as a mixin invented to avoid a small duplication, and it would make the
next reader trace two hops to find out what a declaration does. Article III's own words — prefer
duplication over the wrong abstraction — cover this exactly.

One thing genuinely is shared and is treated as such: the system check, which already walks every
field of every model and simply gains a second type in its filter. That is a widened filter, not an
abstraction.

Recorded as D7 in `decisions.md`. Nothing else in this feature adds a dependency, a layer, or an
indirection, so Complexity Tracking is otherwise empty.

## Risks

- **The fast-path hazard (R6).** If the receiver is ever connected later than the through model's
  creation, writes silently skip validation and every test that asserts a refusal still passes when
  run in isolation. Mitigated by binding the two together in `contribute_to_class`, and by a test
  that attaches a foreign concept through `.add()` on a real model rather than calling the receiver
  directly.
- **Installing a hook on someone else's model.** Wrapping `full_clean` on the consuming class is the
  most invasive thing this feature does. It is guarded to run once per class, it delegates, and it
  merges rather than replaces the error dictionary — but a consuming model that overrides
  `full_clean` itself after the field is declared would shadow it. Worth a README sentence.
- **Two fields on one model against one vocabulary.** The generated through model is named from the
  owning model and the field name, so two declarations cannot collide, but this is asserted rather
  than assumed: the test app carries a model with both a `ConceptField` and a `MultiConceptField` against
  the same vocabulary.
- **`ProtectedError` is not `ValidationError`.** A curator deleting through a form or the admin sees
  an exception, not a friendly message. That is exactly what FS-009 already does for the single-value
  field, so the behaviour is consistent; making it friendly belongs to the admin slice (#89), not
  here.
