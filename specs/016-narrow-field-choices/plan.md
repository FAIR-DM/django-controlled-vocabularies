# Implementation Plan: Narrow a field's choices to part of a vocabulary

**Branch**: `016-narrow-field-choices` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/016-narrow-field-choices/spec.md`

## Summary

Both concept fields gain three mutually exclusive arguments — `collection`, `concepts`, `branch` —
that narrow choices inside the one vocabulary a declaration names. Research R1 found that all four
enforcement paths (model validation, form choices, this package's widget, this package's search
endpoint) already read the same method, `get_limit_choices_to()`, and R2 found that Django resolves
a **callable** `limit_choices_to` at every one of them. So the feature is delivered by changing what
that attribute holds, not by teaching four call sites about collections and hierarchies.

Each restriction resolves to `Q(pk__in=<queryset of concept ids>)` — a subquery rather than a join,
because this package's own two paths call `complex_filter()` bare where Django wraps it in
`Exists()` (R3), so a join-shaped `Q` would duplicate rows in exactly the places our own tests
cover. The three axes then differ only in how the inner queryset is built: a membership lookup, a
slug list, and an iterative downward widening over the stored `broader` edges that terminates when a
level adds nothing new (R5) — which is where FR-004's cyclic-graph guarantee comes from, rather than
from a separate cycle check.

Two places do not fall out of that seam and are the plan's real work: the many-valued field enforces
writes through an `m2m_changed` receiver that tests the vocabulary directly and never consults
`limit_choices_to` (R4), and an ordered collection's sequence cannot travel through a filter at all,
so it is applied in the widget's queryset and nowhere else (R6).

## Technical Context

**Language/Version**: Python 3.11+ per Article X; the resolved development environment is 3.14

**Primary Dependencies**: Django 5.2 LTS and 6.0; `django-tomselect` 2026.6.2 (already a runtime
dependency — this feature adds none)

**Storage**: The project's own database. SQLite in the test suite and the demo; PostgreSQL in
deployment. No new tables, no new columns, no migration to this package's own models.

**Testing**: pytest + pytest-django + factory_boy from `mvp-shared[test]`; suite mirrors the source
tree per testing standard §4

**Target Platform**: A Django project installing this package

**Project Type**: Reusable Django package

**Performance Goals**: None set for this feature, deliberately. A branch restriction costs one query
per level of hierarchy depth **per resolution**, not once per declaration — the callable is
re-resolved on every autocomplete request, on every widget render and at every validation. The
autocomplete endpoint allows anonymous access (`views.py:42`), so that work is reachable without
authentication and repeats per keystroke. Making the closure one query is R7 work and is out of
scope by the spec's own Assumptions; R7 inherits the repetition as well as the depth.

**Constraints**: No database query while a declaration is read (FR-007). No new runtime dependency.
No change in meaning for any declaration that exists today (FR-014).

**Scale/Scope**: Four source files (`fields.py`, `views.py`, `checks.py`, `apps.py`), their mirrored
test modules, the README and `CONTEXT.md`. Plus the test app: every restriction is a declaration
argument, so each axis needs a consuming model in `tests/testapp/models.py` and therefore a test-app
migration, exactly as each prior feature added one. No change to this package's own models, and so
no migration under `controlled_vocabularies/migrations/`.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after the design below.*

| Article | Bearing on this feature | Verdict |
|---|---|---|
| I — Test-First | Every task writes its failing test first. No pre-existing test is modified: the feature is additive and FR-014 says so. | Pass |
| II — Simplicity | The design adds one concept (a restriction resolving to a subquery) and reuses the existing seam for all three axes. Iterative closure chosen over raw recursive SQL precisely because the optimisation is speculative (R5). | Pass |
| III — Anti-Abstraction | The three axes share one resolution point on the existing `ConceptFieldMixin` rather than gaining a class hierarchy of restriction types. There is no second implementation to generalise for. | Pass |
| IV — Integration-First | The contract is the declaration a consumer writes; acceptance scenarios exercise it through a real consuming model, a real form and a real endpoint. | Pass |
| V — Security & data-safety | No new external input, no rendering path, no auth surface. Slugs from a declaration reach the ORM as parameters, never string-interpolated SQL. | Pass |
| VI — Documentation | README, `CONTEXT.md` and CHANGELOG ship in this PR as US-7. | Pass |
| VII — Dependency discipline | No new dependency. | Pass |
| VIII — Dual compatibility contract | Additive: every existing declaration keeps its meaning (FR-014). No published URI or serialization is touched. | Pass |
| IX — URI identity & data safety | Unchanged. The delete protection and the through model's `PROTECT` are untouched. | Pass |
| X — Stack & architecture | No raw SQL, no backend-specific construct (R5). Models stay the source of truth. | Pass |
| XII — Internationalization | Curator-facing refusal messages are translated with named placeholders. The two declaration rules raise `TypeError`, which the article exempts as a developer-facing diagnostic — and which every existing refusal in `fields.py` already is (R7). | Pass |
| XI — RDF fidelity | Does not bear. A restriction narrows what a *consuming project's* field accepts. No vocabulary content, no published URI and no serialization changes, so nothing round-trips differently. | Pass |
| XIII — Data-model conventions | No field added to this package's models, so no indexing decision and no migration of its own. The test app gains consuming models and one migration, consolidated to a single file before the PR as the article requires. The queries the restrictions issue ride existing indexes: `unique_collection_member` and `cv_collection_member_order_idx` for membership, the auto-indexed FKs on `ConceptRelation` for the closure. | Pass |
| XIV — Test structure | New tests land in the existing `tests/test_fields.py`, `tests/test_forms.py`, `tests/test_checks.py` as new `Test<Subject>` classes. No new factories: `CollectionFactory` and `ConceptRelation` helpers already exist. | Pass |
| XV — Cohesion | Restriction resolution is a small group of related behaviours sharing a subject, so it lives on `ConceptFieldMixin` beside `_normalise_vocabulary`/`_apply_vocabulary` rather than as loose module functions. | Pass |

No violations. Complexity Tracking below is therefore empty.

## Project Structure

### Documentation (this feature)

```text
specs/016-narrow-field-choices/
├── spec.md              # signed off 2026-08-25
├── decisions.md         # D1–D7 from S1, grows through the run
├── research.md          # Phase 0 — R1–R8
├── plan.md              # this file
├── progress.md          # stage/gate log
├── tasks.md             # Phase 2
└── feature-state.json   # ledger
```

No `data-model.md`: this feature adds no model, no field and no migration. No `contracts/`: the
contract is a Python declaration, specified in `spec.md` and documented in the README.

### Source Code (repository root)

```text
controlled_vocabularies/
├── fields.py       # ConceptFieldMixin: accept, validate and resolve the three restrictions;
│                   # deconstruct them; make the m2m receiver restriction-aware
├── views.py        # ConceptAutocompleteView.apply_ordering(): ordered-collection sequence
├── checks.py       # new W005 — a restriction naming an absent target
└── apps.py         # register the new check

tests/
├── test_fields.py  # declaration rules, resolution, enforcement, deconstruct
├── test_forms.py   # the choices a form and the widget carry
├── test_views.py   # the choices the endpoint serves, and their order
├── test_checks.py  # W005
└── testapp/
    ├── models.py       # one consuming model per restriction axis
    └── migrations/     # their table, consolidated to one file before the PR

README.md · CONTEXT.md · CHANGELOG.md
```

**Structure Decision**: the existing package layout, unchanged. This feature adds no module, because
every change belongs beside behaviour that already exists in one of the four files above. A separate
`restrictions.py` was considered and rejected under Article III — it would be a new module holding
one function used by one class.

## Design

### A1 — What a declaration accepts

`ConceptFieldMixin` gains the argument handling, so both fields inherit one contract exactly as they
already do for `vocabulary` (`fields.py:29-50` states the reason: leaving each class to implement it
separately is what let them drift apart the first time).

- `collection: str | None`, `concepts: list[str] | None`, `branch: str | None`, all defaulting to
  `None`, all naming their target by slug within the declaration's one vocabulary.
- Each slug is validated by the same rule `_normalise_vocabulary` already applies — a non-empty
  string — and refused with `TypeError` otherwise. `concepts` additionally collapses duplicates
  (FR-003) with `dict.fromkeys`, the existing idiom, and refuses an empty list.
- **FR-005:** any restriction present with `len(self.vocabulary) != 1` raises `TypeError`. This is
  checked after `_normalise_vocabulary` has run, so both "several" and "none" are one condition.
- **FR-006:** more than one restriction present raises `TypeError`.

Both refusals are raised from `_apply_vocabulary`'s neighbourhood, where `limit_choices_to` is
already refused, so a reader finds every declaration rule in one place.

### A2 — What a restriction resolves to

One method on the mixin returns the `Q` for the field's current restriction, or the existing
vocabulary-only `Q` when there is none. It is installed as `limit_choices_to` **as a callable**
(R2), so it is never invoked while the declaration is read (FR-007) and is re-resolved at each of the
four paths in R1 — which is what makes FR-002 and FR-004's "resolved live" true without a cache to
invalidate.

Shape, uniform across the three axes (R3):

| Restriction | Inner queryset |
|---|---|
| `collection` | `CollectionMember.objects.filter(collection__slug=…, collection__scheme__slug=…).values("concept")` |
| `concepts` | not a subquery — `Q(scheme__slug=…, slug__in=…)`, which needs no join and cannot duplicate |
| `branch` | the closure from A3, as `values("pk")` or an id list |

Every form is `Q(scheme__slug=<the one vocabulary>) & <the narrower term>`, so the vocabulary
restriction is never weakened by the narrower one — a concept outside the vocabulary stays refused
even if some other vocabulary's collection happens to share a slug.

An unresolvable target — a collection slug matching nothing — yields a `Q` matching nothing, so the
field offers nothing and refuses everything. That is the silent state US-5's check exists to report;
it is deliberately not an exception, per FR-007.

### A3 — The branch closure

Iterative widening over the stored `broader` edges (R5):

1. Start with the named root's id, resolved within the declaration's vocabulary.
2. Repeatedly select `ConceptRelation.objects.filter(kind=BROADER, target_id__in=<frontier>)`,
   taking `source_id` as the next frontier, minus everything already seen.
3. Stop when a round adds nothing.

Termination on a cyclic graph is a property of step 3, not a separate guard (FR-004, SC-006). A root
that does not exist yields the empty set, which is A2's unresolvable case.

Confined to one function, so R7 can replace it with a single recursive statement later without
anything downstream noticing (R5).

### A4 — The many-valued field's write guard

`_refuse_concepts_outside_vocabulary` (`fields.py:376-422`) is the one enforcement path that does not
read `limit_choices_to` (R4). Both its branches are re-expressed against the resolved restriction:

- forward — the incoming concepts are the ones in `pk_set`; refuse any that the restriction's
  queryset does not contain.
- reverse — the single incoming concept is `instance`; refuse it on the same test.

The receiver is bound with the field itself rather than with `vocabulary`, so one resolution serves
both branches and they cannot drift. The `if self.vocabulary` guard at binding time
(`fields.py:607`) stays exactly as it is: a restriction implies exactly one vocabulary (FR-005), so
it is already true whenever a restriction exists, and leaving it alone preserves the `bulk_create`
fast path for unrestricted fields (FS-010 R6).

The refusal message names what the field is restricted to. Article XII means one static msgid per
message with the restriction joined into a single named placeholder — the pattern
`fields.py:210-220` and `fields.py:412-422` already use for the vocabulary list, for the same
reason.

### A5 — Ordering

`ConceptAutocompleteView.apply_ordering()` overrides the base method
(`django_tomselect/autocompletes.py:686-727`) and applies the collection's member order when, and
only when, both hold: the field's restriction is a collection the curator marked `ordered`, and the
request carries no search term. Anything else falls through to `super()` and the inherited
`("label", "pk")`. The declaration is already resolved on that request by `_restrict_to_declaration`
(`views.py:105-116`), so nothing new has to be plumbed through.

This is the browsable list — the widget's own queryset is not (R6). `forms.py` is not changed by
this story.

**The position is a `Subquery` annotation, never a join.** `CollectionMember.concept` carries
`related_name="collection_memberships"` and a concept may belong to several collections, so ordering
through `collection_memberships__position` duplicates rows for any concept with a second membership.
The annotation is `Subquery(CollectionMember.objects.filter(concept=OuterRef("pk"),
collection__slug=<declared>, collection__scheme__slug=<declared>).values("position")[:1])`, and the
ordering is on that annotation. Its tests assert no duplicate rows by count, matching the assertion
US-1 already carries.

### A6 — The system check

A new function beside `check_concept_field_vocabularies`, emitting `controlled_vocabularies.W005`,
registered in `apps.ready()` alongside the existing four. New id rather than reusing W001, because a
project silences by id and the two decisions are independent (R8). Same batching, same
`DatabaseError` guard, same reasoning. It reports the specific absent target — the one missing member
of a ten-item `concepts` list, not the list (FR-009).

### A7 — Migrations

`ConceptFieldMixin.deconstruct()` (`fields.py:145-170`) already pops `limit_choices_to`
unconditionally, which is what keeps a callable out of the emitted kwargs. It gains the three new
arguments, emitted only when set, so an existing declaration's migration output is byte-identical
(FR-011, FR-014). `Field.clone()` runs on every `makemigrations`, `migrate` and test-database build,
so this is exercised constantly rather than only by a dedicated test — but it gets a dedicated test
anyway, because the failure mode is a rebuild that raises on kwargs `__init__` refuses.

## Story sequencing

US-4 (the declaration rules) is foundational: it owns argument acceptance, and the other two P1
stories are the resolution behind arguments it defines. It is implemented first, sequentially, and
the three that follow are independent of each other.

| Order | Story | Depends on | Note |
|---|---|---|---|
| 1 | US-4 declaration rules | — | Foundational: A1 and A7. No restriction resolves before this exists. |
| 2 | US-1 collection | US-4 | A2's simplest axis; carries the m2m guard rework (A4) that US-2 and US-3 then reuse. |
| 3 | US-2 concepts list | US-4, US-1 | Smallest increment; the only axis needing no subquery. |
| 4 | US-3 branch | US-4, US-1 | A3. The largest single piece of new logic. |
| 5 | US-5 absent targets | US-1..3 | A6. Needs all three target kinds to exist to report them. |
| 6 | US-6 ordered sequence | US-1 | A5. Droppable — one method override in `views.py`, no other story depends on it. |
| 7 | US-7 docs and messages | all | Documents the delivered surface, so it goes last. |

Stories 2 and 3 in this order both touch `fields.py`; they run sequentially in one checkout rather
than as parallel worktrees, because a shared test database and a shared file are exactly the
conditions that make fan-out cost more than it saves.

## Complexity Tracking

No Constitution Check violations. Nothing to justify.
