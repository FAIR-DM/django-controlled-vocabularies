# Feature Specification: Create and edit a vocabulary

**Feature Branch**: `017-create-edit-vocabulary`

**Created**: 2026-10-23

**Status**: Draft

**Input**: Issue [#175](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/175) — "A curator should be able to create a vocabulary and edit it from a web page, without writing any code or touching a terminal. Today the only ways to get a vocabulary into the system are to import a published file or to write Python. That puts the package out of reach of the people who actually own the terms. Only someone trusted to curate should be able to reach these pages. Everyone else keeps seeing the read-only view they see now. Deleting a vocabulary belongs here too. It should say plainly what will go with it, rather than quietly taking every concept inside."

**Serves**: G1 (code-free vocabulary management) · **Roadmap**: R5 · **Issue**: #175

> Scope note: this is the first of five slices of roadmap item R5, and the other four depend on it.
> This feature owns **the vocabulary record itself**: creating one, editing its details, and
> deleting it, plus the controls on the existing browsing pages that lead there.
> **Out of scope:** adding, editing and removing the concepts inside a vocabulary, which is
> [#176](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/176); a concept's labels
> and notes per language, which is
> [#177](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/177); the hierarchy and
> relations between concepts, which is
> [#178](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/178); collections, which is
> [#179](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/179); publishing a
> vocabulary and fixing its identifier permanently, which is R4; and permissions granted per
> vocabulary rather than across all of them, which is G11.

## Clarifications

### Session 2026-10-23 (intake)

The maintainer confirmed this reading of the issue at intake, with nothing added for research and
planning.

- **Q: Can a vocabulary imported from a publisher be edited here?** → A: No. G8 treats an imported vocabulary as a read-only reference, and the browsing pages already show curators whether a vocabulary was imported because that decides whether it may be edited here. An imported vocabulary can still be deleted, which is how a curator drops a reference the site no longer wants. Integrated into User Stories 2 and 3, FR-008 and FR-013.
- **Q: Who is "trusted to curate"?** → A: A user holding Django's ordinary model permissions on vocabularies: add to create one, change to edit one, delete to delete one, each action needing its own. Permissions per vocabulary are G11 and stay out. Integrated into FR-001 to FR-004.
- **Q: Can a curator choose a vocabulary's address segment?** → A: No. It follows the name, as it already does for a vocabulary authored here, so renaming moves the vocabulary's address. Integrated into FR-010.
- **Q: What happens to the default language once a vocabulary has concepts?** → A: It cannot be changed, which the package already enforces. The edit form shows it as fixed rather than accepting a change and refusing it on save. Integrated into FR-011.
- **Q: What happens when a curator deletes a vocabulary whose concepts a project's records point at?** → A: The deletion is refused, and the page says what is using them, rather than raising a database error or breaking that data. Integrated into FR-015.
- **Q: Where does a curator land after creating a vocabulary?** → A: On the new vocabulary's own page, which already says when a vocabulary holds no concepts. Integrated into FR-007.

### Session 2026-10-23 (coverage scan)

Ambiguities found by the structured coverage scan over the drafted specification, resolved against
the intake decisions, the shipped models, `CONTEXT.md` and the constitution.

- **Q: What does someone who is not signed in get at an editing address, and what does someone signed in without the permission get?** → A: Someone not signed in is sent to sign in, and returns to the page afterwards. Someone signed in without the permission is refused. Neither sees the form. Integrated into FR-004. Rationale in `decisions.md` D1.
- **Q: Which of a vocabulary's details does the form offer?** → A: Its name, description, default language and every publication detail the browsing page shows: publisher, creator, licence, version and when it last changed. Its identifier is not offered, because fixing an identifier is publication, which is R4. Integrated into FR-005 and FR-009. Rationale for offering the last-changed date in `decisions.md` D2.
- **Q: Two vocabularies whose names produce the same address segment: what happens?** → A: The second is refused, and the form says which field is at fault and why, keeping everything else the curator entered. The package already refuses the collision. The form reports it instead of failing. Integrated into FR-006.
- **Q: Why is deletion refused outright when concepts are in use, rather than offering to clear the references?** → A: Clearing a project's reference changes that project's data, which this package does not own. Integrated into FR-015. Rationale in `decisions.md` D3.
- **Q: What does a curator see after a change succeeds?** → A: A confirmation that the change was made, on the page they land on: the vocabulary's page after a create or edit, the list of vocabularies after a delete. Integrated into FR-007, FR-012 and FR-016.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A curator creates a vocabulary (Priority: P1)

A curator who wants a new vocabulary opens the list of vocabularies, chooses to create one, gives it
a name and whatever else they know about it, and saves. They land on the new vocabulary's page, which
shows what they entered and that it holds no concepts yet.

**Why this priority**: This is the feature. Today a vocabulary comes from an import or from Python,
and every later slice of R5 needs a vocabulary a curator made.

**Independent Test**: Sign in as a user with permission to add vocabularies, create one from the list
of vocabularies with only a name, and confirm its page is served at an address derived from that
name. Then sign in as a user without that permission and confirm the list offers no way to create
one and the creation address refuses them.

**Acceptance Scenarios**:

1. **Given** a user with permission to add vocabularies, **When** they open the list of vocabularies,
   **Then** it offers a way to create one.
2. **Given** that user on the creation form, **When** they save with a name and nothing else,
   **Then** a vocabulary exists with that name, held on this site, and they are on its page with a
   confirmation that it was created.
3. **Given** that user, **When** they save with a description, a default language and publication
   details, **Then** the vocabulary's page shows each of them.
4. **Given** a vocabulary already exists, **When** the user saves a new one whose name produces the
   same address segment, **Then** nothing is created, the form says the name is taken, and
   everything else they entered is still there.
5. **Given** the user saves without a name, **Then** nothing is created and the form says the name
   is required.
6. **Given** a user without permission to add vocabularies, **When** they open the list, **Then** it
   offers no way to create one, **and When** they request the creation address directly, **Then**
   they are refused.
7. **Given** someone not signed in, **When** they request the creation address, **Then** they are
   sent to sign in.

---

### User Story 2 - A curator edits a vocabulary held here (Priority: P1)

A curator opens a vocabulary authored on this site, chooses to edit it, changes its name or details,
and saves. The vocabulary's page shows the change. If they renamed it, the vocabulary is now at the
address its new name produces.

**Why this priority**: A vocabulary that cannot be corrected after it is created is only half
manageable. Creating and editing together make the record code-free.

**Independent Test**: As a user with permission to change vocabularies, edit a vocabulary held here,
rename it and change its description, and confirm its page at the new address shows both changes.
Confirm an imported vocabulary's page offers no edit and its editing address refuses the same user.

**Acceptance Scenarios**:

1. **Given** a user with permission to change vocabularies, **When** they open the page of a
   vocabulary held here, **Then** it offers a way to edit it.
2. **Given** that user on the edit form, **Then** the form holds the vocabulary's current values.
3. **Given** that user, **When** they change the description and save, **Then** the vocabulary's
   page shows the new description, with a confirmation that it was saved.
4. **Given** that user, **When** they change the name and save, **Then** the vocabulary is served at
   the address the new name produces, and they land there.
5. **Given** a vocabulary that holds concepts, **When** the user opens its edit form, **Then** the
   default language is shown as fixed and cannot be changed through the form.
6. **Given** a vocabulary with no concepts, **When** the user changes its default language and saves,
   **Then** the change is kept.
7. **Given** the edit form, **When** the user cancels, **Then** nothing changes and they return to the
   vocabulary's page.
8. **Given** a vocabulary imported from a publisher, **When** that user opens its page, **Then** it
   offers no way to edit it, **and When** they request its editing address directly, **Then** they
   are refused.
9. **Given** a user without permission to change vocabularies, **When** they open any vocabulary's
   page, **Then** it offers no way to edit it, **and When** they request an editing address directly,
   **Then** they are refused.

---

### User Story 3 - A curator deletes a vocabulary (Priority: P2)

A curator who no longer wants a vocabulary chooses to delete it. Before anything happens they are
told what goes with it: how many concepts and how many collections. They confirm and the vocabulary
is gone, or they back out and nothing changes. If any of its concepts are in use by a project's
records, the deletion is refused and they are told what is using them.

**Why this priority**: Deleting matters less often than creating or editing, but a curator who makes
a mistake, or imports a vocabulary the site no longer wants, must be able to remove it without code.

**Independent Test**: As a user with permission to delete vocabularies, delete a vocabulary holding
concepts and a collection, confirm the confirmation step reported both counts, and confirm the
vocabulary, its concepts and its collection are gone afterwards. Repeat with a vocabulary whose
concept a consuming model's record points at, and confirm nothing is deleted.

**Acceptance Scenarios**:

1. **Given** a user with permission to delete vocabularies, **When** they open a vocabulary's page,
   **Then** it offers a way to delete it, whether the vocabulary is held here or imported.
2. **Given** that user chooses to delete, **Then** before anything is deleted they are shown how many
   concepts and how many collections will be deleted with the vocabulary, and asked to confirm.
3. **Given** the confirmation step, **When** the user confirms, **Then** the vocabulary and
   everything it holds are deleted, and they are on the list of vocabularies with a confirmation that
   it was deleted.
4. **Given** the confirmation step, **When** the user backs out, **Then** nothing is deleted and they
   return to the vocabulary's page.
5. **Given** a vocabulary one of whose concepts a project's record points at, **When** the user asks
   to delete it, **Then** they are told the deletion cannot go ahead and which kinds of record use
   its concepts, and are offered no way to confirm.
6. **Given** a vocabulary in use as in scenario 5, **When** a delete is submitted for it anyway,
   **Then** nothing is deleted and the user is told why.
7. **Given** a user without permission to delete vocabularies, **When** they open a vocabulary's
   page, **Then** it offers no way to delete it, **and When** they request the deletion address
   directly, **Then** they are refused.

---

### Edge Cases

- A vocabulary renamed so that its name produces no usable address segment (punctuation only, for
  example) is refused, and the form says why.
- A user who holds the change permission but not the delete permission is offered editing and no
  deletion, and the reverse holds too. Each control follows its own permission.
- A vocabulary deleted or renamed by another curator while the edit form is open: saving the stale
  form either saves to the vocabulary still there or reports that it no longer exists. It never
  creates a second vocabulary.
- A vocabulary whose concepts are referenced by records of several kinds: the refusal names every
  kind.
- The default language becomes fixed between opening the form and saving it, because a concept was
  added meanwhile: the save is refused with the reason, and nothing else on the form is lost.
- A browser without JavaScript: creating, editing, cancelling and deleting all work. Anything that
  depends on JavaScript, such as a warning about unsaved changes, is an addition and never the only
  way something works.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Only a user holding the permission to add vocabularies MAY create one through these
  pages.
- **FR-002**: Only a user holding the permission to change vocabularies MAY edit one through these
  pages.
- **FR-003**: Only a user holding the permission to delete vocabularies MAY delete one through these
  pages.
- **FR-004**: A creation, editing or deletion address requested by someone not signed in MUST send
  them to sign in and back afterwards. Requested by a signed-in user without the permission it needs,
  it MUST refuse them. Neither may see the form or change anything.
- **FR-005**: The creation form MUST accept a name, which is required, and optionally a description,
  a default language chosen from the site's configured languages, a publisher, a creator, a licence,
  a version and the date it last changed.
- **FR-006**: A form that cannot be saved MUST say which field is at fault and why, and MUST keep
  every value the curator entered.
- **FR-007**: After a vocabulary is created, the curator MUST land on its page with a confirmation
  that it was created. A vocabulary created here MUST be held on this site, its identifier computed
  from the site's address.
- **FR-008**: Only a vocabulary held on this site MAY be edited. An imported vocabulary MUST offer no
  way to edit it, and its editing address MUST refuse every user.
- **FR-009**: The edit form MUST offer the same details as the creation form, holding the
  vocabulary's current values. It MUST NOT offer the vocabulary's identifier or its address segment.
- **FR-010**: Renaming a vocabulary MUST move it to the address its new name produces, as the
  package already does for a vocabulary held here.
- **FR-011**: Once a vocabulary holds a concept, the edit form MUST show its default language as
  fixed and MUST NOT accept a change to it.
- **FR-012**: After an edit is saved, the curator MUST land on the vocabulary's page, at its current
  address, with a confirmation that it was saved. Cancelling an edit MUST change nothing and return
  them to that page.
- **FR-013**: Any vocabulary, held here or imported, MAY be deleted by a user holding the permission
  to delete vocabularies.
- **FR-014**: Before a deletion, the curator MUST be shown how many concepts and how many collections
  will be deleted with the vocabulary, and MUST confirm before anything is deleted. Backing out MUST
  change nothing.
- **FR-015**: A vocabulary any of whose concepts a record outside this package points at MUST NOT be
  deleted. The curator MUST be told this before being asked to confirm, with the kinds of record that
  use its concepts, and a deletion submitted regardless MUST delete nothing and say why.
- **FR-016**: After a deletion, the curator MUST land on the list of vocabularies with a confirmation
  that it was deleted.
- **FR-017**: The list of vocabularies MUST offer a way to create a vocabulary to a user holding the
  permission to add one, and to nobody else.
- **FR-018**: A vocabulary's page MUST offer a way to edit it only to a user who may edit that
  vocabulary under FR-002 and FR-008, and a way to delete it only to a user holding the permission
  to delete vocabularies. Everyone else MUST see the page exactly as before this feature.
- **FR-019**: These pages MUST be served wherever the browsing pages are mounted and MUST NOT depend
  on the Django admin being installed.
- **FR-020**: Creating, editing, cancelling and deleting MUST all work in a browser that does not run
  JavaScript.
- **FR-021**: The package documentation MUST describe how a curator creates, edits and deletes a
  vocabulary, which permission each action needs, and why an imported vocabulary cannot be edited.

### Requirement → story

| Story | Requirements |
|---|---|
| US1 — create | FR-001, FR-004, FR-005, FR-006, FR-007, FR-017, FR-019, FR-020, FR-021 |
| US2 — edit | FR-002, FR-004, FR-006, FR-008, FR-009, FR-010, FR-011, FR-012, FR-018, FR-019, FR-020, FR-021 |
| US3 — delete | FR-003, FR-004, FR-013, FR-014, FR-015, FR-016, FR-018, FR-019, FR-020, FR-021 |

### Key Entities

- **Vocabulary** (`ConceptScheme`): the record this feature creates, edits and deletes. Its name,
  description, default language and publication details are what a curator works with. Whether it
  is held here or imported decides whether it may be edited.
- **Curator**: a user holding at least one of the permissions to add, change or delete vocabularies.
  A new term for `CONTEXT.md`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A curator with no access to code or a terminal can take a vocabulary from nothing to a
  named, described page on the site, change its details, and delete it, using only the browser.
- **SC-002**: A user without the curator permissions finds no new control on any page and cannot
  change a vocabulary by requesting an editing address directly.
- **SC-003**: No deletion removes a concept that a project's record points at.
- **SC-004**: Before confirming a deletion, a curator can say exactly how many concepts and
  collections it will remove.
- **SC-005**: Every string these pages show can be translated, and none is fixed in one language.
- **SC-006**: A person with a fresh clone can sign in to the demo as a curator and create, edit and
  delete a vocabulary using the documented commands that already serve the browsing pages.

## Assumptions

- An imported vocabulary is one whose identifier a publisher fixed, which is the signal the browsing
  pages already use. A vocabulary published from this site (R4) will also carry a fixed identifier,
  and whether it stays editable is R4's to decide.
- The vocabulary's page already says when a vocabulary holds no concepts (014, FR-014). Adding a
  concept is #176, so a vocabulary created here stays empty until that feature lands.
- Permissions across all vocabularies are enough for single-team use. Per-vocabulary permissions are
  G11.
- A vocabulary holds hundreds of concepts rather than tens of thousands, so counting them for the
  deletion step needs no special treatment. Scale is R7.
- The project mounting the package provides sign-in. The package sends someone to the project's
  configured sign-in address and adds no sign-in of its own.
