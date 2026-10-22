# Implementation Plan: Concepts keep the identifier they were published under

**Branch**: `005-concepts-keep-identifier` | **Date**: 2026-08-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-concepts-keep-identifier/spec.md`

## Summary

Split the one address `ConceptScheme`, `Concept`, and `Collection` carry today into identity and
location. Each model gains a single nullable stored column holding an **externally assigned**
identifier, plus two accessors: `uri` (unchanged name, now meaning the static URI — the stored value
when present, the R1 composition otherwise) and `local_url` (always the R1 composition, this site's own
address). Fixedness is the presence of the stored value, not a separate flag (research R2). Uniqueness
is a per-model `UniqueConstraint` on the column plus a cross-model validation check, because no
portable database constraint spans three tables (research R4). Validation refuses anything that is not
an absolute URI with a scheme, refuses `javascript`/`data`/`vbscript`, and caps length at 500
characters, running on both the field validators and `save()` because Django's `save()` never calls
`full_clean()` (research R5). Lookup by identifier queries the stored column first and falls back to
R1's base-relative parse, shared across the three managers by one mixin so the import work in #50 can
resolve schemes and collections too (research R6).

The upgrade needs **no data migration and no backfill**: a pre-existing row simply has no stored value,
so it composes exactly what it composed before. That satisfies FR-009 and Article IX by construction.
One migration adds three nullable columns and three constraints. No routes, no views, no UI.

## Technical Context

**Language/Version**: package runtime floor Python 3.11 (Art. X); dev/test toolchain (`mvp-shared[test]`)
needs 3.12+, so CI exercises 3.12/3.13 (unchanged from #15–#18).

**Primary Dependencies**: Django 5.2 LTS + 6.0. **No new runtime dependency.** Identifier validation uses
`urllib.parse` from the standard library rather than Django's `URLValidator`, which is built for
`http`/`https`/`ftp` and would reject the `urn:` identifiers real vocabularies use (research R5).
`rdflib` belongs to import and export (#50, R4) and would fail `deptry` as an unused dependency here.

**Storage**: host project's relational database via the Django ORM; one nullable column and one unique
constraint per existing model, one migration, no data migration.

**Testing**: `pytest` + `pytest-django`; `factory_boy` factories mirroring the source tree per the family
testing standard (`tests/factories.py`, `tests/test_models.py`, `tests/test_factories.py`,
`tests/test_standards.py`).

**Target Platform**: an installable Django app (also runnable standalone).

**Project Type**: single project — a reusable Django app package.

**Performance Goals**: none specific to this slice. Lookup of an externally assigned identifier is an
indexed equality match; lookup of a provisional one keeps R1's slug-based resolution. Both are
single-row reads with no traversal.

**Constraints**: the published `uri` accessor and the existing lookup keep their names and meanings
(FR-014); an externally assigned identifier is never recomputed or normalised (FR-002); fixedness never
reverses (FR-013); validation must hold on the `save()` path, not only `full_clean()`; every new field
carries translatable label and help text and every refusal message uses named placeholders (FR-010);
existing rows must report unchanged identifiers after the upgrade (FR-009).

**Scale/Scope**: three nullable columns, three unique constraints, two accessors per model, one manager
mixin, one migration, factory support, tests. No UI, no routes, no new models.

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design (unchanged).*

- **I Test-First** — tasks order the failing test before its implementation in every story phase. Pass.
- **IX URI identity and downstream-data safety** — this feature advances the article directly: identity
  moves from "always composed" to "the publisher's when there is one", so upsert-by-URI becomes
  satisfiable for external content for the first time. No deletion semantics change. Migrations preserve
  every existing identifier by construction, because there is no backfill to get wrong. Pass.
- **X Stack and architecture norms** — no new dependency, models stay the source of truth, nothing here
  touches RDF. Pass.
- **XI RDF fidelity** — untouched: import normalisation and export are #50 and R4. This feature only makes
  the identity they depend on storable. Pass.
- **XII Internationalization** — new field labels, help text, and every refusal message are lazily
  translatable with named placeholders (US-5). Pass.
- **XIII Deliberate indexing** — the stored identifier column is the lookup column and is indexed by its
  unique constraint; the decision is recorded in `data-model.md`. Pass.

## Project Structure

### Documentation (this feature)

```
specs/005-concepts-keep-identifier/
├── spec.md
├── decisions.md
├── research.md
├── data-model.md
├── contracts/python-api.md
├── quickstart.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```
controlled_vocabularies/
├── conf.py               # unchanged — still the single read site for the base address
├── models.py             # + stored column, uri/local_url accessors, validation, manager mixin
└── migrations/
    └── 0005_*.py         # three nullable columns + three unique constraints
tests/
├── factories.py          # + externally assigned identifier support
├── test_models.py        # identity, lookup, provisional composition, local URLs
├── test_factories.py
└── test_standards.py     # field metadata + indexing walk covers the new columns
```

## Complexity Tracking

| Choice | Simpler option rejected | Why the simpler option loses |
|---|---|---|
| Per-model unique constraint plus a cross-model validation check | A shared `Identifier` table giving true cross-table uniqueness | The shared table costs a join on every identity read, a third table in every fixture, and a data-moving migration to undo. It prevents a collision that needs one source file to give a concept and a collection the same identifier. Revisit when a real vocabulary produces one. |
| Stored column holds external identifiers only, provisional ones compose on read | One always-populated column, re-synced on save | Fails FR-005's configured-address clause, because already-saved rows keep the old address until something touches them. It also adds a second source of truth for a derivable value, plus a resync command nobody asked for. |
| Validation on both the field validators and in `save()` | Field validators alone | Django's `save()` never calls `full_clean()`, so field-only validation leaves the import path unprotected — the one path this feature exists to serve. The R1 slug work hit exactly this. |
| Hand-rolled scheme and length checks via `urllib.parse` | Django's `URLValidator` | `URLValidator` rejects the `urn:` identifiers real published vocabularies use, and permits the script-bearing schemes this feature must refuse. |
