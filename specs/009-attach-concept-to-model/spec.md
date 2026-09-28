# Feature Specification: Attach a concept from a chosen vocabulary to a model

**Feature Branch**: `009-attach-concept-to-model`

**Created**: 2026-08-11

**Status**: Draft

**Input**: Issue [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) — "A Django project should be able to point one of its own models at a concept from a chosen vocabulary with a single field declaration, the way it would use any other model field. Right now that means hand-rolling a foreign key and enforcing the vocabulary constraint yourself, which is the boilerplate this package exists to remove. The consuming record should be able to read back the concept's name and its identifier without knowing anything about how concepts are stored. And a concept that some record is actually using should not be able to vanish out from under it."

**Serves**: G2 (one-field consumption — this is the goal stated almost word for word) · **Roadmap**: R3 · **Issue**: #86

> Scope note: this is the first of four slices of roadmap item R3, and the one every other slice builds on. It owns **the single-value field itself**: declaring it, constraining what may be stored in it, reaching the concept's label and identifier from the consuming record, and refusing to let a concept disappear while a record points at it. Selection in a form uses whatever Django renders for a relation by default. **Out of scope:** attaching several concepts at once ([#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87)), search-as-you-type selection and the scale work that comes with it ([#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88)), the Django admin ([#89](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/89)), getting vocabularies into the database at all (R2, delivered), publication and deprecation (R4), serving RDF (R4), and the curator-facing editing interface (R5).

## Clarifications

### Session 2026-08-11 (intake)

One decision was taken with the maintainer at intake, because it decides whether the field is usable in a project whose deployment order has not yet run an import.

- **Q: A field is declared in code, but the vocabulary it names is data that arrives by import. What happens on an install where that import has not run yet?** → A: The field never fails at import or migration time over a missing vocabulary. The gap is reported as a Django system check, so it surfaces in CI and on deploy, and at runtime the field simply has nothing to offer. Whether an empty value is then an error is decided by the field's own required-or-optional declaration, exactly as for any other Django field. The alternative — refusing to boot — would make a fresh install unbootstrappable, because the vocabulary can only be imported by a project that is already running. Integrated into FR-003, FR-004, and User Story 4.

### Session 2026-08-11 (coverage scan)

Four further ambiguities surfaced by the structured coverage scan over the drafted spec, resolved here against the intake decision, `CONTEXT.md`, and the constitution.

- **Q: How does a declaration name its vocabulary, given the vocabulary may not exist when the declaration is read?** → A: By the vocabulary's slug. The candidates are its slug, its URI, and a reference to the row itself. A row reference is ruled out by the intake decision, since resolving one needs a database. A URI is ruled out for a vocabulary authored on this site, because `CONTEXT.md` makes that URI dynamic — composed from the site's configured address — so the same vocabulary carries a different identifier on a developer machine and in production, and a declaration naming one would be wrong in the other. The slug is unique app-wide and is the segment the local address is built from. Its known weakness is that a locally authored vocabulary's slug is re-derived from its name on save, so renaming one breaks declarations naming it. That failure is caught by the very check the intake decision adds, which reports the named vocabulary as absent, and a curator who does not want a slug to move sets it explicitly. Integrated into FR-002 and Edge Cases.
- **Q: A system check that fails stops `migrate` from running. Does this one?** → A: No. It is a warning, not an error, and it carries a stable identifier so a project that knows the vocabulary arrives later can silence it. An error would contradict the intake decision directly: `manage.py migrate` runs the system checks first, so an error on a missing vocabulary would block the migration that creates the tables the vocabulary is imported into. The check must also stay silent when it cannot ask the question at all — an unmigrated or unreachable database is not evidence that a vocabulary is missing. Integrated into FR-004 and Edge Cases.
- **Q: Where does the vocabulary constraint bite — at validation, or in the database?** → A: At validation, through the field's own validation and the choices it offers, in the same place every other rule in this package is enforced. `CONTEXT.md` already records that a bulk queryset write bypasses model-level rules, and this rule is no different. A database-level constraint would have to duplicate each concept's vocabulary onto the consuming table to be checkable, which trades a real schema cost and a synchronisation problem against a bypass that requires deliberately writing around the model layer. Integrated into FR-005 and Assumptions.
- **Q: In which language does a record read back its concept's label?** → A: The active language, falling back to the vocabulary's default language when the concept carries no preferred label in the active one. A concept always has a preferred label in its vocabulary's default language, so the readback never comes back empty for a concept that exists. Returning nothing for a site whose active language a vocabulary does not carry would make the readback unusable for exactly the multilingual case G6 exists to serve. The underlying per-language reads stay available unchanged for a caller that wants one specific language. Integrated into FR-008.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A project attaches a concept with one declaration (Priority: P1)

A developer building a Django project adds a field to one of their own models naming a vocabulary, runs `makemigrations` and `migrate`, and from then on assigns concepts from that vocabulary to their records and reads them back. They write no foreign key, no vocabulary constraint, and no lookup helper.

**Why this priority**: This is G2 stated as a user journey, and the reason the package exists. Without it every consumer hand-rolls the same foreign key and the same constraint check, which is the boilerplate the package was written to remove.

**Independent Test**: Declare the field on a test model naming a vocabulary present in the database, migrate, assign a concept from that vocabulary, save, reload the record, and confirm the same concept comes back.

**Acceptance Scenarios**:

1. **Given** a model declaring the field against a vocabulary that exists, **When** a concept from that vocabulary is assigned and the record saved, **Then** reloading the record returns that concept.
2. **Given** the same model, **When** `makemigrations` runs, **Then** it produces a migration, and running it and then `makemigrations --check` reports no further changes.
3. **Given** a declaration passing the ordinary field options — optional, a reverse name, a database index choice — **When** the model is used, **Then** each behaves as it does on any other Django relation field.
4. **Given** a record with no concept assigned and a field declared optional, **When** the record is validated and saved, **Then** it saves without error.

---

### User Story 2 - Selections stay inside the named vocabulary (Priority: P1)

A concept from some other vocabulary cannot end up in the field. A developer who assigns one is told so when the record is validated, and a form built from the model offers only concepts from the named vocabulary in the first place.

**Why this priority**: The constraint is the whole difference between this field and a plain foreign key to `Concept`. Without it the package removes boilerplate by removing the guarantee that boilerplate existed to provide.

**Independent Test**: With two vocabularies in the database, assign a concept from the wrong one and confirm validation refuses it, then build a form from the model and confirm its offered choices contain only the named vocabulary's concepts.

**Acceptance Scenarios**:

1. **Given** two vocabularies each holding concepts, **When** a concept from the vocabulary the field does not name is assigned and the record validated, **Then** validation fails with a message naming the expected vocabulary.
2. **Given** a form generated from the consuming model, **When** its choices are inspected, **Then** every one is a concept of the named vocabulary and no concept of any other vocabulary appears.
3. **Given** a form submission carrying a concept from another vocabulary, **When** the form is validated, **Then** it is rejected rather than saved.
4. **Given** a concept assigned from the correct vocabulary, **When** the record is validated, **Then** validation passes.

---

### User Story 3 - A concept in use cannot vanish (Priority: P1)

A curator tidying up a vocabulary tries to delete a concept that a record somewhere points at. The deletion is refused and the record is untouched. Deleting the vocabulary holding that concept is refused for the same reason.

**Why this priority**: Article IX makes this a day-one invariant, and R3 is the release where it first has something to protect — [#19](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/19) was deferred precisely because nothing could reference a concept until this feature existed. A reference that can be broken by an ordinary delete is worse than no reference at all, because the data loss is silent.

**Independent Test**: Point a record at a concept, attempt to delete that concept, confirm the deletion is refused and both the concept and the record survive. Repeat for the vocabulary containing it.

**Acceptance Scenarios**:

1. **Given** a record pointing at a concept, **When** that concept is deleted, **Then** the deletion is refused and both the concept and the record remain.
2. **Given** the same record, **When** the vocabulary holding that concept is deleted, **Then** the deletion is refused and nothing in the vocabulary is removed.
3. **Given** a concept no record points at, **When** it is deleted, **Then** it is deleted, because the guard protects references rather than forbidding removal.
4. **Given** a record pointing at a concept, **When** the record itself is deleted, **Then** it is deleted and the concept remains, because the protection runs one way.

---

### User Story 4 - A vocabulary that has not been imported yet (Priority: P2)

A developer clones a project, creates an empty database, and runs the migrations before any vocabulary has been imported. Nothing fails. Running `manage.py check` tells them which vocabulary the project expects and has not got, so the gap is visible in CI and on deploy rather than discovered by a form that mysteriously offers nothing.

**Why this priority**: Every fresh install and every CI run passes through this state, because a vocabulary can only be imported by a project that already runs. It is second only to the field working at all.

**Independent Test**: With an empty database and a model declaring the field against a vocabulary nobody has imported, run `makemigrations`, `migrate` and the test suite and confirm each succeeds, then run `check` and confirm it names the missing vocabulary as a warning.

**Acceptance Scenarios**:

1. **Given** a model naming a vocabulary absent from the database, **When** `makemigrations` and `migrate` are run, **Then** both succeed.
2. **Given** the same project, **When** `manage.py check` is run, **Then** it reports a warning identifying the field and the vocabulary it names.
3. **Given** the same project, **When** a form is built from the consuming model, **Then** it offers no choices and does not raise.
4. **Given** a project that silences the check by its identifier, **When** `check` is run, **Then** it reports nothing for that field.
5. **Given** a database whose tables do not exist yet, **When** `check` is run, **Then** it reports nothing rather than failing on the missing table.

---

### User Story 5 - The record reads back the label and the identifier (Priority: P2)

Code rendering a record — a template, a serializer, an export — asks it for the attached concept's name and its identifier and gets both. It does not query label tables, and it does not build an address out of parts.

**Why this priority**: The issue names this explicitly, and without it every consumer reimplements label resolution and learns the storage layout the field exists to hide. It sits below the first three because a record with the wrong concept in it, or one whose concept has been deleted, is a worse outcome than an awkward read.

**Independent Test**: With a concept carrying preferred labels in more than one language, read the label from the consuming record under each active language and confirm the resolution and its fallback, then read the identifier and confirm it matches the concept's own.

**Acceptance Scenarios**:

1. **Given** a record whose concept has a preferred label in the active language, **When** the label is read from the record, **Then** it is the label in that language.
2. **Given** a record whose concept has no preferred label in the active language, **When** the label is read, **Then** it is the label in the vocabulary's default language rather than empty.
3. **Given** a record with a concept attached, **When** the identifier is read, **Then** it is the concept's own URI, unchanged.
4. **Given** a record with nothing attached, **When** either is read, **Then** the read returns nothing rather than raising.

---

### User Story 6 - Translatable messages, documentation, and reusable test material (Priority: P3)

Every string the field puts in front of a person is translatable, the README shows a developer how to declare the field, `CONTEXT.md` carries the term the package now uses in public, and the fixtures this feature needs are reachable by the three sibling features that follow it.

**Why this priority**: Constitutional obligations that apply across the feature rather than to one journey through it. The fixture point matters more than usual here, because #87, #88 and #89 all build directly on this field.

**Independent Test**: Assert no user-visible string in the field is a bare literal, that the README documents the declaration and the readback, that `CONTEXT.md` defines the term, and that the consuming test model and its fixtures live where a sibling feature can reach them.

**Acceptance Scenarios**:

1. **Given** the field's validation messages and its `help_text`, **When** the source is inspected, **Then** each is wrapped for translation with named placeholders, per Article XII.
2. **Given** the shipped documentation, **When** the README is read, **Then** it shows a field declaration, the readback of label and identifier, and what happens when the named vocabulary is absent.
3. **Given** the test suite, **When** the modules are located, **Then** they mirror the source tree per testing standard §4 and the consuming model and fixtures are shared rather than redefined per test.

---

### Edge Cases

- A locally authored vocabulary is renamed, which re-derives its slug, and declarations naming the old slug now name nothing. The check reports it as an absent vocabulary. Setting the slug explicitly is what prevents it moving.
- Two vocabularies cannot share a slug, so a declaration never resolves to more than one.
- The named vocabulary exists but holds no concepts. The field offers nothing and the check stays quiet, because the vocabulary is present and empty rather than missing.
- A concept is moved from the named vocabulary to another one while a record points at it. The reference survives, and the record now holds a concept from outside the field's vocabulary until it is next validated.
- The database is unreachable or unmigrated when the check runs. Nothing is reported, because the check cannot distinguish a missing vocabulary from a missing table.
- A concept is deleted through a bulk queryset delete. The deletion is still refused, because the protection lives in the database relation rather than in model validation.
- A concept is assigned to a record through a bulk queryset write. The vocabulary constraint is bypassed, as every model-level rule in this package is by a bulk write.
- The vocabulary is imported after the project started. The field picks it up without a restart, because nothing about the vocabulary is cached at declaration time.
- A form field is rendered against a vocabulary with tens of thousands of concepts. It works and it is slow, and making it fast is [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST ship a model field that attaches a single concept to a consuming project's model through one declaration, and that behaves as an ordinary Django relation field for migrations, forms, validation, and serialization.
- **FR-002**: The declaration MUST name ~~exactly one vocabulary~~ **zero, one, or several vocabularies**, by ~~that~~ **each** vocabulary's slug, and MUST resolve ~~it~~ **them** without requiring the vocabulary to exist when the declaration is read. ~~Naming no vocabulary MUST be refused, because an unconstrained field is a plain foreign key and offers none of this field's guarantees.~~ **[Amended by #111, 2026-08-12]** — the struck clause carried the assumption FS-010's `decisions.md` D9 had already overturned for the many-valued field: an unconstrained field still protects its reference from deletion and still reads back a label and an identifier, which is what a plain foreign key does not give you. The two fields now take the same three shapes and mean the same thing by each, so a field naming none gives up the restriction and nothing else. An empty slug is still refused, for both fields: no vocabulary can carry one, so a declaration holding it would offer no choices at all while reading as a restricted field.
- **FR-003**: Declaring the field against a vocabulary absent from the database MUST NOT prevent the project from importing its models, generating migrations, running migrations, or starting. No database query MUST be issued while the declaration is being read.
- **FR-004**: The package MUST contribute a Django system check that reports, as a warning with a stable identifier, every declared field whose named vocabulary is absent from the database. It MUST NOT report an error, because `migrate` runs the checks first and an error would block the migration that creates the tables the vocabulary is imported into. It MUST report nothing when the database cannot be queried at all.
- **FR-005**: Storing a concept that does not belong to the named vocabulary MUST be refused when the record is validated, with a curator-facing message naming the expected vocabulary. Enforcement lives at the model and form validation layer, alongside every other rule in this package.
- **FR-006**: The choices a form offers for the field MUST be limited to concepts of the named vocabulary, so an invalid selection is unreachable rather than merely refused after the fact.
- **FR-007**: A concept MUST NOT be deletable while any record references it, per Article IX, and the refusal MUST hold for a bulk queryset delete as well as a single one. Deleting the vocabulary holding a referenced concept MUST be refused for the same reason. Deleting a consuming record MUST NOT affect the concept.
- **FR-008**: A consuming record MUST expose the attached concept's preferred label without the caller querying label storage. The label MUST be resolved in the active language, falling back to the vocabulary's default language when the concept carries no preferred label in the active one. A record with nothing attached MUST return nothing rather than raise.
- **FR-009**: A consuming record MUST expose the attached concept's URI unchanged, without the caller composing it from parts. A record with nothing attached MUST return nothing rather than raise.
- **FR-010**: The field MUST accept the ordinary Django field options a relation takes — including optional, blank, a reverse accessor name, and the deliberate indexing choice Article XIII requires — and MUST NOT silently override any of them.
- **FR-011**: Every string the field puts in front of a person, including validation messages and `help_text`, MUST be translatable per Article XII, with named placeholders so the message identifiers stay static. `help_text` MUST be present, per the same article.
- **FR-012**: `CONTEXT.md` MUST define the term this feature puts into a consuming project's code, and MUST be reconciled where it already describes the consumption field. The README MUST document declaring the field, reading the label and identifier back, and the behaviour when the named vocabulary is absent. The CHANGELOG MUST record the addition.

### Key Entities *(include if feature involves data)*

- **Consumer model**: A model belonging to the project that installs this package, carrying one or more of these fields. This package knows nothing about it beyond the reference.
- **The field**: The declaration on that model. It holds a reference to one concept, remembers which vocabulary that concept must come from, and reaches the concept's label and identifier on the record's behalf.
- **Named vocabulary**: The vocabulary a declaration points at, identified by slug. It may be absent when the declaration is read, and it arrives by import.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A project attaches a controlled-vocabulary concept to one of its own models with a single field declaration, writing no foreign key, no vocabulary constraint, and no label lookup of its own.
- **SC-002**: No validated write path stores a concept from outside the named vocabulary, and no form offers one.
- **SC-003**: Every attempt to delete a referenced concept is refused with the concept and the referencing record intact, including through a bulk delete and including by way of deleting the vocabulary that holds it.
- **SC-004**: From a consuming record, the attached concept's preferred label and its URI are each reached in one read, and the label is correct for a site whose active language the concept carries and for one it does not.
- **SC-005**: A project declaring the field against a vocabulary absent from the database generates migrations, migrates, starts and runs its tests without failure, and `manage.py check` names the field and the vocabulary it expects.
- **SC-006**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, migrations are consolidated per Article XIII, and no user-visible string in the field is untranslatable.

## Assumptions

- **Vocabularies arrive by import.** R2 delivered that, and this feature loads nothing itself. A project with no vocabulary in its database is a project that has not run one, not a case this feature handles differently.
- **The constraint is a model-layer rule.** A bulk queryset write bypasses it, as it bypasses every model-level rule in this package — `CONTEXT.md` already records this for `static_uri`. The delete guard is the exception, because it lives in the database relation and therefore holds against a bulk delete too.
- **Scale belongs to the sibling.** The default form representation loads the named vocabulary's concepts, which is fine for the vocabularies a test fixture holds and unacceptable for the ones import now brings in. Making that usable is [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88), and this feature deliberately does not anticipate it.
- **Deprecation does not exist yet.** A concept is either present or absent. Publication and deprecation arrive with R4, and until then this field cannot distinguish a live concept from a retired one, because nothing marks one.
- **No release carries the old behaviour.** The package is at `0.0.x` with its first publish still ahead in the v0.1.0 milestone, so adding a field owes no upgrade path and no deprecation cycle.
- **The multiple-value field will reuse this.** [#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87) states the same guarantees for a set of concepts. This feature is not built to anticipate it, but its constraint, its check, and its test material should not be shaped so that #87 has to duplicate them.
