# Feature Specification: Attach several concepts from a chosen vocabulary to a model

**Feature Branch**: `010-attach-several-concepts`

**Created**: 2026-08-12

**Status**: Refined

**Refined**: 2026-08-12 — naming a vocabulary became optional. The declaration now accepts one vocabulary, several, or none at all, so a project can carry a keywords field drawing on whatever it has imported. Affects FR-002, FR-004, FR-005, FR-006, SC-002, User Story 2, and adds User Story 8.

**Input**: Issue [#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87) — "Plenty of records need more than one concept. A dataset is tagged with several methods, a publication covers several topics. The same single-field convenience should extend to attaching a set of concepts from a chosen vocabulary, with the same guarantees: selections stay inside that vocabulary, and a concept in use does not disappear."

**Serves**: G2 (one-field consumption) · **Roadmap**: R3 · **Issue**: #87 · **Depends on**: [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) (delivered)

> Scope note: this is the second of four slices of roadmap item R3, and it builds directly on the single-value field delivered by [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86). It owns **the multiple-value field**: declaring it, constraining every member of the set to the vocabularies the declaration names, saying what an empty set means, reaching each attached concept's label and identifier from the consuming record, and refusing to let a concept disappear while any record holds it. Selection in a form uses whatever Django renders for a many-valued relation by default. **Out of scope:** search-as-you-type selection and the scale work that comes with it ([#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88)), the Django admin ([#89](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/89)), an order over the attached set, any cap on how many concepts a record may hold, getting vocabularies into the database at all (R2, delivered), publication and deprecation (R4), and the curator-facing editing interface (R5).

## Clarifications

### Session 2026-08-12 (intake)

One decision was taken with the maintainer at intake, because it decides what the feature is rather than how it is built.

- **Q: Does the set of attached concepts carry an order the consuming project can rely on?** → A: No. The set is unordered, and a record's concepts come back in a stable but unspecified order. Tagging a dataset with several methods reads as a set rather than a sequence, and an order would put a position on every membership of every consuming model permanently, for a want nobody has stated. The collections feature already covers deliberately ordered groupings of concepts, on the vocabulary side where the order is the curator's. If ordered tagging is ever wanted on the consumer side, it arrives then as its own feature. Integrated into FR-001 and Assumptions.

### Session 2026-08-12 (coverage scan)

Four further ambiguities surfaced by the structured coverage scan over the drafted spec, resolved here against the intake decision, the delivered single-value field, `CONTEXT.md`, and the constitution.

- **Q: Where does the vocabulary constraint bite, given a many-valued relation is written through its own manager rather than by assignment?** → A: At form validation, in the choices a form offers, **and on the relation's own write path**. For the single-value field, validating the record was enough, because the value is an attribute of the record and record validation sees it. A many-valued relation is not: it is written by its own manager, after the record is saved, and validating the record never inspects it. Leaving enforcement at record validation alone would mean the ordinary way to use this field — adding concepts through the relation — carries none of the guarantee the field exists to provide, which is the difference between this field and a plain many-to-many to `Concept`. The refusal therefore holds wherever a membership is created, and the message names the expected vocabulary as the single-value field's does. Integrated into FR-005 and Assumptions.
- **Q: What does declaring the field required mean, when a many-valued relation has no empty state at the database level?** → A: At least one concept, checked when a record is validated and by any form built from the model, and the field declared optional accepts a record holding no concepts at all. A record is saved before its memberships can be written, so the check is a validation rule rather than a storage constraint, and a project that writes memberships without validating gets the same latitude it gets everywhere else in this package. Integrated into FR-010 and User Story 5.
- **Q: A record already holds a concept and the same concept is attached again. Is that an error?** → A: No. It is a set, so attaching a concept already present leaves the record holding it exactly once and reports no error. Refusing would make a caller check membership before every write for no benefit, and a set with a duplicate in it is not a state the feature has any reading for. Integrated into FR-001 and Edge Cases.
- **Q: What happens to the memberships when the consuming record itself is deleted?** → A: The record goes, its memberships go with it, and every concept it held survives untouched. The protection runs one way — it exists so a curator cannot pull a concept out from under a record, not so a record cannot be deleted. This matches the single-value field, where deleting the record leaves the concept alone. Integrated into FR-007 and User Story 3.

### Session 2026-08-12 (refinement)

Raised by the maintainer after the plan was reviewed and before any code was written.

- **Q: Must a declaration name exactly one vocabulary?** → A: No. It names one, several, or none. The original requirement refused an unnamed vocabulary on the grounds that an unconstrained field is a plain many-to-many, and that reasoning was too narrow: a record tagged with keywords drawn from whatever the project has imported is a standard shape in research metadata, and a field naming several vocabularies — keywords from one of two published schemes — is the more common form of it. Naming several is the same restriction with a wider set. Naming none drops the restriction entirely, and the field then guarantees what remains: references that cannot be deleted out from under a record, and labels and identifiers readable from it. Integrated into FR-002, FR-004, FR-005, FR-006, SC-002, User Story 2 and User Story 8.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A project attaches several concepts with one declaration (Priority: P1)

A developer building a Django project adds a field to one of their own models naming a vocabulary, runs `makemigrations` and `migrate`, and from then on attaches any number of concepts from that vocabulary to each record and reads them back. They write no many-to-many, no join model, and no vocabulary constraint of their own.

**Why this priority**: This is the feature. Records that need several concepts are the common case the issue opens with — a dataset tagged with several methods, a publication covering several topics — and without this each consumer hand-rolls the join and the constraint that the single-value field already spared them.

**Independent Test**: Declare the field on a test model naming a vocabulary present in the database, migrate, attach two concepts from that vocabulary, save, reload the record, and confirm both come back and no third appears.

**Acceptance Scenarios**:

1. **Given** a model declaring the field against a vocabulary that exists, **When** two concepts from that vocabulary are attached and the record reloaded, **Then** both come back.
2. **Given** the same model, **When** `makemigrations` runs, **Then** it produces a migration, and running it and then `makemigrations --check` reports no further changes.
3. **Given** a record holding a concept, **When** the same concept is attached again, **Then** the record holds it exactly once and nothing is reported as an error.
4. **Given** a record holding two concepts, **When** one is removed, **Then** the record holds the other and the removed concept itself still exists.
5. **Given** a declaration passing the ordinary options a many-valued relation takes — a reverse accessor name among them — **When** the model is used, **Then** each behaves as it does on any other Django relation.

---

### User Story 2 - Every selection stays inside the vocabularies the field names (Priority: P1)

A concept from a vocabulary the declaration does not name cannot end up in a record's set. A developer who attaches one is refused, and a form built from the model offers only concepts from the named vocabularies in the first place.

*Refined 2026-08-12: reads "the vocabularies the field names" throughout, because a declaration may now name several. A declaration naming none has no restriction to enforce and is User Story 8's subject.*

**Why this priority**: The constraint is the whole difference between a field that names vocabularies and a plain many-to-many to `Concept`. A guarantee that holds when a form is submitted but not when the relation is written directly is not a guarantee, because writing the relation directly is how a many-valued field is ordinarily used.

**Independent Test**: With two vocabularies in the database, attach a concept from an unnamed one directly through the relation and confirm the refusal, submit a form carrying one and confirm the rejection, then inspect a generated form's choices and confirm only the named vocabularies' concepts appear.

**Acceptance Scenarios**:

1. **Given** two vocabularies each holding concepts, **When** a concept from a vocabulary the field does not name is attached through the relation, **Then** it is refused with a message naming the expected vocabularies, and the record's set is unchanged.
2. **Given** the same record, **When** several concepts are attached at once and one of them is from an unnamed vocabulary, **Then** the whole write is refused and the record's set is unchanged.
3. **Given** a form generated from the consuming model, **When** its choices are inspected, **Then** every one is a concept of a named vocabulary and no concept of any other vocabulary appears.
4. **Given** a form submission carrying a concept from an unnamed vocabulary, **When** the form is validated, **Then** it is rejected rather than saved.
5. **Given** concepts from a named vocabulary, **When** they are attached, **Then** the write succeeds.

---

### User Story 3 - A concept anyone holds cannot vanish (Priority: P1)

A curator tidying up a vocabulary tries to delete a concept that some record has attached. The deletion is refused and every record keeps its set intact. Deleting the vocabulary holding that concept is refused for the same reason.

**Why this priority**: Article IX makes this a day-one invariant, and a many-valued relation is where it is easiest to lose: Django's default for this shape is to drop the membership silently when the concept goes, so a record would quietly end up tagged with fewer concepts than it was and nothing would say so. The single-value field got this from the relation itself. Here it has to be built.

**Independent Test**: Attach a concept to a record, attempt to delete that concept both singly and through a bulk delete, confirm both are refused and that the concept, the record and the membership all survive. Repeat for the vocabulary containing it.

**Acceptance Scenarios**:

1. **Given** a record holding a concept, **When** that concept is deleted, **Then** the deletion is refused and the concept, the record and the membership all remain.
2. **Given** the same record, **When** the concept is deleted through a bulk queryset delete, **Then** the deletion is refused for the same reason.
3. **Given** the same record, **When** the vocabulary holding that concept is deleted, **Then** the deletion is refused and nothing in the vocabulary is removed.
4. **Given** a concept no record holds, **When** it is deleted, **Then** it is deleted, because the guard protects references rather than forbidding removal.
5. **Given** a record holding two concepts, **When** the record itself is deleted, **Then** the record and its memberships go and both concepts remain.
6. **Given** a record holding a concept, **When** that concept is removed from the record's set and then deleted, **Then** the deletion succeeds, because nothing holds it any more.

---

### User Story 4 - The record reads back the labels and the identifiers (Priority: P2)

Code rendering a record — a template, a serializer, an export — asks it for the names and the identifiers of the concepts attached to it and gets both. It does not query label tables, and it does not build addresses out of parts.

**Why this priority**: The issue asks for the same convenience the single-value field gives, and without it every consumer reimplements label resolution across a set and learns the storage layout the field exists to hide. It sits below the first three because a record holding the wrong concepts, or one whose concepts have been deleted, is a worse outcome than an awkward read.

**Independent Test**: With concepts carrying preferred labels in more than one language, read the labels from a record holding several of them under each active language and confirm the resolution and its fallback, then read the identifiers and confirm they match the concepts' own.

**Acceptance Scenarios**:

1. **Given** a record holding several concepts each with a preferred label in the active language, **When** the labels are read from the record, **Then** they are the labels in that language, one for each attached concept.
2. **Given** a record holding a concept with no preferred label in the active language, **When** the labels are read, **Then** that concept's label is the one in the vocabulary's default language rather than empty.
3. **Given** a record holding several concepts, **When** the identifiers are read, **Then** they are the concepts' own URIs, unchanged, one for each.
4. **Given** a record holding no concepts, **When** either is read, **Then** the read returns nothing to iterate over rather than raising.

---

### User Story 5 - Required means at least one (Priority: P2)

A developer declaring the field decides whether a record may exist with no concepts attached. Declared optional, a record with an empty set is valid. Declared required, a record with an empty set is refused when it is validated and by any form built from the model.

**Why this priority**: A many-valued relation has no empty state at the database level, so "required" has to be given a meaning here or every consumer invents its own. It sits below the guarantees because a record with too few concepts is a milder failure than one holding a concept from the wrong vocabulary.

**Independent Test**: Declare the field twice, once optional and once required, and confirm that an empty set validates in the first case and is refused in the second, both through record validation and through a form.

**Acceptance Scenarios**:

1. **Given** a model whose field is declared optional, **When** a record with no concepts attached is validated, **Then** validation passes.
2. **Given** a model whose field is declared required, **When** a record with no concepts attached is validated, **Then** validation fails with a message that names the field.
3. **Given** a form built from a model whose field is required, **When** it is submitted with nothing selected, **Then** it is rejected.
4. **Given** a form built from a model whose field is optional, **When** it is submitted with nothing selected, **Then** it saves.

---

### User Story 6 - A vocabulary that has not been imported yet (Priority: P2)

A developer clones a project, creates an empty database, and runs the migrations before any vocabulary has been imported. Nothing fails. Running `manage.py check` tells them which vocabulary the project expects and has not got, naming this field alongside any single-value one.

**Why this priority**: Every fresh install and every CI run passes through this state, because a vocabulary can only be imported by a project that already runs. The single-value field already established both the behaviour and the check, so what this story owns is that the new field is covered by it rather than quietly exempt.

**Independent Test**: With an empty database and a model declaring the field against a vocabulary nobody has imported, run `makemigrations`, `migrate` and the test suite and confirm each succeeds, then run `check` and confirm the warning names this field and its vocabulary.

**Acceptance Scenarios**:

1. **Given** a model naming a vocabulary absent from the database, **When** `makemigrations` and `migrate` are run, **Then** both succeed.
2. **Given** the same project, **When** `manage.py check` is run, **Then** it reports a warning identifying this field and the vocabulary it names, under the same identifier the single-value field's warning uses.
3. **Given** the same project, **When** a form is built from the consuming model, **Then** it offers no choices and does not raise.
4. **Given** a database whose tables do not exist yet, **When** `check` is run, **Then** it reports nothing rather than failing on the missing table.

---

### User Story 7 - Translatable messages, documentation, and reusable test material (Priority: P3)

Every string the field puts in front of a person is translatable, the README shows a developer how to declare the multiple-value field and read it back, `CONTEXT.md` carries the term the package now uses in public, and the test material this feature needs extends what the single-value field left rather than duplicating it.

**Why this priority**: Constitutional obligations that apply across the feature rather than to one journey through it. The test-material point matters here because the single-value field deliberately left its consuming model and fixtures shareable, and the two features that follow will need both.

**Independent Test**: Assert no user-visible string in the field is a bare literal, that the README documents the declaration and the readback, that `CONTEXT.md` defines the term, and that the consuming test model and fixtures are extended rather than redefined.

**Acceptance Scenarios**:

1. **Given** the field's validation messages and its `help_text`, **When** the source is inspected, **Then** each is wrapped for translation with named placeholders, per Article XII.
2. **Given** the shipped documentation, **When** the README is read, **Then** it shows the multiple-value declaration, the readback of labels and identifiers, and what required and optional mean for it.
3. **Given** the test suite, **When** the modules are located, **Then** they mirror the source tree per testing standard §4 and the consuming model and fixtures are shared with the single-value field's rather than duplicated.

---

### User Story 8 - A field that draws on more than one vocabulary (Priority: P2)

*Added 2026-08-12 by refinement.*

A project tagging records with keywords does not always have one vocabulary in mind. Sometimes it has two or three published schemes it accepts, and sometimes it accepts whatever has been imported. A developer declares the field naming several vocabularies, or naming none at all, and the field behaves accordingly: the restriction covers exactly the vocabularies named, and a declaration naming none imposes no restriction.

**Why this priority**: Keywords drawn from more than one scheme are a standard shape in research metadata, and a field that cannot express it sends every such project back to the hand-rolled many-to-many this package exists to remove. It sits below the guarantees because a field naming one vocabulary — the common case and every other story's subject — works without it.

**Independent Test**: Declare the field three ways against the same database — one vocabulary, two, and none — and confirm the restriction each one enforces: concepts outside the named set refused in the first two, nothing refused in the third, and each form offering exactly the corresponding choices.

**Acceptance Scenarios**:

1. **Given** a field naming two vocabularies, **When** a concept from either is attached, **Then** the write succeeds.
2. **Given** the same field, **When** a concept from a third vocabulary is attached, **Then** it is refused with a message naming the expected vocabularies.
3. **Given** the same field, **When** a form is generated from the model, **Then** its choices are the concepts of both named vocabularies and no others.
4. **Given** a field naming no vocabulary, **When** a concept from any vocabulary is attached, **Then** the write succeeds.
5. **Given** the same field, **When** a form is generated from the model, **Then** its choices are every concept in the database.
6. **Given** a field naming no vocabulary, **When** `manage.py check` is run, **Then** it reports nothing for that field, because the field names no vocabulary that could be missing.
7. **Given** a field naming a vocabulary and a field naming none on the same model, **When** a concept is deleted while either holds it, **Then** the deletion is refused, because the delete protection does not depend on the restriction.

---

### Edge Cases

- A record's set is written before the record has been saved. The write cannot happen, as for any many-valued relation in Django, and the failure is Django's own rather than something this field reports differently.
- Every concept is removed from a required field's set on an existing record. The record is now invalid and says so the next time it is validated, which is the same latitude every model-level rule in this package has.
- A concept is moved to another vocabulary while records hold it. The memberships survive, and those records hold a concept from outside the field's vocabulary until they are next validated.
- The named vocabulary exists but holds no concepts. The field offers nothing and the check stays quiet, because the vocabulary is present and empty rather than missing.
- A locally authored vocabulary is renamed, which re-derives its slug, and declarations naming the old slug now name nothing. The check reports it as an absent vocabulary, exactly as it does for the single-value field.
- The same model declares both a single-value and a multiple-value field against the same vocabulary. Both work and neither interferes with the other's reverse accessor.
- A membership is created through a bulk queryset write that goes straight at the join. The vocabulary constraint is bypassed, as every model-level rule in this package is by a bulk write. The delete guard is not, because it lives in the database relation.
- A form is rendered against a vocabulary with tens of thousands of concepts. It works and it is slow, and making it fast is [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88). A field naming no vocabulary reaches that point sooner, because its choices are every concept in the database.
- A declaration names several vocabularies and one of them is absent. The check warns about that one and stays quiet about the others, and the field offers the concepts of the vocabularies that are present.
- A declaration names the same vocabulary twice. It is one restriction, not two, and the field behaves as though it were named once.
- A declaration names no vocabulary, and the database holds none either. The field offers nothing, refuses nothing, and warns about nothing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST ship a model field that attaches any number of concepts to a consuming project's model through one declaration, and that behaves as an ordinary Django many-valued relation for migrations, forms, validation, and serialization. The attached concepts are an unordered set: a concept attached twice is held once, and no order over the set is promised or relied upon.
- **FR-002**: The declaration MUST name zero, one, or several vocabularies, by slug, and MUST resolve them without requiring any of them to exist when the declaration is read. Naming several restricts the field to the union of those vocabularies' concepts. Naming none imposes no restriction on which concepts may be attached, and the field then carries the guarantees that do not depend on one: the delete protection of FR-007, the readback of FR-008 and FR-009, and the required-set rule of FR-010. *(Refined 2026-08-12; previously required exactly one and refused a declaration naming none.)*
- **FR-003**: Declaring the field against a vocabulary absent from the database MUST NOT prevent the project from importing its models, generating migrations, running migrations, or starting. No database query MUST be issued while the declaration is being read.
- **FR-004**: The system check the package already contributes MUST cover this field too, reporting every named vocabulary absent from the database under the same identifier and the same warning-not-error rule as the single-value field. A field naming no vocabulary MUST produce no warning, because it names nothing that could be missing. *(Refined 2026-08-12.)*
- **FR-005**: Attaching a concept that belongs to none of the named vocabularies MUST be refused, with a curator-facing message naming the expected vocabularies. The refusal MUST hold when the relation is written directly, not only when a form is validated, and a write carrying several concepts of which any is invalid MUST be refused whole, leaving the record's set unchanged. A field naming no vocabulary refuses nothing on these grounds. *(Refined 2026-08-12.)*
- **FR-006**: The choices a form offers for the field MUST be limited to concepts of the named vocabularies, so an invalid selection is unreachable rather than merely refused after the fact. A field naming no vocabulary offers every concept. *(Refined 2026-08-12.)*
- **FR-007**: A concept MUST NOT be deletable while any record holds it, per Article IX, and the refusal MUST hold for a bulk queryset delete as well as a single one. Deleting the vocabulary holding a held concept MUST be refused for the same reason. Deleting a consuming record MUST remove its own memberships and leave every concept it held intact.
- **FR-008**: A consuming record MUST expose the preferred label of each attached concept without the caller querying label storage. Each label MUST be resolved in the active language, falling back to the vocabulary's default language when the concept carries no preferred label in the active one. A record holding nothing MUST return an empty result rather than raise.
- **FR-009**: A consuming record MUST expose the URI of each attached concept unchanged, without the caller composing it from parts. A record holding nothing MUST return an empty result rather than raise.
- **FR-010**: The field MUST let the declaration decide whether a record may hold no concepts. Declared required, a record with an empty set MUST be refused when validated and by any form built from the model, with a message naming the field. Declared optional, an empty set MUST validate.
- **FR-011**: The field MUST accept the ordinary Django options a many-valued relation takes — including a reverse accessor name — and MUST NOT silently override any of them. The indexing of the relation MUST be a deliberate, recorded decision per Article XIII.
- **FR-012**: Every string the field puts in front of a person, including validation messages and `help_text`, MUST be translatable per Article XII, with named placeholders so the message identifiers stay static. `help_text` MUST be present, per the same article.
- **FR-013**: `CONTEXT.md` MUST define the term this feature puts into a consuming project's code. The README MUST document declaring the field, reading labels and identifiers back, what required and optional mean for it, and the three shapes a declaration's vocabulary naming may take — including what a field naming none does and does not guarantee. The CHANGELOG MUST record the addition. *(Refined 2026-08-12.)*

### Key Entities *(include if feature involves data)*

- **Consumer model**: A model belonging to the project that installs this package, carrying one or more of these fields. This package knows nothing about it beyond the references.
- **The field**: The declaration on that model. It holds references to any number of concepts, remembers which vocabulary those concepts must come from, and reaches their labels and identifiers on the record's behalf.
- **Membership**: One record's hold on one concept. It is what the delete guard protects, and it is removed when the record is deleted or the concept is detached.
- **Named vocabulary**: The vocabulary a declaration points at, identified by slug. It may be absent when the declaration is read, and it arrives by import.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A project attaches several controlled-vocabulary concepts to one of its own models with a single field declaration, writing no join model, no vocabulary constraint, and no label lookup of its own.
- **SC-002**: No write path that passes through the relation or a form puts a concept from outside the named vocabularies into a record's set, and no form offers one. Where the declaration names no vocabulary, every concept is inside it by definition, and the criterion holds trivially rather than being waived. *(Refined 2026-08-12.)*
- **SC-003**: Every attempt to delete a held concept is refused with the concept, the record and the membership intact, including through a bulk delete and including by way of deleting the vocabulary that holds it.
- **SC-004**: From a consuming record, the labels and the URIs of every attached concept are each reached in one read, and the labels are correct for a site whose active language a concept carries and for one it does not.
- **SC-005**: A record with no concepts attached is valid where the declaration says it may be and refused where it says it may not, both when validated and through a form.
- **SC-006**: A project declaring the field against a vocabulary absent from the database generates migrations, migrates, starts and runs its tests without failure, and `manage.py check` names the field and the vocabulary it expects.
- **SC-007**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, migrations are consolidated per Article XIII, and no user-visible string in the field is untranslatable.

## Assumptions

- **The single-value field is the precedent, not a library to generalise.** [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) delivered the naming by slug, the constraint, the check and the readback, and this feature matches them so a project meets one idea rather than two. Whether the two fields end up sharing code is a design question, and Article III says the shared abstraction has to be earned by the second use rather than assumed.
- **A field naming no vocabulary is still worth declaring.** *(Added by the 2026-08-12 refinement.)* It gives up the restriction and keeps everything else: a reference that cannot be deleted out from under it, labels and identifiers readable from the record, and the required-set rule. That is the difference between it and a plain many-to-many to `Concept`, and it is the whole difference — the field promises nothing about which concepts land in it, and the documentation says so rather than implying a guarantee that is not there.
- **The set is unordered.** Settled at intake. Collections already give a curator a deliberately ordered grouping of concepts on the vocabulary side, which is where an order has an owner. An order on the consumer side would be a permanent cost on every membership for a want nobody has stated.
- **Vocabularies arrive by import.** R2 delivered that, and this feature loads nothing itself. A project with no vocabulary in its database is a project that has not run one.
- **The constraint is a model-layer rule, and the delete guard is not.** A bulk write straight at the join bypasses the vocabulary constraint, as every model-level rule in this package is bypassed by a bulk write, and `CONTEXT.md` already records this. The delete guard is the exception, because it lives in the database relation and holds against a bulk delete too.
- **Scale belongs to the sibling.** The default form representation loads the named vocabulary's concepts, which is fine for the vocabularies a test fixture holds and unacceptable for the ones import now brings in. Making that usable is [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88), and this feature deliberately does not anticipate it.
- **Deprecation does not exist yet.** A concept is either present or absent. Publication and deprecation arrive with R4, and until then this field cannot distinguish a live concept from a retired one, because nothing marks one.
- **No release carries the old behaviour.** The package is at `0.0.x` with its first publish still ahead in the v0.1.0 milestone, so adding a field owes no upgrade path and no deprecation cycle.
