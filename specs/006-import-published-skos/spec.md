# Feature Specification: Import a published SKOS vocabulary from a file

**Feature Branch**: `006-import-published-skos`

**Created**: 2026-08-03

**Status**: Draft

**Input**: Issue [#50](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/50) — "Curators have vocabularies that already exist as published files, such as the heat-flow vocabularies and larger sets from external publishers, and no way to get them into this app short of retyping them. They want to point the app at a SKOS file, in whichever of the common serializations it happens to use, and have its concepts land as ordinary editable records, complete with their labels and notes, the relationships between them, and any collections they belong to. Running the same import again should bring the vocabulary up to date rather than wiping it and starting over, because by then other data may already reference those concepts."

**Serves**: G4 (faithful round-trip — a vocabulary the system cannot read in is one it can never give back) · G8 (external vocabularies as read-only references — reading a published file is the only way one arrives) · G6 (multilingual concepts — a published vocabulary carries its labels and notes in whatever languages it has) · **Roadmap**: R2 · **Issue**: #50

> Scope note: this is the second slice of roadmap item R2 and the one the rest of it stands on. [#49](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/49) gave every record an identifier that can belong to an external publisher, and a lookup that resolves it; this feature reads a published file and turns it into records matched by those identifiers. The entry point here is **programmatic** — running an import from the command line is [#52](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/52), which wraps what this feature exposes. Language handling is bounded deliberately (see Clarifications): this feature keeps what the models can store and reports the rest, while [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51) owns how that reporting reads to a curator and the guarantee that a re-import fills in a language added to the site afterwards. **Out of scope:** exporting or serving RDF (R4), the concept consumption field (R3), the editing interface (R5), browsing (R6), verbatim storage of predicates the models do not hold (see Assumptions — it needs the document store and the export that reads it back out), any command-line or web-facing entry point, and importing from a URL rather than a file.

## Clarifications

### Session 2026-08-03

Five ambiguities surfaced by the coverage scan, resolved against the intake discussion, the constitution, and what R1's models actually enforce. Longer rationale is in `decisions.md`.

- **Q: Which languages may an import store?** → A: Only the languages the site is configured for. This is not really a policy choice available to this feature: `ConceptLabel` and `ConceptNote` both refuse a `language` outside `settings.LANGUAGES`, and they do it on the write path R1 built for exactly this purpose — `Concept.add_label` and `Concept.add_note` validate before saving. An import could evade the check by writing rows directly, but that means deliberately breaking an invariant the models state, to store content the app has no way to display. So a value in an unconfigured language is set aside and reported, exactly like a predicate the models do not hold. This narrows what [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51) has left to build — the mechanical filtering is unavoidable here — leaving it the curator-facing quality of that report and the explicit guarantee that a re-import populates a language added to the site after the first run. Integrated into FR-014 and FR-015.
- **Q: What decides the imported vocabulary's default language?** → A: The file, where it says: the language the vocabulary declares itself in if the site is configured for it, otherwise the language most of its preferred labels use if the site is configured for it, otherwise the site's own default. The vocabulary's default language anchors every concept's identity (`Concept.label` is the preferred label in that language, and the slug derives from it), so importing a French vocabulary into a site whose default is English must not leave every concept unable to name itself. Integrated into FR-005.
- **Q: What happens to a concept with no preferred label in that default language?** → A: It is set aside and reported, and the run continues. `Concept.label` is required and its slug derives from it, so there is no record to create. This is not fatal: one unusable concept in a large vocabulary should not cost the curator the other ten thousand, and the report names it. Relationships pointing at it are set aside by the same rule that covers any missing end (FR-011). Integrated into FR-006.
- **Q: Where does an imported record's slug come from, and what happens when two collide?** → A: From the label, by the derivation R1 already applies on save, with a deterministic numeric suffix when that slug is already taken inside the same vocabulary. Nothing is invented: identity is the static URI, and the slug only decides where the record is viewed on this site. A slug that moves on a later re-import because the publisher renamed the concept is acceptable and expected — [#49](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/49) established that a local URL follows a rename while the identifier does not. Integrated into FR-007.
- **Q: A concept or collection identified only by a blank node — set aside or fatal?** → A: Fatal. Every record this app stores is matched by its identifier, on the first run and on every re-run, and a blank node supplies none. Inventing one would produce a record that duplicates itself the next time the same file is read, which is the precise failure the upsert rule exists to prevent. A blank node used *structurally* — the list that carries an ordered collection's members — is not an identity and is read normally. Integrated into FR-004.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A published file becomes a vocabulary here (Priority: P1)

A curator has a vocabulary published as a file — the heat-flow vocabularies as Turtle, an external publisher's set as RDF/XML or JSON-LD. They point the app at it. The vocabulary the file declares is created here, carrying the identifier its publisher gave it, and its concepts land as ordinary records, each holding its own published identifier and its preferred label. If the file declares no vocabulary, the caller has to say which one the concepts belong to; if the caller names one and the file declares another, nothing is imported, because pouring one publisher's vocabulary into another's would corrupt both.

**Why this priority**: This is the whole point of the feature and of R2 — until a real vocabulary can be read in, nothing downstream can be tested against real data. Implemented alone it already delivers the thing the issue asks for: a published file stops being something a curator would have to retype.

**Independent Test**: In a test, read a small vocabulary from a fixture file in each of the three serializations and assert the vocabulary and its concepts exist, each holding the identifier the file gave it; read a file declaring no vocabulary with and without a named target and assert the first is refused and the second succeeds; read a file whose vocabulary identifier differs from the named target and assert nothing at all was written.

**Acceptance Scenarios**:

1. **Given** a Turtle file declaring a vocabulary and three concepts, **When** it is imported, **Then** the vocabulary exists holding the identifier the file gave it, the three concepts exist holding theirs, and each concept belongs to that vocabulary.
2. **Given** the same vocabulary published as RDF/XML and as JSON-LD, **When** each is imported into an empty database, **Then** the result is the same records with the same identifiers in every case.
3. **Given** a file in a serialization the app does not read, or a file that cannot be parsed at all, **When** it is imported, **Then** the run fails, says so, and the database is unchanged.
4. **Given** a file whose vocabulary identifier is already held by a vocabulary here, **When** it is imported, **Then** that vocabulary is updated rather than a second one created.
5. **Given** a file declaring no vocabulary of its own, **When** it is imported with no target named, **Then** the run fails and says why; **and When** it is imported naming an existing vocabulary, **Then** its concepts are added to that one.
6. **Given** a file declaring a vocabulary, **When** it is imported naming a *different* existing vocabulary as the target, **Then** the run fails and nothing is written.
7. **Given** a file in which a concept carries no identifier, only a blank node, or one whose identifier the identity rules refuse, **When** it is imported, **Then** the run fails, the report names the offending concept, and the database is unchanged.
8. **Given** a file with several separate problems, **When** it is imported, **Then** one run reports all of them rather than stopping at the first.
9. **Given** a vocabulary published in a language other than the site's default, which the site is configured for, **When** it is imported, **Then** the vocabulary's default language is the one the file uses and every concept carries its own label; **and Given** a vocabulary in a language the site is not configured for at all, **When** it is imported, **Then** the vocabulary falls back to the site's default language.
10. **Given** two concepts in one file whose preferred labels derive the same slug, **When** it is imported, **Then** both concepts exist, holding their own distinct published identifiers, and their slugs differ; **and When** the same file is imported again, **Then** each concept keeps the slug it was given.
11. **Given** any completed run, **When** its report is read, **Then** what was created, what was updated, and what was set aside with its reason are each available as data rather than only as a message to print.

---

### User Story 2 - Running the same import again brings the vocabulary up to date (Priority: P1)

By the time a curator re-runs an import, other data in the project may already point at these concepts. Re-running the file therefore updates the vocabulary in place rather than replacing it. Every record is matched by the identifier it was published under. A concept the file still contains is brought into line with the file, including dropping a label the publisher has corrected away. A concept the file no longer mentions is left exactly as it is and named in the report, because something may already reference it and retiring a concept properly is a later, deliberate act rather than a side effect of reading a file.

**Why this priority**: It is the invariant the constitution makes load-bearing (Article XI: re-import is additive and upserts by identifier, never delete-and-recreate) and the reason the issue was written the way it was. A first import that cannot be re-run safely is a one-shot tool that becomes dangerous the moment the vocabulary matters.

**Independent Test**: In a test, import a fixture, import it again unchanged and assert every record kept its database key and nothing was duplicated; import an edited copy in which one concept's label changed, one label was removed, and one concept was deleted, then assert the change and the removal landed, the deleted concept is still present, and the report names it.

**Acceptance Scenarios**:

1. **Given** a vocabulary imported once, **When** the identical file is imported again, **Then** no record is duplicated, no record is recreated, and every existing reference to a concept still resolves.
2. **Given** a concept whose preferred label the publisher has since corrected, **When** the updated file is imported, **Then** the concept keeps its identifier and its database identity, and reports the new label.
3. **Given** a concept from which the publisher has removed an alternative label, a note, or a relationship, **When** the updated file is imported, **Then** that value is gone from the record, because the file is authoritative for the concepts it contains.
4. **Given** a concept the updated file no longer mentions at all, **When** the file is imported, **Then** that concept is untouched — still present, still holding its identifier, still referenced — and the report names it as no longer present in the source.
5. **Given** a vocabulary whose own name, description or publication details the publisher has changed, **When** the updated file is imported, **Then** the vocabulary reflects the change, including a detail the file no longer gives, and keeps its identifier.
6. **Given** a run that fails partway through for any reason, **When** the failure occurs, **Then** the database is exactly as it was before the run started.

---

### User Story 3 - The concepts arrive with their labels and notes (Priority: P2)

A published concept is more than a name. It carries preferred labels in several languages, alternative and hidden labels people search by, a definition, and notes of various kinds. All of it lands as ordinary editable records, in every language the site is configured for. Content in a language the site does not support cannot be stored and is reported rather than dropped in silence, and so is any part of the file the models have no place for.

**Why this priority**: Labels and notes are the substance of a vocabulary — a concept with only a default-language name is barely worth importing — and G6 is one of the goals this feature serves. It is second to the identity and re-run behaviour only because those two decide whether the data is safe, and this decides how much of it there is.

**Independent Test**: In a test, import a fixture whose concepts carry preferred labels in two configured languages, alternative and hidden labels, a definition and several note kinds, then assert each landed against the right concept with the right language and kind; include a label in an unconfigured language and a predicate the models do not hold, and assert both are named in the report and neither is stored.

**Acceptance Scenarios**:

1. **Given** a concept with preferred labels in two languages the site is configured for, **When** it is imported, **Then** both are stored, and the one in the vocabulary's default language is the concept's own label.
2. **Given** a concept with alternative and hidden labels, **When** it is imported, **Then** each is stored against that concept as its own kind, in its own language.
3. **Given** a concept with a definition and notes of several kinds, **When** it is imported, **Then** each is stored as a note of the matching kind, in its own language.
4. **Given** a concept carrying a label or note in a language the site is not configured for, **When** it is imported, **Then** nothing is stored for that language and the report names the language and how many values it set aside.
5. **Given** a file carrying values the models have no place for — a notation, a mapping to another vocabulary, a predicate from outside SKOS — **When** it is imported, **Then** the concepts still import, and the report names what was set aside rather than passing over it silently.
6. **Given** a concept with no preferred label in the vocabulary's default language, **When** it is imported, **Then** that concept is set aside and named in the report, and the rest of the vocabulary imports.

---

### User Story 4 - The relationships between concepts arrive (Priority: P2)

A vocabulary's shape is in its relationships: which concepts are broader than which, and which are merely related. Those arrive too, in the single canonical direction the app stores, so a file that states both a broader and its matching narrower produces one relationship rather than two contradictory ones. Publishers routinely export a slice of a larger vocabulary, so a relationship pointing at a concept that is neither in the file nor already here is set aside and reported rather than failing the run.

**Why this priority**: Without relationships an imported vocabulary is a flat list, and the hierarchy is what makes it navigable and what R3's subtree-scoped consumption will need. It comes after labels because a concept with no name cannot usefully be related to anything.

**Independent Test**: In a test, import a fixture stating broader in one direction, narrower in the other, and a symmetric related pair, then assert exactly one relationship exists per pair and in the canonical direction; include a relationship pointing outside the file and assert it is reported and not stored; re-import with one relationship removed and assert it is gone.

**Acceptance Scenarios**:

1. **Given** a file stating that one concept is broader than another, **When** it is imported, **Then** one relationship exists between them in the canonical direction.
2. **Given** a file stating the same relationship the other way round, as narrower, **When** it is imported, **Then** the same single canonical relationship results, not a second one.
3. **Given** a file stating both directions of the same pair, **When** it is imported, **Then** exactly one relationship is stored and nothing is duplicated.
4. **Given** a file stating that two concepts are related, **When** it is imported, **Then** one symmetric relationship is stored, not one in each direction.
5. **Given** a relationship whose other end is neither in the file nor already in the database, **When** the file is imported, **Then** the run succeeds, the relationship is not stored, and the report names both ends.
6. **Given** a relationship whose other end is not in the file but *is* already here from an earlier import, **When** the file is imported, **Then** the relationship is stored.
7. **Given** a re-import of a file from which a relationship has been removed, **When** it runs, **Then** the relationship is gone and both concepts remain.

---

### User Story 5 - Collections arrive, ordered ones in order (Priority: P2)

Published vocabularies group concepts into collections, and some of those collections are deliberately ordered — a sequence a curator chose, which alphabetical sorting would destroy. Collections land as records of their own, holding their published identifiers, with their membership, and an ordered collection keeps the order the file gave it.

**Why this priority**: Collections are part of what the issue asks for and R1 already models them, including ordering. They are last of the P2 slices because a vocabulary is usable without them, and a collection whose concepts failed to import would have nothing to hold.

**Independent Test**: In a test, import a fixture containing an unordered collection and an ordered one, assert each exists holding its published identifier with the right members, and assert the ordered one reports its members in the file's order; re-import with a member removed and assert the membership matches the file.

**Acceptance Scenarios**:

1. **Given** a file containing a collection with three members, **When** it is imported, **Then** the collection exists holding its published identifier, inside the imported vocabulary, with exactly those three concepts as members.
2. **Given** a file containing an ordered collection, **When** it is imported, **Then** the collection is marked as ordered and its members come back in the order the file listed them.
3. **Given** a collection whose member is a concept that is neither in the file nor already here, **When** it is imported, **Then** the collection is still created, that member is not stored, and the report names it.
4. **Given** a re-import in which a collection has gained one member and lost another, **When** it runs, **Then** the membership matches the file and the collection keeps its identifier.
5. **Given** a collection identified only by a blank node, **When** the file is imported, **Then** the run fails and names it, on the same rule that governs concepts.

---

### User Story 6 - Translatable messages, deliberate indexing, and reusable test material (Priority: P3)

Every message this feature puts in front of a person is translatable, any field it adds is a deliberate indexing decision with translatable metadata, and the fixture files and helpers it needs are left in the suite in a shape the two features that follow can use rather than rebuild.

**Why this priority**: A family-wide standard carried by every slice of R1 and by [#49](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/49) before this one (constitution Articles XII and XIII). It adds no capability but gates the merge, so it travels at P3. The fixtures are paid back immediately: [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51) and [#52](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/52) both need vocabularies on disk to import.

**Independent Test**: The existing standards suite walks model fields and messages; extend it to whatever this feature adds. Separately, assert the fixture files are discoverable from the suite and that importing each produces the records its test expects.

**Acceptance Scenarios**:

1. **Given** any message this feature shows a person — a failure, or an entry in the report — **When** it is produced, **Then** it is translatable and uses named placeholders rather than values baked into the text.
2. **Given** any model field this feature adds, **When** its metadata is inspected, **Then** it declares a translatable label and non-empty help text, and its indexing is a recorded decision.
3. **Given** the test suite, **When** a test asks for a published vocabulary in each supported serialization, **Then** it gets a fixture file without building one inline.
4. **Given** developer-facing diagnostics, **When** they are produced, **Then** they are exempt from translation, as elsewhere in the package.

### Edge Cases

- A file both declares a vocabulary and names concepts that say they belong to a different one. The concepts that claim another vocabulary are set aside and reported; the run does not silently move them.
- A concept appears twice in the same file under the same identifier, with conflicting labels. The file is malformed in a way the app cannot resolve, so the run fails and names the identifier rather than picking a winner.
- Two concepts in one vocabulary have the same preferred label, so both derive the same slug. The second gets a deterministic suffix. Their identifiers are untouched and distinct.
- A file states that a concept is broader than itself, or a cycle of broader relationships. The existing model rules refuse a self-relationship; a cycle is not something this feature detects, and the graph coherence rules R1 established apply unchanged.
- A vocabulary is imported into a site, and later a concept's identifier is found to be held by a record of a different kind — a collection in one file, a concept in another. This is a contradictory source and is reported while reading, rather than surfacing as a database constraint violation.
- An import that sets aside every concept in the file still succeeds, with an empty vocabulary and a report saying so. A file the app could read but could take nothing from is not a failure of the run; it is a fact about the file, and the report is where it belongs.
- Re-importing a file after the site has been configured for an additional language brings in the values for that language, because the file is authoritative for the concepts it contains. Guaranteeing and testing that behaviour deliberately is [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51).
- A very large vocabulary — tens of thousands of concepts — is the case G5 cares about. This feature must not be written in a way that forbids it, but performance work is not in scope here.
- The file's vocabulary identifier matches a vocabulary here that was authored locally rather than imported. It is updated like any other match: identity is the identifier, and how a locally authored vocabulary came to hold a published identifier is not this feature's business.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST expose a **programmatic import** that takes a SKOS file and produces records, and returns a **report** of what it did. No command-line or web-facing entry point is added here (#52 owns the first).
- **FR-002**: The import MUST read Turtle, RDF/XML, and JSON-LD. The caller MAY state the serialization; when they do not, it MUST be determined from the file, and a file whose serialization cannot be determined or read MUST fail the run with a translatable message.
- **FR-003**: A run MUST be all-or-nothing: if it fails, the database MUST be exactly as it was before it started. A run MUST collect and report every problem it meets rather than stopping at the first.
- **FR-004**: Every record the import creates or updates MUST be matched by its **static URI** (#49). A vocabulary, concept, or collection whose identifier is absent, is a blank node, or is refused by the identity rules MUST fail the run and be named in the report. A blank node used structurally — the list carrying an ordered collection's members — is not an identity and MUST be read normally.
- **FR-005**: The **file is the authority for which vocabulary is being imported.** A vocabulary the file declares MUST be created when its identifier is not held here and updated when it is. The caller MAY name a target vocabulary, which MUST then match the file's; a mismatch MUST fail the run. A file declaring no vocabulary MUST fail the run unless the caller names the target. An imported vocabulary's default language MUST be taken from the file where the file says — the language it declares itself in, else the language most of its preferred labels use — and MUST fall back to the site's default when neither is a language the site is configured for.
- **FR-006**: Concepts MUST be created inside the vocabulary being imported, each holding the identifier the file gave it and its preferred label in the vocabulary's default language. A concept carrying no preferred label in that language MUST be set aside and reported, and MUST NOT fail the run.
- **FR-007**: An imported record's slug MUST be derived by the rule the models already apply, and MUST be made unique within its vocabulary by a deterministic suffix when the derived value is taken. A slug MUST NOT be derived from the identifier, and the identifier MUST NOT be altered to fit a slug.
- **FR-008**: Preferred, alternative, and hidden labels MUST be stored against their concept, each with its language and kind.
- **FR-009**: Definitions and notes MUST be stored against their concept as the matching note kind, each with its language. A source predicate normalised onto another — a foreign description read as a definition — MUST be reported, never applied silently (Article XI).
- **FR-010**: Relationships between concepts MUST be stored in the single canonical direction the models hold. A file stating both a relationship and its inverse, or stating a symmetric relationship in both directions, MUST produce exactly one stored relationship.
- **FR-011**: A relationship or collection membership whose other end is neither in the file nor already in the database MUST be set aside and reported, and MUST NOT fail the run. One whose other end is already in the database from an earlier import MUST be stored.
- **FR-012**: Collections MUST be created inside the imported vocabulary, holding their published identifiers, with their membership. A collection the file declares as ordered MUST be marked ordered and MUST keep the order the file gives.
- **FR-013**: **Re-running an import MUST upsert, never delete-and-recreate** (Article XI). For a record the file contains, the file MUST be authoritative for that record's own content — labels, notes, relationships, and membership MUST end up matching the file, including the removal of values the file no longer carries. A record the file does not mention MUST be left untouched and MUST be named in the report. No record's identifier is ever rewritten by a re-import (#49, FR-002 there).
- **FR-014**: Values the app cannot store MUST be set aside and reported, never dropped in silence (Article XI). This covers at least: content in a language the site is not configured for, predicates the models have no place for, notations, and mappings to other vocabularies.
- **FR-015**: The report MUST be a structured result the caller can act on, not only text. It MUST distinguish what was created, what was updated, what was set aside and why, what was stored under a different predicate than the file used and why, and what is present here but absent from the source. It MUST be sufficient for #52 to render a command-line summary and a rehearsal preview without re-reading the file. *(Amended during implementation, decisions.md D26: "stored, but not verbatim" is a fifth outcome, and filing it under set-aside would make that bucket — the one #51 filters on — mean two different things.)*
- **FR-016**: Every message this feature puts in front of a person, in a failure or in the report, MUST be translatable with named placeholders. Developer-facing diagnostics are exempt (Article XII).
- **FR-017**: Any model field this feature adds MUST carry translatable metadata and non-empty help text, and its indexing MUST be a deliberate recorded decision (Articles XII and XIII).
- **FR-019**: A vocabulary's publication details MUST be kept on the vocabulary: its publisher (`dcterms:publisher`), creator (`dcterms:creator`), licence (`dcterms:license`), version (`owl:versionInfo`) and last-modified date (`dcterms:modified`). Each holds one value, a literal's text or an address as published. Where the file gives several, the first in alphabetical order MUST be kept and each other MUST be reported as set aside. A last-modified date and time MUST keep its date and be reported as normalised, and a last-modified value that is not a date MUST be set aside and reported. A detail the file does not give MUST be cleared, as the description is.
- **FR-018**: The test suite MUST ship a published vocabulary as a fixture file in each supported serialization, discoverable from the suite, so the features that follow do not rebuild them.

### Key Entities *(include if feature involves data)*

- **Import run**: one reading of one file into one vocabulary. Atomic — it lands whole or not at all — and re-runnable, matching every record by its static URI.
- **Import report**: the structured outcome of a run. What was created, what was updated, what was set aside and why, what was normalised and why, and what is here but no longer in the source. The contract #51 and #52 build on.
- **Set-aside entry**: one thing the run could not store, with what it was and why. A language the site is not configured for, a predicate with no home in the models, a relationship end that does not exist, a concept with no usable preferred label.
- **Normalisation entry**: one thing the run *did* store, but under a different predicate than the file used, with what it was and why — a foreign description read as a definition, say. Distinct from a set-aside entry because the value is in the database, and a caller filtering set-aside entries is asking what did not make it in (decisions.md D26).
- **ConceptScheme**: written with its name, description and default language, and with the five publication details of FR-019, which it holds in fields of its own.
- **Concept, Collection, ConceptLabel, ConceptNote, ConceptRelation, CollectionMember (unchanged)**: written as R1 defined them, through the identity #49 established.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A published vocabulary is imported from a Turtle, an RDF/XML, and a JSON-LD file, and each produces the same vocabulary and concepts holding the same published identifiers — verified by test.
- **SC-002**: Importing the same file twice leaves every record with the database identity it had after the first run, with nothing duplicated and every reference intact — verified by test.
- **SC-003**: A re-import of an edited file applies a corrected label, removes a value the publisher dropped, and leaves a concept the file no longer mentions in place while naming it in the report — verified by test.
- **SC-004**: A failing run leaves the database exactly as it was, for at least an unparseable file, an unreadable serialization, and a refused identifier — verified by test.
- **SC-005**: One run of a file carrying several distinct problems reports all of them — verified by test.
- **SC-006**: A file declaring no vocabulary is refused with no target named and succeeds with one, and a file whose vocabulary contradicts the named target is refused with nothing written — verified by test.
- **SC-007**: Preferred, alternative, and hidden labels, and definitions and notes of each supported kind, land against the right concept in the right language — verified by test.
- **SC-008**: A label or note in a language the site is not configured for is stored nowhere and named in the report, and the concept it belongs to still imports — verified by test.
- **SC-009**: A vocabulary published in a language other than the site's default imports with that language as its default and every concept named — verified by test.
- **SC-010**: A broader stated one way, a narrower stated the other, and a related stated twice each produce exactly one stored relationship in the canonical direction — verified by test.
- **SC-011**: A relationship or membership pointing outside the file does not fail the run, is named in the report, and is stored when its other end is already in the database — verified by test.
- **SC-012**: An ordered collection returns its members in the file's order after an import and after a re-import that changes that order — verified by test.
- **SC-013**: Values the models cannot hold — a notation, a mapping, an unmodelled predicate — are named in the report and the run still succeeds — verified by test.
- **SC-014**: The report distinguishes created, updated, set aside with a reason, normalised with a reason, and present-but-absent-from-source, as data rather than prose — verified by test.
- **SC-015**: Every message this feature shows a person is translatable with named placeholders — verified by the standards test.
- **SC-016**: A published vocabulary fixture exists in each supported serialization and is loaded by the tests from the suite rather than built inline — verified by test.
- **SC-017**: Two concepts whose labels derive the same slug both import with distinct slugs and distinct identifiers, and each keeps its slug when the same file is imported again — verified by test.
- **SC-018**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python and Django matrix.

## Assumptions

- **Verbatim storage of everything is not on the table yet.** The constitution's escrow promise — unknown predicates held verbatim and re-emitted — needs a document store the models do not have, and it only pays off once export exists to read it back out (R4). Confirmed at grilling: this feature imports what the models can hold and reports the rest, and escrow becomes its own feature sequenced with export. Until then, "nothing is dropped silently" is met by the report rather than by storage.
- **The models decide the language boundary, not this feature.** `ConceptLabel` and `ConceptNote` refuse a language the site is not configured for on the write path R1 provides, so filtering is very nearly mechanical rather than chosen. What [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51) is left owning is how that lands in front of a curator and the explicit additive-re-import guarantee. This is surfaced at the Spec gate rather than settled here, because it changes what a sibling issue is for.
- **Deletion is never a consequence of reading a file.** A concept absent from the source is reported, not removed. Retiring a concept is deprecation, which arrives with the lifecycle work in R4 ([#19](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/19)). Confirmed at grilling.
- **A file, not a URL.** The import reads a file the caller supplies. Fetching a vocabulary over the network brings in retries, caching, redirects, and content negotiation, none of which the issue asks for.
- **Which SKOS constructs map where is fixed by R1's models.** The mapping from SKOS predicates onto labels, notes, relationships, and collections follows what the models already define, including the canonical relationship direction and the note kinds. Where a source uses a construct with an obvious equivalent, normalising it is allowed and must be reported (Article XI); where it does not, the value is set aside.
- **The parsing library is a planning decision.** The package already depends on rdflib for the RDF boundary and the constitution names it, but how the file is read, how the graph is traversed, and how the work is batched are S3 decisions. The specification fixes what must be true of the result.
- **Performance is bounded but not designed here.** G5 wants tens of thousands of concepts to stay responsive. This feature must not preclude that, and the reading strategy is chosen at planning with it in mind, but no throughput target is set and none is tested.
