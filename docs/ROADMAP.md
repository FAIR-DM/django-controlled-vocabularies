# Roadmap: django-controlled-vocabularies

**Date:** 2026-08-11

This document was designed against [GOALS.md](../GOALS.md). See also [CONTEXT.md](../CONTEXT.md) for
domain terminology and [CONSTITUTION.md](../CONSTITUTION.md) for project standards.

## Versioning

Releases are gated on goal importance, not on a fixed count of features.

| Version | Gate | Meaning |
|---|---|---|
| `0.0.x` | building toward the Essential goals | pre-viable; expect churn; git-pin only, nothing on PyPI |
| `0.1.0` | all Essential goals delivered | the minimum usable release; first PyPI publish |
| `0.1.x` to `0.x` | Expected goals, at whatever granularity the work takes | each advances one or more Expected goals; patches are fixes |
| `1.0.0` | all Expected goals delivered | the complete, dependable release |
| `1.x` | stable line | non-breaking fixes and additive features only |
| `2.0` | next major | breaking changes |

Aspirational goals may be developed against v2 or v1 as required.

Two rules this table encodes. A goal does not equal a minor release: some goals take several
minors, and one minor can move two goals. And once `1.0` ships, a breaking change cannot go out as
`1.x`; it waits for the next major, because a consumer pinned to `>=1,<2` is trusting that it will
not break.

`v0.1.0` was published on 2026-08-26. The per-item marks below have not been reconciled against
what that release actually contains: R3's consumption field and R6's browsing pages have both
shipped without being marked, while R4's RDF publishing and R5's management interface have not
shipped at all — so the release went out ahead of the gate this table sets for it. Reconciling the
two is its own piece of work.

## Essential goals: v0.1.0

Everything needed to reach a minimum usable release.

### R1 — Core domain foundation

*Large, expect several stories · advances the foundation, and G6 directly.* **Delivered.**

Nothing else can be built until the system can represent a vocabulary and everything inside it, so
this goes first. It shipped as four features:

- a vocabulary and its concepts
  ([#15](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/15));
- multilingual labels and notes
  ([#16](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/16));
- the relationship graph
  ([#17](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/17));
- collections
  ([#18](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/18)).

**Deliverables:**

- models for concept schemes, concepts, collections, labels, and concept relationships;
- creation and querying through the ORM;
- stable identity for concepts;
- tests covering the identity and safety behaviour.

Two items were written into R1 at the start and moved out while it was being built.

The Django admin moved to R5. All four features deferred every admin and editor surface, because a
curator-facing interface is one coherent piece of work, and building a quarter of it against each
model in turn produces something nobody would want to keep.

The concept lifecycle moved to R4
([#19](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/19), closed as
deferred rather than rejected). A concept only becomes unsafe to remove once the vocabulary holding
it has been published, and publication is a vocabulary-level release event that arrives with R4.
Until something can reference a concept, a delete guard defends against a harm that cannot happen.

Serves the foundation and G6. Out of scope: RDF import and export, the consumption field, the
served URLs, and the editing interface.

### R2 — RDF import

*Full feature · advances G4, and G8, G6.* **Delivered.**

Import is the only way to get real vocabularies into the system: the heat-flow vocabularies already
published as Turtle, large external sets, and whatever a curator starts from. Until it existed,
nothing downstream could be tested against real data. It shipped as four features:

- concepts keeping the identifier they were published under
  ([#49](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/49));
- importing a published SKOS vocabulary from a file, in any of Turtle, RDF/XML, or JSON-LD
  ([#50](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/50));
- keeping the languages the site supports and reporting the rest
  ([#51](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/51));
- running an import from the command line
  ([#52](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/52)).

**Deliverables:**

- reading vocabularies from Turtle, RDF/XML, and JSON-LD into the models;
- a re-runnable, safe import that upserts rather than delete-and-recreates;
- external vocabularies normalised to the app's configured languages, with what was set aside
  reported to the user, and an additive re-import that fills in newly added languages;
- both a management command and a programmatic entry point.

Serves G4, G8, and G6. Out of scope: export and serving, the consumption field, the editing
interface.

### R3 — Concept consumption field

*Full feature · advances G2.*

This is what the whole package was built for: letting a Django project attach controlled-vocabulary
concepts to its own models as first-class data. It depends on R1, and with R2 delivered there are
now real imported vocabularies to build and test the field against, rather than only fixtures.

**Deliverables:**

- a field (single and multiple) that attaches concepts from a chosen vocabulary to a consumer's
  model;
- autocomplete-backed selection in forms and the Django admin;
- referential integrity, so a referenced concept cannot silently disappear;
- the concept's label and identity reachable from the consuming record.

Serves G2. Out of scope: import, export and serving, the editing interface.

### R5 — Vocabulary management interface

*Large, multi-feature · advances G1.*

The graphical, code-free way for curators to create, edit, and delete vocabularies and concepts. It
is the last Essential goal, so `0.1.0` cannot ship without it. It comes after the consume items
because it needs the domain in place, and it comes before publishing: there is nothing to publish
until a vocabulary can be authored here.

**Deliverables:**

- create and edit schemes, concepts, and collections through the UI;
- edit labels and notes per language;
- manage hierarchy and relationships between concepts.

A fuller brief gets written when it reaches the front of the queue.

### R4 — RDF publishing and stable URIs

*Full feature · advances G3, and G4.*

This follows the management interface: publishing a vocabulary, and freezing its concept URIs,
means something only once a vocabulary can be authored here rather than only imported. It closes
the consume loop and makes the stable-URI promise real: a published concept URI has to resolve to
standards-compliant RDF. The details belong in this feature's own spec.

It also absorbs the concept lifecycle deferred out of R1. Publishing a vocabulary and freezing its
concept URIs are the same moment, so the rules that protect a published concept belong here rather
than in the foundation. Until a vocabulary can be published, a curator simply deletes a concept
instead.

**Deliverables:**

- vocabulary publication as a deliberate, one-way release, after which a concept is retired by
  deprecation instead of deletion;
- concept and scheme URLs that resolve to valid SKOS in Turtle and at least one other
  serialization, chosen by content negotiation;
- a human-readable response alongside the machine ones;
- a vocabulary exported this way that re-imports cleanly.

Serves G3 and G4. Out of scope: the editing interface, browsing external sources.

## Expected goals: v1.0.0

Anything that advances toward the v1.0.0 release.

### R6 — Vocabulary browsing

*Full feature · advances G7.* A read-only way for people to search and move around concepts, across
both local vocabularies and imported external ones, so a stable URI leads somewhere a person can
use.

### R7 — Scale hardening

*Full feature · advances G5.* Keep search, browse, and autocomplete responsive at tens of thousands
of concepts, and support navigation over deep hierarchies.

### R8 — Embeddable and standalone modes

*Full feature · advances G9.* Make the app a good guest inside a host Django project, and, with a
thin wrapper, a system that runs on its own.

### R9 — Adopt the heat-flow vocabularies as first real content

*Small to medium · advances G10.* Move the existing heat-flow vocabularies onto this app as the
first production content, exercising the manage, consume, and publish loop on a real dataset.

## Aspirational goals: v2.0

Bigger bets, taken on once the 1.x line is stable.

### R10 — Collaborative curation

*Draft · large · advances G11.* Several curators working the same vocabularies under object-level
permissions.

### R11 — Vocabulary versioning

*Draft · large · advances G12.* Track versions of a vocabulary as it changes so a consumer can cite
the version it used.
