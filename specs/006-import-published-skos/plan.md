# Implementation Plan: Import a published SKOS vocabulary from a file

**Branch**: `006-import-published-skos` | **Date**: 2026-08-03 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `specs/006-import-published-skos/spec.md`

## Summary

A published SKOS file becomes records. One new module reads a file into an rdflib graph, walks it
in a fixed order — vocabulary, concepts, labels and notes, relationships, collections — and writes
through the model helpers R1 built, matching every record by the identifier its publisher assigned
via the `get_by_uri` lookup #49 added for exactly this. The whole run sits inside one transaction
and returns a structured report; anything unstorable becomes a report entry rather than an
exception, and the small set of fatal findings rolls the transaction back at the end rather than
raising at the first.

No new models. Two new runtime dependencies: `rdflib`, which the RDF boundary has always been
planned around, and `defusedxml`, which closes an entity-expansion route into RDF/XML parsing that
was measured rather than assumed (`research.md` R3).

## Technical Context

**Language/Version**: Python 3.11+ (package floor), tested on 3.12 and 3.13

**Primary Dependencies**: Django ≥5.2; **rdflib 7.6** (new — the RDF parsing boundary);
**defusedxml 0.7** (new — pre-flight scan of RDF/XML against entity expansion)

**Storage**: the existing relational models — `ConceptScheme`, `Concept`, `ConceptLabel`,
`ConceptNote`, `ConceptRelation`, `Collection`, `CollectionMember`. **No migration.**

**Testing**: pytest + pytest-django; fixture vocabulary files on disk under `tests/fixtures/`

**Target Platform**: any Django project installing this app; also the standalone runner

**Project Type**: installable Django app (library)

**Performance Goals**: none set. The reading strategy must not preclude tens of thousands of
concepts (G5), which rules out anything quadratic in concept count, but no throughput target is
specified or tested (spec Assumptions).

**Constraints**: imported RDF is untrusted (Article V). A run is atomic (FR-003). Writes go
through the model helpers so the models' own validation applies (`research.md` R5).

**Scale/Scope**: one new module tree, six stories, no schema change.

## Constitution Check

| Article | Status | Note |
|---|---|---|
| I — Test-First | Pass | Every task below is a test-first pair; the fixture files land before the reader that consumes them. |
| II — Simplicity | Pass, with two dependencies justified in Complexity Tracking | No abstraction layer over rdflib, no plugin registry for serializations, no predicate-registry machinery — the mapping is a module-level table (`research.md` R4). |
| III — Anti-Abstraction | Pass | One reader, one report type. No base class per serialization: rdflib already abstracts the three formats behind one `parse` call. |
| IV — Integration-First | Pass | The report *is* the contract #51 and #52 consume, so it is designed and tested before the reader's internals are polished. Acceptance scenarios drive from a real file on disk, the way a curator touches it. |
| V — Security & data-safety | **Pass, and the reason for a dependency** | Imported RDF is named untrusted by this article. External entities were probed and are not resolved; internal entity expansion was probed and **is** — 781kB from a 400-byte file. Closed by the defusedxml pre-flight scan (`research.md` R3). |
| VI — Documentation | Pass | README gains the import surface, CHANGELOG entry, docstrings on the public callable and the report. |
| VII — Dependency discipline | Pass | Both dependencies are declared in this PR, alongside the code importing them, per the standing note in `pyproject.toml`. `deptry` covers the rest. |
| VIII — Compatibility | Pass | Purely additive to the Python API. No published URI or serialization changes — this feature reads, it does not publish. |
| IX — URI identity | **Central** | Upsert by URI, never delete-and-recreate; no migration touches identity; identifiers are never rewritten by a re-import. FR-004 and FR-013 restate the article's own words. |
| X — Stack & architecture | Pass | Models stay the source of truth; RDF is read only at this boundary and never stored as a graph. SKOS-only, with everything else set aside. |
| XI — RDF fidelity | **Partial, deliberately, and recorded** | The escrow clause is **not** met: unknown predicates are reported, not stored verbatim. Deferred with the maintainer's agreement to a feature sequenced with export (decisions.md D1). Normalisation is surfaced, never silent (FR-009). Re-import is additive and upserts by URI. |
| XII — i18n | Pass | Every failure and report message translatable with named placeholders (FR-016). |
| XIII — Data-model conventions | Not applicable | No model fields added, so no indexing decision and no migration. Stated rather than skipped, since every prior feature in this repo carried one. |

**Article XI is the one entry that is not a clean pass, and it is deliberate.** It is recorded in
`decisions.md` D1, was surfaced at the Spec gate, and must not be described as satisfied anywhere
this feature ships.

## Project Structure

### Documentation (this feature)

```
specs/006-import-published-skos/
├── spec.md              # the specification (S1)
├── decisions.md         # self-resolved decisions and rationale (S1, extended here)
├── research.md          # rdflib behaviour, the security probe, the SKOS mapping (S3)
├── plan.md              # this file
└── tasks.md             # the task graph (S3)
```

### Source Code (repository root)

```
controlled_vocabularies/
├── models.py            # unchanged
├── conf.py              # unchanged
└── exchange/            # new
    ├── __init__.py      # public surface: import_skos(), ImportReport
    ├── skos.py          # the reader: graph -> records
    ├── mapping.py       # SKOS predicate -> model mapping table (research.md R4)
    ├── report.py        # ImportReport, SetAsideEntry, outcome kinds
    └── safety.py        # pre-flight scan of untrusted RDF/XML (research.md R3)

tests/
├── test_exchange/       # mirrors the source tree (testing-structure standard)
│   ├── test_skos.py
│   ├── test_report.py
│   └── test_safety.py
└── fixtures/            # published vocabularies as files
    ├── rock.ttl
    ├── rock.rdf
    ├── rock.jsonld
    └── …                # edited copies for the re-import scenarios
```

**Structure Decision**: a package (`exchange/`) rather than a single module, because the report is a
public type that #51 and #52 import, and the safety scan is independently testable. The public
surface is re-exported from `exchange/__init__.py` so consumers import one name.

## Complexity Tracking

| Addition | Why it is justified | Alternative rejected |
|---|---|---|
| **rdflib** runtime dependency | Reading three RDF serializations correctly is not something to hand-roll; the package has always been designed around rdflib at the import/export boundary (Article X, `docs/brainstorm.md`), and `pyproject.toml` already reserves its declaration for the code that imports it. | Writing three parsers. Not seriously considered. |
| **defusedxml** runtime dependency | A measured memory-exhaustion route through RDF/XML entity expansion, reachable by any deployment that lets a curator supply a file (`research.md` R3). Article V names imported RDF untrusted. | Refusing every document with a DTD — rejected, it also refuses legitimate namespace-entity files. Capping file size — rejected, the amplification starts small. |
| **`exchange/` package rather than one module** | The report is a public type two other features consume, and the safety scan is separately testable. Four small modules with one job each. | One `importers.py`. Rejected: it would put a public contract, a security control, and a long graph walk in one file. |

Nothing else here adds an abstraction. There is no serialization plugin layer, no predicate
registry (the mapping is a dict), and no importer base class — rdflib already hides the format
differences behind one call, and a second RDF-shaped source does not exist to generalise against
(Article III).
