# Feature Specification: Relationships between concepts

**Feature Branch**: `003-relationships-between-concepts`

**Created**: 2026-07-25

**Status**: Draft

**Input**: Issue [#17](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/17) — "Concepts within a vocabulary need to link to one another: a broader/narrower hierarchy, and a looser 'related' association, so a vocabulary is a structured graph rather than a flat list, navigable in both directions."

**Serves**: G4 (faithful round-trip of a vocabulary — the graph structure is part of what must survive export) · **Roadmap**: R1 · **Issue**: #17

> Scope note: this feature turns a vocabulary from a flat set of concepts (FS-001, FS-002) into a structured graph: concepts link to one another through a broader/narrower hierarchy and a symmetric related association, readable from both ends. A link is a statement in the concept's `data` document, an entry holding the target's URI under `skos:broader`, `skos:narrower` or `skos:related`, kept as the publisher stated it. Only the stated direction is stored, and the pages show the other end. Interaction is purely programmatic — no admin or editor UI. **Out of scope:** named collections (FS-004), and RDF export (R4). A link to a concept in another vocabulary is stored like any other statement and is shown by the pages, and the package does not model it as a separate mechanism.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Broader/narrower hierarchy, readable both ways (Priority: P1)

A vocabulary arranges its concepts into a hierarchy: "Granite" is placed under "Igneous rock" by stating a broader concept. Reading "Igneous rock" back, "Granite" appears among its narrower concepts without the file ever stating the narrower direction separately — one statement, both directions readable. A concept may be placed under more than one broader concept (polyhierarchy): "Granite" can state both "Igneous rock" and "Plutonic rock" as broader.

**Why this priority**: This is the core of the feature and the whole of what makes a vocabulary a graph rather than a list. The inverse-pair guarantee (state `broader`, read `narrower` back) is the load-bearing behaviour every downstream navigation, publish and export path depends on. Implemented alone, it is a viable, navigable concept hierarchy.

**Independent Test**: In a test, create a vocabulary with three concepts, give one two broader concepts in its document, then read the broader links from the child with `linked_uris("skos:broader")` and render each parent's page, and assert the child appears as narrower on both pages — without any narrower statement having been made.

**Acceptance Scenarios**:

1. **Given** a vocabulary with concepts "Igneous rock" and "Granite", **When** "Granite" states the broader concept "Igneous rock", **Then** `granite.linked_uris("skos:broader")` returns the URI of "Igneous rock", and the page of "Igneous rock" lists "Granite" among its narrower concepts, with no separate narrower statement made.
2. **Given** that hierarchy, **When** "Granite" also states the broader concept "Plutonic rock", **Then** `granite.linked_uris("skos:broader")` returns both URIs (polyhierarchy is allowed), and both parents' pages list "Granite" as narrower.
3. **Given** a broader link from "Granite" to "Igneous rock", **When** the link is removed from "Granite"'s document and it is saved, **Then** neither page shows the other in either direction.
4. **Given** a concept that states a narrower link to another concept, **When** the pages are read, **Then** the stated narrower link is shown, and the other concept's page shows the concept as broader.
5. **Given** a concept with no broader or narrower links, **When** `linked_uris()` is read for either predicate, **Then** the result is an empty list.

---

### User Story 2 - The related association, symmetric (Priority: P2)

A vocabulary records a sideways association between two concepts where neither is above the other: "Granite" is related to "Quartz" — they belong together, but neither is a kind of the other. The association reads the same from either concept: the page of "Granite" shows "Quartz", and the page of "Quartz" shows "Granite", from the single statement.

**Why this priority**: The related association is the second half of the graph the issue asks for and what captures the associations the strict hierarchy cannot. It reuses US-1's linking mechanism and is not needed for the hierarchy to be correct, so it follows it.

**Independent Test**: In a test, state a related link on one concept, read the pages of both concepts and assert each shows the other, and assert the link is stored once, in the concept that stated it.

**Acceptance Scenarios**:

1. **Given** concepts "Granite" and "Quartz", **When** "Granite" states "Quartz" as related, **Then** the page of "Granite" shows "Quartz" as related and the page of "Quartz" shows "Granite" as related, from the one statement.
2. **Given** "Granite" related to "Quartz", **When** "Quartz" also states "Granite" as related, **Then** each page shows the other once, not twice.
3. **Given** "Granite" related to "Quartz", **When** the related link is removed from "Granite"'s document and it is saved, **Then** neither page shows the other as related.

---

### User Story 3 - Links are kept as published (Priority: P2)

A vocabulary's links are stored exactly as its publisher stated them. The package does not police the graph: two concepts joined in a broader/narrower line may also be stated as related, a concept may state itself, a link may name a concept held in another vocabulary or nowhere on the site, and a broader chain may close into a loop. Each of these is stored and shown as stated, because a faithful copy of a published vocabulary is what the package is for, and the publisher is responsible for its own graph.

**Why this priority**: Refusing a published statement would mean discarding part of what was published, which is the failure this storage exists to avoid. Making the boundary explicit stops a later change from quietly adding an enforcement that drops data.

**Independent Test**: In a test, import a file whose concepts state a duplicate link, a self link, a related link between a broader/narrower pair, a link to an unknown URI, and a broader loop, and assert that every statement is stored and that no error is raised.

**Acceptance Scenarios**:

1. **Given** "Granite" stating "Igneous rock" as broader, **When** "Granite" also states "Igneous rock" as related, **Then** both statements are stored and both are shown.
2. **Given** a concept that states a link to its own URI, **When** it is saved, **Then** the statement is stored, and no refusal is raised.
3. **Given** a concept that states a broader link to a URI no record of this site holds, **When** the page is read, **Then** the link is shown as the URI, as a link when it is a web address and as text otherwise.
4. **Given** a concept that states a related link to a concept of another vocabulary held here, **When** the page is read, **Then** the link leads to that concept's page.
5. **Given** a broader chain "Granite" → "Igneous rock" → "Rock", **When** "Rock" states the broader concept "Granite" (closing a loop), **Then** the statement is stored and no traversal of the hierarchy is performed.

---

### User Story 4 - Relation test scaffolding (Priority: P3)

A contributor building a later feature — browsing, export — constructs a small graph of related concepts in a few lines using the test factories, instead of writing link statements by hand in every test.

**Why this priority**: Every downstream feature that reads the graph (RDF export, the browsing pages, the consumption field's collection restriction) needs graph-shaped test data. It is cheap to add and paid back immediately, but nothing ships to a user because of it, so P3.

**Independent Test**: Write a test that asks the factory for a concept hierarchy and a related pair and asserts the graph is present and readable from both ends.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** a test requests a small concept hierarchy from the factory, **Then** it receives saved concepts linked broader/narrower, whose pages show both directions.
2. **Given** the factories, **When** a test requests a related pair, **Then** it receives two concepts joined by a single related statement.

### Edge Cases

- A concept given two broader concepts (polyhierarchy) reads both back; removing one statement leaves the other intact.
- A concept's page shows the inverse of a link only for concepts of its own vocabulary. A link stated by a concept of another vocabulary is not turned around.
- Reading a concept's broader, narrower or related links when it has none returns an empty list, not an error.
- A link names its target by URI. When the target's record is later deleted, the link stays in the document and the page shows the URI as text.
- Links are held in the document as lists of `{"@id": ...}` entries, so the same URI listed twice in one list is two entries. An import stores each distinct statement a file makes once.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A concept MUST be able to state one or more broader concepts, as `{"@id": ...}` entries under `skos:broader` in its document; polyhierarchy (several broader concepts) MUST be supported.
- **FR-002**: The inverse direction MUST be derived when read, never required to be stated: if a concept states another as broader, the other's page MUST list it as narrower, and a concept that states another as narrower MUST be listed as broader on the other's page. Only the stated direction is stored.
- **FR-003**: A concept MUST be able to state related concepts under `skos:related`. The association MUST read the same from either concept from a single statement, and a statement made from both ends MUST be shown once on each page.
- **FR-004**: The programming interface MUST let a caller read the URIs a concept links to under any predicate with `linked_uris(curie)`, returning an empty list when there are none.
- **FR-005**: A link MUST be removable by editing the concept's document and saving it, after which neither concept's page shows the other in that direction.
- **FR-006**: A link to the concept itself MUST be stored as stated. The package MUST NOT refuse it.
- **FR-007**: A duplicate link, and a pair stated as both broader and related, MUST be stored as stated. The package MUST NOT enforce SKOS disjointness.
- **FR-008**: A link MAY name a concept of another vocabulary, or a URI no record of the site holds, and MUST be stored as stated. A link to a record held here MUST lead to that record's page, and any other MUST be shown as its URI.
- **FR-009**: The system MUST NOT traverse the hierarchy to prevent cycles in the broader relation; a publisher MAY state a cyclic chain, and this is a recorded, deliberate non-guarantee.
- **FR-010**: The test suite MUST ship factories (or equivalent fixtures) able to produce concepts joined by broader/narrower and related links, readable from both ends.

### Key Entities *(include if feature involves data)*

- **Link**: an entry holding a target URI, `{"@id": "..."}`, in a record's document under `skos:broader`, `skos:narrower` or `skos:related`. It belongs to the record that stated it. The page of the target shows the inverse.
- **Record (links)**: unchanged in identity and labelling, now reachable as a node in a graph — it can report the URIs it links to, and its page shows the links other concepts of its vocabulary make to it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Through the ORM alone, a developer can give a concept several broader concepts and read the narrower concepts back from each parent's page, with no narrower statement made — verified by test.
- **SC-002**: A related link stated by one concept is shown, identically, on the other concept's page, and is shown once when both state it — verified by test.
- **SC-003**: A self link, a duplicate link, a broader and a related link between one pair, and a link to a concept held elsewhere are all stored as stated, without error — verified by test.
- **SC-004**: A link to a record held here leads to its page, and a link to anything else is shown as its URI — verified by test.
- **SC-005**: A cyclic broader chain can be stored without error and without the system performing hierarchy traversal — verified by test, documenting the deliberate non-guarantee.
- **SC-006**: A test obtains a navigable concept graph (broader/narrower and a related pair) from the factories in a few lines.
- **SC-007**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python/Django matrix.

## Assumptions

- **Programmatic only.** This feature has no user interface, including the Django admin. Links are written to a concept's document and read through `linked_uris()` and the browsing pages.
- **Links are kept as published.** The package holds a vocabulary faithfully, and what is wrong in a published graph is the publisher's to correct. A link is never refused, merged, dropped or rewritten.
- **Cycle prevention is deliberately not provided.** SKOS does not formally forbid a cycle in the broader relation, and detecting one requires walking the hierarchy on every write — the same traversal cost this feature avoids. Acyclicity is not guaranteed; recorded as a deliberate non-guarantee (FR-009, SC-005).
- **The inverse is read, not stored.** Showing the other end of a link means finding the concepts of the vocabulary whose documents mention the concept's URI. It costs a query when the page is built and no row per link.
- **Links to other vocabularies are statements like any other.** A link to a concept in another vocabulary (`skos:exactMatch`, `skos:closeMatch` and the rest of the mapping predicates) is kept in the document the same way as a broader link, and is shown by the pages. The package gives it no separate handling.
- **RDF projection is later.** How broader/narrower/related are emitted as `skos:broader` / `skos:narrower` / `skos:related` on export belongs to R4. This feature makes the graph exist in the stored documents so that feature has something to project; it does not itself serialize RDF.
