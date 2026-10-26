# Feature Specification: Represent a vocabulary and its concepts

**Feature Branch**: `001-vocabulary-concepts`

**Created**: 2026-07-23

**Status**: Refined

**Input**: Issue [#15](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/15) — "A project needs to hold a controlled vocabulary and the concepts inside it, and to create and query both through Django's ORM and admin. Every concept must carry a stable, permanent identifier that stays fixed even as its wording or its database row changes."

**Serves**: G2, G3 (as an enabler: stable concept identity is what consumption and publishing depend on) · **Roadmap**: R1 · **Issue**: #15

> Scope note: this feature establishes the two stored entities, the vocabulary and the record that holds a concept or a collection, and the identity mechanism. Multilingual names (FS-002), links between concepts (FS-003) and collections (FS-004) are read from the document each row holds. Importing a published file (FS-006) is what normally fills them. Every concept's identifier is a URI, held exactly as given when a publisher assigned it, and composed from a configurable base address when it was not.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Hold a vocabulary (Priority: P1)

A developer or an import creates a controlled vocabulary — for example "Geothermics" — as one `ConceptScheme` row. The row carries a default language and a `data` document that states the vocabulary's own name. Its `pref_label` is a copy of that name in the default language, and its slug is derived from it, once, when the row is first saved.

**Why this priority**: Nothing else in the package can exist without a vocabulary to contain it. This is the ground floor of the ground floor.

**Independent Test**: Create, fetch and delete a vocabulary in a test; verify its slug comes from its name and that no two vocabularies can share a slug.

**Acceptance Scenarios**:

1. **Given** an empty system, **When** a vocabulary is created with the English name "Geothermics" in its document, **Then** it can be retrieved, its `pref_label` is "Geothermics" and its slug is `geothermics`.
2. **Given** the vocabulary "Geothermics", **When** its name in the document is changed to "Geothermal Science" and it is saved, **Then** its `pref_label` becomes "Geothermal Science" and its slug is still `geothermics`.
3. **Given** an existing vocabulary with slug `geothermics`, **When** a second vocabulary is created whose name would produce the same slug, **Then** its slug is made distinct with a numeric suffix (`geothermics-2`), and no two vocabularies can hold the same slug.

---

### User Story 2 - Hold the concepts of a vocabulary (Priority: P1)

A developer or an import adds concepts to a vocabulary. Each is one `Record` row of type `skos:Concept`, belonging to exactly one vocabulary, whose `data` document states its preferred label — "Heat flow", "Thermal conductivity". Its slug is derived once from its published identifier, or from its preferred label when it has none, and is unique within its vocabulary.

**Why this priority**: Concepts are the payload of the whole package; a vocabulary without concepts is an empty shell.

**Independent Test**: Add several concepts to a vocabulary in a test; list them through `scheme.records`, look one up by slug, and delete one — all through the package's programming interface.

**Acceptance Scenarios**:

1. **Given** the vocabulary "Geothermics", **When** a concept with the English preferred label "Heat flow" is added, **Then** the concept can be retrieved from that vocabulary under the slug `heat-flow`.
2. **Given** a concept "Heat flow" in "Geothermics", **When** its preferred label in the document changes to "Terrestrial heat flow" and it is saved, **Then** its `pref_label` and `search_text` follow the new label and its slug is still `heat-flow`.
3. **Given** a vocabulary containing concepts, **When** its records are listed, **Then** every record added — and only those — is returned.
4. **Given** two records in the same vocabulary, **When** a second is saved with a name that would produce the same slug as the first, **Then** it receives a numeric suffix, and the database refuses two records of one vocabulary with the same slug.
5. **Given** a concept in a vocabulary, **When** it is deleted, **Then** it is gone from the vocabulary's record list.
6. **Given** a vocabulary holding records, **When** the vocabulary is deleted, **Then** its records are deleted with it.

---

### User Story 3 - Every record carries a stable identifier (Priority: P1)

Every record and every vocabulary has a `uri`. When it was imported, the `uri` is the identifier its publisher assigned, held exactly as given. When it is created without one, the `uri` is composed once, from a configurable base address plus the vocabulary's slug plus the record's slug — for example `https://example.org/vocabularies/geothermics/heat-flow` — and stays as composed. A row can be looked up by its `uri`, and no two rows of one model can share one.

**Why this priority**: The identifier is what issue #15 exists to establish. Everything downstream — attaching concepts to data, publishing, importing — hangs off this.

**Independent Test**: Create a vocabulary and a concept in a test; verify the composed URI, look the concept up by it, then change the document and verify the URI is unchanged.

**Acceptance Scenarios**:

1. **Given** a base address of `https://example.org/vocabularies`, a vocabulary with slug `geothermics`, and a concept created without a URI whose slug is `heat-flow`, **When** its URI is read, **Then** it is `https://example.org/vocabularies/geothermics/heat-flow`.
2. **Given** a concept's URI, **When** it is used as a lookup key, **Then** exactly that concept is returned.
3. **Given** a record created with the URI `https://publisher.example/rocks/granite`, **When** it is saved, **Then** its `uri` is exactly that value and its slug is `granite`.
4. **Given** a saved record, **When** its document is edited and it is saved again, **Then** its `uri` and `slug` are unchanged.
5. **Given** any two records in the system, **When** their URIs are compared, **Then** they differ.

---

### User Story 4 - Ready-made test scaffolding (Priority: P2)

A contributor building a later feature can construct populated test vocabularies in a couple of lines, using factories shipped with the test suite, instead of hand-assembling vocabularies and concepts in every test.

**Why this priority**: Later features each need test vocabularies on day one. Cheap now, paid back immediately.

**Independent Test**: Write a test that uses only the factories to produce a vocabulary with several concepts, and assert on it.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** a test requests a vocabulary from the factory, **Then** it receives a valid, saved vocabulary with sensible defaults.
2. **Given** the factories, **When** a test requests a concept without specifying a vocabulary, **Then** a containing vocabulary is created automatically and the concept is valid within it.

---

### User Story 5 - Translatable, self-documenting field metadata (Priority: P2)

A developer integrating the package — or a person seeing its fields in a form — always gets a human-readable label and help text for every field, in their own language once translations exist. Nothing user-facing is hard-coded English-only, and the package's fields carry deliberate database indexes, because a consumer of a third-party package cannot add either themselves.

**Why this priority**: a standard for every Django package this maintainer publishes (non-negotiable at review); it gates the merge even though it adds no new capability.

**Independent Test**: a metadata test suite walks every field on both models and asserts the standard holds — no UI needed.

**Acceptance Scenarios**:

1. **Given** any field on a vocabulary or record, **When** its metadata is inspected, **Then** it declares a non-empty help text and a human-readable label, and both are lazily translatable.
2. **Given** a user-facing validation failure (a document that is not a mapping of predicates to lists of entries), **When** the error is raised, **Then** its message is translatable and uses named placeholders rather than baked-in values.
3. **Given** the database table definitions, **When** their indexes are inspected, **Then** the vocabulary slug and both URIs are uniquely indexed, the record's vocabulary reference carries its index, the vocabulary-plus-slug pair is enforced by a composite constraint, and the columns lists sort by are covered by a composite index — and any field left unindexed is a recorded decision, not an omission.

---

### Edge Cases

- A record name or vocabulary name in a non-Latin script (for example "Wärmefluss" or Cyrillic text) must still produce a usable slug. Slugs may hold Unicode letters.
- A row whose document holds no name has an empty `pref_label`, and is still given a slug and a URI.
- Deleting a vocabulary that still contains records removes the vocabulary and its records — a record cannot exist outside a vocabulary.
- Changing a record's name never changes its URI or its slug, because both are fixed when the row is first saved.
- A document that is not an object mapping each predicate to a list of entries is refused by validation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST hold a vocabulary as one `ConceptScheme` row with a URI, a slug, a default language, a `pref_label` and a `data` document, and MUST let a caller create, retrieve and delete it through the ORM.
- **FR-002**: Each vocabulary MUST carry a URL-safe slug that is derived from its published identifier, or from its name when it has none, assigned once when the row is first saved, and unique across all vocabularies.
- **FR-003**: The package MUST hold a concept or collection as one `Record` row belonging to exactly one vocabulary, with a `type`, a URI, a slug, a `pref_label`, a `search_text` and a `data` document. A record MUST NOT exist outside a vocabulary.
- **FR-004**: Each record MUST carry a URL-safe slug that is derived from its published identifier, or from its preferred label when it has none, assigned once when the row is first saved, and unique within its vocabulary.
- **FR-005**: Every vocabulary and record MUST have a `uri`. One that arrived with a URI MUST keep it exactly as given. One created without MUST be given a URI composed once from a configurable base address, its vocabulary's slug where it has one, and its own slug.
- **FR-006**: A record MUST be retrievable by its URI, by its vocabulary-plus-slug pair, and as part of a listing of its vocabulary's records.
- **FR-007**: Slug derivation MUST handle non-ASCII input. A collision MUST be resolved when the slug is derived, by a numeric suffix, and the database MUST enforce uniqueness at the scope of the entity (site-wide for vocabularies, per-vocabulary for records).
- **FR-008**: The test suite MUST ship factories (or equivalent fixtures) for vocabularies and records, usable by this and later features' tests.
- **FR-009**: Every model field MUST declare a human-readable label (`verbose_name`) and a non-empty `help_text`, both lazily translatable.
- **FR-010**: Every user-facing string — field labels, help text, model verbose names, and validation messages — MUST be translatable; validation messages use named placeholders so their translatable form is static. Developer-facing diagnostics are exempt.
- **FR-011**: Field indexing MUST be deliberate: fields with a lookup path are indexed at definition (unique, foreign-key, or composite constraint), and any queryable-but-unindexed field is a recorded decision.
- **FR-012**: A `data` document MUST be validated as an object that maps each predicate to a list of entries, each entry a link (`@id`) or a literal (`@value`, with at most an `@language` or an `@type`).

### Key Entities

- **Vocabulary (concept scheme)**: the named container — carries a URI, a slug, a default language, a copy of its name, and a document of its own statements. Holds any number of records.
- **Record**: a concept or collection within exactly one vocabulary — carries its type, a URI, a slug that is unique within its vocabulary, copies of its name and its labels, and a document of every statement made about it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can create a vocabulary, add concepts to it, and retrieve any concept by its identifier, in under ten lines of code.
- **SC-002**: Every record in a system has exactly one URI and no two records share one, regardless of how many vocabularies exist.
- **SC-003**: Changing a stored name changes the copy kept for sorting and searching and never moves an identifier, with no manual step.
- **SC-004**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python/Django matrix.
- **SC-005**: A test for a later feature can obtain a populated vocabulary from the factories in three lines or fewer.
- **SC-006**: Every field on both models exposes translatable, non-empty metadata, every user-facing message is translatable, and the indexing of every field is either present or recorded as a decision — all verified by automated tests.

## Assumptions

- A name is read from the row's document, and the copy in `pref_label` is the name in the vocabulary's default language. A row published without a name in that language takes its first name in any language.
- The base address used to compose a URI is deployment-level configuration, `CONTROLLED_VOCABULARIES_BASE_URI`, and is only used for a row created without a URI.
- Names in other languages (FS-002), links between concepts (FS-003) and collections (FS-004) are statements in the document, not further tables.
- Notation codes are statements in the document like any other, and have no column of their own.
- No user interface of any kind — including the Django admin — is part of this feature; interaction is purely programmatic.
