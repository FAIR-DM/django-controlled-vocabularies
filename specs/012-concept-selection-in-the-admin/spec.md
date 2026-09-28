# Feature Specification: Concept selection inside the Django admin

**Feature Branch**: `012-concept-selection-in-the-admin`

**Created**: 2026-08-13

**Status**: Draft

**Input**: Issue [#89](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/89) — "Most Django projects do their day-to-day data entry through the admin site. A model carrying one of these fields should get the same search-as-you-type concept selection on its admin add and change pages, and it should get it without the project wiring up widgets or endpoints itself. Declaring the field should be enough."

**Serves**: G2 (one-field consumption) · **Roadmap**: R3 · **Issue**: #89 · **Depends on**: [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88) (delivered)

> Scope note: this is the fourth and last slice of roadmap item R3, whose deliverables name selection "in forms and the Django admin" — [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88) delivered the forms half, and this is the admin half. It owns **what a consuming project's own model does on its admin add and change pages**: that the concept search control is what the field renders as there, that the page offers no way to create or edit a concept, that inline forms get the same control including rows added after the page loads, that an explicit choice in a project's `ModelAdmin` wins over the default, and that a project which does not use the admin is unaffected. **Out of scope:** an admin for this package's own schemes, concepts and collections, which is the curator interface (R5); the admin's changelist — its search box, filters and columns; a human-facing interface for browsing vocabularies (R6); keeping search and deep hierarchies fast at scale (R7); publication and deprecation (R4); and every guarantee the two consumption fields and the search endpoint already make, which this feature reuses unchanged.

## Clarifications

### Session 2026-08-13 (intake)

One decision was taken with the maintainer at intake, because it decides what the feature is rather than how it is built.

- **Q: On a consuming model's admin page, should the concept field offer Django's "create a new related record" affordance?** → A: No. The control is selection-only. Django's admin normally puts an add button beside a foreign-key field, and a change button beside a chosen record, so that a person filling in a form can create or edit the related record in a popup. A controlled vocabulary stops being controlled the moment someone entering a sample record can invent a concept mid-form, and concept authoring belongs to the curator interface. The affordance is absent today only because this package registers nothing in the admin, so the requirement is a forward-looking one: it stays absent once the curator interface registers the models. Integrated into FR-004 and User Story 2.

### Session 2026-08-13 (coverage scan)

Five further ambiguities surfaced by the structured coverage scan over the drafted specification, resolved here against the intake decision, the delivered fields and endpoint, `CONTEXT.md` and the constitution.

- **Q: Does "selection-only" cover the view and delete affordances as well as add and change?** → A: Yes, all four. Django's related-field wrapper offers add, change, delete and view as one set, and the reasoning that removes the first two removes the second two: deleting a shared concept from the page of a record that merely references it is worse than creating one, and a view affordance points at a curator page that is not this feature's to design and does not exist yet. A person who wants to read a concept's definition is served by the browsing interface R6 brings, not by a popup onto an editing form. Integrated into FR-004 and Edge Cases.
- **Q: When a project declares `autocomplete_fields`, `raw_id_fields` or a widget of its own for the field, what happens?** → A: The project's declaration wins, silently. This package supplies a default, and a default that argued with an explicit instruction would be a bug rather than a safeguard. No warning is raised, because nothing is wrong: a project that has asked for the admin's own autocomplete has asked for it. The one thing this feature owes such a project is that nothing breaks: the field, its vocabulary constraint and its delete protection are unchanged whichever control renders. Integrated into FR-005 and User Story 4.
- **Q: Do inline forms get the control, including rows added after the page loads?** → A: Both, and the second is the load-bearing half. A consuming model is at least as often edited as an inline of something else as it is on its own page, and the admin builds a new inline row in the browser by copying a hidden template row. A control that worked only in the rows rendered by the server would appear to work, then fail on exactly the row someone was adding — a quiet half-feature. Integrated into FR-003 and User Story 3.
- **Q: Does the package now require `django.contrib.admin`?** → A: No. A project consuming vocabularies without ever enabling the admin must be unaffected: nothing this feature adds may be imported at startup in a way that assumes the admin is installed, and the existing system checks must not start reporting on it. The behaviour must also reach a project that runs its own `AdminSite` rather than the default one, because a custom site is ordinary Django and a feature that only worked on the default would fail silently on it. Integrated into FR-006, FR-007 and User Story 5.
- **Q: What happens where the admin shows the field read-only?** → A: The concept is shown by its preferred label and no control renders, which is what a read-only field means. The feature adds no editing surface where the admin has decided there is none, and the same holds for a person whose permissions give them view access to the page but not change access. Integrated into FR-008 and Edge Cases.

### Session 2026-08-14 (design review)

One amendment, raised by the design review before anything was built and recorded here rather than left to the implementation.

- **Q: Does FR-004's refusal of the view affordance reach a field the admin renders read-only?** → A: No, and it cannot. A read-only field is excluded from the form, so no form field and no widget is built for it, and the mechanism that declines the admin's related-object wrapper never runs. Django's `AdminReadonlyField` renders a single-value relation as a link to that record's own admin change page, falling back to plain text only while the model is unregistered. No package can decline that. The requirement is therefore scoped to the editable control, which is what "selection-only" was about: a read-only field offers no selection at all, and following a link to a concept's own page is not authoring one from a data-entry form. A read-only many-to-many field is unaffected either way — Django renders it as plain text. Integrated into FR-004 and FR-008; rationale in `decisions.md` D14.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The admin page gets the same control, declaring nothing (Priority: P1)

A project registers one of its own models in the admin. The model declares a field carrying a vocabulary. On the add page and on the change page, the person types a few letters into that field and picks a concept from the matches, exactly as they would on any other form in the project. The `ModelAdmin` names no widget, no form and no field list to make this happen.

**Why this priority**: This is the feature. The admin is where most Django projects do their day-to-day data entry, so a consumption field that is excellent everywhere except the admin is a consumption field most projects meet at its worst.

**Independent Test**: Register a consuming model in the admin with a bare `ModelAdmin`, request its add page and the change page of a saved record, and confirm the concept field renders as the search control in both, that the page carries no list of the vocabulary's concepts, and that a form submitted from either page saves the chosen concept.

**Acceptance Scenarios**:

1. **Given** a consuming model registered with a `ModelAdmin` that declares nothing about the field, **When** the add page is requested, **Then** the single-value field renders as the concept search control.
2. **Given** the same registration, **When** the change page of a saved record is requested, **Then** the field renders as the control and shows the concept the record already holds, under its preferred label.
3. **Given** a consuming model declaring the multiple-value field, **When** either page is requested, **Then** it renders as the control, shows every concept the record holds, and each is removable before submission.
4. **Given** a vocabulary holding many thousands of concepts, **When** either page is requested, **Then** the rendered page carries no list of them and does not grow with the vocabulary.
5. **Given** either page, **When** it is submitted with a concept chosen, **Then** the record saves with that concept attached, and every rule the field already enforced — its vocabulary constraint, its required rule, its delete protection — applies unchanged.
6. **Given** a project that has included the package's route and declared the control's supporting package and middleware, **When** the admin is used, **Then** nothing further is configured for the admin specifically.

---

### User Story 2 - Concepts are chosen here, never created (Priority: P1)

Someone entering a record in the admin can pick any concept the field allows and can pick no other. They cannot create a concept, edit one, or delete one from that page, not because the buttons are hidden from them by permission, but because a page for entering a record is not where a shared vocabulary is authored.

**Why this priority**: It is the decision the maintainer took at intake, and getting it wrong is worse than not shipping the feature. Django adds these affordances automatically the moment the related model is registered in the admin, so the curator interface arriving in R5 would silently put a "create a concept" button on every consuming project's data-entry page unless this feature refuses it now.

**Independent Test**: Register the package's own concept model in a test admin site alongside a consuming model, request the consuming model's add and change pages as a superuser, and confirm the rendered field offers no add, change, delete or view affordance for the related concept, while the control itself still works.

**Acceptance Scenarios**:

1. **Given** the concept model registered in the same admin site and a superuser with every permission, **When** a consuming model's add page is rendered, **Then** the concept field offers no affordance to add a concept.
2. **Given** the same, **When** a change page holding a concept is rendered, **Then** it offers no affordance to change, delete or view that concept.
3. **Given** the same, **When** the page is rendered, **Then** the control itself is unaffected: searching, choosing and saving work as in User Story 1.
4. **Given** the concept model **not** registered in the admin, **When** either page is rendered, **Then** the result is the same, because the absence of these affordances does not depend on what is registered.
5. **Given** the multiple-value field, **When** either page is rendered, **Then** the same holds for it.

---

### User Story 3 - Inline rows, including the ones added on the page (Priority: P2)

A model is edited as an inline of another, say measurements inside a sample, and each row carries a concept field. Every row rendered with the page has the control, and so does every row the person adds by clicking "Add another", which is the row they are most likely to be filling in.

**Why this priority**: Inlines are how the admin edits related records, and a consuming model is as likely to be met as a row inside something else as it is on its own page. It sits below the first two because a control that is correct on the main form can be extended to rows, while one that offers the wrong concepts is wrong everywhere.

**Independent Test**: Register a parent model with a tabular inline and a stacked inline of a consuming model, request the parent's change page, and confirm the control renders in each existing row. Then confirm the row the admin copies to build a new one carries the control in a usable state, and that a parent saved with a newly added row stores the concept chosen in it.

**Acceptance Scenarios**:

1. **Given** a parent model with an inline of a consuming model and two saved rows, **When** the parent's change page is rendered, **Then** both rows carry the control, each showing the concept its row holds.
2. **Given** the same page, **When** a new inline row is added on the page, **Then** that row carries a working control rather than an inert copy.
3. **Given** a new row with a concept chosen in it, **When** the parent is saved, **Then** the row is created holding that concept.
4. **Given** an inline row whose field declares a different vocabulary from the parent form's field, **When** each is searched, **Then** each offers only what its own declaration allows.
5. **Given** an inline with no saved rows, **When** the page is rendered, **Then** the first row added on the page behaves as in scenario 2.

---

### User Story 4 - A project's own choice wins (Priority: P2)

A project has a reason to want something else for a field: the admin's own autocomplete, a raw identifier box, a widget it wrote, or no control at all because the field is read-only there. It declares that in its `ModelAdmin`, and that is what it gets, with no warning and nothing to override.

**Why this priority**: A default that cannot be turned off is not a default. This is what makes the feature safe to ship into projects that already have opinions about their admin, and it costs nothing to honour, but a project discovering it cannot escape would have to stop using the field altogether.

**Independent Test**: Register the same consuming model three times against separate admin sites, one declaring the field in `autocomplete_fields`, one in `raw_id_fields`, one overriding the widget through a form — and confirm each renders what it asked for, that no system check or warning fires, and that a record saved through each is correct.

**Acceptance Scenarios**:

1. **Given** a `ModelAdmin` naming the field in `autocomplete_fields`, **When** the page is rendered, **Then** the admin's own autocomplete renders and this package's control does not.
2. **Given** a `ModelAdmin` naming the field in `raw_id_fields`, **When** the page is rendered, **Then** the raw identifier control renders.
3. **Given** a `ModelAdmin` whose form declares its own widget for the field, **When** the page is rendered, **Then** that widget renders.
4. **Given** any of the three, **When** the form is submitted with a valid concept, **Then** the record saves, and with an ineligible one, **Then** the field refuses it exactly as it always did.
5. **Given** any of the three, **When** the project's checks run, **Then** nothing is reported, because an explicit declaration is an instruction rather than a mistake.
6. **Given** a `ModelAdmin` listing the field among its read-only fields, **When** the page is rendered, **Then** the concept is shown by its preferred label and no control renders.
7. **Given** a person with permission to view the page but not to change it, **When** it is rendered, **Then** the same read-only presentation applies.

---

### User Story 5 - The admin stays optional (Priority: P2)

A project consumes vocabularies without ever enabling the Django admin. It sees no change: nothing new is imported at startup, no check reports on an admin it does not have, and nothing fails. A project running its own admin site rather than the default one gets the feature in full.

**Why this priority**: This package's fields are for any Django project, and the admin is an optional application. A feature that quietly made it a requirement would break projects that never asked for it, and the failure would appear at startup rather than on a page.

**Independent Test**: Run the package's test suite and system checks with `django.contrib.admin` absent from the installed applications, and confirm nothing fails and nothing new is reported. Separately, register a consuming model against a custom `AdminSite` and confirm the control renders and works there.

**Acceptance Scenarios**:

1. **Given** a project without the admin installed, **When** it starts and its checks run, **Then** nothing this feature adds is loaded and no new check output appears.
2. **Given** the same project, **When** a form carrying either field is rendered outside the admin, **Then** it behaves exactly as it did before this feature.
3. **Given** a project registering a consuming model on a custom admin site, **When** its add and change pages are rendered, **Then** the control renders and works as on the default site.
4. **Given** a project using both the default site and a custom one, **When** each renders the same consuming model, **Then** both get the control.

---

### User Story 6 - Documented, translatable, and tested where it belongs (Priority: P3)

The README tells a developer that a model declaring one of these fields gets search-as-you-type in the admin with nothing to configure, and that concepts are chosen there rather than created. Any string the feature puts in front of a person is translatable, and its tests sit where the test structure says they sit.

**Why this priority**: Constitutional obligations spanning the feature rather than one journey through it. They sit last because they describe how the work is finished rather than what it does, and none of them can be judged before the behaviour exists.

**Independent Test**: Read the README section on the admin, confirm it states what a project must do and what the page will not offer, assert that no user-visible string this feature adds is a bare literal, and confirm the test modules mirror the source tree and reuse the consuming models and fixtures the delivered fields left shared.

**Acceptance Scenarios**:

1. **Given** the shipped documentation, **When** the README is read, **Then** it states that registering a consuming model in the admin is enough, that the wiring is the same three entries the forms feature already asks for, that concepts cannot be created or edited from a consuming record's page, and how a project overrides the default.
2. **Given** the feature's user-visible strings, **When** the source is inspected, **Then** each is wrapped for translation per Article XII, with named placeholders.
3. **Given** the test suite, **When** the modules are located, **Then** they mirror the source tree per testing standard §4 and reuse the shared consuming models and fixtures rather than defining new ones.
4. **Given** the CHANGELOG, **When** it is read, **Then** it records the addition.
5. **Given** `CONTEXT.md`, **When** it is read, **Then** any term this feature introduces into the package's public vocabulary is defined there, and the concept search control's entry reflects that it is now the admin's representation too.

---

### Edge Cases

- The field is listed in the admin's read-only fields. No control renders and the concept is shown by its preferred label, which is what read-only means.
- The person has permission to view the page but not to change it. The same read-only presentation applies, and no control is rendered for them to use.
- The package's own models are registered in the admin by the curator interface. The consuming model's page still offers no add, change, delete or view affordance for a concept.
- A record holds a concept from a vocabulary its field no longer names. The change page shows the concept rather than dropping it, and the field's ordinary validation decides what happens on submission, exactly as outside the admin.
- The project has not included the package's route, or has not declared the control's supporting package or its middleware. The existing system check reports each, and the admin adds no fourth requirement to report.
- A vocabulary the field names has not been imported. The search returns nothing, the page still renders, and the existing check is what tells the developer.
- The person's browser runs no JavaScript. The control cannot work, as outside the admin, and the form's server-side validation is unchanged, so nothing invalid is saved by a page that failed to enhance.
- Two inline rows on one page carry fields declared against different vocabularies. Each searches its own.
- The same consuming model is registered on more than one admin site with different declarations. Each site renders what it declares.
- The admin's popup for adding a related record is reached by some other route on the page. It is unaffected for every other field on the model, because this feature changes only what the concept fields offer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A model declaring either consumption field, registered in the Django admin with a `ModelAdmin` that says nothing about that field, MUST render the concept search control on its add page and its change page. A consuming project MUST NOT have to name a widget, declare a form, list the field, or configure anything in the `ModelAdmin` to get this.
- **FR-002**: The admin MUST require no wiring beyond the entries the project already adds for the forms feature: the package's route, the control's supporting package among the installed applications, and that package's middleware. This feature MUST NOT introduce a fourth setup step, and the existing system check MUST remain the single place a missing entry is reported.
- **FR-003**: The control MUST render in admin inline forms, both in rows rendered with the page and in rows the admin builds in the browser after it loads, and a row added in the browser MUST be usable rather than an inert copy. A concept chosen in such a row MUST be saved with the parent.
- **FR-004**: Where a consuming model's admin page renders the concept field as a control, that control MUST offer no affordance to add, change, delete or view the related concept, whether or not the package's own models are registered in the admin and whatever permissions the person holds. Concept authoring belongs to the curator interface. *(Amended at the design review, `decisions.md` D14: the requirement is scoped to the editable control. A field the admin renders read-only is not a control, and Django renders every read-only relation as a link to that record's own admin page from `AdminReadonlyField`, which no package can decline. See FR-008.)*
- **FR-005**: Where a project's `ModelAdmin` makes its own explicit choice for the field — naming it in `autocomplete_fields` or `raw_id_fields`, or declaring a widget or form of its own — that choice MUST win, silently and with no check or warning raised. Every guarantee the field itself makes MUST hold whichever control renders.
- **FR-006**: The package MUST NOT require `django.contrib.admin`. Nothing this feature adds may be imported at startup in a way that assumes the admin is installed, and no check may report on the admin in a project that does not have it.
- **FR-007**: The behaviour MUST reach a consuming model registered on a custom `AdminSite` as well as on the default one, and MUST hold when the same model is registered on more than one site.
- **FR-008**: Where the admin presents the field read-only, through its read-only field list or because the person may view the page but not change it, the concept MUST be shown by its preferred label and no control MUST be rendered. This is Django's own read-only rendering, which links a single-value relation to the related record's admin page once that model is registered; the package neither adds to it nor suppresses it, and it is not a selection surface. *(Recorded at the design review, `decisions.md` D14.)*
- **FR-009**: Rendering an admin page MUST NOT load the field's eligible concepts into it, and the rendered page MUST NOT grow with the size of the vocabulary. Searching, matching, display, paging and the rule that the restriction is derived from the field declaration are the delivered endpoint's, unchanged and reused rather than reimplemented for the admin.
- **FR-010**: Every guarantee the two consumption fields already make — the vocabulary constraint, the delete protection, the required rule, the label and identity readback — MUST be unchanged by this feature, in the admin as outside it.
- **FR-011**: Every string this feature puts in front of a person MUST be translatable per Article XII, with named placeholders so the message identifiers stay static.
- **FR-012**: The README MUST document that registering a consuming model in the admin is sufficient, that the wiring is unchanged, that concepts cannot be created or edited from a consuming record's page, and how a project overrides the default. `CONTEXT.md` MUST reflect that the concept search control is the admin's representation of these fields too, and the CHANGELOG MUST record the addition.
- **FR-013**: Any new runtime dependency MUST be justified and declared alongside the code that imports it per Article VII, and the dependency checks MUST pass.

### Key Entities *(include if feature involves data)*

- **The admin page**: A consuming project's add or change page for one of its own models, generated by the admin from a `ModelAdmin` the project registers. What this feature decides is which control the concept fields on that page render as, and what the page does not offer beside them.
- **The inline row**: One consuming record edited inside another model's admin page, either rendered with the page or built in the browser from the admin's hidden template row. Both kinds carry the control.
- **The explicit declaration**: A statement in a project's own `ModelAdmin` about how a field should render. It overrides this package's default and is never argued with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consuming model registered in the admin with a bare `ModelAdmin` offers search-as-you-type on its add and change pages, with nothing declared about the field and nothing configured for the admin.
- **SC-002**: No admin page of a consuming record offers a way to create, change, delete or view a concept, including with the package's own models registered and the person holding every permission.
- **SC-003**: Every inline row carries a working control, including a row added on the page after it loaded, and a concept chosen in such a row is saved with the parent.
- **SC-004**: A `ModelAdmin` naming the field in `autocomplete_fields` or `raw_id_fields`, or declaring its own widget, renders exactly that, and the project's checks report nothing.
- **SC-005**: The package's test suite and system checks pass with `django.contrib.admin` absent from the installed applications, and the control works on a custom admin site.
- **SC-006**: An admin page carrying a vocabulary of tens of thousands of concepts renders the same size as one carrying a handful.
- **SC-007**: Every existing test of the two consumption fields and the search endpoint stays green, unchanged.
- **SC-008**: Coverage floors hold (project ≥ 90%, patch ≥ 85%), lint, type-check and dependency checks pass, and no user-visible string this feature adds is untranslatable.

## Assumptions

- **The forms feature is the contract, and this feature changes none of it.** [#88](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/88) settled what a typed string matches, what a result shows, how results are bounded, and that the restriction is derived from the field declaration rather than taken from the request. The admin reuses all of it. Nothing about searching, matching or eligibility is decided again here, and no admin-specific endpoint exists.
- **The wiring is the same three entries.** A project already adds the package's route, the control's supporting package and that package's middleware for forms to work. The admin needs those and nothing more, and the issue's "without the project wiring up widgets or endpoints itself" is about what a `ModelAdmin` declares, not about those three.
- **The curator interface is R5's, and this feature does not anticipate it** beyond refusing the affordances it would otherwise switch on. Registering the package's own models in the admin is that item's work.
- **The changelist is out of scope.** Searching, filtering or displaying by concept on the admin's list page is not part of this feature. The issue names the add and change pages, and a filter over a vocabulary of tens of thousands of concepts is its own problem.
- **A project may already have decided.** Projects that consume this package may have existing admin declarations for these fields, and this feature must lose to them rather than win. That is what keeps it safe to adopt without an audit of every `ModelAdmin`.
- **The control needs a browser that runs scripts**, in the admin exactly as outside it. Server-side validation is unchanged, so a page that fails to enhance can submit nothing the field would have accepted anyway.
- **No release carries the old behaviour.** The package is at `0.0.x` with its first publish still ahead in the v0.1.0 milestone, so changing what these fields render as in the admin owes no upgrade path and no deprecation cycle.
