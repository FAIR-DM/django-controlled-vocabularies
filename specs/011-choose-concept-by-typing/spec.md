# Feature Specification: Choose a concept by typing instead of scrolling

**Feature Branch**: `011-choose-concept-by-typing`

**Created**: 2026-08-13

**Status**: Draft

**Input**: Issue [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88) — "A vocabulary with tens of thousands of concepts cannot be presented as a dropdown list. Anyone filling in a form that carries one of these fields should be able to type a few letters and pick from the matches, without the page loading the whole vocabulary first. This is what makes the field usable against the real vocabularies that import now brings in, rather than only against small test fixtures."

**Serves**: G2 (one-field consumption) · **Roadmap**: R3 · **Issue**: #88 · **Depends on**: [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) (delivered), [#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87) (delivered)

> Scope note: this is the third of four slices of roadmap item R3, and the first that puts anything of this package on a page. It owns **how a concept is chosen in a form**: the search-as-you-type control that both consumption fields render as by default, the search endpoint the package's own URL configuration carries, what a typed string matches and what the list shows, and the rule that the declaration's restriction is applied where the results are produced rather than taken from the request. **Out of scope:** the Django admin ([#89](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/89)), which builds on this; the wider work of keeping search, browse and deep hierarchies responsive at scale (R7); a human-facing interface for browsing vocabularies (R6); getting vocabularies into the database (R2, delivered); publication, deprecation and served RDF (R4); and the curator-facing editing interface (R5).

## Clarifications

### Session 2026-08-13 (intake)

Two decisions were taken with the maintainer at intake, because each decides what the feature is rather than how it is built.

- **Q: What does a typed string match against?** → A: The concept's names, not only the one it displays. Matching runs over the preferred label, the alternative labels and the hidden labels a concept carries in the active language, and over the default-language preferred label that every concept has. Hidden labels exist in SKOS precisely so a misspelling or a retired name still leads to the right concept, and a search that ignored them would throw that away. The list itself only ever shows the preferred label, so two concepts found by different names still read as themselves. Integrated into FR-004, FR-005 and User Story 2.
- **Q: Outside the admin, what does a project have to do to get this?** → A: Include one route. The package carries the search endpoint in its own URL configuration, and a project includes it once. Everything else is automatic: the form control is the default representation of both consumption fields, so a project declaring `ConceptField` or `ConceptsField` gets search-as-you-type without knowing the control exists, and it never declares a widget, writes an endpoint, or configures anything per field. The form control passes a parameter to the endpoint identifying which declaration the search is for, so the results honour what that declaration restricts the field to. Integrated into FR-001, FR-002, FR-006 and User Stories 1 and 4. *(Corrected at the plan stage, `decisions.md` D10: it is two entries, not one — the route, and the control's supporting package among the project's installed applications. Corrected again during implementation, `decisions.md` D15: three entries — the third is the supporting package's middleware, without which the control is not put on the page at all. Everything else in this answer stands.)*

### Session 2026-08-13 (coverage scan)

Five further ambiguities surfaced by the structured coverage scan over the drafted spec, resolved here against the intake decisions, the delivered fields, `CONTEXT.md` and the constitution. One of them corrects an intake answer.

- **Q: Can a typed string match a concept's notation, as agreed at intake?** → A: No, and not because the idea is wrong. A concept cannot carry a notation: the models have no place for one, and the importer already reports a published `skos:notation` as a value it set aside rather than stored. A requirement to match on notation would be a requirement to match on something no record holds. Matching therefore covers the three kinds of label, and notation joins it in the feature that gives a concept somewhere to keep one. Integrated into FR-004 and Assumptions.
- **Q: Who may call the search endpoint?** → A: Anyone the project routes to it. The endpoint returns concept preferred labels and identifiers, which is the data R4 will publish at stable public URIs by design, so a permission rule here would guard something the package intends to serve openly. What the endpoint must never do is reveal more than the field it is asked about would offer, which is FR-006's subject rather than an access rule. A project holding vocabularies it does not want read restricts the include, and the README says so rather than leaving it to be discovered. Integrated into FR-006, FR-012 and Assumptions.
- **Q: What does the control offer before anything is typed?** → A: A first page of the concepts the field allows, in a stable order, rather than an empty list. The problem the issue names is the page loading a whole vocabulary up front, not a person being shown anything at all, and a small vocabulary stays browsable this way. Integrated into FR-003 and Edge Cases.
- **Q: What bounds a result set?** → A: A page. The endpoint answers with a bounded number of concepts and says whether more exist, and the control asks for the next page as the person keeps looking. A search for a single common letter across tens of thousands of concepts must cost the same as any other search, and returning every match would reproduce the problem the feature exists to remove one layer down. Integrated into FR-007 and Success Criteria.
- **Q: How does matching treat case and accents?** → A: Case is ignored. Accents are not folded, and the specification does not promise they are, because whether `é` matches `e` is decided by the database's own collation and this package supports more than one. Promising accent-insensitivity would mean either a portable implementation nobody asked for or a guarantee that quietly holds on one database and not another. Integrated into FR-004 and Assumptions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A concept is chosen by typing (Priority: P1)

Someone filling in a form on a project that uses this package meets a field carrying a vocabulary. They type a few letters, the matching concepts appear as they type, they pick one, and they save. The page they loaded never carried the vocabulary, and neither the developer who built the form nor the person filling it in did anything to make this the behaviour.

**Why this priority**: This is the feature, and it is what makes the fields delivered by [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) and [#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87) usable against a real vocabulary rather than a fixture. A field that renders tens of thousands of options into a page is not slow, it is unusable.

**Independent Test**: Build an ordinary `ModelForm` from a model declaring each field, render it, and confirm the rendered page contains no concept options for the vocabulary. Then request the endpoint with a few letters and confirm the matching concepts come back, and that submitting the chosen concept saves the record.

**Acceptance Scenarios**:

1. **Given** a model declaring the single-value field against a vocabulary holding many concepts, **When** an ordinary `ModelForm` is rendered from it, **Then** the rendered output carries no list of that vocabulary's concepts, and the number of concepts in the database does not change what is rendered.
2. **Given** the same form, **When** a few letters are searched for, **Then** the concepts whose names contain them come back and nothing else does.
3. **Given** the same form, **When** it is submitted carrying a chosen concept, **Then** the record saves with that concept attached, exactly as it did before this feature existed.
4. **Given** a model declaring the multiple-value field, **When** the same is done, **Then** several concepts can be chosen, each is removable before submission, and the record saves holding all of them.
5. **Given** a project that has declared neither a widget nor a form field of its own, **When** either field is rendered, **Then** it is this control, because it is the field's default representation.

---

### User Story 2 - Found by any of its names, shown by one (Priority: P1)

A person searching does not always know the name a vocabulary prefers. They type a synonym, an old name, or a misspelling the curator anticipated, and the concept they mean is in the list — under its preferred label, which is the name the vocabulary would have them use.

**Why this priority**: A search that only matches the displayed label is a search that only finds what the user already knew to call it, which is most of the value of a controlled vocabulary thrown away. Alternative and hidden labels exist for exactly this, and imported vocabularies arrive carrying them.

**Independent Test**: Give one concept a preferred label, an alternative label and a hidden label in the active language, search for a fragment of each in turn, and confirm the same concept comes back every time and is displayed under its preferred label each time.

**Acceptance Scenarios**:

1. **Given** a concept with an alternative label in the active language, **When** a fragment of that alternative label is searched for, **Then** the concept is returned and displayed under its preferred label.
2. **Given** a concept with a hidden label in the active language, **When** a fragment of that hidden label is searched for, **Then** the concept is returned and displayed under its preferred label.
3. **Given** a concept whose preferred label in the active language differs from its default-language one, **When** a fragment of either is searched for, **Then** the concept is returned, and it is displayed under the preferred label for the active language.
4. **Given** a concept with no labels at all in the active language, **When** a fragment of its default-language preferred label is searched for, **Then** it is returned and displayed under that label rather than blank.
5. **Given** a concept matching on more than one of its labels, **When** it is searched for, **Then** it appears once.
6. **Given** a search whose letters differ only in case from a concept's label, **When** it runs, **Then** the concept is returned.

---

### User Story 3 - The results honour what the field allows (Priority: P1)

A field declared against one vocabulary offers that vocabulary's concepts and no others, and it does so because the endpoint works out what the field allows, not because the page asked politely. Someone editing the request by hand gets the same answers the honest page would.

**Why this priority**: Article V, and the whole point of a field that names a vocabulary. A restriction the browser is trusted to carry is not a restriction, and the parameter the control sends is the obvious place for that mistake. The field would still refuse a bad concept when the record is validated, so this is not the last line of defence, but a search that offers concepts the form then rejects is a broken form.

**Independent Test**: With three vocabularies in the database, search through the parameter a field declared against one of them produces, and confirm only that vocabulary's concepts come back. Then alter the parameter to name another vocabulary, a field on a model that does not exist, and something that is not one of this package's fields at all, and confirm each returns nothing rather than widening the results.

**Acceptance Scenarios**:

1. **Given** a field declared against one vocabulary and three vocabularies in the database, **When** the endpoint is asked for a string matching concepts in all three, **Then** only the declared vocabulary's concepts come back.
2. **Given** the same field, **When** the request is altered to name a different vocabulary, **Then** the results are still the declared vocabulary's concepts, because the restriction comes from the declaration.
3. **Given** a request naming something that is not one of this package's concept fields, **When** the endpoint answers, **Then** it returns nothing and no error that discloses what does exist.
4. **Given** a field declared against several vocabularies, **When** a search runs, **Then** the results are the concepts of exactly those vocabularies.
5. **Given** a field declared against no vocabulary, **When** a search runs, **Then** every concept in the database is eligible, because that declaration restricts nothing.
6. **Given** a chosen concept submitted through the form, **When** the record is validated, **Then** the field's own refusal still applies unchanged, because this feature adds a filter on what is offered and removes no guarantee.

---

### User Story 4 - One route, and nothing else to wire (Priority: P2)

A developer adding this package to a project installs it, adds one entry to the project's URL configuration and one to its installed applications, and every form in the project that carries one of these fields now has search-as-you-type. They declare no widget, write no view, and add nothing to any form class.

*(Amended at the plan stage, `decisions.md` D10. The specification promised one step. Django finds another package's templates and static files only inside an installed application, so the control's supporting package has to be declared as one. Neither step is silent: the system check reports either when it is missing.)*

**Why this priority**: The one thing a project must do has to be small, obvious and documented, because everything else in this package is automatic and a hidden setup step would be discovered as a bug. It sits below the behaviour stories because a project that has not wired the route needs to be told so clearly, not to be spared the step.

**Independent Test**: In a project with the route included, render a form and use the control end to end. Remove the route, render the same form, and confirm the failure names what is missing rather than raising an unresolved-address error from somewhere inside the package.

**Acceptance Scenarios**:

1. **Given** a project with the package installed and its route included, **When** a form carrying either field is rendered and used, **Then** search-as-you-type works with nothing else configured.
2. **Given** a project that has not included the route, **When** the project is checked, **Then** it is told that the route is missing and what to add, rather than failing when a form is first rendered.
2a. **Given** a project that has not declared the control's supporting package among its installed applications, **When** the project is checked, **Then** it is told that too, and what to add.
3. **Given** a project with the route included under an address of its choosing, **When** a form is rendered, **Then** the control asks the address the project actually used rather than a hard-coded one.
4. **Given** the shipped documentation, **When** the README is read, **Then** all three wiring steps are shown in the order a developer does them, along with what the endpoint exposes and how a project restricts it.

---

### User Story 5 - A real vocabulary stays usable (Priority: P2)

A vocabulary with tens of thousands of concepts behaves like any other: the form loads at the same speed as one carrying a small vocabulary, a search for a single common letter answers as quickly as a specific one, and the person scrolls the results they care about rather than the vocabulary.

**Why this priority**: This is the reason the issue exists, and it is the difference between the field working against fixtures and working against what import now brings in. It sits below the first three because a control that is correct and unbounded can be bounded, while one that offers the wrong concepts is wrong at every size.

**Independent Test**: Load a vocabulary large enough that the difference is unmistakable, render a form, and confirm the rendered page does not grow with the vocabulary. Then search for a string matching a large share of it and confirm the answer carries a bounded number of concepts, says more exist, and that asking again returns the following ones without repeating or skipping any.

**Acceptance Scenarios**:

1. **Given** a vocabulary with many thousands of concepts, **When** a form carrying it is rendered, **Then** the rendered output is the same size as for a vocabulary with a handful, because no concept is written into the page.
2. **Given** the same vocabulary, **When** a search matches more concepts than one page holds, **Then** the answer carries one page of them and indicates that more exist.
3. **Given** the same search, **When** the following page is asked for, **Then** it returns the next concepts in the same order, with none repeated and none skipped.
4. **Given** the control with nothing typed into it, **When** it is opened, **Then** it offers a first page of the concepts the field allows, in a stable order.
5. **Given** a field declared against no vocabulary in a database holding several, **When** a search runs, **Then** it is bounded the same way, because that field's eligible set is every concept there is.

---

### User Story 6 - An existing record shows what it holds (Priority: P2)

Someone opens the edit form of a record that already has concepts attached. The control shows what is attached, by name, without them typing anything, and they change one and leave the rest alone.

**Why this priority**: A control that only works for a blank form is half a control, and the failure mode is quiet — a person opens a record, sees an empty box, and saves the emptiness back. It sits with the other second-priority stories because it depends on the first three being right.

**Independent Test**: Save a record holding one concept through the single-value field and another holding three through the multiple-value field, reopen each form, and confirm the attached concepts are shown by their preferred labels in the active language, that submitting without touching the control leaves the record unchanged, and that removing one and saving removes exactly that one.

**Acceptance Scenarios**:

1. **Given** a record holding a concept, **When** its form is rendered, **Then** the control shows that concept under its preferred label in the active language.
2. **Given** a record holding several concepts, **When** its form is rendered, **Then** all of them are shown, each removable.
3. **Given** either form, **When** it is submitted without the control being touched, **Then** the record's concepts are unchanged.
4. **Given** a record holding a concept from a vocabulary its field no longer names, **When** the form is rendered, **Then** the concept is still shown rather than silently dropped, and the field's ordinary validation decides what happens on submission.

---

### User Story 7 - Translatable strings, documentation, and test material (Priority: P3)

Every string this feature puts in front of a person is translatable, the README shows the route include and what the control does, `CONTEXT.md` carries the terms the package now uses in public, and the test material extends what the two delivered fields left rather than duplicating it.

**Why this priority**: Constitutional obligations that apply across the feature rather than to one journey through it. They matter more than usual here because this is the first slice that ships a template, a static asset and a user-visible string that is not a validation message.

**Independent Test**: Assert that no user-visible string in the control, the endpoint or the check is a bare literal, that the README documents the route and the control, that `CONTEXT.md` defines the terms, and that the consuming test models and fixtures are the shared ones.

**Acceptance Scenarios**:

1. **Given** the feature's user-visible strings, **When** the source is inspected, **Then** each is wrapped for translation with named placeholders, per Article XII, and any template loads and uses the translation tags.
2. **Given** the shipped documentation, **When** the README is read, **Then** it shows the route include, what search-as-you-type does for both fields, what the endpoint exposes, and how a project that must restrict access does so.
3. **Given** the test suite, **When** the modules are located, **Then** they mirror the source tree per testing standard §4 and reuse the consuming models and fixtures the delivered fields left shared.
4. **Given** a new runtime dependency, **When** the dependency checks run, **Then** it is declared alongside the code that imports it and its justification is recorded, per Article VII.

---

### Edge Cases

- Nothing is typed. The control offers a first page of the concepts the field allows, in a stable order, rather than an empty list.
- A search matches nothing. The control says so and offers nothing, and no error is raised.
- The vocabulary a field names has not been imported. The search returns nothing, the form still renders, and the system check the package already contributes is what tells the developer the vocabulary is missing.
- The route is not included. The project is told at check time, rather than discovering it when a page is first rendered.
- The person's browser runs no JavaScript. The control cannot work, and the form's server-side validation is unchanged, so nothing invalid can be saved by a page that failed to enhance.
- The request asks for a page beyond the last one. It returns nothing and says no more exist.
- A concept is deleted between a search and a submission. The submission fails the field's own validation, exactly as it would have before this feature.
- Two concepts in different vocabularies share a preferred label, and a field naming no vocabulary offers both. They are indistinguishable in the list by label alone, and the list shows which vocabulary each belongs to for that reason.
- A field names several vocabularies and one of them is absent. The search returns the concepts of the ones that are present.
- The active language has no labels at all for any concept. Every result is displayed under its default-language preferred label, which every concept has.
- The endpoint is asked about a field on a model that exists but is not one of this package's concept fields. It returns nothing, and its response does not distinguish that case from a model that does not exist.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Both consumption fields MUST render, by default and in any Django form built from a consuming model, as a control a person types into to search for a concept. A consuming project MUST NOT have to name a widget, declare a form field, or configure anything per field or per form to get this.
- **FR-002**: The package MUST carry the search endpoint in its own URL configuration, for a project to include once at an address of the project's choosing. The control MUST resolve that address rather than assume one, so a project's choice of prefix is honoured. *(Amended at the plan stage, `decisions.md` D10: a project also declares the control's supporting package among its installed applications, because that is how Django finds another package's templates and static files. Amended again during implementation, `decisions.md` D15: a project also declares that package's middleware, because the control is only put on the page when it is present. Three steps, each reported by the system check when missing.)*
- **FR-003**: Rendering a form MUST NOT load the field's eligible concepts into the page, and the rendered output MUST NOT grow with the size of the vocabulary. Opening the control without typing MUST offer a first page of eligible concepts in a stable order.
- **FR-004**: A typed string MUST match a concept whose preferred, alternative or hidden label in the active language contains it, and MUST also match on the default-language preferred label every concept carries. Matching MUST ignore case. A concept matching on more than one of its labels MUST appear once. Accent folding is NOT promised, because it belongs to the database's collation rather than to this package.
- **FR-005**: A result MUST be displayed under the concept's preferred label, resolved in the active language and falling back to the vocabulary's default language, whichever label the match was made on. Where a field's eligible concepts may span vocabularies, a result MUST also show which vocabulary it belongs to.
- **FR-006**: The endpoint MUST derive the restriction on its results from the field declaration the request identifies, and MUST NOT take the restriction from the request itself. A request identifying anything that is not one of this package's concept fields MUST return no results, and MUST NOT disclose whether the named model or field exists. A field naming no vocabulary MUST make every concept eligible, which is that declaration's meaning rather than an exemption.
- **FR-007**: The endpoint MUST answer with a bounded page of results and MUST indicate whether more exist, and the control MUST be able to ask for the following page. Paging MUST be stable: successive pages of one search neither repeat nor skip a concept.
- **FR-008**: The control MUST show the concepts a record already holds when its form is rendered, by preferred label, for both the single-value and the multiple-value field. A concept the field's current declaration would no longer offer MUST still be shown rather than dropped.
- **FR-009**: Submitting the form MUST attach exactly the chosen concepts, and every guarantee the two delivered fields already make — the vocabulary constraint, the delete protection, the required rule, the readback — MUST be unchanged by this feature.
- **FR-010**: The system check the package already contributes MUST report a project that has not included the package's route, a project that has not declared the control's supporting package among its installed applications, and a project that has not declared that package's middleware, identifying in each case what to add. It MUST remain a warning rather than an error where the existing check is, and MUST NOT query the database while running.
- **FR-011**: The feature MUST ship whatever template and static assets the control needs as part of the package, so a project installs nothing separately and adds nothing to its own asset pipeline beyond what Django's own static file handling does.
- **FR-012**: The endpoint MUST expose only what a result needs — a concept's preferred label, its identifier, and the vocabulary it belongs to — and MUST NOT return editorial notes, hidden labels, or any field beyond those, whichever label the match was made on. The README MUST state what the endpoint exposes and that a project needing to restrict access to concept data restricts the include.
- **FR-013**: Every string this feature puts in front of a person MUST be translatable per Article XII, including any string in a shipped template, with named placeholders so the message identifiers stay static.
- **FR-014**: `CONTEXT.md` MUST define the terms this feature introduces into the package's public vocabulary. The README MUST document the route include, the default control on both fields, what the endpoint exposes, and the browser requirement. The CHANGELOG MUST record the addition.
- **FR-015**: Any new runtime dependency MUST be justified and declared alongside the code that imports it, per Article VII, and the dependency checks MUST pass.

### Key Entities *(include if feature involves data)*

- **The control**: What either consumption field renders as in a form. It holds the concepts currently chosen, asks the endpoint as the person types, and submits concept identifiers exactly as the plain form representation did.
- **The search endpoint**: The package's own view, carried in its URL configuration, which answers a search with a bounded page of eligible concepts. It decides eligibility from the field declaration named in the request.
- **The field reference**: What the control sends so the endpoint knows which declaration it is searching on behalf of. It identifies a declared field, and the endpoint resolves the restriction from that declaration rather than from anything else in the request.
- **The result**: One concept as the list shows it — its preferred label in the active language, its identifier, and the vocabulary it belongs to.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A form carrying either consumption field renders identically in size whether its vocabulary holds ten concepts or tens of thousands, and a person selects a concept from the large one by typing a few letters.
- **SC-002**: A concept is found by a fragment of its preferred, alternative or hidden label in the active language, and by its default-language preferred label, and is shown under its preferred label in every case.
- **SC-003**: No request to the endpoint returns a concept the identified field would not accept, including requests altered to name another vocabulary, another model, or a field this package did not declare.
- **SC-004**: Every search answers with a bounded page regardless of how many concepts match, and paging through one search visits each matching concept exactly once.
- **SC-005**: A project gets the behaviour by installing the package and including one route, and a project that has not included it is told so by `manage.py check` rather than by a failing page.
- **SC-006**: A record holding concepts opens in a form showing them by name, and submitting the form untouched leaves the record's concepts unchanged.
- **SC-007**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, migrations are consolidated per Article XIII, and no user-visible string this feature adds is untranslatable.

## Assumptions

- **The delivered fields are the contract, and this feature changes none of it.** [#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86) and [#87](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/87) settled what a declaration means, what it refuses and what it reads back. This feature changes how a person picks a concept and nothing about what may be stored, so every existing guarantee holds untouched and the existing tests stay green.
- **The restriction is enforced where the results are made.** The control tells the endpoint which declaration it is searching for, and the endpoint works the restriction out from that declaration. Nothing about which concepts are eligible is taken from the request, which is what keeps an altered request from widening the results or reaching anything else.
- **Concept labels and identifiers are open data.** The endpoint returns what R4 will publish at stable public URIs by design, so no permission rule guards it by default. A project holding vocabularies it does not want read restricts the include, and the README says so.
- **Notation is not matchable yet.** A concept has nowhere to keep a `skos:notation` — the importer reports one as set aside rather than stored — so matching on it is not a requirement here. It joins the search in the feature that gives a concept somewhere to hold it.
- **Accent folding belongs to the database.** Whether a search for `e` finds `é` is decided by collation, and this package supports more than one database. Case-insensitivity is promised because it is portable, and accent-insensitivity is not promised because it is not.
- **The control needs a browser that runs scripts.** There is no non-scripted fallback in this feature, and the form's server-side validation is unchanged, so a page that fails to enhance can submit nothing the field would have accepted anyway.
- **The admin is the sibling's.** Getting this behaviour onto the admin's add and change pages without a project wiring anything is [#89](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/89), which depends on this. This feature deliberately does not anticipate it beyond leaving the endpoint and the control reusable.
- **Scale hardening is R7.** This feature makes the form usable against a real vocabulary by never loading one and by bounding every answer. Keeping search, browse and deep hierarchies fast across the package is its own roadmap item, and no benchmark or performance budget is claimed here.
- **No release carries the old behaviour.** The package is at `0.0.x` with its first publish still ahead in the v0.1.0 milestone, so changing what these fields render as owes no upgrade path and no deprecation cycle.
