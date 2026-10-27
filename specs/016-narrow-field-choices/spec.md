# Feature Specification: Narrow a field's choices to a collection or a branch

**Feature Branch**: `016-narrow-field-choices`

**Created**: 2026-08-25

**Status**: Draft

**Input**: Issue [#164](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/164) — "Some vocabularies are large. A field on a consuming model rarely wants all of one, and offering every concept in a vocabulary of thousands makes the field harder to use and makes the wrong answer easier to pick. A consuming project should be able to point a field at the part of a vocabulary that suits it: the members of a named collection."

**Serves**: G2 (one-field consumption — a field that can only take a whole vocabulary is a field a large vocabulary cannot be consumed through) · **Roadmap**: R3 · **Issue**: #164

> Scope note: R3 delivered the consumption fields and their vocabulary restriction. This slice adds a **second, finer restriction inside a single named vocabulary**, of one of two kinds, and the declaration rules that keep it unambiguous. A *collection* restriction limits a field to the members of one collection: a `Record` of type `skos:Collection` or `skos:OrderedCollection`, whose members are the URIs in its document. A *branch* restriction limits a field to one concept and every concept below it in the hierarchy, which is the `skos:broader` and `skos:narrower` links the vocabulary's documents state. **Out of scope:** any change to the existing vocabulary restriction or to declarations that do not use the new arguments; restricting a field to a list of concepts, which the package does not provide; creating or editing collections or hierarchy, which a published vocabulary's import supplies; publication and deprecation (R4).

## Clarifications

### Session 2026-08-25 (intake)

Decisions taken with the maintainer at intake that decide behaviour a consumer would otherwise discover by guessing.

- **Q: What does a consumer write to name a collection?** → A: Its URI, the way a vocabulary is named (#233, ADR 0026), so one rule covers every argument. A URI does not move when a collection is renamed, and a declaration naming a URI that no collection holds is reported by the system check in User Story 4. Integrated into FR-001 and Edge Cases.
- **Q: A collection can be ordered, which states a deliberate sequence. Does that sequence reach a field restricted to it?** → A: Yes, where a person looks at the choices. A collection small enough to restrict a field to is exactly the case where the sequence is visible to whoever picks a value, and if it does not reach here it reaches nowhere a consumer ever looks. The concept search offers an ordered collection's members in its sequence while the search box is empty. It is specified as its own P2 story rather than folded into User Story 1, so it can be dropped without the restriction losing its meaning. Integrated into FR-008 and User Story 5.

### Session 2026-08-25 (coverage scan)

Ambiguities surfaced by the structured coverage scan over the drafted spec, resolved against the intake decisions, FS-009's precedents, and the constitution.

- **Q: What happens when a declaration combines the restriction with several vocabularies, or with none?** → A: It is refused when the declaration is read, the way the existing fields already refuse `on_delete`, `through` and `limit_choices_to`. A collection belongs to one vocabulary, so with several vocabularies named the restriction would narrow some of them and not others. Refusing at declaration time rather than at validation time means the failure lands on the developer who wrote it, in the process that imports the model, rather than on whoever first submits a form. Integrated into FR-003 and User Story 3.
- **Q: Does a restriction naming a collection absent from the database stop the project?** → A: No, and for exactly the reason FS-009 recorded for a missing vocabulary: collections arrive by import, which only a running project can perform, so refusing to boot would make a fresh install unbootstrappable. The gap is reported by the same system check FS-009 established, as a warning carrying a stable identifier, silent when the database cannot be queried at all. Integrated into FR-006 and User Story 4.

### Session 2026-10-27 (branch restriction)

Decisions taken with the maintainer when the branch restriction was added, recorded in ADR 0027.

- **Q: Why a branch, when a collection already narrows a field?** → A: A publisher almost always ships `skos:broader` and `skos:narrower` links and rarely ships collections, because a collection is a curator's own grouping. Without a branch, a consumer restricting an imported vocabulary to one subject area has nothing to name. Integrated into User Story 2.
- **Q: Does a branch include the concept it names, or only what is below it?** → A: Inclusive. A consumer naming a branch is naming a subject area, and the branch's own term is usually the right answer where nothing below it is more specific. The argument is therefore named for a branch rather than for what is under one. Integrated into FR-012.
- **Q: A link between two concepts can be stated by either side. Which counts?** → A: Both, at every step. A concept is below another when its own document states `skos:broader` the other, or the other's document states `skos:narrower` it, which is how the vocabulary's pages already read the hierarchy. A field that followed only one direction would disagree with the page a person browsed to find the concept. Integrated into FR-012.
- **Q: What if the stored links form a cycle?** → A: The read ends and returns each concept once. A published vocabulary can contain a cycle, and a read that never ends on data the database accepted is a defect. Integrated into FR-013.
- **Q: May a field carry a collection and a branch together?** → A: No. A collection and a branch narrow in different ways and nothing in the declaration says whether the result is their overlap or their union, so it is refused when the declaration is read, as the earlier combinations were. Integrated into FR-001 and User Story 3.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A field is restricted to a collection's members (Priority: P1)

A developer whose project uses a vocabulary of several thousand concepts declares a field naming that vocabulary and one of its collections. The field then accepts and offers that collection's members and nothing else. When an import of the vocabulary adds a concept to the collection, the field picks it up with no code change and no restart.

**Why this priority**: This is the request's own case. It establishes everything else the restriction needs — resolving a target within one named vocabulary, applying a second restriction on top of the vocabulary one, and carrying that through migrations.

**Independent Test**: With a vocabulary holding a collection and concepts outside it, declare both fields restricted to the collection, confirm a member is accepted and a non-member refused, confirm the offered choices are exactly the members, then add a concept to the collection and confirm the field offers it without the declaration changing.

**Acceptance Scenarios**:

1. **Given** a field restricted to a collection, **When** a member of that collection is assigned and the record validated, **Then** validation passes.
2. **Given** the same field, **When** a concept of the named vocabulary that is not a member is assigned and the record validated, **Then** validation fails with a message naming the collection.
3. **Given** a form built from the consuming model, **When** its choices are inspected, **Then** they are exactly the collection's members.
4. **Given** the same declaration on the multi-value field, **When** a set containing a non-member is attached, **Then** the whole write is refused and the record's existing set is untouched.
5. **Given** a concept added to the collection's document after the project started, **When** the field's choices are next read, **Then** the new member is among them.
6. **Given** the declaration, **When** `makemigrations` runs and then `makemigrations --check`, **Then** a migration is produced and the check reports no further changes.
7. **Given** a collection whose members include a URI no concept holds, **When** the field's choices are read, **Then** that URI offers nothing and causes no error.

---

### User Story 2 - A field is restricted to a branch of the hierarchy (Priority: P1)

A developer using an imported vocabulary that ships its broader and narrower links and no collections declares a field naming one concept as a branch root. The field then accepts that concept and every concept below it, however deep, and nothing else. When the publisher's next import adds terms under that concept, the field picks them up with no code change and no restart.

**Why this priority**: It is the restriction that works on an imported vocabulary as published, which is the common case. Without it, the same developer has no way to name a subject area, and a field offers the whole vocabulary or a collection nobody published.

**Independent Test**: Build a vocabulary three levels deep, declare both fields restricted to a mid-level concept, and confirm that concept, its children and its grandchildren are all accepted while a sibling branch and the concept above the root are refused.

**Acceptance Scenarios**:

1. **Given** a field restricted to a branch, **When** the branch root itself is assigned and the record validated, **Then** validation passes.
2. **Given** the same field, **When** a concept two levels below the root is assigned, **Then** validation passes.
3. **Given** a concept that is below the root only because the root's own document states it as `skos:narrower`, **When** it is assigned, **Then** validation passes, and so it does for a concept whose own document states `skos:broader` the root.
4. **Given** the same field, **When** a concept in a sibling branch is assigned, **Then** validation fails with a message naming the branch.
5. **Given** the same field, **When** the concept the root is itself below is assigned, **Then** validation fails, because the restriction runs downward only.
6. **Given** a branch root with nothing below it, **When** the field's choices are read, **Then** they are exactly that one concept.
7. **Given** a form built from the consuming model, **When** its choices are inspected, **Then** they are exactly the branch.
8. **Given** the same declaration on the multi-value field, **When** a set containing a concept outside the branch is attached, **Then** the whole write is refused and the record's existing set is untouched.
9. **Given** a concept added below the root after the project started, **When** the field's choices are next read, **Then** the new concept is among them.
10. **Given** stored links that form a cycle, **When** the field's choices are read, **Then** the read ends and returns each concept once.
11. **Given** a concept of another vocabulary linked below the root, **When** the field's choices are read, **Then** it is not among them, nor is anything below it.
12. **Given** the declaration, **When** `makemigrations` runs and then `makemigrations --check`, **Then** a migration is produced and the check reports no further changes.

---

### User Story 3 - A declaration that cannot mean anything is refused (Priority: P1)

A developer writes a declaration that restricts a field to a collection or a branch while naming two vocabularies, or none, or that gives both a collection and a branch. The model does not import. The message says which rule was broken, so the mistake is fixed where it was made rather than found by whoever first uses the form.

**Why this priority**: The rules this story enforces are the only thing keeping the restriction unambiguous, and the failure is otherwise silent: with several vocabularies named, a collection or branch narrows only the one it belongs to, and with two restrictions given, one of them quietly wins. Silence here produces a field that looks constrained and is not, which is worse than the unrestricted field the developer started from.

**Independent Test**: Attempt each invalid declaration — a restriction alongside several vocabularies, alongside no vocabulary, with an empty value, and a collection together with a branch — and confirm each is refused when the declaration is read, with a message identifying the rule.

**Acceptance Scenarios**:

1. **Given** a declaration naming several vocabularies and a collection, **When** the declaration is read, **Then** it is refused with a message stating that the restriction needs exactly one vocabulary.
2. **Given** a declaration naming no vocabulary and a collection, **When** the declaration is read, **Then** it is refused for the same reason.
3. **Given** a declaration naming one vocabulary and a collection, **When** the declaration is read, **Then** it is accepted.
4. **Given** any declaration not using the restriction, **When** the declaration is read, **Then** it behaves exactly as it did before this feature existed.
5. **Given** a restriction that is not a URI, a slug or an empty string among them, **When** the declaration is read, **Then** it is refused, on the same reasoning that already refuses a vocabulary named by anything but its URI.
6. **Given** a declaration that also supplies `limit_choices_to`, **When** the declaration is read, **Then** it is refused, because the package derives that restriction itself.
7. **Given** a declaration naming a collection and a branch, **When** the declaration is read, **Then** it is refused with a message stating that a field carries at most one restriction.
8. **Given** a declaration naming several vocabularies, or none, and a branch, **When** the declaration is read, **Then** it is refused with a message stating that the restriction needs exactly one vocabulary.

---

### User Story 4 - A restriction naming a target that is absent is reported, not silent (Priority: P2)

A developer mistypes a collection's or a branch root's URI, or names one that this project's import has not brought in yet. The project still imports its models, migrates and starts. Running `manage.py check` names the field and the collection or concept it expects, so the gap shows up in CI and on deploy instead of as a form that mysteriously offers nothing.

**Why this priority**: A restriction is the one kind of declaration whose failure mode is an empty field rather than an error, and an empty field looks identical whether the target is missing, misspelt or genuinely empty. It sits below the restriction itself because a project whose targets are all present never reaches this story.

**Independent Test**: Declare a field naming a collection, and another naming a branch root, absent from the database, confirm `makemigrations`, `migrate` and the test suite all succeed, then run `check` and confirm each is reported as a warning identifying the field and the missing target.

**Acceptance Scenarios**:

1. **Given** a field restricted to a collection absent from the named vocabulary, **When** `makemigrations` and `migrate` are run, **Then** both succeed.
2. **Given** the same project, **When** `manage.py check` is run, **Then** it reports a warning identifying the field and the collection it names.
3. **Given** a collection URI that another vocabulary holds but the named one does not, **When** `check` is run, **Then** it is still reported, because the pair of vocabulary and collection is what is looked up.
4. **Given** a project that silences the check by its identifier, **When** `check` is run, **Then** it reports nothing for that field.
5. **Given** a database whose tables do not exist yet, **When** `check` is run, **Then** it reports nothing rather than failing.
6. **Given** a collection that exists and holds no members, **When** `check` is run, **Then** it reports nothing, because the collection is present and empty rather than missing.
7. **Given** a field restricted to a branch whose root is absent from the named vocabulary, **When** `check` is run, **Then** it reports a warning identifying the field, the root's URI and the vocabulary.
8. **Given** a URI that a collection of the named vocabulary holds, or a concept of another vocabulary, **When** a branch names it as its root and `check` is run, **Then** it is still reported, because the root must be a concept of the named vocabulary.
9. **Given** a branch root that exists and has nothing below it, **When** `check` is run, **Then** it reports nothing.

---

### User Story 5 - An ordered collection's sequence reaches the choices (Priority: P2)

A vocabulary marks a collection as ordered and lists its members in a deliberate sequence. A field restricted to that collection offers them in that order in the concept search, while the search box is still empty, so the sequence the publisher arranged is the sequence whoever fills the form sees.

**Why this priority**: It is the only place a consumer ever sees an ordered collection's order, so without it the ordering has no reader. It is second-tier because the restriction is correct and complete without it, and it was qualified at intake as worth having only if it does not complicate the selection control.

**Independent Test**: Restrict a field to an ordered collection whose members' sequence differs from both alphabetical and creation order, and confirm the concept search returns the choices in the published sequence while nothing is typed; repeat with the collection unordered and confirm no sequence is promised.

**Acceptance Scenarios**:

1. **Given** a field restricted to an ordered collection, **When** the concept search is asked with an empty search, **Then** the choices come back in the collection's member order.
2. **Given** the same collection with its member list reordered by a later import, **When** the search is next asked, **Then** it reflects the new sequence.
3. **Given** a typed search, **When** the results are read, **Then** they follow relevance, not the collection's sequence.
4. **Given** a field restricted to a collection that is not ordered, **When** its choices are read, **Then** the restriction still holds and no particular sequence is promised.
5. **Given** an ordered collection with a member removed, **When** the choices are read, **Then** the survivors keep their relative order.

---

### User Story 6 - Translatable messages, documentation, and vocabulary (Priority: P3)

Every message this restriction puts in front of a person is translatable, the documentation shows a developer how to narrow a field to a collection or a branch, and `CONTEXT.md` records what the package now means by a restricted field.

**Why this priority**: Constitutional obligations spanning the feature rather than any one journey through it. The README point carries more weight than usual here, because the feature is a public declaration surface a consumer writes by hand, and there is no way to discover it other than being told.

**Independent Test**: Assert no user-visible string this restriction adds is a bare literal, that the documentation describes the restriction and the declaration rule, and that `CONTEXT.md` carries the term.

**Acceptance Scenarios**:

1. **Given** the refusal messages and the fields' `help_text`, **When** the source is inspected, **Then** each is wrapped for translation with named placeholders, per Article XII.
2. **Given** the shipped documentation, **When** it is read, **Then** it shows the restriction, states that it needs exactly one vocabulary and that a collection and a branch cannot be combined, and says what happens when the named collection or root is absent.
3. **Given** a field carrying a restriction and no `help_text` of its own, **When** its `help_text` is read, **Then** it describes a field restricted within its vocabulary rather than one offering the whole of it.
4. **Given** `CONTEXT.md`, **When** it is read, **Then** it defines the restriction this feature adds.

---

### Edge Cases

- The collection is resolved inside the one named vocabulary, so a collection belonging to some other vocabulary is simply absent here and reported as absent.
- A collection's URI does not change when it is renamed, so a rename does not break a declaration naming it.
- The named collection exists and holds no members. The field offers nothing and the check stays quiet, because the collection is present and empty rather than missing — the same distinction FS-009 drew for an empty vocabulary.
- A concept is removed from the collection while a record points at it. The reference survives, and the record holds a concept outside its field's restriction until it is next validated — the same outcome FS-009 recorded for a concept moved between vocabularies.
- A collection of either type, `skos:Collection` or `skos:OrderedCollection`, can be named. Its members are those under `skos:member` and `skos:memberList`.
- A concept is assigned through a bulk queryset write. The restriction is bypassed, as every model-level rule in this package is by a bulk write.
- The collection is imported after the project started. The field picks it up without a restart, because nothing about it is resolved at declaration time.
- A collection lists a member that is a collection, or a concept held by another vocabulary. The field is limited to concepts of the named vocabulary, so such a member is never offered.
- A concept below the branch root is linked to a concept of another vocabulary, or to a URI no record holds. The walk stays inside the named vocabulary, so neither is offered, and nothing below them is reached through them.
- A concept has several broader concepts, one of them inside the branch. It is offered, because it states a link to a concept of the branch.
- A collection is listed under the root's `skos:narrower`. A collection is never offered, whatever links to it.
- The branch root is a collection, or a concept of another vocabulary. The field offers nothing, and the check reports it.
- A branch is read each time a choice is validated or searched, in one query over the stored links, so a link added by an import is followed from the next read.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Both concept fields MUST accept one optional restriction that narrows choices inside the vocabulary a declaration names — a collection or a branch, naming its target by URI, resolved within that vocabulary. A value that is not a URI MUST be refused, and a declaration giving both a collection and a branch MUST be refused with a message stating that a field carries at most one restriction.
- **FR-002**: A collection restriction MUST limit the field to that collection's members, resolved live rather than fixed when the declaration is read, so a membership change reaches the field without a code change or a restart. A collection of either type MUST be accepted as the target.
- **FR-003**: The restriction MUST be refused when the declaration does not name exactly one vocabulary, at the point the declaration is read, with a message stating the rule.
- **FR-004**: No database query MUST be issued while a declaration is being read, exactly as for the existing vocabulary restriction, so a project imports its models, generates migrations, migrates and starts with the named collection absent.
- **FR-005**: The restriction MUST be enforced both in the choices a form offers and when a record is validated, for the single-value and the multi-value field alike, with a person-facing message naming the collection or the branch the field is restricted to. For the multi-value field a write containing any concept outside the restriction MUST be refused whole, leaving the record's existing set untouched.
- **FR-006**: The package's existing system check MUST additionally report, as a warning with a stable identifier, every declared field whose named collection is absent from the named vocabulary, or whose branch root is not a concept of it, identifying the specific absent target by vocabulary and URI. It MUST report nothing when the database cannot be queried, and nothing for a collection that exists and is empty or a root that has nothing below it.
- **FR-007**: A restriction MUST survive `deconstruct()` and rebuild from the emitted arguments, so migrations, `makemigrations --check` and the test-database build are unaffected, and the emitted arguments MUST record the restriction itself rather than any expression derived from it.
- **FR-008**: Where the restriction is a collection marked ordered, the concept search MUST offer the collection's members in the sequence it lists them while the search term is empty, and MUST return to relevance order once a term is typed. No sequence is promised anywhere else.
- **FR-009**: Every string this restriction puts in front of a person, including refusal messages and the `help_text` a restricted field falls back to, MUST be translatable per Article XII, with named placeholders so message identifiers stay static.
- **FR-010**: The documentation MUST describe both restrictions, the declaration rules, and the behaviour when the named collection or root is absent. `CONTEXT.md` MUST carry the terms.
- **FR-011**: A declaration not using a restriction MUST behave exactly as it did before this feature, including one naming several vocabularies or none.
- **FR-012**: A branch restriction MUST limit the field to the concept named as its root and every concept below it at any depth, within the one named vocabulary. A concept is below another when its own document states `skos:broader` the other, or the other's document states `skos:narrower` it, and both directions MUST be followed at every step. The walk MUST run downward only, so the root's broader concepts and its siblings are never offered, and only concepts (`skos:Concept`) are offered.
- **FR-013**: A branch MUST be resolved in a single query over the stored links, live at the time a choice is validated, offered or searched, and that query MUST end when the stored links form a cycle, returning each concept once. No query is issued while the declaration is read.

### Key Entities *(include if feature involves data)*

- **Restriction**: The second, narrower constraint a declaration may carry inside its one named vocabulary: `collection=<uri>`, `branch=<uri>`, or none, which is every declaration that exists without it. A declaration carries at most one.
- **Collection**: A publisher-defined grouping of concepts within one vocabulary, optionally ordered, held as a `Record` of type `skos:Collection` or `skos:OrderedCollection`. This feature reads it and never writes it.
- **Branch**: A concept and every concept below it in the hierarchy the vocabulary's documents state with `skos:broader` and `skos:narrower`. The concept it grows from is its root. This feature reads the hierarchy and never writes it.
- **Named target**: The collection or branch root a restriction points at, identified by URI within the named vocabulary. It may be absent when the declaration is read, and it arrives by import.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consuming project restricts a field to part of one vocabulary, writing no query, no validator and no form-field override of its own.
- **SC-002**: No validated write path stores a concept outside a field's restriction, and no form offers one, for the single-value and multi-value field alike.
- **SC-003**: A restriction reflects a change to the collection's membership, or to the links below a branch root, on the next read, with no code change, no migration and no restart.
- **SC-004**: Every declaration that combines a restriction with anything other than exactly one vocabulary, or with another restriction, fails when the model is imported, and the message identifies the rule broken.
- **SC-005**: A project whose restriction target is absent from the database generates migrations, migrates, starts and runs its tests without failure, and `manage.py check` names the field and the collection or root it expects.
- **SC-006**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, migrations are consolidated per Article XIII, and no user-visible string this feature adds is untranslatable.

## Assumptions

- **Collections and hierarchy arrive by import.** This feature creates neither. A project whose vocabulary has no collections names a branch of its hierarchy or the whole vocabulary, and one whose vocabulary has neither names the whole vocabulary or a different vocabulary.
- **The restriction is a model-layer rule.** A bulk queryset write bypasses it, as it bypasses every model-level rule in this package. The delete protection the existing fields provide is unchanged and still holds against a bulk delete.
- **A field carries at most one restriction.** A collection or a branch narrows a field, and a list of named concepts is not provided. Combining a collection and a branch has an intersection reading and a union reading that nothing in the declaration tells apart, so it is refused.
- **The hierarchy is read from the links the documents state.** A link is read from the `skos:broader` or `skos:narrower` entry of either record, as the vocabulary's pages read it. A vocabulary that states a link only from one side is still followed.
- **Membership is read from the collection's document.** A member is a URI under `skos:member` or `skos:memberList`, and it is a choice only when it names a concept of the named vocabulary.
- **Deprecation does not exist yet.** A concept is either present or absent, so a restriction cannot exclude a retired concept. Publication and deprecation arrive with R4.
