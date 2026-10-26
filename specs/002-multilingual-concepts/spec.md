# Feature Specification: Multilingual names and descriptions for concepts

**Feature Branch**: `002-multilingual-concepts`

**Created**: 2026-07-24

**Status**: Draft

**Input**: Issue [#16](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/16) — "Each concept should carry its names and descriptions in several languages: a preferred name per language, plus any number of alternative and hidden names, and definitions and notes that also vary by language."

**Serves**: G6 (multilingual concepts — labels and definitions carry per-language values) · **Roadmap**: R1 · **Issue**: #16

> Scope note: this feature covers how a record's names and descriptions are held in several languages, and how a record's identity behaves once names exist in many languages. Every statement is an entry in the record's `data` document, tagged with its language, so a record holds any number of languages and the site's `LANGUAGES` setting does not limit them. Interaction is purely programmatic — no admin or editor UI. Links between concepts (FS-003), collections (FS-004), importing a file (FS-006) and the browsing pages (FS-014, FS-015) are separate features that read what this one stores.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preferred labels in several languages, identity preserved (Priority: P1)

A concept holds a preferred label in each language its publisher used — "Heat flow" (en), "Wärmefluss" (de) — and any one language's preferred label can be read back. The vocabulary's **default language** decides which of them is copied into the record's `pref_label` column. A record's stable identity (its slug and URI) is fixed when the record is first saved, so adding, changing or removing a label in any language never disturbs it.

**Why this priority**: This is the core promise of the feature and the whole of goal G6's minimum. It also settles the question the multilingual model forces — which label names a concept in lists and sorting — without which none of the richer label or note stories are safe to build. Implemented alone, it is a viable multilingual concept.

**Independent Test**: In a test, create a vocabulary and a concept with preferred labels in two languages, read each back by language, then add and edit a non-default-language label and assert the concept's URI and slug are unchanged.

**Acceptance Scenarios**:

1. **Given** a vocabulary whose default language is English, **When** a concept is saved with the English preferred label "Heat flow" and a German preferred label "Wärmefluss", **Then** `label("en")` returns "Heat flow", `label("de")` returns "Wärmefluss", `pref_label` is "Heat flow", and the concept's slug is `heat-flow`.
2. **Given** that concept, **When** the German preferred label is changed to "Terrestrischer Wärmefluss" or removed entirely and the concept is saved, **Then** the concept's slug and URI are unchanged.
3. **Given** that concept, **When** the English preferred label is changed to "Terrestrial heat flow" and the concept is saved, **Then** `pref_label` is "Terrestrial heat flow" and the slug and URI are unchanged.
4. **Given** a concept that holds only a German preferred label in a vocabulary whose default language is English, **When** it is saved, **Then** its `pref_label` is the German label, so the concept is still listed under a name.
5. **Given** a concept with preferred labels in two languages, **When** `display_label()` is called while a language is active, **Then** it returns the label in the active language, and `pref_label` when the concept has none in that language.

---

### User Story 2 - Alternative and hidden labels per language (Priority: P2)

A concept holds any number of alternative names and any number of hidden names in each language — synonyms a person might search by ("terrestrial heat flow", "geothermal heat flow") and misspellings or deprecated forms to catch but not display — each tagged to its language and independent of the preferred label.

**Why this priority**: Alternative and hidden labels are what make a vocabulary findable and forgiving of how people actually type. They build directly on US-1's per-language label mechanism but are not needed for the identity model to be correct, so they follow it.

**Independent Test**: In a test, store several alternative and hidden labels in two languages on a concept, read them back filtered by language, and assert the counts and language tags are preserved and that they are distinct from the preferred label.

**Acceptance Scenarios**:

1. **Given** a concept with an English preferred label, **When** its document holds two English alternative labels and one German alternative label, **Then** the entries under `skos:altLabel` with the language `en` are both English values and none of the German one.
2. **Given** a concept, **When** its document holds hidden labels in a language, **Then** they are stored and readable per language and are held separately from alternative labels.
3. **Given** a concept, **When** its alternative or hidden labels are added, changed or removed, **Then** its slug and URI are unaffected.
4. **Given** a concept with preferred, alternative and hidden labels in several languages, **When** it is saved, **Then** `search_text` holds every one of them, one per line.

---

### User Story 3 - Definitions and documentary notes per language (Priority: P2)

A concept holds its meaning and editorial context in each language: a definition, and any of the SKOS documentary notes — scope note, example, editorial note, history note, change note, and a general note — each language-tagged, so a reader in any language gets the concept explained in theirs.

**Why this priority**: Descriptions are half of what issue #16 asks for and are what a published vocabulary needs to be usable rather than a bare list of names. They reuse US-1's per-language mechanism, but the vocabulary is navigable without them, so they sit at P2 alongside the other label enrichments.

**Independent Test**: In a test, store a definition and each kind of documentary note in two languages on a concept, read them back filtered by language, and assert each note type is held and returned distinctly and tagged to its language.

**Acceptance Scenarios**:

1. **Given** a concept, **When** its document holds an English and a German definition, **Then** each is readable by its language.
2. **Given** a concept, **When** its document holds a scope note, an example, an editorial note, a history note, a change note and a general note in a language, **Then** each is stored under its own predicate and readable per language.
3. **Given** a concept, **When** definitions or notes are added, changed or removed in any language, **Then** the concept's slug and URI are unaffected.

---

### User Story 4 - Per-vocabulary default language (Priority: P2)

A site hosting several vocabularies in different working languages gives each vocabulary a default language. A German vocabulary copies its concepts' German preferred labels into `pref_label`, and an English one its English labels. A vocabulary an import creates takes the most common language among its records' preferred labels, and the site's `LANGUAGE_CODE` when no label carries a language.

**Why this priority**: The package is explicitly meant to host several independently published vocabularies at once, and they will not all share one language. Without a per-vocabulary default, a German vocabulary in an English-language site would be sorted and listed under whichever label came first. It refines US-1's naming rule rather than standing alone, so it follows it.

**Independent Test**: In a test, create two vocabularies with different default languages, add a concept to each with preferred labels in both languages, and assert each concept's `pref_label` is the label in its own vocabulary's default language.

**Acceptance Scenarios**:

1. **Given** a vocabulary whose default language is `en`, **When** a concept with English and German preferred labels is saved, **Then** its `pref_label` is the English one.
2. **Given** a vocabulary whose default language is `de`, **When** a concept with English and German preferred labels is saved, **Then** its `pref_label` is the German one.
3. **Given** a vocabulary, **When** its default language is read, **Then** it reports the value stored on the vocabulary, which is required.
4. **Given** a file that declares a vocabulary whose records' preferred labels are mostly German, **When** it is imported, **Then** the new vocabulary's default language is `de`.

---

### User Story 5 - A slug that can be supplied (Priority: P2)

A developer who does not want a record's slug derived from its label — because the label's language is awkward in a URL, or a specific stable path is wanted — supplies the slug when the record is created. The slug is kept exactly as given, and later changes to the preferred label do not move it.

**Why this priority**: It removes the sharp edge of anchoring identity to a label, since nothing forces an identifier the developer did not choose. It is a refinement of the identity model, so P2.

**Independent Test**: In a test, create a concept with a supplied slug, assert the slug is exactly what was supplied, then change the preferred label and assert the slug does not change; create a second concept without a slug and assert it is derived from the label.

**Acceptance Scenarios**:

1. **Given** a new concept, **When** a slug is supplied, **Then** the concept's slug is exactly that value and is not derived from the preferred label.
2. **Given** a concept with a supplied slug, **When** its preferred label changes, **Then** the slug is unchanged.
3. **Given** a concept created without a slug or a URI, **When** it is saved, **Then** the slug is derived from its preferred label.
4. **Given** a supplied slug that another record of the same vocabulary holds, **When** the concept is validated, **Then** it is refused, because a slug is unique within its vocabulary.

---

### User Story 6 - Multilingual test scaffolding (Priority: P3)

A contributor building a later feature constructs a concept already populated with labels and notes across several languages in a couple of lines, using the test factories, instead of assembling multilingual state by hand in every test.

**Why this priority**: Every sibling feature and the import work need multilingual test data. It is cheap to add here and paid back immediately, but nothing ships to a user because of it, so P3.

**Independent Test**: Write a test that asks the factory for a multilingual concept and asserts it has preferred labels and at least one note in more than one language.

**Acceptance Scenarios**:

1. **Given** the test suite, **When** a test requests a multilingual concept from the factory, **Then** it receives a valid, saved concept with preferred labels in more than one language.
2. **Given** the factories, **When** a test requests labels or notes in specific languages, **Then** the produced concept carries exactly those.

---

### User Story 7 - Translatable field metadata and deliberate indexing (Priority: P3)

Every field this feature adds carries a human-readable, translatable label and help text, all user-facing strings and validation messages are translatable, and each new field's database indexing is a deliberate, recorded decision — because a consumer of a third-party package cannot add any of these themselves.

**Why this priority**: A standard for every Django package this maintainer publishes (non-negotiable at review), already established for FS-001's fields. It adds no new capability but gates the merge, so it travels with the feature at P3.

**Independent Test**: The existing metadata test suite, which walks every concrete field on the models, covers the fields this feature adds. No UI needed.

**Acceptance Scenarios**:

1. **Given** any field added by this feature, **When** its metadata is inspected, **Then** it declares a non-empty help text and a human-readable label, both lazily translatable.
2. **Given** a user-facing validation failure introduced here (a document whose entries are not shaped as links or literals), **When** the error is raised, **Then** its message is translatable and uses named placeholders rather than baked-in values.
3. **Given** the database definitions of the new fields, **When** their indexes are inspected, **Then** the copy used for name lookup and sorting is covered by an index, and any queryable-but-unindexed field is a recorded decision, not an omission.

### Edge Cases

- A preferred label in a non-Latin script (Cyrillic, CJK) in the default language must still produce a usable slug, because slugs may hold Unicode letters.
- A concept with preferred labels only in non-default languages takes the first of them for its `pref_label`, so it is still listed under a name.
- Changing a vocabulary's default language after records exist does not change any slug or URI. It changes the `pref_label` of each record the next time that record is saved.
- Requesting labels or notes for a language the concept has none in returns an empty result, not an error.
- A concept with no name in any language has an empty `pref_label`, and is still given a slug and a URI.
- Two preferred labels in one language are stored as published. The package keeps what the publisher said, and does not enforce SKOS's one-per-language rule.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A record's document MUST be able to hold, for each language, preferred labels, alternative labels and hidden labels, and any language tag MUST be accepted, whatever `settings.LANGUAGES` holds.
- **FR-002**: A record's `pref_label` MUST be a copy of its name in its vocabulary's default language, refreshed on every save. Where the record has no name in that language it MUST be the record's first name in any language.
- **FR-003**: A record's slug MUST, when not supplied, derive once from its published identifier or, when it has none, from its `pref_label`. Its URI MUST compose exactly as FS-001 establishes; this feature MUST preserve that identity mechanism.
- **FR-004**: Adding, changing or removing any label or note, in any language, MUST NOT change a record's slug or URI after the record has first been saved.
- **FR-005**: A record MUST support any number of alternative labels and any number of hidden labels per language, each held distinctly from the other and from the preferred label.
- **FR-006**: A record MUST support, per language, a definition and each of the SKOS documentary notes — scope note, example, editorial note, history note, change note, and a general note — each holdable independently and more than once per language.
- **FR-007**: The programming interface MUST let a caller read a record's entries under any predicate (`values()`), its name in one language (`label()`), and its name in the active language (`display_label()`), returning an empty result or `None` for a language with no such value.
- **FR-008**: One language's labels and notes MUST be storable without supplying or altering any other language's entries.
- **FR-009**: Each vocabulary MUST have a required default language, set on the vocabulary, which decides which preferred label is copied into `pref_label` for the records it holds. A vocabulary created by an import MUST take the most common language among its records' preferred labels, or the site's `LANGUAGE_CODE` when no label has one.
- **FR-010**: A slug supplied when a row is created MUST be kept exactly, and MUST NOT be re-derived when the preferred label later changes.
- **FR-011**: A record's `search_text` MUST hold every preferred, alternative and hidden label it carries, in every language, one per line, refreshed on every save.
- **FR-012**: Slug uniqueness within a vocabulary (from FS-001) MUST continue to hold for derived and supplied slugs. A derived slug that collides takes a numeric suffix, and a supplied one that collides is refused.
- **FR-013**: The test suite MUST ship factories (or equivalent fixtures) able to produce a concept populated with preferred labels, and at least alternative labels and notes, across more than one language.
- **FR-014**: Every model field this feature adds MUST declare a human-readable, lazily translatable label and non-empty help text; every user-facing string and validation message MUST be translatable, with validation messages using named placeholders so their translatable form is static. Developer-facing diagnostics are exempt.
- **FR-015**: Indexing of the fields this feature adds MUST be deliberate: the copy used for name lookup and sorting MUST be covered by an index, and any queryable-but-unindexed field MUST be a recorded decision.

### Key Entities *(include if feature involves data)*

- **Record (names and descriptions)**: a term within exactly one vocabulary, carrying in its document — per language — preferred labels, alternative labels, hidden labels, a definition, and the documentary notes (scope note, example, editorial note, history note, change note, general note). Its identity (slug, URI) is fixed when it is first saved.
- **Vocabulary / ConceptScheme (default language)**: carries a required default language that decides which preferred label is copied into each record's `pref_label`.
- **Label**: a language-tagged name for a concept — preferred, alternative, or hidden — held as an entry under `skos:prefLabel`, `skos:altLabel` or `skos:hiddenLabel`.
- **Note**: a language-tagged descriptive value on a concept — a definition or one of the SKOS documentary note types — held as an entry under its own predicate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Through the ORM alone, a developer can give a concept preferred, alternative and hidden labels plus a definition and documentary notes in any language and read every one of them back filtered by language.
- **SC-002**: `pref_label` is the preferred label in the vocabulary's default language, and a concept with none in that language is still named — verified by test.
- **SC-003**: A concept's URI is provably unchanged by any addition, change or removal of content in any language — verified by a test that mutates labels and notes and asserts URI stability.
- **SC-004**: A concept with a supplied slug keeps it when its label changes, and a concept without one derives it once from its label — both verified by test.
- **SC-005**: Two vocabularies with different default languages each copy their own default language's label into `pref_label` — verified by test.
- **SC-006**: A test obtains a fully multilingual concept (preferred labels and notes in more than one language) from the factories in three lines or fewer.
- **SC-007**: Every field this feature adds exposes translatable, non-empty metadata and a recorded indexing decision, and every validation message it introduces is translatable with named placeholders — all verified by the standards test.
- **SC-008**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python/Django matrix.

## Assumptions

- **Programmatic only.** This feature has no user interface, including the Django admin. Names and descriptions are written to a record's document and read through its methods.
- **Languages are whatever the publisher used.** A record's document accepts any language tag. The site's `LANGUAGES` setting does not limit what is stored, and a language is neither matched to a configured one nor substituted for it.
- **The default language is the vocabulary's.** The vocabulary's own `default_language` column decides which label is copied into `pref_label`. The site's `LANGUAGE_CODE` is only the fallback for a vocabulary an import creates from labels that carry no language.
- **Imported vocabularies keep their own slugs.** For a published vocabulary, a record's slug is derived once from the last part of its URI and never re-derived or edited. FR-010's supplied slug is the same mechanism for a record created in code.
- **Notation codes are statements like any other.** A `skos:notation` is held in the document under its own predicate, with no column of its own.
- **SKOS label rules are not enforced.** The SKOS condition that a concept's preferred, alternative and hidden labels in one language be pairwise distinct, and that there be at most one preferred label per language, is left to the publisher. A document is stored as published.
- **Other features are untouched.** Links between concepts (FS-003), collections (FS-004), importing (FS-006) and the browsing pages (FS-014, FS-015) read the same document and are specified on their own.
