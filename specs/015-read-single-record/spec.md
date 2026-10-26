# Feature Specification: Read a single record

**Feature Branch**: `015-read-single-record`

**Created**: 2026-08-24

**Status**: Draft

**Input**: Issue [#142](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/142) — "Every concept, collection and ordered collection in the database already has an address on this site, and nothing serves it — the address leads nowhere. Each should open a page showing what the record holds and where it sits among the records around it, in the languages its names and descriptions were recorded in. All three kinds are addressed the same way, by the vocabulary they belong to and their own slug, so one path serves them all."

**Serves**: G7 (vocabulary browsing) · **Roadmap**: R6 · **Issue**: #142

> Scope note: this is the third and last slice of roadmap item R6. It depends on
> [#141](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/141), which served a
> vocabulary's own page and deliberately left every concept and collection on it unlinked, because
> nothing served an individual record's address yet. This feature owns **the pages an individual
> record's address leads to** — one for a concept, one for a collection — everything the database
> records about that record, the links from it to the records it names, and the links from the
> vocabulary's page that finally reach it.
> **Out of scope:** stepping through the broader/narrower hierarchy as a tree, which the maintainer
> removed from #141 and which a page showing one step in each direction does not reintroduce;
> searching for a term without knowing which vocabulary holds it, which no roadmap item currently
> covers; returning a machine-readable representation when a record's address is
> asked for one, which belongs with export rather than with browsing; editing anything shown; any
> access rule of the package's own; keeping
> these pages fast at a scale the project has not yet met, which is R7; and publication and
> deprecation, which are R4.

## Clarifications

### Session 2026-08-24 (intake)

Seven decisions were taken with the maintainer at intake, each deciding what the feature is rather
than how it is built.

- **Q: The issue says all three kinds are addressed the same way, so one path serves them all. The shipped models compose a concept's address as `{vocabulary}/{slug}` and a collection's as `{vocabulary}/collection/{slug}`. Which is it?** → A: The addresses stay exactly as the records already compose them. The maintainer's requirement is that a published record's identifier must equal the address it is served at, so an external consumer's stored identifier leads a reader back to the record here — and both shapes satisfy that. The extra segment is what keeps a collection's address visibly apart from a concept's. Evidence that a type discriminator is normal and permitted: SKOS constrains nothing about URI shape, AGROVOC distinguishes `…/agrovoc/c_1234` from `…/agrovoc/skosCollection_cb7b7c4a`, and GEMET distinguishes `…/gemet/concept/95` from `…/gemet/group/96`. Integrated into FR-001 and FR-002.
- **Q: Does this feature serve collections as well as concepts?** → A: Yes. The vocabulary page lists a vocabulary's collections unlinked on the explicit grounds that this feature gives them somewhere to lead, so serving only concepts would leave the dead address precisely where the previous feature promised it would be filled. There are two pages rather than the issue's three: an ordered collection is a collection of type `skos:OrderedCollection`, whose members are listed in a sequence, so it is the same page with its members in the publisher's sequence. Integrated into User Story 2, FR-002 and FR-013.
- **Q: The issue asks for a record "in the languages its names and descriptions were recorded in", which is a different rule from the one the vocabulary page ships with. Which applies?** → A: The same rule the vocabulary page uses — the language the site is being read in, falling back to the vocabulary's own default language. One language, not all of them. Integrated into FR-005.
- **Q: What does "where it sits among the records around it" cover?** → A: One step in every direction and no further: its broader concept, its narrower concepts, its related concepts, the collections it belongs to, and the vocabulary that holds it. No path back up to the top of the hierarchy — walking up one step at a time reaches it, and computing an ancestor chain on every page view is a cost R7 exists to deal with. Integrated into User Story 3, FR-010 and FR-011.
- **Q: What shape is the page?** → A: A definition list of everything recorded about the record, each row keyed by the predicate's CURIE — `skos:prefLabel`, `skos:broader` — with the value beside it. Any value that is itself a record shows as a CURIE too, carrying that record's full canonical identifier on hover and linking to it. Integrated into User Stories 1 and 3, and FR-003, FR-006 and FR-007.
- **Q: "Everything" includes hidden labels, which the previous feature established exist to be matched on and never shown. Do they appear?** → A: No. Every predicate except hidden labels, which stay out of sight — a hidden label is where a vocabulary keeps misspellings, superseded wording and terms deliberately retired, and a raw complete view would put all of them in front of any reader. Integrated into FR-004.
- **Q: A CURIE needs a prefix per vocabulary, and nothing records one. Where does it come from?** → A: Derived from the vocabulary's slug, which is already unique across every vocabulary on the site, so the short form is never ambiguous and nobody has to maintain one. The cost, accepted: an imported vocabulary is shown under our slug rather than the prefix its own community uses, with the full canonical identifier still on hover and behind the link. Storing a real prefix per vocabulary changes what the package records and belongs with identity, not with browsing. Integrated into FR-006 and Assumptions.

### Session 2026-08-24 (drafting)

Ambiguities the intake decisions left open, resolved while drafting against the shipped models,
`CONTEXT.md` and the constitution.

- **Q: A CURIE links to "it" — the record's page on this site, or the canonical identifier the hover shows?** → A: The record's page on this site. The hover carries the canonical identifier, which for an imported record belongs to its publisher, while the link carries the reader somewhere they can actually read. A value that names a record this site does not hold, such as a mapping to another vocabulary, is shown as its URI, and is a link to that address when it is a web address. Integrated into FR-007.
- **Q: Which collections a concept belongs to has no SKOS property to key it on. Where does it go?** → A: Its own section below the definition list, with a plain-language heading. Every row in the list is a statement the record makes about itself and has a real property behind it, including `skos:narrower`, which is shown from the broader links other concepts state. Membership is a statement other records make about this one, and inventing a CURIE for it would misrepresent the data. Integrated into FR-014.
- **Q: What distinguishes an ordered collection from an unordered one on the page?** → A: Its type row, which reads `skos:OrderedCollection` rather than `skos:Collection`, and the property its members appear under, which is `skos:memberList` rather than `skos:member`. Both are honest SKOS: an ordered collection genuinely is a distinct class with a distinct membership property. Integrated into FR-012 and FR-013.
- **Q: A concept's page shows a definition. Which of the seven kinds of note does it show?** → A: All of them the record carries. The maintainer asked for everything recorded except hidden labels, and each kind of note has its own SKOS property to key its row on, so nothing has to be grouped or interpreted. Integrated into FR-003.
- **Q: What does a reader see for a predicate the record carries no value for in any available language?** → A: No row at all. A list of rows reading "none" for every property a publisher has not filled in tells a reader nothing and buries what was filled in. A record carrying nothing beyond its label shows its label, its type, its identifier and its vocabulary. Integrated into FR-018.
- **Q: What happens at an address naming no record?** → A: The page is reported as not found, the same as an address naming no vocabulary. An address whose vocabulary segment names no vocabulary is equally not found, rather than reported differently. Integrated into FR-001 and FR-002.

### Session 2026-08-24 (coverage scan)

Four further ambiguities surfaced by the structured coverage scan run over the drafted
specification. The scan found the domain model, the user journeys, the empty and not-found states,
the scale assumptions and the glossary already covered; these four were not.

- **Q: The full identifier is disclosed on hover. A keyboard user, a touch user and a screen reader have no hover. Is it unreachable for them?** → A: No, and the specification must not say hover as though it were the only way. Hovering is how a pointer reveals it; the requirement is that every reader can obtain the full identifier behind a short form without leaving the page, by whatever means their device offers. How that is done is a design question, but a page where a whole class of readers cannot expand a single short form does not meet the goal the short forms exist for. Integrated into FR-007 and SC-003.
- **Q: This is a linked-data package, and the address being served is the record's own identifier. Does asking that address for RDF return RDF?** → A: Not in this feature. Serving a machine-readable representation at the same address is a real and expected thing for a published vocabulary, and it is a different feature from a page a person reads: it has its own formats, its own round-trip fidelity rules, and it belongs with export rather than with browsing. Declared out of scope in the scope note and raised at the spec gate as the obvious thing R6 leaves behind.
- **Q: A concept's status — draft, published, deprecated — "Everything recorded" would include it.** → A: The package keeps no status of its own. A concept its publisher marked `owl:deprecated` carries that statement in its document, and the page shows it as a row like any other statement. A lifecycle of the package's own belongs to the publication feature, R4. Integrated into Assumptions.
- **Q: A record's identifier can be a string an external publisher supplied, and the page puts it in a link and in whatever carries the full form.** → A: Values reach the reader as text through the template layer with nothing marked safe, and a publisher-supplied identifier reaches an attribute only as a link's destination — the same treatment the vocabulary page already gives an identifier it did not author. An import separately refuses an identifier that begins `javascript:`, `data:` or `vbscript:`. Integrated into FR-021.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open a concept and read what it holds (Priority: P1)

Someone who has an identifier for a concept — stored in their own database, cited in a paper, or
handed to them by a colleague — opens it and gets a page about that concept: what it is called, what
it means, every note recorded against it, what kind of thing it is, and its identifier. Everything
the database holds about that concept is on the page, each fact labelled with the property it was
recorded under, so a reader who knows SKOS sees exactly what was stored and a reader who does not
still sees the term and its definition.

**Why this priority**: It is the feature. A vocabulary published as linked data promises that its
identifiers lead somewhere, and until this page exists every concept identifier this site has ever
composed leads nowhere. Nothing else in the feature has value without it.

**Independent Test**: Load a concept's own composed address directly, with no other page in play,
and confirm the page names the concept, shows every value recorded against it, and reports not found
for an address naming no concept.

**Acceptance Scenarios**:

1. **Given** a concept with a preferred label, a definition and a scope note, **When** a visitor
   opens the concept's own address, **Then** the page shows each of those values on its own row,
   labelled with the SKOS property it was recorded under.
2. **Given** a concept carrying alternative labels and hidden labels, **When** a visitor opens its
   page, **Then** the alternative labels appear and no hidden label appears anywhere on it.
3. **Given** a concept whose labels exist in several languages, **When** a visitor reads the site in
   one of them, **Then** each value appears in that language, and where the concept has no value in
   it, in the vocabulary's own default language.
4. **Given** a concept carrying no notes at all, **When** a visitor opens its page, **Then** the page
   shows its label, its type, its identifier and its vocabulary, and shows no empty rows for the
   properties it does not carry.
5. **Given** an address inside a real vocabulary naming no concept, **When** a visitor opens it,
   **Then** the page is reported as not found.

---

### User Story 2 - Open a collection and see what it holds (Priority: P2)

Someone follows a collection's identifier and gets a page about that collection: its name, its
identifier, what kind of collection it is, and the concepts it gathers. An ordered collection shows
its members in the sequence its publisher gave; an unordered one shows them as the set it is.

**Why this priority**: A collection's address is dead in exactly the same way a concept's is, and the
vocabulary page already lists collections on the promise that this feature reaches them. It ranks
below the concept page only because a vocabulary's concepts are what most readers arrive for.

**Independent Test**: Load a collection's own composed address directly and confirm the page names
the collection, lists its members, and distinguishes an ordered collection from an unordered one.

**Acceptance Scenarios**:

1. **Given** an unordered collection holding three concepts, **When** a visitor opens its address,
   **Then** the page shows its name, its type as an unordered collection, and its three members.
2. **Given** an ordered collection whose members are listed in a sequence, **When** a visitor opens
   its address, **Then** the members appear in that sequence and the page shows its type as an
   ordered collection.
3. **Given** a collection holding no members, **When** a visitor opens its address, **Then** the page
   shows the collection and says it holds nothing, rather than showing an empty membership row.

---

### User Story 3 - Follow a record to the records around it (Priority: P2)

A reader on a concept's page sees which concept is broader than it, which are narrower, and which are
related, each shown in short form. Hovering one shows the full identifier it stands for, and
following it opens that record's own page. The same is true of the vocabulary the concept belongs to,
and of a collection's members. A reader who lands on one record can walk the vocabulary from it
without ever typing an address.

**Why this priority**: It turns a set of separate pages into something a person can browse, and it is
what makes the short forms on the page readable — a CURIE a reader cannot expand is a code, not an
identifier.

**Independent Test**: From a concept with a broader concept, a narrower concept and a related
concept, confirm each appears in short form, carries its full identifier, and leads to that record's
page.

**Acceptance Scenarios**:

1. **Given** a concept with a broader concept, **When** a visitor opens its page, **Then** the
   broader concept appears as a short form built from its vocabulary and its own slug, and following
   it opens that concept's page.
2. **Given** a concept that is the broader of two others, **When** a visitor opens its page, **Then**
   both narrower concepts appear, although only the opposite direction is stored.
3. **Given** any record shown in short form, **When** a visitor hovers it, **Then** the full
   canonical identifier of that record is shown.
4. **Given** a concept in a vocabulary published elsewhere, **When** a visitor hovers its short form,
   **Then** the identifier shown is the publisher's, while the link leads to the record's page on
   this site.

---

### User Story 4 - Reach a record from the vocabulary that holds it (Priority: P2)

A person browsing a vocabulary's page follows any concept or collection listed on it straight to that
record's own page. The entries that have been plain text since the vocabulary page shipped become the
links they were always meant to be.

**Why this priority**: It completes the path a person actually walks — list of vocabularies, then a
vocabulary, then a record — for a reader who arrives with no identifier at all. It is small, and it
is the last thing standing between the browsing pages and a reader who can use them.

**Independent Test**: From a vocabulary's page, follow a concept entry and a collection entry and
confirm each reaches the right record's page.

**Acceptance Scenarios**:

1. **Given** a vocabulary holding concepts, **When** a visitor opens its page and follows a concept
   in the list, **Then** that concept's own page opens.
2. **Given** a vocabulary holding collections, **When** a visitor follows one of them, **Then** that
   collection's own page opens.
3. **Given** a search that has narrowed the vocabulary's list of concepts, **When** a visitor follows
   a result, **Then** that concept's page opens.

---

### User Story 5 - See which collections a concept belongs to (Priority: P3)

A reader on a concept's page sees the collections that gather it, named and linked, set apart from
the properties the concept itself carries.

**Why this priority**: It is the smallest slice and the only one a reader can obtain another way, by
opening the collections of the vocabulary and reading their members. It ranks last for that reason,
not because membership does not matter.

**Independent Test**: From a concept that two collections gather, confirm both are named below the
list of properties and each leads to its collection's page.

**Acceptance Scenarios**:

1. **Given** a concept gathered by two collections, **When** a visitor opens its page, **Then** both
   are named in a section of their own, distinct from the properties the concept carries, and each
   leads to that collection's page.
2. **Given** a concept no collection gathers, **When** a visitor opens its page, **Then** no such
   section appears, rather than an empty one.

### Edge Cases

- A concept whose vocabulary has one default language and whose labels exist only in another: every
  value falls back to the vocabulary's default, and nothing is shown blank.
- A concept and a collection whose slugs differ: each is reachable at its own address, a
  collection's carrying its own segment.
- A record whose identifier was assigned by an external publisher: the page shows that identifier as
  its own, while remaining served at this site's composed address for it.
- A concept related to a concept in another vocabulary held on this site: the short form carries the
  other vocabulary's prefix, and the link leads to its page here.
- A collection gathering a concept from another vocabulary: the member is shown with its own
  vocabulary's prefix, so a reader can see it comes from elsewhere.
- A link to a record this site does not hold: the value is shown as the URI it names, as a link to
  that address when it is a web address and as text otherwise.
- An address whose vocabulary segment names no vocabulary: reported as not found, not distinguished
  from an address whose record segment names no record.
- A concept and a collection of one vocabulary cannot share a slug, because both are records of one
  vocabulary, and a collection's address keeps its own segment all the same.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST serve a page at the address every concept already composes — the
  vocabulary's address followed by the concept's own slug — and MUST report the page not found for an
  address naming no concept, including one whose vocabulary segment names no vocabulary.
- **FR-002**: The package MUST serve a page at the address every collection already composes, which
  carries its own distinguishing segment, and MUST report the page not found for an address naming no
  collection. The addresses served MUST be the ones the records already compose, unchanged, so that a
  record's identifier and the address it is read at are the same string wherever the record's
  identifier is this site's own.
- **FR-003**: A record's page MUST show every value the database records against it as a
  term-and-value pair, the term being the CURIE of the SKOS property the value was recorded under,
  covering its preferred label, its alternative labels, and each of its notes under the property of
  its own kind.
- **FR-004**: A hidden label MUST NOT appear on any page this feature serves.
- **FR-005**: A value MUST be shown in the language the site is being read in where the record
  carries one in that language, and otherwise in the vocabulary's own default language. One language
  MUST be shown, not every language a value was recorded in.
- **FR-006**: A value that is itself a record MUST be shown as a CURIE whose prefix is the slug of the
  vocabulary holding that record and whose local part is the record's own slug.
- **FR-007**: A CURIE standing for a record MUST link to that record's page on this site, and its
  full canonical identifier MUST be obtainable by any reader without leaving the page — a reader
  using a pointer, a reader using a keyboard, a reader on a touch screen and a reader using a screen
  reader alike. Where the record's identifier was assigned by an external publisher, the identifier
  disclosed MUST be the publisher's while the link MUST still lead to this site's page for it.
- **FR-008**: A record's page MUST show the record's own identifier, as a link, exactly as the
  vocabulary page shows a vocabulary's.
- **FR-009**: The pages MUST carry no access rule of their own: whatever the site holds is shown to
  whoever requests the page, leaving any restriction to the project mounting the package's routes.
- **FR-010**: A concept's page MUST show its broader concept, its narrower concepts and its related
  concepts, each as a row keyed by the SKOS property that names the relation. The narrower concepts
  MUST be shown although only the opposite direction is stored.
- **FR-011**: A record's page MUST show the vocabulary that holds it, keyed by the SKOS property for
  it, and MUST NOT show any further step of the broader/narrower hierarchy than the one step in each
  direction FR-010 requires.
- **FR-012**: A record's page MUST show what kind of thing the record is, keyed by the RDF type
  property — a concept, an unordered collection, or an ordered collection, the last two
  distinguished from one another.
- **FR-013**: A collection's page MUST show the concepts it gathers, keyed by the SKOS membership
  property for an unordered collection and by the ordered-membership property for an ordered one, and
  an ordered collection's members MUST appear in the sequence the list gives.
- **FR-014**: A concept's page MUST name the collections that gather it, below the term-and-value
  pairs and outside them, under a heading in plain language rather than a CURIE, each linking to that
  collection's page. A concept no collection gathers MUST show no such section rather than an empty
  one.
- **FR-015**: A vocabulary's page MUST link every concept and every collection it lists to that
  record's own page, replacing the plain text it shows today, and a narrowed list of concepts MUST
  link its results the same way.
- **FR-016**: The term-and-value pair MUST be rendered by one reusable component used at every place
  a pair appears, rather than by markup written out per page.
- **FR-017**: A collection holding no members MUST say so, and MUST NOT show an empty membership row.
- **FR-018**: A property the record carries no value for in any available language MUST produce no
  row at all, rather than a row reading as empty or absent.
- **FR-019**: Every string these pages show a reader MUST be translatable, none being fixed in one
  language.
- **FR-020**: The pages MUST show every statement of a record, including a link to a record this
  site does not hold, which MUST be shown as the URI it names, as a link when it is a web address and
  as text otherwise.
- **FR-021**: Every value these pages show MUST reach the reader as text escaped by the template
  layer, with no value marked safe, and a value an external publisher supplied MUST reach an
  attribute only as the destination of a link.

### Key Entities

- **Concept**: a term within a vocabulary, a `Record` of type `skos:Concept`; carries preferred,
  alternative and hidden labels per language, notes of several kinds, and an identifier that is its
  publisher's where it has one and this site's composed address otherwise.
- **Collection**: a publisher's grouping of concepts within a vocabulary, a `Record` of type
  `skos:Collection` or `skos:OrderedCollection`, whose members are listed in its document, in a
  sequence when it is ordered.
- **Link**: an entry in a record's document naming another resource by URI, stored as the publisher
  stated it, with the inverse of a broader, narrower or related link shown from the other end.
- **Vocabulary**: the container a record belongs to, supplying the record's address, the default
  language its values fall back to, and the slug the record's short form is prefixed with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person holding only a concept's identifier, and knowing nothing else about this site,
  can open it and say what the term means.
- **SC-002**: Everything the database records about a concept, other than its hidden labels, is
  visible on that concept's page.
- **SC-003**: A person on any record's page can reach every record it names without typing an
  address, and can obtain the full identifier behind every short form without leaving the page,
  whether they are using a pointer, a keyboard, a touch screen or a screen reader.
- **SC-004**: A person can start at the list of vocabularies and reach any concept or any collection
  the site holds by following links alone.
- **SC-005**: A reader can tell an ordered collection from an unordered one, and read the ordered
  one's members in their curated sequence.
- **SC-006**: The number of database queries a record's page runs does not grow with the number of
  values, relations or members it shows.
- **SC-007**: Every string these pages show a reader can be translated, and none is fixed in one
  language.
- **SC-008**: A person with a fresh clone can open a concept page and a collection page within the
  same documented commands that already serve the vocabulary pages, and the same walk runs unattended
  on every proposed change.

## Assumptions

- **Cross-vocabulary links are statements like any other.** A concept's exact, close, broad, narrow and
  related matches are kept in its document, and the page shows them. The target usually has no row
  here, so it is shown as its URI.
- **No vocabulary records a short prefix**, so short forms are built from a vocabulary's slug. A
  vocabulary published elsewhere is therefore shown under this site's slug for it rather than the
  prefix its own community uses. Recording a real prefix changes what the package stores and belongs
  with identity rather than with browsing.
- **The package keeps no concept status of its own.** A concept its publisher marked
  `owl:deprecated` shows that statement as a row like any other. A draft, published and deprecated
  lifecycle belongs to the publication feature, R4.
- **A record's page is served for every record the site holds**, whether its vocabulary is held here
  or was imported, because a record's page is where the record is read and its identifier is a
  separate question from its address.
- **The reusable term-and-value component is this package's own.** The user-interface package this
  project builds on offers a label-and-value pair, but it renders a heading and a paragraph rather
  than a definition list, so there is nothing upstream to consume. The component is proposed upstream
  once its shape has proved itself in use.
- **These pages are read-only and carry no permission rule**, consistent with the vocabulary pages
  they extend.
