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

`v0.1.0` was published on 2026-08-26. Of the two Essential goals it delivers G2 through R3's
consumption field, and G8 through R2's import, short of one deliverable: a site's declared
vocabularies, loaded by one command. It also carries R6's browsing pages, which advance an Expected
goal.

## Essential goals: v0.1.0

Everything needed to reach a minimum usable release.

### R1 — Core domain foundation

*delivered in [#15](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/15), [#16](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/16), [#17](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/17), [#18](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/18) · advances the foundation, and G6 directly.*

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

- models for vocabularies and the records they hold, with every statement kept in a JSON document;
- creation and querying through the ORM;
- stable identity for concepts;
- tests covering the identity and safety behaviour.

Two items were written into R1 at the start and moved out while it was being built.

The Django admin moved to R5. All four features deferred every admin and editor surface, because a
curator-facing interface is one coherent piece of work, and building a quarter of it against each
model in turn produces something nobody would want to keep.

The concept lifecycle was deferred
([#19](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/19)) and has since been
dropped. A concept is deprecated when its publisher says so, and a concept a record references
cannot be deleted.

Serves the foundation and G6. Out of scope: RDF import and export, the consumption field, the
served URLs, and the editing interface.

### R2 — RDF import

*partly delivered in [#49](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/49), [#50](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/50), [#51](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/51), [#52](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/52) · advances G8, and G6.*

Import is the only way to get real vocabularies into the system: the heat-flow vocabularies already
published as Turtle, large external sets, and whatever a curator starts from. Until it existed,
nothing downstream could be tested against real data. It shipped as four features:

- concepts keeping the identifier they were published under
  ([#49](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/49));
- importing a published SKOS vocabulary from a file, in any of Turtle, RDF/XML, or JSON-LD
  ([#50](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/50));
- keeping every statement a file makes, in every language
  ([#51](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/51));
- running an import from the command line
  ([#52](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/52)).

**Deliverables:**

- reading vocabularies from Turtle, RDF/XML, and JSON-LD into the models;
- a re-runnable, safe import that upserts rather than delete-and-recreates;
- every statement a published file makes kept as published, in every language, including notations,
  mappings to other vocabularies and statements outside SKOS, stored as one JSON document per
  vocabulary and per record
  ([#219](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/219));
- both a management command and a programmatic entry point;
- not yet delivered: the vocabularies a site declares, loaded by one command
  ([#221](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/221)).

Serves G8 and G6. Out of scope: export and serving, the consumption field, the editing
interface.

### R3 — Concept consumption field

*partly delivered in [#86](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/86), [#87](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/87), [#88](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/88), [#89](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/89), [#111](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/111), [#164](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/164) · advances G2.*

This is what the whole package was built for: a Django project attaches controlled-vocabulary
concepts to its own models as first-class data. It shipped as five features and one fix:

- attaching a concept from a chosen vocabulary to a model
  ([#86](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/86));
- attaching several concepts
  ([#87](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/87));
- choosing a concept by typing instead of scrolling
  ([#88](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/88));
- concept selection inside the Django admin
  ([#89](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/89));
- narrowing a field's choices to part of a vocabulary
  ([#164](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/164));
- the single and multiple fields naming their vocabulary the same way
  ([#111](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/111)).

**Deliverables:**

- a field (single and multiple) that attaches concepts from a chosen vocabulary to a consumer's
  model;
- autocomplete-backed selection in forms and the Django admin;
- referential integrity, so a referenced concept cannot silently disappear;
- the concept's label and identity reachable from the consuming record.

Two changes to the field are open: storing the concept's URI in the column the field adds
([#220](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/220)), and renaming
`ConceptsField` to `MultiConceptField`
([#222](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/222)).

Serves G2. Out of scope: import, export and serving, the editing interface.

## Expected goals: v1.0.0

Anything that advances toward the v1.0.0 release.

### R6 — Vocabulary browsing

*delivered in [#140](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/140), [#141](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/141), [#142](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/142) · advances G7.*

People search and move around concepts on read-only pages, across both local vocabularies and
imported external ones, so a stable URI leads somewhere a person can use. It shipped as three
features:

- finding a vocabulary
  ([#140](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/140));
- looking inside a vocabulary
  ([#141](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/141));
- reading a single record
  ([#142](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/142)).

[Browsing](browsing.md) covers mounting the pages.

### R7 — Scale hardening

*Full feature · advances G5.*

Keep search, browse, and autocomplete responsive at tens of thousands of concepts, and support
navigation over deep hierarchies.

### R8 — Embeddable and standalone modes

*Full feature · advances G9.*

Make the app a good guest inside a host Django project, and, with a thin wrapper, a system that runs
on its own.

### R9 — Adopt the heat-flow vocabularies as first real content

*Small to medium · advances G10.*

Move the existing heat-flow vocabularies onto this app as the first production content, exercising
the import and consume loop on a real dataset.

## Aspirational goals: v2.0

Bigger bets, taken on once the 1.x line is stable.

### R5 — Vocabulary management interface

*delivered in [#175](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/175) · advances G1.*

A curator creates, edits and deletes a vocabulary, and the concepts, labels, notes, hierarchy and
collections inside it, without the Django admin. This is set aside with G1. The package has no
pages that create, edit or delete a vocabulary
([#175](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/175), removed in
[#219](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/219)), and
[#176](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/176),
[#177](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/177),
[#178](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/178) and
[#179](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/179) were closed as
not planned. The package's job is importing and referencing published vocabularies, and
authoring returns when a project needs it.

### R4 — RDF publishing and stable URIs

*Full feature · advances G3, and G4.*

Serving a vocabulary held here as standards-compliant RDF at stable concept URIs, with content
negotiation. It means something only once a project authors its own vocabularies, so it follows
R5. A concept in a vocabulary published here is deprecated the same way as an imported one: the
vocabulary states it.

**Deliverables:**

- vocabulary publication as a deliberate, one-way release that freezes its concept URIs;
- concept and scheme URLs that resolve to valid SKOS in Turtle and at least one other
  serialization, chosen by content negotiation;
- a human-readable response alongside the machine ones;
- a vocabulary exported this way that re-imports cleanly.

Serves G3 and G4. Out of scope: the editing interface, browsing external sources.

### R10 — Collaborative curation

*Draft · large · advances G11.*

Several curators working the same vocabularies under object-level permissions.

### R11 — Vocabulary versioning

*Draft · large · advances G12.*

Track versions of a vocabulary as it changes so a consumer can cite the version it used.
