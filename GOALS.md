# GOALS — django-controlled-vocabularies

Enduring goals this project pursues. Identity lives in the README; when work happens and which
release delivers it lives in the roadmap — this file names no versions. A goal is a capability
or quality you steer toward, not a task you complete: its id is stable, its importance is a tag
that can change, and whether it has been addressed enough is judged through the roadmap, specs,
and review rather than the goal itself.

**Importance** — `Essential`: not worth adopting without it · `Expected`: a complete,
dependable version is expected to have it · `Aspirational`: a genuine want whose absence never
makes the package incomplete.

**Status** — unmarked means accepted and live · `draft`: captured, not yet refined ·
`rejected`: decided against, kept with a reason and an ADR link when it's a design stance.

| ID | Goal | Importance | Status | Notes |
|----|------|------------|--------|-------|
| G1 | **Code-free vocabulary management** — create, edit, and deprecate vocabularies and concepts through a web interface, without writing code. | Aspirational | | Set aside until a project needs to author its own vocabularies. The package's job is importing and referencing published ones. |
| G2 | **One-field consumption** — attach concepts to any Django model through a single field, so a vocabulary evolves as data rather than a code release of every consumer. | Essential | | |
| G3 | **Standards-compliant publishing** — serve valid SKOS/RDF at stable, permanent concept URIs, with content negotiation. | Aspirational | | |
| G4 | **Faithful round-trip of managed vocabularies** — vocabularies you author and manage here export as complete, valid SKOS, with nothing lost. | Aspirational | | |
| G5 | **Scale to large vocabularies** — tens of thousands of concepts stay responsive to search, browse, and autocomplete. | Expected | | |
| G6 | **Multilingual concepts** — labels and definitions carry per-language values, editable one language at a time. | Expected | | |
| G7 | **Vocabulary browsing** — a human-facing interface to search and navigate concepts, across both locally managed and external vocabularies. | Expected | | |
| G8 | **External vocabularies as read-only references** — import pre-published vocabularies to browse and consume without editing them. | Essential | | |
| G9 | **Embeddable and standalone** — usable both installed into an existing Django project and run as a standalone system. | Expected | | |
| G10 | **Real adoption** — the FairDM ecosystem and its heat-flow vocabularies rely on it instead of bespoke vocabulary code. | Expected | | |
| G11 | **Collaborative curation** — multiple curators work under object-level permissions. | Aspirational | draft | 2026-07-22 — single-team use works via ordinary Django auth; genuine multi-curator collaboration is the want. |
| G12 | **Vocabulary versioning** — track versions of a vocabulary as it evolves, so consumers can cite the version they used. | Aspirational | draft | 2026-07-22 — matters for research reproducibility; heavyweight, not yet designed. |

_Written 2026-07-22. Revise as the goals change._
