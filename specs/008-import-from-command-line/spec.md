# Feature Specification: Run an import from the command line

**Feature Branch**: `008-import-from-command-line`

**Created**: 2026-08-10

**Status**: Draft

**Input**: Issue [#52](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/52) — "Importing a vocabulary is usually an operational task, part of setting up a deployment or refreshing from an upstream publisher, and the people doing it work from a terminal or a deployment script rather than a Python shell. They want a command that takes a file, reports what it did, and can be run first in a rehearsal mode that shows the outcome without writing anything."

**Serves**: G8 (external vocabularies as read-only references — a vocabulary nobody can get into a deployment is one nobody can reference) · G4 (faithful round-trip — the import half of it, reached without a Python shell) · **Roadmap**: R2 · **Issue**: #52

> Scope note: this is the fourth and last slice of roadmap item R2, and the one that closes its "both a management command and a programmatic entry point" deliverable. FS-006 built the import and its structured report, and FS-007 fixed that it keeps every statement in every language. This feature owns **where an operator stands when they run one and what they read afterwards**: a management command, a source that may be a local file or a URL, a rendering of the existing report at a terminal, and a dry run that reports the same outcome and keeps none of it. It adds no new import behaviour — every decision about what a file means was made upstream of it. The command takes no target vocabulary: the source declares which vocabulary it is, and a source that declares none is refused. A site may also declare the vocabularies it uses in its settings, keyed by the slug its fields name them by, and load every one of them with a second command (US-7, from issue #221). The programmatic entry point accepts a target for a source that declares none, and pointing a deployment script at the wrong address is the operator's mistake to make and not this package's to prevent. **Out of scope:** any change to what the import stores, exporting or serving RDF (R4), the consumption field (R3), the editing interface and any web-facing entry point, browsing (R6), scheduling repeat runs, storing where a vocabulary was fetched from in the database, deleting anything a source no longer lists, and importing anything the source does not itself declare as a SKOS concept scheme.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A vendored file imports from a terminal (Priority: P1)

An operator setting up a deployment has a published SKOS file on disk, checked in alongside the project or downloaded ahead of time. They run one command naming that path and the vocabulary is in the database. They read, in the terminal, how many records were created and how many updated, and which records the source no longer mentions.

**Why this priority**: This is the feature's reason to exist and the deliverable R2 has been carrying unfinished. Everything the import does has been reachable only from a Python shell, which is not where the people who install and refresh vocabularies work.

**Independent Test**: Run the command against a fixture file in a database with no vocabularies and confirm the vocabulary, its concepts, their labels, and their relationships are present afterwards, and that the command's output names the counts.

**Acceptance Scenarios**:

1. **Given** an empty database and a published SKOS file on disk, **When** the command is run with that path, **Then** the vocabulary and its concepts exist afterwards and the output names how many of each were created.
2. **Given** a database already holding that vocabulary, **When** the command is run again with the same file, **Then** the output names what was updated rather than created, and no concept is duplicated.
3. **Given** a file whose serialization cannot be determined from its name, **When** the command is run with the serialization named explicitly, **Then** it imports as if the name had carried it.
4. **Given** a path that does not exist, **When** the command is run with it, **Then** it fails naming the path, writes nothing, and exits non-zero.

---

### User Story 2 - A vocabulary imports straight from its publisher (Priority: P1)

An operator refreshing from upstream has no local copy and does not want one. They run the same command with the address the publisher serves the vocabulary from, and it lands exactly as a downloaded copy would have. Nothing about the address is kept — refreshing again means running the command again, and the deployment script is what remembers where.

**Why this priority**: The half of the source argument the maintainer added at intake, and the one that makes the command usable without a vendoring step. It is also the package's first outbound network request, so it carries its own failure modes rather than sharing the file path's.

**Independent Test**: Serve a fixture over a local HTTP stub and import it by URL, then import the identical bytes from disk, and confirm the two runs produce the same records and the same report.

**Acceptance Scenarios**:

1. **Given** a published SKOS document reachable over HTTPS whose identifiers are absolute, **When** the command is run with that URL, **Then** the vocabulary lands exactly as importing the same bytes from a file would, and nothing records where it came from.
2. **Given** a published document stating its identifiers relative to its own address, **When** the command is run with that URL, **Then** its concepts are stored under the publisher's URIs rather than under any address local to the machine that fetched it.
3. **Given** a URL that cannot be reached, or answers with an error status, **When** the command is run with it, **Then** it fails naming the URL and what went wrong, writes nothing, and exits non-zero.
4. **Given** a URL answering with something that is not RDF at all, such as a publisher's landing page, **When** the command is run with it, **Then** it fails saying the content could not be read as SKOS rather than reporting an empty vocabulary.
5. **Given** a URL whose scheme is neither `http` nor `https`, **When** the command is run with it, **Then** it is refused as an unsupported source rather than read as a filename.

---

### User Story 3 - A run can be dry-run before it is kept (Priority: P1)

Before importing a vocabulary into a deployment that already holds data, an operator wants to see what the run would do. They add a flag, get the report a live run would have produced, and the database is untouched afterwards. If the dry run shows a problem in their file, they fix the file and dry run again, having written nothing.

**Why this priority**: Named explicitly in the issue, and the reason an operator will reach for the command at all on a database that matters. A report they can only get by committing to the change is not a dry run.

**Independent Test**: Run a dry-run import against a populated database, assert the report matches a live run of the same source against the same starting state, and assert every table is unchanged afterwards.

**Acceptance Scenarios**:

1. **Given** a populated database, **When** a source is imported in dry run mode, **Then** the report names what would be created and updated, and no row anywhere has changed.
2. **Given** the same database and source, **When** the dry run is followed by a live run, **Then** the live run's report matches the dry run's.
3. **Given** a source that would be refused, **When** it is dry-run, **Then** the dry run reports the refusal rather than reporting success.
4. **Given** any dry run, **When** it finishes, **Then** its output states that nothing was kept, so a report of two hundred created concepts cannot be mistaken for a completed import.

---

### User Story 4 - The outcome of a run is readable at a terminal (Priority: P2)

After importing a vocabulary, an operator sees how many records were created, how many were updated, and how many were left untouched because the source no longer mentions them, and is told which ones those are. Every count prints, because a count of zero and a missing line mean different things to a reader.

**Why this priority**: The rendering half of the import report, which FS-006 made available as data. It is P2 rather than P1 because US-1 already tells an operator the vocabulary is present — this tells them what changed in it.

**Independent Test**: Import a fixture into a database that already holds records the fixture no longer mentions, and assert the output holds a count for each bucket and names each absent record, and that at verbosity 0 nothing prints.

**Acceptance Scenarios**:

1. **Given** an import that created and updated records, **When** the command finishes, **Then** the output names how many were created and how many were updated.
2. **Given** a run where the vocabulary holds records the source no longer mentions, **When** the command finishes, **Then** the output names how many, and names each, as present but no longer mentioned by the source.
3. **Given** a run where nothing was created, nothing updated and nothing absent, **When** the command finishes, **Then** each count prints as zero rather than being omitted.
4. **Given** the command run at verbosity 0, **When** it finishes, **Then** nothing is printed, as with any Django command.

---

### User Story 5 - A refused run is unmistakable (Priority: P2)

When the importer refuses a source, the operator sees why in plain terms, the database is untouched, and a deployment script halts on the exit status rather than continuing as though the vocabulary were present.

**Why this priority**: The half of the contract a script depends on. It is separable from the successful path and independently testable, but an operator meets it only when something is wrong.

**Independent Test**: Run the command against sources covering each refusal the importer can raise, and assert on the exit status, the message, and an unchanged database in every case.

**Acceptance Scenarios**:

1. **Given** a source declaring no concept scheme, **When** the command is run with it, **Then** it is refused as not being a SKOS vocabulary, nothing is written, and the exit status is non-zero.
2. **Given** a source the safety scan refuses, **When** the command is run with it, **Then** it is refused with that reason and nothing is parsed further.
3. **Given** a source whose content is refused after parsing, **When** the command is run with it, **Then** every problem found is reported rather than only the first, and nothing is written.
4. **Given** a source that imports and leaves records the source no longer mentions in place, **When** the command finishes, **Then** the exit status is zero, because leaving records untouched is a completed import and not a failure.

---

### User Story 6 - Translatable messages, documentation, and reusable test material (Priority: P3)

Everything the command prints is translatable, the README tells an operator the command exists and how to run it, and the fixtures and helpers this feature needs are usable by the features that follow.

**Why this priority**: Constitutional obligations that apply to the whole feature rather than to one journey through it, and the first surface of this package a person meets in their own language.

**Independent Test**: Assert no user-visible string in the command is a bare literal, that the README documents the command and the CHANGELOG records it, and that the HTTP stub and fixtures live where another feature can reach them.

**Acceptance Scenarios**:

1. **Given** the command's help text and every message it prints, **When** the source is inspected, **Then** each is wrapped for translation with named placeholders, per Article XII.
2. **Given** the shipped documentation, **When** the README is read, **Then** it documents the command, both source forms, and the dry run flag, alongside the programmatic entry point.
3. **Given** the test suite, **When** the modules are located, **Then** they mirror the source tree per testing standard §4 and the fixtures are reusable rather than inlined per test.

---

### User Story 7 - A site's vocabularies are declared once and loaded with one command (Priority: P2)

A developer whose site relies on several vocabularies lists them in the project's settings, each under the slug the site's fields name it by, with the file shipped beside the code or the address it is published at. On every deploy they run one command, and every declared vocabulary is loaded or refreshed. A vocabulary that fails is reported and the others still load, and the deploy script stops on the exit status.

**Why this priority**: Without it a site using five vocabularies has five commands to remember on every deploy, and the slug a field names depends on how each publisher shaped its URI. It is P2 because US-1 and US-2 already load any one vocabulary.

**Independent Test**: Declare two fixture vocabularies, one of them failing, run the command, and confirm the good one is held under its declared slug, the failing one left nothing behind, and the command exited non-zero. Run it again and confirm the rows were updated in place.

**Acceptance Scenarios**:

1. **Given** a vocabulary declared under a slug, **When** the command is run in an empty database, **Then** the vocabulary is loaded and holds the declared slug, whatever its URI.
2. **Given** that vocabulary already loaded, **When** the command is run again, **Then** it is found by its declared slug and updated in place, and no row is duplicated.
3. **Given** a source that no longer lists a record the vocabulary holds, **When** the command is run, **Then** the record is reported and kept.
4. **Given** several declared vocabularies, one of which cannot be loaded, **When** the command is run, **Then** the others are loaded, the failing one is reported with its reason and nothing of it is kept, and the exit status is non-zero.
5. **Given** a declared source that publishes a vocabulary other than the one already held under its slug, **When** the command is run, **Then** it is refused and neither vocabulary changes.
6. **Given** a vocabulary already loaded under a different slug, **When** it is declared and the command is run, **Then** it is reported naming the slug it holds, and it is not renamed.
7. **Given** a dry run, **When** the command finishes, **Then** every report printed and nothing was kept.
8. **Given** one or more slugs named on the command line, **When** the command is run, **Then** only those vocabularies are loaded, and a slug that is not declared is refused before anything loads.
9. **Given** a field naming a vocabulary that is neither declared nor loaded, **When** `manage.py check` runs, **Then** it warns under an id of its own, distinct from the warning for a vocabulary that is declared but not loaded yet.

### Edge Cases

- A source value beginning with a scheme other than `http`/`https` is refused as an unsupported source, rather than being read as a relative filename that then fails to exist.
- A URL that redirects is followed. A redirect chain that does not terminate fails as an unreachable source.
- A URL that never answers fails on a timeout rather than hanging a deployment indefinitely.
- A URL answering with a success status and an HTML body fails as unreadable content, not as an empty vocabulary.
- A file exists but cannot be read for permission reasons — reported as such, distinctly from a file that is absent.
- A source declares more than one concept scheme, which the importer already refuses. The command surfaces that refusal unchanged.
- A dry run of a source that would be refused reports the refusal and still exits non-zero, because the outcome it is previewing is a failure.
- The database is unreachable or unmigrated when the command runs — Django's own failure, surfaced rather than caught.
- An empty file, or a file that parses to a graph with no SKOS content, is refused rather than importing an empty vocabulary.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST ship a Django management command that imports a published SKOS vocabulary, so that a deployment can import one without executing Python written for the occasion.
- **FR-002**: The command MUST take exactly one source argument, which is either a local filesystem path or an `http`/`https` URL, distinguished by the value itself. Any other URL scheme MUST be refused as an unsupported source, and a Windows drive letter MUST NOT be mistaken for one.
- **FR-003**: A URL source MUST be retrieved and then imported through the same path a local file takes, including the existing safety scan. The address it was fetched from MUST be the base URI its identifiers resolve against, so a vocabulary published with relative identifiers is stored under the URIs its publisher assigned. Nothing about the address MUST be stored.
- **FR-004**: The command MUST let the operator name the source's serialization explicitly, and otherwise MUST determine it as the programmatic entry point already does.
- **FR-005**: The command MUST delegate the import itself to the existing programmatic entry point and MUST NOT reimplement any part of reading, matching, or writing. It MUST NOT offer a way to name a target vocabulary: the source declares which vocabulary it is.
- **FR-006**: On a completed run the command MUST report how many records were created, how many were updated, and how many the vocabulary holds that the source no longer mentions. Every count MUST print, including a count of zero.
- **FR-007**: Each record the vocabulary holds that the source no longer mentions MUST be named, so an operator can see which existing data the run left untouched.
- **FR-008**: At verbosity 0 the command MUST print nothing, as any Django command does. A refusal is unaffected, because it is raised as an error and not printed as a report.
- **FR-009**: The command MUST offer a dry run mode that performs the whole import and produces the report a live run of the same source against the same database state would produce, then leaves the database unchanged. The report MUST be produced by the import itself rather than by a separate prediction of it.
- **FR-010**: A dry run's output MUST state that nothing was kept, so its counts cannot be read as a completed import.
- **FR-011**: A run the importer refuses MUST print why in terms an operator can act on, MUST leave the database unchanged, and MUST exit non-zero. Where the importer collects several problems, all of them MUST be printed.
- **FR-012**: A run that completes MUST exit zero, however many records it left untouched, because leaving them is an expected outcome of importing a published vocabulary and not a failure.
- **FR-013**: A source that declares no concept scheme MUST be refused as not being a SKOS vocabulary. The command names no target vocabulary, so this follows from the existing entry point rather than adding a rule to it.
- **FR-014**: A source that cannot be retrieved, opened, or read MUST fail naming the source and the cause, MUST write nothing, and MUST exit non-zero. A retrieval that cannot complete MUST fail rather than wait indefinitely.
- **FR-015**: Every string the command prints, including its help text, MUST be translatable per Article XII, with named placeholders so the message identifiers stay static.
- **FR-016**: `CONTEXT.md` MUST define **dry run**, which this feature puts in front of an operator. The documentation MUST describe the command, both source forms, and the dry run flag.

- **FR-017**: The package MUST read a `CONTROLLED_VOCABULARIES` setting: a mapping from a vocabulary's slug to its `source`, a path or an `http`/`https` URL, and an optional `format`.
- **FR-018**: The package MUST ship a second management command that loads every declared vocabulary, or only those named, each through the same path `import_skos` takes, in a transaction of its own, printing each one's report.
- **FR-019**: A vocabulary the command creates MUST take its declared slug, and every later run MUST find it by that slug rather than by a slug derived from its URI. A vocabulary already held under another slug MUST be reported and not renamed.
- **FR-020**: A vocabulary that fails MUST be reported with its reason and leave nothing behind, MUST NOT stop the others, and MUST make the command exit non-zero. The command MUST offer the same dry run as `import_skos`.
- **FR-021**: `manage.py check` MUST warn about a field naming a vocabulary that is neither declared nor loaded, under an id distinct from the warning for a declared vocabulary that is not loaded yet.

### Key Entities *(include if feature involves data)*

- **Source**: What the operator points the command at — a filesystem path or an `http`/`https` URL. It resolves to bytes and nothing about it is stored in the database.
- **Declared vocabulary**: An entry in `CONTROLLED_VOCABULARIES`: the slug fields name a vocabulary by, and the source it is loaded from.
- **Dry run**: A run performed in full and then abandoned, reporting what it did without keeping any of it.
- **Import report**: The structured outcome FS-006 defined. This feature reads it and renders it. It adds nothing to it and parses none of its rendered messages.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with shell access to a deployment and a published SKOS file imports it with a single command and writes no Python.
- **SC-002**: A vocabulary imported by URL is stored under the URIs its publisher assigned, including where the document states them relative to its own address. For a document whose identifiers are absolute, importing it by URL and importing the identical bytes from disk produce the same records and the same report.
- **SC-003**: A dry run against a given database state produces the same report as a live run against that same state, and leaves every table unchanged.
- **SC-004**: The output of a completed run names how many records were created, updated and left untouched, and names each record left untouched.
- **SC-005**: Every refusal the importer can raise exits non-zero with an explanation and an unchanged database, and every completed run exits zero.
- **SC-006**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, and no user-visible string in the command is untranslatable.

## Assumptions

- **The operator is trusted.** A management command is run by whoever already has shell access to the deployment and its database, so a URL they type is an instruction, not untrusted input. The command does not restrict which addresses may be fetched, and pointing it at the wrong one is the operator's error to make. This is a deliberate position taken at intake, recorded so it is not later read as an omission. Content fetched from any address remains untrusted as *content*, and passes through the existing safety scan unchanged.
- **Retrieval needs no new runtime dependency.** The standard library covers fetching bytes over HTTP, and the package's dependency discipline (Article VII) prefers that to adding a client for one call site.
- **The import's behaviour is fixed.** Every decision about what a source means was made by FS-006 and FS-007. If rendering the report at a terminal shows the report itself to be insufficient, that is a finding against those features, not a licence to change them here.
- **Repeat runs are the caller's business.** Scheduling and retrying sit outside this feature, and a deployment script or a scheduler owns them. Where a vocabulary comes from is remembered in the project's settings, never in the database.
