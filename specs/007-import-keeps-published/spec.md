# Feature Specification: Import keeps every published language

**Feature Branch**: `007-import-keeps-published`

**Created**: 2026-08-04

**Status**: Draft

**Input**: Issue [#51](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/51) — "External vocabularies are often published in far more languages than a given site cares about. An import should keep what the publisher published, in every language it was published in, so that nothing vanishes silently and nothing has to be fetched again when a site later wants another language."

**Serves**: G8 (external vocabularies as read-only references — a published vocabulary kept in full is one a site can reference in any language) · G6 (multilingual concepts — every language a publisher offers is a language the vocabulary holds) · G4 (faithful round-trip — a language kept is a language that can be given back) · **Roadmap**: R2 · **Issue**: #51

> Scope note: this is the third slice of roadmap item R2. FS-006 built the import itself, and every statement it reads goes into the document of the row it describes. This feature fixes what that means for languages: a language tag is stored as published, a vocabulary's languages are not matched against the site's `LANGUAGES` setting, and adding a language to the site later changes nothing that is stored. It also fixes where an imported row's address comes from, so that a translated name can never move it. The entry point remains **programmatic**. Rendering a report at a terminal is FS-008. **Out of scope:** any command-line or web-facing surface (FS-008), exporting or serving RDF (R4), the concept consumption field (R3), browsing (R6), and translating content between languages.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A vocabulary imports in every language it was published in (Priority: P1)

A site configured for British English imports a published vocabulary whose labels and notes are tagged `en`, `en-gb`, `en-us`, `fr` and `de`. Every one of them is stored, under the tag the publisher gave it. The same holds whatever the site is configured for: a site with no `LANGUAGES` setting of its own, and a site configured for plain `en`, store exactly the same content.

**Why this priority**: This is the feature's reason to exist. A publisher's languages are part of what it published, and a site that discards the ones it does not read today has to fetch the vocabulary again the day it wants one. Regional and script variants are ordinary in published vocabularies, so storing a tag as published is the only rule that cannot mismatch.

**Independent Test**: Import a fixture carrying a concept's labels in five language tags, including regional variants of one language, into a site configured for one language only, and assert every label is stored under its own tag.

**Acceptance Scenarios**:

1. **Given** a site configured for `en-gb` only, **When** a vocabulary whose labels are tagged `en` is imported, **Then** each concept carries its label under `en`.
2. **Given** a site configured for `en` only, **When** a vocabulary whose labels are tagged `en-gb` is imported, **Then** each concept carries its label under `en-gb`.
3. **Given** a site configured for `en` only, **When** a vocabulary whose labels are tagged `fr` is imported, **Then** those values are stored under `fr`, and the report names nothing as set aside.
4. **Given** a file carrying one concept's preferred label in `en`, `en-gb` and `en-us`, **When** it is imported, **Then** all three are stored, each under its own tag, and none is substituted for another.
5. **Given** a file carrying alternative labels in `en-gb` and `en-us`, **When** it is imported, **Then** both are stored.
6. **Given** a tag differing from another only in case, such as `EN-GB` and `en-gb`, **When** `label("en-gb")` is read, **Then** the match ignores case.

---

### User Story 2 - The vocabulary's default language comes from what it publishes (Priority: P1)

A vocabulary an import creates takes as its default language the language most of its records' preferred labels carry, so a German vocabulary in an English-language site is named and listed in German. Where no label carries a language, it takes the site's `LANGUAGE_CODE`. A vocabulary that already exists keeps its default language, and a later import does not change it.

**Why this priority**: The default language decides which preferred label is copied into every record's `pref_label`, which is what lists sort by and what a name falls back to. Importing a vocabulary with no usable default would leave every concept unnamed in its lists.

**Independent Test**: Import a fixture whose preferred labels are mostly `de-at` into a site whose `LANGUAGE_CODE` is `en`, and assert the vocabulary's default language is `de-at` and every concept's `pref_label` is its `de-at` label. Import a fixture with untagged labels and assert the default is `en`.

**Acceptance Scenarios**:

1. **Given** a vocabulary whose records' preferred labels are mostly in `de-at`, **When** it is imported, **Then** the vocabulary's default language is `de-at` and every concept's `pref_label` is its `de-at` label.
2. **Given** a vocabulary whose labels carry no language tag, **When** it is imported, **Then** its default language is the site's `LANGUAGE_CODE`.
3. **Given** a vocabulary already held with the default language `en`, **When** a file mostly in `fr` is imported into it, **Then** its default language is still `en`.
4. **Given** a concept with no preferred label in the vocabulary's default language, **When** it is imported, **Then** its `pref_label` is its first preferred label in any language, so it is still listed under a name.

---

### User Story 3 - Adding a language to the site changes nothing that is stored (Priority: P2)

A site imports a vocabulary, later configures an additional language, and runs the same import again. Everything is as it was. The languages were stored the first time, so there is nothing to fill in. No row's identifier, address or database identity changes, and no stored value in any language changes except where the file itself changed it.

**Why this priority**: The behaviour follows from storing every language, which is why it sits below the work that changes what is stored. It is still the sentence a project relies on when it adopts a vocabulary before its own language list is final, and a test turns it into a promise.

**Independent Test**: Import a multilingual fixture into a site configured for one language, reconfigure for two, import the same file again, and compare every row before and after.

**Acceptance Scenarios**:

1. **Given** a vocabulary imported into a site configured only for `en`, **When** the site is configured for `en` and `fr` and the same file is imported again, **Then** the concepts already present carry the same French labels and notes they carried after the first import.
2. **Given** the same re-import, **When** the rows are compared with their state before it, **Then** every identifier, address and database identity is unchanged.
3. **Given** the same re-import, **When** the English content is compared, **Then** it is unchanged except where the file itself changed it.
4. **Given** the site is configured for `en` and `en-gb`, **When** a file carrying `en-us` values is imported, **Then** the values are stored under `en-us`, and configuring `en-us` afterwards moves nothing.

---

### User Story 4 - An address is made from the published identifier, never from a translated name (Priority: P2)

An imported record's address on this site is `/{vocabulary}/{record}`, and both segments come from identifiers its publisher assigned. A concept renamed by the publisher, a vocabulary whose name arrives in a different language on a later import, and a change in the site's languages leave every address where it was.

**Why this priority**: Addresses get bookmarked and cited, and a name in a given language is the wrong thing to derive them from, because the name depends on the language that happens to win. Deriving from the identifier, which the publisher fixed, is the only source that does not move.

**Independent Test**: Import a fixture, rename a concept and the vocabulary in the file, change the site's languages, import again, and compare every slug.

**Acceptance Scenarios**:

1. **Given** a concept published with the identifier `https://example.org/rocks/granite`, **When** it is imported, **Then** its slug is `granite`. **And Given** an identifier with a fragment, such as `https://example.org/rocks#granite`, **Then** its slug is `granite`, the fragment.
2. **Given** a vocabulary imported once, **When** the publisher renames a concept and the file is imported again, **Then** the concept's slug and address are unchanged.
3. **Given** a vocabulary imported once, **When** its own name arrives in a different language on a later import, **Then** the vocabulary's slug is unchanged, and so is the address of every record inside it.
4. **Given** two records in one vocabulary whose identifiers end in the same segment, **When** the file is imported, **Then** both import with distinct slugs, and both keep them when the same file is imported again.
5. **Given** a record created in code with no identifier, **When** it is first saved, **Then** its slug is derived from its preferred label, and it keeps that slug when the label later changes.

---

### User Story 5 - Translatable messages and reusable test material (Priority: P3)

Every message this feature puts in front of a person is translatable, and the vocabularies it needs on disk are fixtures that the features after it can use.

**Why this priority**: A standard carried by every slice of R1 and by both preceding slices of R2 (constitution Articles XII, XIII and XIV). It adds no capability but gates the merge, so it travels last. The fixtures are paid back immediately, because FS-008 needs a vocabulary with variant language tags to demonstrate its summary against.

**Independent Test**: The standards test finds no untranslated message, and the new fixtures load from the suite rather than being built inline.

**Acceptance Scenarios**:

1. **Given** any message this feature adds, **When** the standards test runs, **Then** it is translatable with named placeholders.
2. **Given** the test suite, **When** a test needs a vocabulary carrying variant language tags, **Then** it loads one from the fixtures rather than constructing it inline.

### Edge Cases

- A published tag carrying more subtags than the vocabulary's default language, such as `zh-Hans-CN` against a default of `zh-Hans`. The tags are different, so `label("zh-Hans")` does not return the `zh-Hans-CN` value, and `pref_label` takes the first preferred label in any language when the default has none.
- A value carrying no language tag is stored without one, and is shown only where a reader's language and the default language both lack a match.
- A vocabulary whose predominant language differs from the site's `LANGUAGE_CODE` is named in its own language, and the site's setting plays no part.
- A published tag that is not a language the site has ever heard of is stored all the same, as a tag.
- The same file imported twice stores the same documents, because entries are written in a fixed order.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A language tag MUST be stored exactly as the file publishes it, on the entry it belongs to. Preferred, alternative and hidden labels, definitions and notes MUST each keep every language the file offers.
- **FR-002**: The import MUST NOT match a published tag against `settings.LANGUAGES`, substitute one tag for another, choose between variants of one language, or drop a value for its language. The `LANGUAGES` setting MUST have no effect on what is stored.
- **FR-003**: Variants of one language, such as `en`, `en-gb` and `en-us`, MUST be stored side by side, for every kind of value including the preferred label.
- **FR-004**: A language tag MUST be compared without regard to case when a name or value is read with `label()` or `display_label()`.
- **FR-005**: A vocabulary an import creates MUST take as its default language the language most used by its records' preferred labels, and the site's `LANGUAGE_CODE` when none carries one. The same file MUST give the same default on every run. A vocabulary that already exists MUST keep its default language.
- **FR-006**: A record's `pref_label` MUST be a copy of its preferred label in its vocabulary's default language, refreshed on every save. Where it has none in that language, it MUST be the record's first preferred label in any language.
- **FR-007**: Re-running an import after a language is added to the site's configuration MUST leave every stored value, identifier, address and database identity unchanged, except where the file itself changed a value.
- **FR-008**: An imported record's slug MUST be derived from the identifier its publisher assigned, and MUST NOT be derived from any translated value. It MUST NOT be recomputed on a later import for any reason — not a changed label, not a changed configured-language set, not a changed default language. The slug is the last segment of the published identifier: its fragment where it has one, otherwise the last segment of its path.
- **FR-009**: FR-008 governs the vocabulary's own slug on the same terms, so an address is `/{vocabulary}/{record}` with **both** segments derived from published identifiers. A vocabulary whose name arrives in a different language on a later import MUST NOT move the address of a single record it holds.
- **FR-010**: A row created in code with no identifier MUST derive its slug from its label when it is first saved, and MUST keep that slug afterwards. For such a row this application composes the identifier *from* the slug, so the dependency runs the other way.
- **FR-011**: Where two records in one vocabulary would derive the same slug, the collision MUST be resolved deterministically by a numeric suffix, in the order of their identifiers, so that the same file produces the same slugs on every import.
- **FR-012**: This feature MUST NOT add a command-line, web-facing, or other surface for a person. What the import reports is defined by FS-006, and FS-008 owns rendering it.
- **FR-013**: Every message this feature puts in front of a person MUST be translatable with named placeholders. Developer-facing diagnostics are exempt (Article XII).
- **FR-014**: The project's glossary MUST define the document, the copied columns and the default language, so the vocabulary of the stored model matches the vocabulary of the documentation.
- **FR-015**: The test suite MUST ship a published vocabulary fixture carrying variant language tags for one base language, discoverable from the suite, so FS-008 does not rebuild it.

### Key Entities *(include if feature involves data)*

- **Language tag**: the tag on an entry of a row's document, kept exactly as published. Variants of one language are distinct tags.
- **Default language**: the vocabulary's own `default_language`, which decides which preferred label is copied into each record's `pref_label`.
- **Slug**: the address segment of a row, derived once from its published identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A vocabulary published only as `en` imports into a site configured only for `en-gb`, with every concept carrying its labels and notes under `en` — verified by test.
- **SC-002**: A vocabulary published only as `en-gb` imports into a site configured only for `en`, with every concept carrying its labels and notes under `en-gb` — verified by test.
- **SC-003**: A vocabulary published in a language the site does not configure at all stores every value, and the report names nothing as set aside — verified by test.
- **SC-004**: A file offering `en`, `en-gb` and `en-us` for one value stores all three — verified by test.
- **SC-005**: Alternative labels, hidden labels and notes published in several variants of one language are all stored — verified by test.
- **SC-006**: `label()` matches a tag without regard to case — verified by test.
- **SC-007**: A vocabulary declaring labels mostly in a variant of a language takes that tag as its default language, and every concept is named — verified by test.
- **SC-008**: A vocabulary whose labels carry no language takes the site's `LANGUAGE_CODE` as its default — verified by test.
- **SC-009**: Configuring an additional language, including one that shares a base with one the site already holds, and importing the unchanged file again, leaves every stored value, identifier, slug and address as it was — verified by test.
- **SC-010**: An imported record's slug equals the last segment of its published identifier, for an identifier carrying a fragment and for one carrying none — verified by test.
- **SC-011**: Re-importing a file whose publisher has renamed a record leaves that record's slug and address unchanged — verified by test.
- **SC-012**: Re-importing a file whose vocabulary name arrives in a different language leaves the vocabulary's slug, and the address of every record inside it, unchanged — verified by test.
- **SC-013**: Two records in one vocabulary whose identifiers end in the same segment both import, with distinct slugs, and both keep those slugs when the same file is imported again — verified by test.
- **SC-014**: A row created in code with no identifier derives its slug from its label when first saved, and keeps it when the label later changes — verified by test.
- **SC-015**: Every message this feature shows a person is translatable with named placeholders — verified by the standards test.
- **SC-016**: The glossary defines the document, the copied columns and the default language — verified by review of `CONTEXT.md`.
- **SC-017**: A published vocabulary fixture carrying variant language tags exists and is loaded by the tests from the suite rather than built inline — verified by test.
- **SC-018**: Every functional requirement above is exercised by at least one automated test, and the suite passes across the supported Python and Django matrix.

## Assumptions

- **The stored document is the account.** Every language a file publishes is in the document of the row it describes, so no separate record of what was left behind is needed. A project that wants less language reads fewer of them.
- **A tag is opaque to the import.** The import does not parse a tag into a base language and a script, so it joins no variants and chooses between none. Presenting a reader's language, and falling back to the vocabulary's default, is the work of the pages that read the document.
- **The site's languages are the site's.** The `LANGUAGES` setting decides what the site offers a reader, and plays no part in what an import stores.
- **A site that upgrades re-imports.** Storing every language changes what an import keeps, and a site on a version that matched languages imports its vocabularies again to gain the content that matching set aside.
- **Fixtures from FS-006 are reused where they serve**, and the variant fixture is added alongside them rather than replacing any.
