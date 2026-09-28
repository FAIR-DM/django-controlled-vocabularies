# Feature Specification: Run an import from the command line

**Feature Branch**: `008-import-from-command-line`

**Created**: 2026-08-10

**Status**: Draft

**Input**: Issue [#52](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/52) — "Importing a vocabulary is usually an operational task, part of setting up a deployment or refreshing from an upstream publisher, and the people doing it work from a terminal or a deployment script rather than a Python shell. They want a command that takes a file and a target vocabulary, reports what it did and what it set aside, and can be run first in a rehearsal mode that shows the outcome without writing anything."

**Serves**: G8 (external vocabularies as read-only references — a vocabulary nobody can get into a deployment is one nobody can reference) · G4 (faithful round-trip — the import half of it, reached without a Python shell) · **Roadmap**: R2 · **Issue**: #52

> Scope note: this is the fourth and last slice of roadmap item R2, and the one that closes its "both a management command and a programmatic entry point" deliverable. [#50](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/50) built the import and its structured report, and [#51](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/51) decided what a curator is told about content that could not be kept. This feature owns **where an operator stands when they run one and what they read afterwards**: a management command, a source that may be a local file or a URL, a rendering of the existing report at a terminal, and a dry run that reports the same outcome and keeps none of it. It adds no new import behaviour — every decision about what a file means was made upstream of it. **Out of scope:** any change to what the import stores or sets aside, exporting or serving RDF (R4), the consumption field (R3), the editing interface and any web-facing entry point (R5), browsing (R6), scheduling or automating repeat runs, remembering where a vocabulary was fetched from, and importing anything the source does not itself declare as a SKOS concept scheme.

## Clarifications

### Session 2026-08-10

Two intake decisions widened the issue as written, and both are the maintainer's, recorded here because a reader of the issue alone would not predict them. Longer rationale is in `decisions.md`.

- **Q: The issue says the command takes "a file". Does it take anything else?** → A: A URL as well. Vendoring a published vocabulary means pointing at a filesystem path. Taking it straight from its publisher means pointing at the address it is served from. [#50](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/50) put "importing from a URL rather than a file" out of scope, so this is the first place it lands, and it is the package's first outbound network request. Integrated into FR-002 and FR-003.
- **Q: The issue says the command takes "a target vocabulary". How does an operator name one?** → A: They do not, and the command offers no way to. The source declares which vocabulary it is. A source that declares no concept scheme is not SKOS and is refused. The programmatic entry point accepts a target for exactly two cases — supplying a vocabulary for a source that declares none, and refusing a run whose source declares a different one than the caller expected — and the maintainer ruled both out at the command line: pointing a deployment script at the wrong address is the operator's mistake to make and not this package's to prevent. Integrated into FR-005 and FR-013.

### Session 2026-08-10 (coverage scan)

Five further ambiguities surfaced by the structured coverage scan over the drafted spec, resolved here against the intake decisions, the constitution, and what #50 and #51 already built.

- **Q: How does the command tell a filesystem path from a URL?** → A: From the value itself — a source beginning `http://` or `https://` is fetched, and anything else is read from disk. A flag choosing between them would make the operator restate what the value already says. A value carrying some other scheme is refused rather than handed to the filesystem, because `ftp://vocab.ttl` is a stated intention this feature does not serve and reading it as a relative filename would fail with the wrong explanation. Integrated into FR-002 and Edge Cases.
- **Q: A dry run reports what a live run "would" do. How faithful is that, exactly?** → A: It is the same run. The dry run performs the whole import — parse, match, write, set aside — inside a transaction it then abandons, so its report is produced by the code that produces a live one rather than by a second code path predicting it. Anything a live run would discover only at write time is discovered, which matters because several of the reasons a value is set aside are refusals by the models themselves. A predictive dry run would be a second implementation of the import, drifting from the first, and it would be silent about exactly the failures an operator runs a dry run to find. Integrated into FR-009.
- **Q: Does a run that set values aside succeed?** → A: Yes, and it exits zero. Set-asides are the normal outcome of importing a published vocabulary into a site configured for a subset of its languages — #51 exists because they are expected, not exceptional. Only a run the importer refuses outright exits non-zero. A deployment script therefore learns from the exit status whether the vocabulary is present, which is the question it can act on, and reads the report for the question a person acts on. Integrated into FR-011 and FR-012.
- **Q: A large external vocabulary can set aside hundreds of values. Does the command print all of them?** → A: No. By default it prints counts — per bucket, and within the set-aside bucket per reason, with the per-language breakdown #51 built. Individual entries are printed only when asked for. Several hundred lines scrolling past answers "what happened" and buries "what should I change", which is the question #51 was written to make answerable. Django's own `--verbosity` already means this, so it carries the choice rather than a new flag. Integrated into FR-007 and FR-008.
- **Q: Is "dry run" an established term in this project?** → A: No, it is new here, and it will appear in the command's help text and its output. The project keeps its vocabulary in `CONTEXT.md`, so it belongs there rather than only inside a spec an operator will never open. Integrated into FR-016.

### Session 2026-08-10 (post-gate, from planning research)

One amendment to text drafted here, made after the Spec gate and reported to the maintainer at the plan notification. It corrects a criterion this spec got wrong, and does not change the scope he approved. Measurements are in `research.md` R2, rationale in `decisions.md` D10.

- **Q: A document may state its identifiers relative to its own address. What are they relative to when the document was fetched rather than opened?** → A: The address it was fetched from. Parsing resolves relative identifiers against wherever the document was read, so a fetched document written to a temporary file and parsed from there acquires identities like `file:///tmp/tmpa1b2c3/concept-a` — different on every run, and belonging to no publisher. Article IX makes a concept's URI its identity and #49 built matching on the identifier its publisher assigned, so this is a defect rather than a detail. SC-002 originally required a URL import and a disk import of identical bytes to produce identical records, which is false for exactly these documents and false in the direction where the URL form is correct. Integrated into FR-003, SC-002, and User Story 2.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A vendored file imports from a terminal (Priority: P1)

An operator setting up a deployment has a published SKOS file on disk, checked in alongside the project or downloaded ahead of time. They run one command naming that path and the vocabulary is in the database. They read, in the terminal, how many concepts were created and how many updated, and are told whether anything was set aside.

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

1. **Given** a populated database, **When** a source is imported in dry run mode, **Then** the report names what would be created, updated and set aside, and no row anywhere has changed.
2. **Given** the same database and source, **When** the dry run is followed by a live run, **Then** the live run's report matches the dry run's.
3. **Given** a source that would be refused, **When** it is dry-run, **Then** the dry run reports the refusal rather than reporting success.
4. **Given** any dry run, **When** it finishes, **Then** its output states that nothing was kept, so a report of two hundred created concepts cannot be mistaken for a completed import.

---

### User Story 4 - The account of what was set aside is readable at a terminal (Priority: P2)

After importing an external vocabulary, an operator sees how much was set aside and why, grouped so the shape of it is visible at a glance, with the per-language breakdown that says which configuration change would recover the most. They can ask for the individual entries when they want them, and by default they do not scroll past.

**Why this priority**: The rendering half of #51. That feature made the account available as data and said so explicitly. This is where a person reads it. It is P2 rather than P1 because US-1 already tells an operator that something was set aside — this makes the number actionable.

**Independent Test**: Import a fixture carrying values in several unconfigured languages and assert the default output holds counts per reason and per language and no per-value lines, and that the verbose output holds the entries.

**Acceptance Scenarios**:

1. **Given** an import that set aside several hundred values, **When** the command finishes at default verbosity, **Then** the output names a count per reason rather than a line per value.
2. **Given** the same run, **When** the output is read, **Then** it names how many values were set aside per language.
3. **Given** the same run at raised verbosity, **When** the command finishes, **Then** the individual set-aside entries are printed, each naming its subject and its reason.
4. **Given** a run where the vocabulary holds concepts the source no longer mentions, **When** the command finishes, **Then** those are named as such and are not counted among what was set aside.
5. **Given** a run where nothing was set aside, **When** the command finishes, **Then** the output says so rather than omitting the section.

---

### User Story 5 - A refused run is unmistakable (Priority: P2)

When the importer refuses a source, the operator sees why in plain terms, the database is untouched, and a deployment script halts on the exit status rather than continuing as though the vocabulary were present.

**Why this priority**: The half of the contract a script depends on. It is separable from the successful path and independently testable, but an operator meets it only when something is wrong.

**Independent Test**: Run the command against sources covering each refusal the importer can raise, and assert on the exit status, the message, and an unchanged database in every case.

**Acceptance Scenarios**:

1. **Given** a source declaring no concept scheme, **When** the command is run with it, **Then** it is refused as not being a SKOS vocabulary, nothing is written, and the exit status is non-zero.
2. **Given** a source the safety scan refuses, **When** the command is run with it, **Then** it is refused with that reason and nothing is parsed further.
3. **Given** a source whose content is refused after parsing, **When** the command is run with it, **Then** every problem found is reported rather than only the first, and nothing is written.
4. **Given** a source that imports with values set aside, **When** the command finishes, **Then** the exit status is zero, because setting values aside is a completed import and not a failure.

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
- **FR-003**: A URL source MUST be retrieved and then imported through the same path a local file takes, including the existing safety scan and every normalisation rule. The address it was fetched from MUST be the base URI its identifiers resolve against, so a vocabulary published with relative identifiers is stored under the URIs its publisher assigned. Nothing about the address MUST be stored.
- **FR-004**: The command MUST let the operator name the source's serialization explicitly, and otherwise MUST determine it as the programmatic entry point already does.
- **FR-005**: The command MUST delegate the import itself to the existing programmatic entry point and MUST NOT reimplement any part of reading, matching, or writing. It MUST NOT offer a way to name a target vocabulary: the source declares which vocabulary it is.
- **FR-006**: On a completed run the command MUST report how many records were created, how many updated, how many values were set aside, how many were stored under a predicate or language other than the one published, and what the vocabulary holds that the source no longer mentions.
- **FR-007**: The set-aside account MUST be grouped by reason with a count per reason, and MUST include the per-language breakdown of values not stored for a language reason. Individual entries MUST be printed only at raised verbosity, and MUST NOT be printed by default.
- **FR-008**: Records the vocabulary holds that the source no longer mentions MUST be reported separately from values that were set aside, because they are existing data left untouched rather than incoming content refused.
- **FR-009**: The command MUST offer a dry run mode that performs the whole import and produces the report a live run of the same source against the same database state would produce, then leaves the database unchanged. The report MUST be produced by the import itself rather than by a separate prediction of it.
- **FR-010**: A dry run's output MUST state that nothing was kept, so its counts cannot be read as a completed import.
- **FR-011**: A run the importer refuses MUST print why in curator-facing terms, MUST leave the database unchanged, and MUST exit non-zero. Where the importer collects several problems, all of them MUST be printed.
- **FR-012**: A run that completes MUST exit zero however much it set aside, because setting values aside is an expected outcome of importing a published vocabulary and not a failure.
- **FR-013**: A source that declares no concept scheme MUST be refused as not being a SKOS vocabulary. The command names no target vocabulary, so this follows from the existing entry point rather than adding a rule to it.
- **FR-014**: A source that cannot be retrieved, opened, or read MUST fail naming the source and the cause, MUST write nothing, and MUST exit non-zero. A retrieval that cannot complete MUST fail rather than wait indefinitely.
- **FR-015**: Every string the command prints, including its help text, MUST be translatable per Article XII, with named placeholders so the message identifiers stay static.
- **FR-016**: `CONTEXT.md` MUST define **dry run**, which this feature introduces and puts in front of an operator. The README MUST document the command, both source forms, and the dry run flag. The CHANGELOG MUST record the addition.

### Key Entities *(include if feature involves data)*

- **Source**: What the operator points the command at — a filesystem path or an `http`/`https` URL. It resolves to bytes and nothing about it survives the run.
- **Dry run**: A run performed in full and then abandoned, reporting what it did without keeping any of it.
- **Import report**: The structured outcome #50 defined and #51 extended. This feature reads it and renders it. It adds nothing to it and parses none of its rendered messages.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with shell access to a deployment and a published SKOS file imports it with a single command and writes no Python.
- **SC-002**: A vocabulary imported by URL is stored under the URIs its publisher assigned, including where the document states them relative to its own address. For a document whose identifiers are absolute, importing it by URL and importing the identical bytes from disk produce the same records and the same report.
- **SC-003**: A dry run against a given database state produces the same report as a live run against that same state, and leaves every table unchanged.
- **SC-004**: Importing a vocabulary that sets aside several hundred values produces default output that a person reads without scrolling and that names how many were set aside per reason and per language.
- **SC-005**: Every refusal the importer can raise exits non-zero with an explanation and an unchanged database, and every completed run exits zero regardless of what it set aside.
- **SC-006**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, and no user-visible string in the command is untranslatable.

## Assumptions

- **The operator is trusted.** A management command is run by whoever already has shell access to the deployment and its database, so a URL they type is an instruction, not untrusted input. The command does not restrict which addresses may be fetched, and pointing it at the wrong one is the operator's error to make. This is a deliberate position taken at intake, recorded so it is not later read as an omission. Content fetched from any address remains untrusted as *content*, and passes through the existing safety scan unchanged.
- **Retrieval needs no new runtime dependency.** The standard library covers fetching bytes over HTTP, and the package's dependency discipline (Article VII) prefers that to adding a client for one call site. Whether that holds is a planning question, and adding one would need its justification in `plan.md`.
- **No release carries the old behaviour.** The package is at `0.0.x` with its first publish still ahead in the v0.1.0 milestone, so adding a command owes no upgrade path.
- **The import's behaviour is fixed.** Every decision about what a source means was made by #50 and #51. If rendering the report at a terminal shows the report itself to be insufficient, that is a finding against those features, not a licence to change them here.
- **Repeat runs are the caller's business.** Scheduling, retrying, and remembering where a vocabulary came from all sit outside this feature. A deployment script or a scheduler owns them.
