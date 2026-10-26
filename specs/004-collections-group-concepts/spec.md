# Feature Specification: Collections that group concepts

**Feature Branch**: `004-collections-group-concepts`

**Created**: 2026-07-25

**Status**: Draft

**Input**: Issue [#18](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/18) — "A vocabulary should be able to gather concepts into named collections, optionally in a deliberate order, to capture groupings that aren't part of the broader/narrower hierarchy."

**Serves**: G4 (faithful round-trip of a vocabulary — a collection is part of what a vocabulary holds and must survive export) · **Roadmap**: R1 · **Issue**: #18

> Scope note: this feature adds the last structural piece the foundation needs: a **collection**, a named grouping of concepts *within a single vocabulary*. A collection is a `Record` whose `type` is `skos:Collection` or `skos:OrderedCollection`, and its members are the URIs in its own document, under `skos:member`, or in sequence under `skos:memberList`. A collection may be unordered or carry a deliberate member order, and its membership is orthogonal to the broader/narrower hierarchy: it captures how a vocabulary is organised and displayed, not a semantic relation. Interaction is purely programmatic — no admin or editor UI. **Out of scope:** nested collections (a collection's members are concepts, see Assumptions), the broader/narrower hierarchy and the related association (FS-003), and RDF export of collections (R4).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Gather concepts into a named collection (Priority: P1)

A vocabulary gathers a handful of its concepts into a named collection — "Common igneous rocks" — to capture a grouping that the broader/narrower hierarchy does not express. The collection lists its members, and reading it back returns them; the same concept can also sit in another collection ("Rocks pictured in the field guide") without either grouping disturbing the other.

**Why this priority**: This is the core of the feature and the whole of what the issue asks for at its simplest — a named grouping of concepts that is not the hierarchy. Implemented alone it is a viable, useful capability: a vocabulary can be organised into overlapping named sets. Everything else refines it.

**Independent Test**: In a test, create a vocabulary with several concepts, create a collection whose document lists three of them under `skos:member`, read the members back with `member_uris()` and assert exactly those three appear; list one of them in a second collection and assert both collections report it and neither is disturbed by the other.

**Acceptance Scenarios**:

1. **Given** a vocabulary with concepts "Granite", "Basalt", and "Quartz", **When** a collection "Common igneous rocks" lists "Granite" and "Basalt" under `skos:member`, **Then** `member_uris()` returns exactly the URIs of "Granite" and "Basalt" and not "Quartz".
2. **Given** that collection, **When** a second collection "Field-guide rocks" also lists "Granite", **Then** both collections report "Granite", and removing "Granite" from one document leaves it in the other.
3. **Given** a collection with members, **When** a member is removed from its document and the collection is saved, **Then** `member_uris()` no longer returns it and the remaining members are unaffected.
4. **Given** a collection with no members, **When** `member_uris()` is read, **Then** the result is an empty list — not an error.
5. **Given** a concept, **When** its page is read, **Then** it names every collection of its vocabulary that lists it, and none that does not.

---

### User Story 2 - A collection with a deliberate order (Priority: P2)

A collection of type `skos:OrderedCollection` keeps its members in a deliberate sequence under `skos:memberList` — the order the concepts should be presented in, which is neither alphabetical nor the hierarchy. Reading the ordered collection back returns its members in exactly that sequence, and an import keeps the sequence the file gave. A collection left unordered asserts no sequence over its members.

**Why this priority**: "Optionally in a deliberate order" is the second thing the issue explicitly asks for, and ordered presentation is what distinguishes a curated display list from a plain set. It builds directly on US-1's grouping and is not needed for an unordered grouping to be correct, so it follows at P2.

**Independent Test**: In a test, create an ordered collection with its members in one sequence, read them back and assert the sequence is preserved; reorder two of them and assert the new sequence reads back; separately assert an unordered collection makes no order guarantee.

**Acceptance Scenarios**:

1. **Given** an ordered collection, **When** its document lists "Basalt", then "Granite", then "Gabbro" under `skos:memberList`, **Then** `member_uris()` returns them in that same sequence.
2. **Given** that ordered collection, **When** the list is reordered so "Gabbro" comes first and the collection is saved, **Then** subsequent reads return the new sequence.
3. **Given** an ordered collection of three members, **When** the middle member is removed, **Then** the two remaining members read back in their original relative order.
4. **Given** a collection that is **not** ordered, **When** its members are read, **Then** no particular sequence is promised — the collection is a set, and ordering carries no meaning for it.

---

### User Story 3 - Membership asserts no relation, and is kept as published (Priority: P2)

Putting a concept into a collection never asserts that it is broader than, narrower than, or related to any other member. The grouping is an organisational overlay, sealed off from the semantic graph. A member is stored exactly as the collection names it: a member held by another vocabulary, or by no record of this site, is kept and shown by its URI rather than refused.

**Why this priority**: The independence-from-hierarchy promise is what keeps a collection from being mistaken for a relation (and keeps the exported SKOS meaningful). Keeping a published member list intact is what a faithful copy of a vocabulary requires. Both span the whole membership mechanism, so they are expressed once US-1 exists, at P2 alongside ordering.

**Independent Test**: In a test, list two unrelated concepts in a collection and assert that neither gains a broader, narrower or related link to the other, and that each concept's own document is unchanged; list a URI no record holds and assert it is stored and shown as text.

**Acceptance Scenarios**:

1. **Given** two concepts with no relation between them, **When** a collection lists both, **Then** neither reports the other as broader, narrower, or related — collection membership asserts no semantic relation.
2. **Given** two concepts already joined by a broader/narrower or related link, **When** a collection lists both, **Then** the collection holds them and their existing relation is unchanged — the two mechanisms are independent.
3. **Given** a collection in vocabulary A that lists a concept of vocabulary B, **When** its page is read, **Then** the member is stored as stated and its row links to its page in vocabulary B.
4. **Given** a collection that lists a URI no record holds, **When** its page is read, **Then** the member is shown as its URI, as a link when it is a web address and as text otherwise.

---

### User Story 4 - Collection test scaffolding (Priority: P3)

A contributor building a later feature — export, the browsing pages — constructs a collection of concepts, ordered or not, in a few lines using the test factories, instead of writing member statements by hand in every test.

**Why this priority**: Every downstream feature that reads a vocabulary's structure (RDF export of `skos:Collection` / `skos:OrderedCollection`, the browsing pages, the concept field's collection restriction) needs collection-shaped test data. It is cheap to add and paid back immediately, but nothing ships to a user because of it, so P3.

**Independent Test**: Write a test that asks the factory for a collection with members and asserts they are present, and for an ordered collection with a known sequence and asserts the sequence reads back.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** a test requests a collection with members from the factory, **Then** it receives a saved collection whose members are the requested concepts, all in the collection's own vocabulary.
2. **Given** the factories, **When** a test requests an ordered collection with a given member sequence, **Then** it receives a saved ordered collection that reads its members back in that sequence.

### Edge Cases

- A collection with no members reads back as empty, not an error; a collection whose members are the whole vocabulary is allowed.
- The same concept in two collections is held independently by each; removing it from one leaves the other intact.
- A concept listed twice in one collection's document is two entries. An import stores each distinct statement a file makes once.
- A collection's slug is unique among all the records of its vocabulary, concepts included, because a collection and a concept are rows of one model. A collection is still addressed at its own segment (`/<vocabulary>/collection/<slug>/`), beside a concept's.
- A collection's members are named by URI. When a member's record is later deleted, the URI stays in the collection's document and is shown as text.
- An import of the vocabulary replaces a collection's document with what the file now says, so a member the file no longer lists is dropped from it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A vocabulary MUST be able to hold a named **collection**: a `Record` of type `skos:Collection` or `skos:OrderedCollection` belonging to exactly one vocabulary (`ConceptScheme`), which can be renamed and deleted like any record.
- **FR-002**: A collection MUST be able to list members as `{"@id": ...}` entries under `skos:member`, and under `skos:memberList` when it is ordered. `member_uris()` MUST return exactly the collection's current members, and an empty list when it has none.
- **FR-003**: Collection membership MUST be many-to-many: a concept MAY be listed by several collections at once, and a collection MAY list many concepts. Memberships are independent — removing a concept from one collection MUST NOT affect another.
- **FR-004**: A collection MUST be markable as **ordered** by its type. For an ordered collection, `member_uris()` MUST return its `skos:memberList` members in the sequence they are listed. An unordered collection asserts no order over its members and is read as a set.
- **FR-005**: The sequence of an ordered collection MUST persist, and a change to the list, saved, MUST be what subsequent reads return. Removing a member MUST leave the remaining members' relative order intact.
- **FR-006**: Listing concepts in a collection MUST assert **no semantic relation** between them: a collection's members gain no broader, narrower or related link by virtue of shared membership, and any relation that already exists between two members is left unchanged. Collections and relations (FS-003) are independent mechanisms.
- **FR-007**: A member MUST be stored exactly as the collection names it. The package MUST NOT refuse a member held by another vocabulary or by no record of the site, and MUST show it by its URI, linked when the record is held here.
- **FR-008**: A concept's page MUST name every collection of its vocabulary that lists it, and a collection's page MUST list its members under the predicate that matches its type.
- **FR-009**: A collection MUST carry a stable `uri` and a `slug` unique among the records of its vocabulary, consistent with the vocabulary and concept precedent (Article IX), so the collection can be round-tripped when RDF projection lands. Two collections in one vocabulary MUST be distinguishable by that identifier. (The URI *serialization* itself is R4, out of scope here.)
- **FR-010**: The test suite MUST ship factories (or equivalent fixtures) able to produce a collection with members and an ordered collection with a known member sequence, all members in the collection's own vocabulary.

### Key Entities *(include if feature involves data)*

- **Collection**: a named grouping of concepts within one vocabulary — a `skos:Collection` or `skos:OrderedCollection`. It is a `Record` that belongs to exactly one `ConceptScheme`, lists its members in its own document, and carries a stable identifier within its vocabulary. Distinct from a vocabulary (the container itself) and from the hierarchy (a semantic relation).
- **Collection membership**: an entry in a collection's document naming a member concept by URI. Under `skos:memberList` it carries its place in the sequence.
- **Concept (collections)**: unchanged in identity, labelling and relations. Its page names the collections that list it, found by reading the vocabulary's collections. It gains no relation and no identity behaviour from this feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Through the ORM alone, a collection can be created in a vocabulary, list and drop concept members, and read exactly the current members back (empty when there are none) — verified by test.
- **SC-002**: A concept can be listed by several collections at once, and removing it from one leaves it in the others — verified by test.
- **SC-003**: An ordered collection reads its members back in the sequence they are listed in, a reordering changes that sequence, and removing a member preserves the survivors' relative order — verified by test.
- **SC-004**: An unordered collection makes no order promise and behaves as a set — verified by test.
- **SC-005**: Listing two concepts in a collection creates no broader, narrower or related link between them, and leaves any pre-existing relation between two members unchanged — verified by test.
- **SC-006**: A member held by another vocabulary, and a member no record holds, are stored as stated and shown by their URIs — verified by test.
- **SC-007**: A concept's page names the collections that list it, and a collection carries a stable, distinguishing identifier within its vocabulary (URI plus slug) — verified by test, following the vocabulary and concept precedent.
- **SC-008**: A test obtains a populated collection and an ordered collection with a known sequence from the factories in a few lines.
- **SC-009**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python/Django matrix.

## Assumptions

- **Programmatic only.** This feature has no user interface, including the Django admin. Collections are created, populated, ordered and read through the ORM and the browsing pages.
- **No nested collections.** A collection's members are **concepts**, never other collections. SKOS permits a collection to contain other collections; that nesting is deliberately not provided until a concrete need appears.
- **Ordered is a property of the collection**, set by its type: a collection is either ordered (its members carry a deliberate sequence under `skos:memberList`) or not (a plain set under `skos:member`).
- **Membership is read, not enforced.** The package stores the member list a publisher gave and checks nothing about it beyond the document's shape. A collection may list a concept of another vocabulary, a URI no record holds, or the same concept twice, and what is wrong in a published collection is the publisher's to correct.
- **Identity follows the vocabulary and concept precedent.** A collection gets a stable identifier within its vocabulary — a `uri`, and a slug unique among its vocabulary's records, as concepts have. The RDF *serialization* of a collection — emitting `skos:Collection` / `skos:OrderedCollection`, `skos:member` / `skos:memberList` — belongs to R4 and is out of scope here.
- **Deleting a listed concept does not edit the collection.** A record a concept field references cannot be deleted. A listed concept that is deleted anyway leaves its URI in the collection's document.
