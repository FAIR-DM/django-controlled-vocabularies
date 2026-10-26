# Feature Specification: Concepts keep the identifier they were published under

**Feature Branch**: `005-concepts-keep-identifier`

**Created**: 2026-08-03

**Status**: Draft

**Input**: Issue [#49](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/49) — "An imported vocabulary arrives with identifiers already assigned by whoever published it, and those identifiers are how the rest of the world refers to its concepts. A concept's identifier must be the one its publisher assigned."

**Serves**: G8 (external vocabularies as read-only references — an imported vocabulary cannot reference anything if its identifiers are discarded) · G4 (faithful round-trip — a record that cannot hold its source identifier cannot be exported as itself) · **Roadmap**: R2 · **Issue**: #49

> Scope note: this feature is the first slice of roadmap item R2 and the prerequisite for the rest of it. A vocabulary and a record each have exactly one identifier, the `uri` column. A row that arrives from a publisher holds that publisher's identifier, exactly as given. A row created without one is given an identifier composed from the site's configured base address and its slugs, once, when it is first saved. The address a row is viewed at on this site is separate: it comes from where the browsing pages are mounted and from the row's slugs, never from its identifier. Reading vocabulary files is FS-006, keeping every statement and language is FS-007, and running an import from the command line is FS-008, all of which build on the identity this feature establishes. **Out of scope:** parsing or importing any file, publishing a vocabulary (roadmap R4), the browsing routes themselves (R6), and any way to type an identifier in by hand.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A record keeps the identifier it arrived with (Priority: P1)

A vocabulary published elsewhere is brought in. Its concepts, the vocabulary itself, and any collections in it already have identifiers assigned by their publisher — addresses on the publisher's own site, which is how the rest of the world refers to them. Those identifiers are held exactly as given. The app never rewrites one to look like an address of its own, and never recomputes one because a name or slug changed here. Moving this site to a different address, or reconfiguring the address it composes its own identifiers from, leaves every one of them untouched.

**Why this priority**: This is the whole of what the issue asks for and the blocker sitting in front of the rest of R2. Without somewhere for an external identifier to live, an imported concept cannot be matched back to its source, and the "import upserts by URI" invariant (Article IX) cannot be satisfied for external content at all. Implemented alone it is already useful: a vocabulary's true identifiers survive in the system.

**Independent Test**: In a test, create a vocabulary, a concept, and a collection each carrying an identifier from an unrelated domain, read the identifiers back and assert they are returned verbatim; change each record's name and assert the identifiers are unchanged; change the site's configured base address and assert they are still unchanged.

**Acceptance Scenarios**:

1. **Given** a concept recorded with the identifier `http://vocabs.example.org/rock/granite`, **When** its `uri` is read, **Then** exactly that string is returned, not a value composed from this site's base address.
2. **Given** that concept, **When** its name changes and it is saved, **Then** its `uri` and its slug are unchanged.
3. **Given** that concept, **When** the site's configured base address is changed, **Then** its `uri` is unchanged.
4. **Given** a vocabulary and a collection each recorded with an identifier from an external publisher, **When** their `uri` values are read, **Then** each returns the identifier it was given, and a concept's identifier is not derived from its vocabulary's.
5. **Given** an externally assigned identifier, **When** anything writes to the record, including a re-import that matched the record by that very identifier, **Then** the identifier is not rewritten, normalised, or re-cased.
6. **Given** an import of a file whose subject is a blank node, or whose identifier begins with `javascript:`, `data:` or `vbscript:`, **When** the run is read, **Then** the whole run is refused with a translatable message and nothing is stored.
7. **Given** a `urn:` identifier from a publisher that uses them, **When** it is imported, **Then** it is accepted and held verbatim, as is an identifier in any other scheme that cannot carry executable content.

---

### User Story 2 - Find a record by its identifier, wherever that identifier points (Priority: P2)

Something holding an identifier — an import matching a concept it has seen before, code resolving a reference — asks the system for the record it names. It gets an answer whether the identifier is one of this site's own or belongs to an external publisher.

**Why this priority**: Upsert by identifier is the mechanism FS-006 is built on and the Article IX invariant that keeps a re-import from destroying data. Storing an identifier that cannot then be looked up would leave the feature useless to the thing that needs it. It is second only because storage has to exist before anything can be found by it.

**Independent Test**: In a test, record a concept with an external identifier, look it up by that exact identifier and assert the right concept comes back; look up a local record by its own identifier and assert it still resolves; look up an identifier no record holds and assert the standard not-found behaviour.

**Acceptance Scenarios**:

1. **Given** a concept whose `uri` is `http://vocabs.example.org/rock/granite`, **When** it is looked up with `Record.objects.get(uri=...)`, **Then** that concept is returned.
2. **Given** a vocabulary created here, **When** one of its concepts is looked up by its own `uri`, **Then** that concept is returned.
3. **Given** an identifier no record holds, **When** it is looked up, **Then** `Record.DoesNotExist` is raised, with the same behaviour for an external identifier as for a local one.
4. **Given** two vocabularies, one imported and one created here, **When** a concept from each is looked up by identifier, **Then** each returns its own record and neither is found by the other's identifier.

---

### User Story 3 - A record created here is given an identifier once (Priority: P2)

A vocabulary or record created without an identifier is given one when it is first saved. It is composed from the site's configured address and the row's slugs — `{base}/{vocabulary-slug}` for a vocabulary and `{base}/{vocabulary-slug}/{record-slug}` for a record. It stays as composed, so a later rename or a later change of the configured address does not move it.

**Why this priority**: It keeps a single rule for the whole system — every row has a `uri` — instead of a missing identity that half the app has to special-case. It is not P1 because an imported record can be stored and matched without it.

**Independent Test**: In a test, create a vocabulary and concept with no identifier, assert each reports the identifier composed from the configured address and its slugs; change the document and the configured address, save, and assert the identifiers are unchanged.

**Acceptance Scenarios**:

1. **Given** a concept created here with no identifier, **When** its `uri` is read, **Then** it is the value composed from the site's configured address, its vocabulary's slug, and its own slug.
2. **Given** that concept, **When** its name changes and it is saved, **Then** its `uri` is unchanged.
3. **Given** that concept, **When** the site's configured base address changes and the concept is saved, **Then** its `uri` is unchanged.
4. **Given** any two records in the system, **When** their `uri` values are compared, **Then** no two share one, and the uniqueness is enforced by the database for each model.

---

### User Story 4 - Every record has a place on this site, whoever owns its identifier (Priority: P2)

An imported concept has to be viewable here even though its identifier points at somebody else's site. Every vocabulary, concept and collection therefore has an address on this site, made from where the browsing pages are mounted and from the vocabulary's slug and its own, separate from its identifier. For a row created here and not imported the two can read the same when the pages are mounted at the path of the configured base address, which is why they can look like one thing. For an imported row they differ, and both are needed.

**Why this priority**: It stops the app having to choose between showing an imported concept and telling the truth about who published it, and it is the address the browsing pages (R6) route on.

**Independent Test**: In a test, reverse the page of an imported concept and assert it names a place on this site and is composed from its slugs while its `uri` is the external one; assert a collection's address stays distinguishable from a concept's.

**Acceptance Scenarios**:

1. **Given** an imported concept whose `uri` is on an external site, **When** its page is reversed, **Then** the address is on this site, composed from where the pages are mounted, the vocabulary's slug and the concept's slug.
2. **Given** an imported vocabulary and a collection inside it, **When** their pages are reversed, **Then** each names a place on this site, and a collection's address stays distinguishable from a concept's so the two can never name the same place.

---

### User Story 5 - Translatable field metadata and deliberate indexing (Priority: P3)

Every field this feature adds carries a human-readable, translatable label and help text, every user-facing validation message it introduces is translatable, and each new field's database indexing is a deliberate, recorded decision, because a consumer of a third-party package cannot add any of these themselves. The test factories can also produce a record carrying an externally assigned identifier in a line, so the import work that follows is not blocked on hand-building one.

**Why this priority**: A standard for every Django package this maintainer publishes (constitution Articles XII and XIII). It adds no new capability but gates the merge, so it travels with the feature at P3. The factory addition is small and is paid back immediately by FS-006.

**Independent Test**: The existing metadata test suite walks every concrete field on the models and covers the identifier fields. Separately, ask the factories for a record with an external identifier and assert it is saved and reports that identifier.

**Acceptance Scenarios**:

1. **Given** the `uri` field, **When** its metadata is inspected, **Then** it declares a non-empty help text and a human-readable label, both lazily translatable.
2. **Given** a user-facing refusal this feature introduces, **When** the error is raised, **Then** its message is translatable and uses named placeholders rather than baked-in values.
3. **Given** the database definition of the models, **When** their indexes are inspected, **Then** the identifier used for lookup is indexed, its uniqueness is a database constraint, and any queryable-but-unindexed field is a recorded decision rather than an omission.
4. **Given** the test suite, **When** a test requests a vocabulary, concept, or collection carrying an externally assigned identifier from the factories, **Then** it receives a saved record reporting that identifier.

### Edge Cases

- An externally assigned identifier that happens to sit under this site's own configured address is still held as given and never recomputed.
- Changing the site's configured base address moves no stored identifier. A deployment that changes address after rows were created without identifiers keeps the identifiers it composed at the time.
- Two rows of one model may not hold the same `uri`. When an import meets a record whose identifier is already held, it matches it and updates it. A record held by another vocabulary moves into the vocabulary being imported and takes a new slug there, because an identifier is held once.
- An imported vocabulary and a vocabulary created here can sit side by side, and a row's identifier is its own: a vocabulary whose identifier is external does not make a concept added to it afterwards external, and the reverse holds too.
- An identifier is stored as the publisher wrote it, within the column's bound of 500 characters. A subject with no usable identifier — a blank node, or an identifier beginning `javascript:`, `data:` or `vbscript:` — refuses the whole import, because a stored identifier is rendered as a link.
- Refusing those schemes on the way in does not relieve the browsing pages of escaping what they render. The refusal keeps a hostile value out of the database, and escaping keeps a merely awkward one out of the page.
- Writing around the model, for example with `QuerySet.update()`, can change a stored `uri`. No write path is defended, and that is the decision: keeping a published identifier still is a matter of not editing it, and a value that differs between two imports of the same vocabulary is a defect in the source file.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A vocabulary (`ConceptScheme`) and a record (`Record`, whether a concept or a collection) MUST each carry a single `uri`, the row's identity, readable on every row without exception.
- **FR-002**: An externally assigned `uri` MUST be held verbatim: never composed, never recomputed from the site's configured address or the row's slugs, and never normalised or re-cased. The application MUST NOT itself overwrite a stored value. A re-import matches an existing record by its identifier and therefore has no occasion to rewrite it.
- **FR-003**: A row created without a `uri` MUST be given one when it is first saved, composed from the site's configured base address, its vocabulary's slug where it has one, and its own slug. The value MUST NOT be recomposed by a later save, a rename or a change of the configured address.
- **FR-004**: An import MUST refuse the whole run, writing nothing, when a subject it would store has no usable identifier: a blank node, or an identifier beginning `javascript:`, `data:` or `vbscript:`. Any other identifier MUST be accepted. A `uri` MUST NOT exceed 500 characters, which stays inside the unique-index limit of every mainstream database.
- **FR-005**: No two rows **of the same model** MAY hold the same `uri`, enforced by a database constraint rather than by application code. Uniqueness across the two models is not required: a row's place in its vocabulary is already unique by construction, so a composed identifier cannot collide.
- **FR-006**: Looking a record up by `uri` MUST resolve records whose identifier lies **outside** the site's configured base address as readily as those within it, and MUST raise the standard `DoesNotExist` error when no row holds the identifier given.
- **FR-007**: A vocabulary, a concept and a collection MUST each have an address on this site, made from where the browsing pages are mounted, the vocabulary's slug, and the record's own slug, whoever assigned the row's `uri`. A collection's address MUST stay distinguishable from a concept's.
- **FR-008**: Every model field this feature adds MUST declare a human-readable, lazily translatable label and non-empty help text, and every user-facing refusal it introduces MUST be translatable with named placeholders so the message identifier stays static. Developer-facing diagnostics are exempt.
- **FR-009**: Indexing MUST be deliberate: the `uri` is the column identity lookups run against and MUST be indexed, its per-model uniqueness (FR-005) MUST be a database constraint, and any queryable-but-unindexed field this feature adds MUST be a recorded decision.
- **FR-010**: The test suite MUST ship factories able to produce a vocabulary, a concept and a collection carrying an externally assigned `uri`.

### Key Entities *(include if feature involves data)*

- **URI (`uri`)**: the globally stable identity of a vocabulary, concept or collection. Externally assigned when the row came from a vocabulary published elsewhere, in which case it is that publisher's address, held as given. Composed once from this site's address and the row's slugs when the row was created without one. Identity has always lived here rather than in the database key (Article IX); what this feature establishes is that it can belong to somebody else.
- **Address on this site**: where a row is viewed on this site — the mount path of the browsing pages, the vocabulary's slug, and the record's own slug. Always this site's own, for every row, whoever assigned its `uri`.
- **ConceptScheme, Record**: each holds one `uri` and one `slug`, both fixed when the row is first saved.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A vocabulary, concept or collection recorded with an identifier from an external publisher reports that exact identifier, unchanged, after its name changes and after the site's configured base address is changed — verified by test.
- **SC-002**: A record recorded with an external identifier is found by looking that identifier up, and a record created here is found by its own — verified by test, with `DoesNotExist` raised for an identifier no row holds.
- **SC-003**: A row created here with no identifier reports the identifier composed from the configured address and its slugs, and that value does not move — verified by test.
- **SC-004**: Two rows of one model cannot be stored holding the same `uri`, and the refusal comes from the database constraint — verified by test.
- **SC-005**: An import of a blank node subject, and of one whose identifier begins `javascript:`, `data:` or `vbscript:`, is refused with a translatable message and writes nothing, while a `urn:` identifier is accepted — verified by test.
- **SC-006**: Every row has an address on this site composed from its slugs, an imported row's address and `uri` differ, and a collection's address can never collide with a concept's — verified by test.
- **SC-007**: Every field this feature adds exposes translatable, non-empty metadata and a recorded indexing decision, and every validation message it introduces is translatable with named placeholders — verified by the standards test.
- **SC-008**: A test obtains a vocabulary, concept or collection carrying an externally assigned identifier from the factories in a line.
- **SC-009**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python and Django matrix.

## Assumptions

- **The publication moment belongs to R4.** This feature builds the mechanism — an identifier held as given when externally assigned and composed once otherwise — but nothing here publishes a vocabulary. R4 owns that moment.
- **Every row has a URI.** There is no state in which a row lacks one. A row that arrives with an identifier holds it as given, and a row created without one is given one at its first save and keeps it.
- **The browsing routes are R6's.** The address of a row on this site comes from the routes of the browsing pages, mounted wherever the project chooses, and a system check warns when that mount disagrees with the path of the configured base address.
- **No hand-entered identifiers in a user interface.** Nothing here gives a person a way to type an identifier into a page. An externally assigned identifier arrives with imported content.
- **Matching is not identity.** This feature guarantees an identifier can be stored, is unique, and can be looked up. Deciding which existing record an incoming one *is* is import behaviour and belongs to FS-006.
- **The configured base address is this site's own address.** It composes identifiers only for rows created without one. It has no bearing on an externally assigned identifier.
