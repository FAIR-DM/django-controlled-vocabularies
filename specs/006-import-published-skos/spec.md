# Feature Specification: Import a published SKOS vocabulary from a file

**Feature Branch**: `006-import-published-skos`

**Created**: 2026-08-03

**Status**: Draft

**Input**: Issue [#50](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/50) — "Projects have vocabularies that already exist as published files, such as the heat-flow vocabularies and larger sets from external publishers, and no way to get them into this app short of retyping them. They want to point the app at a SKOS file, in whichever of the common serializations it happens to use, and have its concepts land as records, complete with their labels and notes, the links between them, and any collections they belong to. Running the same import again should bring the vocabulary up to date rather than wiping it and starting over, because by then other data may already reference those concepts."

**Serves**: G4 (faithful round-trip — a vocabulary the system cannot read in is one it can never give back) · G8 (external vocabularies as read-only references — reading a published file is the only way one arrives) · G6 (multilingual concepts — a published vocabulary carries its labels and notes in whatever languages it has) · **Roadmap**: R2 · **Issue**: #50

> Scope note: this is the second slice of roadmap item R2 and the one the rest of it stands on. FS-005 gave every row an identifier that can belong to an external publisher, and a lookup that resolves it. This feature reads a published file and turns it into rows matched by those identifiers. A vocabulary becomes one `ConceptScheme` row and each concept and collection one `Record` row, and every statement the file makes about each is kept in that row's `data` document, in every language (FS-007). The entry point here is **programmatic**. Running an import from the command line is FS-008, which wraps what this feature exposes. **Out of scope:** exporting or serving RDF (R4), the concept consumption field (R3), the editing interface, browsing (R6), any command-line or web-facing entry point, and importing from a URL rather than a file.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A published file becomes a vocabulary here (Priority: P1)

A vocabulary is published as a file — the heat-flow vocabularies as Turtle, an external publisher's set as RDF/XML or JSON-LD. The app is pointed at it. The vocabulary the file declares is created here, carrying the identifier its publisher gave it, and its concepts land as records, each holding its own published identifier and the statements the file makes about it. If the file declares no vocabulary, the caller has to say which one the concepts belong to. If the caller names one and the file declares another, nothing is imported, because pouring one publisher's vocabulary into another's would corrupt both.

**Why this priority**: This is the whole point of the feature and of R2 — until a real vocabulary can be read in, nothing downstream can be tested against real data. Implemented alone it already delivers the thing the issue asks for: a published file stops being something a person would have to retype.

**Independent Test**: In a test, read a small vocabulary from a fixture file in each of the three serializations and assert the vocabulary and its concepts exist, each holding the identifier the file gave it. Read a file declaring no vocabulary with and without a named target and assert the first is refused and the second succeeds. Read a file whose vocabulary identifier differs from the named target and assert nothing at all was written.

**Acceptance Scenarios**:

1. **Given** a Turtle file declaring a vocabulary and three concepts, **When** it is imported, **Then** the vocabulary exists holding the identifier the file gave it, the three concepts exist holding theirs, and each concept belongs to that vocabulary.
2. **Given** the same vocabulary published as RDF/XML and as JSON-LD, **When** each is imported into an empty database, **Then** the result is the same rows with the same identifiers in every case.
3. **Given** a file in a serialization the app does not read, or a file that cannot be parsed at all, **When** it is imported, **Then** the run fails, says so, and the database is unchanged.
4. **Given** a file whose vocabulary identifier is already held by a vocabulary here, **When** it is imported, **Then** that vocabulary is updated rather than a second one created.
5. **Given** a file declaring no vocabulary of its own, **When** it is imported with no target named, **Then** the run fails and says why. **And When** it is imported naming an existing vocabulary, **Then** its concepts are added to that one.
6. **Given** a file declaring a vocabulary, **When** it is imported naming a *different* existing vocabulary as the target, **Then** the run fails and nothing is written.
7. **Given** a file declaring more than one vocabulary, **When** it is imported with no target named, **Then** the run fails and names the vocabularies it found.
8. **Given** a file in which a concept or collection is a blank node, or has an identifier beginning `javascript:`, `data:` or `vbscript:`, **When** it is imported, **Then** the run fails, the report names the offending subject, and the database is unchanged.
9. **Given** a file with several separate problems, **When** it is imported, **Then** one run reports all of them rather than stopping at the first.
10. **Given** a vocabulary whose records' preferred labels are mostly in one language, **When** it is imported, **Then** the vocabulary's default language is that language. **And Given** a vocabulary whose labels carry no language, **Then** its default language is the site's `LANGUAGE_CODE`.
11. **Given** two concepts in one file whose identifiers end in the same segment, **When** it is imported, **Then** both exist, holding their own distinct published identifiers, and their slugs differ. **And When** the same file is imported again, **Then** each concept keeps the slug it was given.
12. **Given** any completed run, **When** its report is read, **Then** what was created, what was updated, and what is absent from the source are each available as data rather than only as a message to print.

---

### User Story 2 - Running the same import again brings the vocabulary up to date (Priority: P1)

By the time an import is run again, other data in the project may already point at these concepts. Running the file again therefore updates the vocabulary in place rather than replacing it. Every record is matched by the identifier it was published under. A concept the file still contains is brought into line with the file, including dropping a statement the publisher has corrected away. A concept the file no longer mentions is left exactly as it is and named in the report, because something may already reference it, and retiring a concept properly is a later, deliberate act rather than a side effect of reading a file.

**Why this priority**: It is the invariant the constitution makes load-bearing (Article XI: re-import is additive and upserts by identifier, never delete-and-recreate) and the reason the issue was written the way it was. A first import that cannot be run again safely is a one-shot tool that becomes dangerous the moment the vocabulary matters.

**Independent Test**: In a test, import a fixture, import it again unchanged and assert every row kept its database key and nothing was duplicated. Import an edited copy in which one concept's label changed, one label was removed, and one concept was deleted, then assert the change and the removal landed, the deleted concept is still present, and the report names it.

**Acceptance Scenarios**:

1. **Given** a vocabulary imported once, **When** the identical file is imported again, **Then** no row is duplicated, no row is recreated, and every existing reference to a concept still resolves.
2. **Given** a concept whose preferred label the publisher has since corrected, **When** the updated file is imported, **Then** the concept keeps its identifier and its database identity, and reports the new label.
3. **Given** a concept from which the publisher has removed an alternative label, a note, or a link, **When** the updated file is imported, **Then** that statement is gone from the record, because the file is authoritative for the concepts it contains.
4. **Given** a concept the updated file no longer mentions at all, **When** the file is imported, **Then** that concept is untouched — still present, still holding its identifier, still referenced — and the report names it as absent from the source.
5. **Given** a vocabulary whose own name, description or publication details the publisher has changed, **When** the updated file is imported, **Then** the vocabulary reflects the change, including a detail the file no longer gives, keeps its identifier, and keeps its default language.
6. **Given** a concept whose identifier is held by a record of another vocabulary here, **When** the file is imported, **Then** the record moves into the vocabulary being imported and takes a new slug there, because an identifier is held once.
7. **Given** a run that fails partway through for any reason, **When** the failure occurs, **Then** the database is exactly as it was before the run started.

---

### User Story 3 - The concepts arrive with every statement they carry (Priority: P2)

A published concept is more than a name. It carries preferred labels in several languages, alternative and hidden labels people search by, a definition, notes of various kinds, a notation, mappings to concepts in other vocabularies, and sometimes statements in vocabularies other than SKOS. All of it lands in the concept's document, in every language the file offers. Nothing the file says about a concept is set aside.

**Why this priority**: Labels and notes are the substance of a vocabulary — a concept with only a name is barely worth importing — and G6 is one of the goals this feature serves. It is second to the identity and re-run behaviour only because those two decide whether the data is safe, and this decides how much of it there is.

**Independent Test**: In a test, import a fixture whose concepts carry preferred labels in several languages, alternative and hidden labels, a definition, several note kinds, a notation, a mapping to another vocabulary and a predicate from outside SKOS. Assert each landed in the right concept's document, with its language, datatype or link intact.

**Acceptance Scenarios**:

1. **Given** a concept with preferred labels in several languages, **When** it is imported, **Then** every one is stored, whatever `settings.LANGUAGES` holds, and the one in the vocabulary's default language is copied into `pref_label`.
2. **Given** a concept with alternative and hidden labels, **When** it is imported, **Then** each is stored under its own predicate, in its own language, and every one is copied into `search_text`.
3. **Given** a concept with a definition and notes of several kinds, **When** it is imported, **Then** each is stored under the predicate it was published under, in its own language.
4. **Given** a concept carrying a `skos:notation`, a mapping such as `skos:exactMatch`, and a predicate from outside SKOS, **When** it is imported, **Then** each is stored in the concept's document, a mapping as a link, and none is reported as set aside.
5. **Given** a literal with a datatype other than a plain string, **When** it is imported, **Then** the value is stored with its datatype.
6. **Given** a concept with no preferred label in the vocabulary's default language, **When** it is imported, **Then** it is still created, and its `pref_label` is its first label in any language.

---

### User Story 4 - The links between concepts arrive (Priority: P2)

A vocabulary's shape is in its links: which concepts are broader than which, and which are merely related. Those arrive too, as the file stated them, in the document of the concept that stated them. A file that states both a broader and its matching narrower produces both statements, and the browsing pages show each from both ends. Publishers routinely export a slice of a larger vocabulary, so a link pointing at a concept that is neither in the file nor held here is stored like any other, and is shown by its identifier.

**Why this priority**: Without links an imported vocabulary is a flat list, and the hierarchy is what makes it navigable and what the browsing pages need. It comes after labels because a concept with no name cannot usefully be linked to anything.

**Independent Test**: In a test, import a fixture stating broader in one direction, narrower in the other, and a symmetric related pair, then assert each statement is stored in the document that made it. Include a link pointing outside the file and assert it is stored. Re-import with one link removed and assert it is gone.

**Acceptance Scenarios**:

1. **Given** a file stating that one concept is broader than another, **When** it is imported, **Then** the stating concept's document holds the link under `skos:broader`.
2. **Given** a file stating the same relationship the other way round, as narrower, **When** it is imported, **Then** the other concept's document holds it under `skos:narrower`, and both pages show the pair.
3. **Given** a file stating that two concepts are related, **When** it is imported, **Then** the statement is stored once in the document that made it, and both pages show it.
4. **Given** a link whose other end is neither in the file nor held here, **When** the file is imported, **Then** the run succeeds and the link is stored.
5. **Given** a re-import of a file from which a link has been removed, **When** it runs, **Then** the link is gone and both concepts remain.

---

### User Story 5 - Collections arrive, ordered ones in order (Priority: P2)

Published vocabularies group concepts into collections, and some of those collections are deliberately ordered — a sequence the publisher chose, which alphabetical sorting would destroy. Collections land as records of their own, holding their published identifiers, with their membership, and an ordered collection keeps the order the file gave it.

**Why this priority**: Collections are part of what the issue asks for. They are last of the P2 slices because a vocabulary is usable without them.

**Independent Test**: In a test, import a fixture containing an unordered collection and an ordered one, assert each exists holding its published identifier with the right members, and assert the ordered one reports its members in the file's order. Re-import with a member removed and assert the membership matches the file.

**Acceptance Scenarios**:

1. **Given** a file containing a collection with three members, **When** it is imported, **Then** the collection exists holding its published identifier, inside the imported vocabulary, with exactly those three concepts as members.
2. **Given** a file containing an ordered collection, **When** it is imported, **Then** the collection's type is `skos:OrderedCollection` and `member_uris()` returns its members in the order the file listed them.
3. **Given** a collection whose member is neither in the file nor held here, **When** it is imported, **Then** the collection is still created and the member is stored as stated.
4. **Given** a re-import in which a collection has gained one member and lost another, **When** it runs, **Then** the membership matches the file and the collection keeps its identifier.
5. **Given** a collection identified only by a blank node, **When** the file is imported, **Then** the run fails and names it, on the same rule that governs concepts.

---

### User Story 6 - Translatable messages, deliberate indexing, and reusable test material (Priority: P3)

Every message this feature puts in front of a person is translatable, and the fixture files and helpers it needs are left in the suite in a shape the features that follow can use rather than rebuild.

**Why this priority**: A standard carried by every slice of R1 and by FS-005 before this one (constitution Articles XII and XIII). It adds no capability but gates the merge, so it travels at P3. The fixtures are paid back immediately: FS-007 and FS-008 both need vocabularies on disk to import.

**Independent Test**: The existing standards suite walks messages; extend it to whatever this feature adds. Separately, assert the fixture files are discoverable from the suite and that importing each produces the rows its test expects.

**Acceptance Scenarios**:

1. **Given** any message this feature shows a person — a failure, or a line of the report — **When** it is produced, **Then** it is translatable and uses named placeholders rather than values baked into the text.
2. **Given** the test suite, **When** a test asks for a published vocabulary in each supported serialization, **Then** it gets a fixture file without building one inline.
3. **Given** developer-facing diagnostics, **When** they are produced, **Then** they are exempt from translation, as elsewhere in the package.

### Edge Cases

- A file declares a vocabulary and also names concepts that say they belong to a different one. A concept with no type is a record only when it says it belongs to the vocabulary being imported, so such a concept is not imported with this file.
- A subject typed as several SKOS classes becomes a record of the last class it matches, in the order concept, collection, ordered collection.
- Two concepts in one vocabulary have identifiers ending in the same segment, so both derive the same slug. The second, in URI order, gets a numeric suffix. Their identifiers are untouched and distinct.
- A statement whose object is a blank node is stored as an `@id` beginning `_:`, since nothing can resolve it.
- A file states that a concept is broader than itself, or a cycle of broader links. Both are stored as published, as FS-003 specifies.
- A subject that is neither typed as a concept or collection, nor states that it belongs to the vocabulary, is not a record, and the statements it makes are not stored.
- An import that finds no concept in the file still succeeds with a vocabulary and no records. The report says what was created.
- A very large vocabulary — tens of thousands of concepts — is the case G5 cares about. This feature must not be written in a way that forbids it, but performance work is not in scope here.
- The file's vocabulary identifier matches a vocabulary here that was created in code rather than imported. It is updated like any other match: identity is the identifier.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST expose a **programmatic import**, `import_skos()`, that takes a SKOS file and produces rows, and returns a **report** of what it did. No command-line or web-facing entry point is added here (FS-008 owns the first).
- **FR-002**: The import MUST read Turtle, RDF/XML, and JSON-LD. The caller MAY state the serialization. When they do not, it MUST be determined from the file, and a file whose serialization cannot be determined or read MUST fail the run with a translatable message.
- **FR-003**: A run MUST be all-or-nothing: if it fails, the database MUST be exactly as it was before it started. A run MUST collect and report every fatal problem it meets in the file rather than stopping at the first.
- **FR-004**: Every row the import creates or updates MUST be matched by its `uri` (FS-005). A concept, collection or vocabulary that is a blank node, or whose identifier begins `javascript:`, `data:` or `vbscript:`, MUST fail the run and be named in the report. A blank node used structurally, such as the list carrying an ordered collection's members, is not an identity and MUST be read normally.
- **FR-005**: The **file is the authority for which vocabulary is being imported.** A vocabulary the file declares MUST be created when its identifier is not held here and updated when it is. The caller MAY name a target vocabulary, which MUST then match the file's, and a mismatch MUST fail the run. A file declaring no vocabulary MUST fail the run unless the caller names the target, and a file declaring several MUST fail it unless the caller names one. A vocabulary the run creates MUST take as its default language the language most used by its records' preferred labels, or the site's `LANGUAGE_CODE` when none carries one. A vocabulary that already exists MUST keep its default language.
- **FR-006**: A concept or collection MUST be created inside the vocabulary being imported, holding the identifier the file gave it and the statements the file makes about it. A concept with no preferred label in the vocabulary's default language MUST still be created.
- **FR-007**: A record's slug MUST be derived from its published identifier — the fragment where it has one, otherwise the last path segment — and MUST be made unique within its vocabulary by a deterministic numeric suffix when the derived value is taken. The identifier MUST NOT be altered to fit a slug.
- **FR-008**: Every statement the file makes about a vocabulary, a concept or a collection MUST be stored in that row's `data` document, under the predicate it was published under, as an entry holding its value, its language or its datatype, or the URI it links to. This covers preferred, alternative and hidden labels, definitions and notes, notations, mappings to other vocabularies, links between concepts, membership, and statements in namespaces other than SKOS.
- **FR-009**: A language tag MUST be stored as published. The import MUST NOT match it against `settings.LANGUAGES`, substitute another for it, or drop it.
- **FR-010**: A link to another resource MUST be stored as stated, whether or not the target is in the file or held here. The import MUST NOT store an inverse the file did not state.
- **FR-011**: Collections MUST be created inside the imported vocabulary, holding their published identifiers, with their membership. A collection the file declares as ordered MUST be stored as `skos:OrderedCollection` and MUST keep the order the file gives its members.
- **FR-012**: **Re-running an import MUST upsert, never delete-and-recreate** (Article XI). For a record the file contains, the file MUST be authoritative for that record's own content: its document MUST end up matching the file, including the removal of statements the file no longer carries. A record the file does not mention MUST be left untouched and MUST be named in the report. No row's identifier is ever rewritten by a re-import (FS-005).
- **FR-013**: The report MUST be a structured result the caller can act on, not only text. It MUST distinguish the URIs created, the URIs updated, the URIs present here but absent from the source, and the fatal findings that refused a run. It MUST be sufficient for FS-008 to render a command-line summary and a rehearsal preview without re-reading the file.
- **FR-014**: An import MUST keep every statement it reads, in every language. A run is refused only for a subject with no usable identifier (FR-004) or a file whose vocabulary cannot be determined (FR-005). No other reason refuses a run or sets a value aside.
- **FR-015**: Every message this feature puts in front of a person, in a failure or in the report, MUST be translatable with named placeholders. Developer-facing diagnostics are exempt (Article XII).
- **FR-016**: The test suite MUST ship a published vocabulary as a fixture file in each supported serialization, discoverable from the suite, so the features that follow do not rebuild them.

### Key Entities *(include if feature involves data)*

- **Import run**: one reading of one file into one vocabulary. Atomic — it lands whole or not at all — and re-runnable, matching every row by its `uri`.
- **Import report** (`ImportReport`): the structured outcome of a run. The URIs created, the URIs updated, the URIs present here but no longer in the source, and the fatal findings that refused a run. The contract FS-008 builds on.
- **Fatal finding** (`FatalFinding`): one reason a whole run was refused, with the subject at fault and a reason from the closed set in `FatalReason`.
- **ConceptScheme**: written with its identifier, its own statements as a document, and a default language.
- **Record**: written with its type, its identifier, its slug, its document, and the copies of its name and labels.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A published vocabulary is imported from a Turtle, an RDF/XML, and a JSON-LD file, and each produces the same vocabulary and concepts holding the same published identifiers — verified by test.
- **SC-002**: Importing the same file twice leaves every row with the database identity it had after the first run, with nothing duplicated and every reference intact — verified by test.
- **SC-003**: A re-import of an edited file applies a corrected label, removes a statement the publisher dropped, and leaves a concept the file no longer mentions in place while naming it in the report — verified by test.
- **SC-004**: A failing run leaves the database exactly as it was, for at least an unparseable file, an unreadable serialization, and a refused identifier — verified by test.
- **SC-005**: One run of a file carrying several distinct problems reports all of them — verified by test.
- **SC-006**: A file declaring no vocabulary is refused with no target named and succeeds with one, and a file whose vocabulary contradicts the named target is refused with nothing written — verified by test.
- **SC-007**: Preferred, alternative, and hidden labels, definitions and notes, notations, mappings and statements outside SKOS land in the right row's document, in every language the file offers — verified by test.
- **SC-008**: A label or note in a language not in `settings.LANGUAGES` is stored, and the concept it belongs to imports — verified by test.
- **SC-009**: A vocabulary published mostly in a language other than the site's default imports with that language as its default — verified by test.
- **SC-010**: A broader stated one way, a narrower stated the other, and a related stated twice are each stored in the document of the concept that stated them, and both pages show each pair — verified by test.
- **SC-011**: A link or membership pointing outside the file does not fail the run and is stored as stated — verified by test.
- **SC-012**: An ordered collection returns its members in the file's order after an import and after a re-import that changes that order — verified by test.
- **SC-013**: The report distinguishes created, updated, absent-from-source and fatal, as data rather than prose — verified by test.
- **SC-014**: Every message this feature shows a person is translatable with named placeholders — verified by the standards test.
- **SC-015**: A published vocabulary fixture exists in each supported serialization and is loaded by the tests from the suite rather than built inline — verified by test.
- **SC-016**: Two concepts whose identifiers derive the same slug both import with distinct slugs and distinct identifiers, and each keeps its slug when the same file is imported again — verified by test.
- **SC-017**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python and Django matrix.

## Assumptions

- **Everything a file says is kept.** A vocabulary and each of its records hold a JSON document of the statements as published, so no statement needs a column of its own and none is dropped for want of one. A row's name and labels are also copied into `pref_label` and `search_text` for sorting and searching.
- **Deletion is never a consequence of reading a file.** A concept absent from the source is reported, not removed. Retiring a concept is a deliberate act, left to a later feature.
- **A file, not a URL.** The import reads a file the caller supplies. Fetching a vocabulary over the network is the command's own step (FS-008), and brings in retries, caching, redirects and content negotiation that this feature does not.
- **The parsing library is a planning decision.** The package depends on rdflib for the RDF boundary and the constitution names it, but how the file is read, how the graph is traversed, and how the work is batched are decisions for planning. The specification fixes what must be true of the result.
- **Performance is bounded but not designed here.** G5 wants tens of thousands of concepts to stay responsive. This feature must not preclude that, but no throughput target is set and none is tested.
