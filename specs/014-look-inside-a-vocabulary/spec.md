# Feature Specification: Look inside a vocabulary

**Feature Branch**: `014-look-inside-a-vocabulary`

**Created**: 2026-08-20

**Status**: Draft

**Input**: Issue [#141](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/141) — "Once a visitor has picked a vocabulary they need a way into its terms, which for a vocabulary of any size means both a way to search it and a way to work down through it from the top. This is the page a vocabulary's own address leads to. It describes the vocabulary and who publishes it, and presents the concepts and collections inside so a person can find one without already knowing its name."

**Serves**: G7 (vocabulary browsing) · **Roadmap**: R6 · **Issue**: #141

> Scope note: this is the second of three slices of roadmap item R6, and it depends on
> [#140](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/140), which
> delivered the list of vocabularies and deliberately left its entries unlinked because nothing
> served a vocabulary's address yet. This feature owns **one page: the page a vocabulary's own
> address leads to**, everything it tells a reader about that vocabulary, the searchable list of
> the concepts it holds, the collections it holds, and the link from the list of vocabularies that
> finally leads here.
> **Out of scope:** a page for an individual concept, collection or ordered collection, which is
> [#142](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/142); **navigating
> the broader/narrower hierarchy, which the maintainer removed from this feature** — the page names
> a concept's broader concept and the vocabulary's top concepts, and how concepts relate in full is
> shown on a concept's own page, which is #142's; searching for a term without knowing
> which vocabulary holds it, which no roadmap item currently covers; editing anything shown here;
> any access rule of the package's own on the page itself; keeping the page fast at a scale the project has not yet
> met, which is R7; and publication, deprecation and the curator interface, which are R4 and R5.

## Clarifications

### Session 2026-08-20 (intake)

Six decisions were taken with the maintainer at intake, because each decides what the feature is
rather than how it is built.

- **Q: The issue says the page shows "who publishes it". Nothing in the data model records a publisher — does this feature start recording one?** → A: No. Provenance only: whether the vocabulary is held on this site or was published elsewhere, exactly as the list of vocabularies already expresses it. The maintainer named a named publisher as a genuine future need, to be derived from an existing record or required on the data model when it comes, and deferred it out of this feature. Integrated into FR-003 and Assumptions.
- **Q: Do the concepts and collections shown here link to their own pages?** → A: Yes, now that #142 serves those addresses. Integrated into FR-011.
- **Q: The vocabulary's identifier — plain text, as it is on the list of vocabularies, or a link?** → A: A link, for every vocabulary. The point of SKOS is that a vocabulary is a linked thing, and presenting a record without rendering its link makes little sense. A vocabulary published elsewhere links to its publisher; a vocabulary held here links to this page, its identifier being computed from this site's address until publication fixes it. This reverses the decision taken one feature ago that an identifier is never a link, and the maintainer expects to revisit it once he has seen it working. Integrated into FR-004, and applied to the list of vocabularies in FR-013.
- **Q: What does searching a vocabulary's concepts match on?** → A: Every name a term goes by — its preferred label, its alternative labels, and its hidden labels, the last of which exist in SKOS precisely to be matched on without ever being shown. Definitions are not matched: prose matching returns results whose connection to the search a visitor cannot see. Integrated into FR-008 and FR-009.
- **Q: How does a visitor work down through the vocabulary from the top?** → A: **They do not, in this feature.** The specification first read to the issue's own words and gave the page a hierarchy stepped through one level at a time; the maintainer removed it on reading it back. The page holds one flat, searchable list of every concept the vocabulary holds. How concepts relate to one another is shown on a concept's own page, which is #142's, and until that exists a reader cannot follow a concept anywhere. Integrated into User Story 2, FR-006 and the scope note; the withdrawn reasoning is kept in `decisions.md` D2 and D3.
- **Q: What are the ways into the terms, then, and how do they relate?** → A: One list and one search over it. The list holds every concept in the vocabulary; the search narrows that same list, the way a search narrows the list of vocabularies. Collections sit apart from it, listed as their own thing, because a collection is a curator's grouping rather than a concept. The maintainer asked for it kept relatively simple, to be expanded once it can be seen. Integrated into User Stories 2, 3 and 4.

### Session 2026-08-20 (coverage scan)

Five further ambiguities surfaced by the structured coverage scan over the drafted specification,
resolved here against the intake decisions, the shipped models, `CONTEXT.md` and the constitution.

- **Q: A concept's notation was agreed as a search target at intake. Can it be matched?** → A: No, because nothing stores it. `CONTEXT.md` defines a notation as a language-independent code for a concept, but no field on the concept holds one and no import path populates one — the search can only match what the data model records, which is the three kinds of label. Adding a notation to the data model is a change to what the package stores, not to how it is browsed, and belongs nowhere near a browsing feature. Recorded as a gap and raised at the spec gate. Integrated into FR-009 and Assumptions.
- **Q: A concept has labels in several languages. Which one does a visitor see?** → A: The one in the language they are reading the site in, where the concept has one, falling back to the vocabulary's own default language, which is the language its concepts' identity is anchored in. Falling back rather than showing nothing matters because a vocabulary imported from a publisher carries whatever languages that publisher wrote in, which need not include the visitor's. Integrated into FR-010.
- **Q: In what order do the concepts appear?** → A: Alphabetically by the label shown, case-insensitively, and the same on every request. It is the only order a reader can predict, and it is the order the list of vocabularies already uses. Integrated into FR-007.
- **Q: What does an entry in the list of concepts tell a reader?** → A: Its label, its broader concept, its definition cut short, its identifier and the collections that hold it, as settled with the maintainer on the running page (session 2026-10-22). Integrated into FR-012.
- **Q: What does a reader see when a vocabulary holds nothing, or a search matches nothing?** → A: Three distinct messages, never one. A vocabulary holding no concepts says so. A search matching nothing says so, repeats what was searched for, and offers the way back. A vocabulary holding no collections shows a dash where its collections would be named, as any missing value is shown. Integrated into FR-014 and FR-015.

### Session 2026-10-22 (layout settled on the running page)

The maintainer reviewed a working version of the page and settled its layout.

- **Q: Where does what the page says about the vocabulary go?** → A: In a side panel beside the list of concepts, at the end of the page, behaving exactly as django-mvp's filter panel does on a list page. The title and lead text stay the vocabulary's name and description. Integrated into FR-002, FR-015 and FR-020.
- **Q: Who sees whether a vocabulary was imported?** → A: Only someone who can change vocabularies. It decides whether a vocabulary may be edited here, and is no concern of a reader. Integrated into FR-003 and FR-005.
- **Q: What does the panel say?** → A: The identifier, the source (for editors), the default language, how many concepts there are, the top concepts where the vocabulary has a hierarchy, and every collection with its member count and whether it is ordered. Integrated into FR-015 and FR-020.
- **Q: The importer reads publication details (publisher, licence, version) from a SKOS file. Are they shown?** → A: Not yet: nothing stores them. Storing and showing them is its own change.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open a vocabulary and know what it is (Priority: P1)

A person who has found a vocabulary on the list — or who was handed its address by a colleague, or
followed its identifier from somewhere else entirely — opens it and gets a page about that
vocabulary: what it is called, what it covers, and its identifier, rendered as the link a
linked-data identifier is meant to be. Someone who can change vocabularies also sees whether it is
held on this site or was published elsewhere. From
the list of vocabularies, the vocabulary's name now leads here, which is the link #140 could not yet
make.

**Why this priority**: This is the feature. A vocabulary's address has led nowhere since the day
records got addresses, and everything else on the page hangs off it existing.

**Independent Test**: Open a vocabulary's address directly on a site holding both a locally authored
vocabulary and an imported one, and confirm each serves a page naming and describing that
vocabulary, showing where it came from, and offering its identifier as a link. Then confirm the list
of vocabularies leads to those same pages.

**Acceptance Scenarios**:

1. **Given** a vocabulary held on this site, **When** its address is requested, **Then** a page is
   served showing its name and its description.
2. **Given** a vocabulary imported from a publisher, **When** its page is read, **Then** the
   identifier its publisher assigned it is shown, and a user who can change vocabularies sees it
   shown as published elsewhere.
3. **Given** a vocabulary authored on this site, **When** a user who can change vocabularies reads
   its page, **Then** it is shown as held here.
3a. **Given** any vocabulary, **When** its page is read by someone who cannot change vocabularies,
   **Then** whether it was imported is not shown.
4. **Given** any vocabulary, **When** its page is read, **Then** its identifier is a link, and
   following it leads to the publisher's address for a vocabulary published elsewhere and back to
   this page for one held here.
5. **Given** a vocabulary with no description, **When** its page is read, **Then** the rest of the
   page is shown without a stray heading or empty space where the description would be.
6. **Given** the list of vocabularies, **When** an entry is followed, **Then** it leads to that
   vocabulary's page.
7. **Given** an address that names no vocabulary the site holds, **When** it is requested, **Then**
   the response says the page was not found rather than failing.
8. **Given** the page, **When** it is requested by someone not signed in, **Then** it is served.
9. **Given** a vocabulary, **When** its page is read, **Then** its default language and the number
   of concepts it holds are shown beside the list.

---

### User Story 2 - See every term the vocabulary holds (Priority: P1)

A person who does not know what is in a vocabulary reads the whole of it: one list, every concept
the vocabulary holds, named in the language they are reading the site in. Nothing is nested and
nothing is hidden behind a step they have to take first — if it is in the vocabulary, it is in the
list. Each entry says enough to tell one term from another without opening it: what it sits under,
what it means, its identifier and the collections it belongs to. Where the vocabulary has a
hierarchy, its top concepts are named beside the list as ways in.

**Why this priority**: P1 alongside the page itself. A page about a vocabulary that does not say
what is in it answers nothing, and this list is what the search in the next story narrows.

**Independent Test**: On a vocabulary holding concepts at every level of a broader/narrower
hierarchy, confirm every one of them appears in the list exactly once, in a stable alphabetical
order, with no concept from any other vocabulary among them.

**Acceptance Scenarios**:

1. **Given** a vocabulary holding concepts, **When** its page is opened, **Then** every concept in
   it appears exactly once.
2. **Given** a vocabulary whose concepts form a broader/narrower hierarchy, **When** its page is
   opened, **Then** the concepts appear as one flat list, with those deeper in the hierarchy shown
   alongside those at the top rather than beneath them.
3. **Given** a concept in another vocabulary, **When** this vocabulary's page is opened, **Then**
   that concept does not appear.
4. **Given** a concept carrying a preferred label in the language the site is being read in,
   **When** it is shown, **Then** that label names it.
5. **Given** a concept carrying no label in that language, **When** it is shown, **Then** the
   vocabulary's own default language names it rather than the row being left unnamed.
6. **Given** the list, **When** the page is requested twice, **Then** the concepts appear in the
   same alphabetical order both times.
7. **Given** more concepts than fit on one page, **When** the list is read, **Then** it is divided
   into pages and can be moved through one page at a time.
8. **Given** a vocabulary holding no concepts, **When** its page is opened, **Then** it says so, and
   the rest of the page is still shown.
9. **Given** any concept in the list, **When** it is read, **Then** it shows its label, linking to the
   concept's own page, and its identifier, linking to the identifier itself.
10. **Given** a concept with a broader concept, a definition and collections holding it, **When** its
   entry is read, **Then** it names the broader concept, shows the definition cut short in the
   reader's language or the vocabulary's default one, and links each collection to its page.
11. **Given** a concept with none of those, **When** its entry is read, **Then** nothing stands in for
   them.
12. **Given** a concept's alternative or hidden labels, **When** its entry is read, **Then** neither
   is shown.
13. **Given** a vocabulary whose concepts form a broader/narrower hierarchy, **When** its page is
   read, **Then** the concepts with no broader concept are named beside the list, each linking to
   its page; a vocabulary with no hierarchy names none.

---

### User Story 3 - Find a term inside the vocabulary (Priority: P2)

A person who knows roughly what the term is called types it, and the list narrows to the terms in
this vocabulary matching it — including terms found under a name they are not shown, which is what a
vocabulary's hidden labels are for. They can send the narrowed list as a link, and get back to the
whole vocabulary from there.

**Why this priority**: The list alone is a complete way in for a small vocabulary, which is every
vocabulary in the demonstration today. Search is what makes a vocabulary of any real size usable.

**Independent Test**: On a vocabulary holding terms with alternative and hidden labels, search for a
word appearing only in a preferred label, then only in an alternative one, then only in a hidden
one, and confirm the term is found each time and that the hidden label itself is never displayed.
Confirm the resulting address, opened fresh, returns the same matches.

**Acceptance Scenarios**:

1. **Given** a vocabulary's page, **When** a word from a concept's preferred label is searched for,
   **Then** that concept remains in the list and non-matching concepts are gone.
2. **Given** a concept carrying an alternative label, **When** a word appearing only in that label
   is searched for, **Then** the concept is found.
3. **Given** a concept carrying a hidden label, **When** a word appearing only in that label is
   searched for, **Then** the concept is found, and the hidden label is not shown anywhere on the
   page.
4. **Given** a concept whose definition contains the searched word and whose labels do not, **When**
   that word is searched for, **Then** the concept is not among the results.
5. **Given** a search in one letter case, **When** the matching text is in another, **Then** it
   still matches.
6. **Given** more concepts than fit on one page, **When** a search is run from the second page of
   the list, **Then** it is applied to every concept in the vocabulary and not only to the page
   being viewed.
7. **Given** a search matching nothing, **When** the results are shown, **Then** the page says
   nothing matched, repeats what was searched for, and offers the way back to the whole list.
8. **Given** a narrowed list, **When** its address is opened in a new session, **Then** the same
   search is applied and the same concepts are shown.
9. **Given** a search matching a concept in another vocabulary, **When** the results are shown,
   **Then** that concept is not among them.

---

### User Story 4 - See the groupings a curator made (Priority: P3)

A person reading a vocabulary sees the collections it holds — the groupings its curator made that
the broader/narrower relations do not express — named beside the list, with how many members each
has and which carry a deliberate order, and can open any of them.

**Why this priority**: Lowest of the four. The groupings are worth knowing about, but are worth less
than the terms themselves.

**Independent Test**: On a vocabulary holding both an ordered and an unordered collection, confirm
both are named on the page with their member counts, that the ordered one is identifiable as
ordered, and that each links to its own page.

**Acceptance Scenarios**:

1. **Given** a vocabulary holding collections, **When** its page is read, **Then** each collection
   is named.
2. **Given** a collection whose members carry a deliberate order, **When** it is shown, **Then** it
   is distinguishable from one that does not.
3. **Given** a vocabulary holding no collections, **When** its page is read, **Then** a dash stands
   where they would be named.
4. **Given** the collections shown, **When** the page is read, **Then** they are separate from the
   list of concepts rather than mixed into it.
5. **Given** a collection named beside the list, **When** the page is read, **Then** it shows how
   many members it has and links to its own page.

---

### Edge Cases

- A vocabulary with no description, no concepts and no collections — the page is still served and
  still identifies the vocabulary.
- A description running to several paragraphs — the page stays readable rather than burying
  everything below it.
- A concept whose label is long enough to break the layout.
- Two concepts in the same vocabulary whose shown labels are identical — both appear, and the order
  they appear in does not change between requests.
- A search string containing characters with a meaning in a query — `%`, `_`, a quote — is treated
  as text to look for, not as an instruction.
- A search string in a non-Latin script, and a search that differs from the text only by letter case
  in such a script — the same database-dependent behaviour the list of vocabularies already
  discloses (ADR 0014) applies here and is disclosed the same way.
- A concept carrying no label in the language the site is being read in — the vocabulary's own
  default language is used rather than showing an unnamed row.
- A concept with several broader concepts — its entry names one of them; its own page names all.
- A collection name too long for one line of its badge — it is cut short, and the whole name is
  available on the link.
- A vocabulary published elsewhere whose identifier is not a resolvable address — it is still shown
  as a link, and following it fails in the browser rather than on this page.
- The page is requested by someone not signed in, on a site where nothing else is public.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST serve a page at the address of every vocabulary the site holds, and
  MUST respond that the page was not found for an address naming no vocabulary.
- **FR-002**: The page MUST show the vocabulary's name as its title and its description as its lead
  text, omitting the lead text cleanly when there is none.
- **FR-003**: The page MUST show a user permitted to change vocabularies whether the vocabulary is
  held on this site or was published elsewhere, and MUST NOT show it to anyone else. It MUST show
  the publisher's own identifier where it was published elsewhere, and MUST NOT claim to name who
  the publisher is, which nothing in the data model records.
- **FR-004**: The vocabulary's identifier MUST be shown as a link, for every vocabulary — the
  publisher's address for one published elsewhere, and this site's own computed address for one held
  here.
- **FR-005**: The page MUST carry no access rule of its own: whoever requests it is served it,
  leaving any restriction to the project mounting the package's routes. The source (FR-003) is the
  one part of it that depends on who is reading.
- **FR-006**: The page MUST list every concept the vocabulary holds, each appearing exactly once, as
  one flat list — a concept's position in the broader/narrower hierarchy MUST NOT nest it, indent
  it, hide it behind another concept, or otherwise change where it appears. No concept of any other
  vocabulary may appear.
- **FR-007**: The list MUST appear in a stable alphabetical order by the label shown that does not
  depend on letter case.
- **FR-008**: A visitor MUST be able to narrow the list by searching, the search covering every
  concept in the vocabulary before the results are divided into pages, covering no concept of any
  other vocabulary, and being carried in the page's own address so that a narrowed list can be
  linked to, bookmarked and returned to.
- **FR-009**: The search MUST match a concept's preferred label in any language, its alternative
  labels and its hidden labels, matching regardless of letter case and treating the search string as
  text rather than as query syntax. It MUST NOT match a concept's definition or any other
  documentary note. A hidden label MUST never be displayed, matched or not.
- **FR-010**: A concept MUST be named in the language the site is being read in where it carries a
  preferred label in that language, and otherwise in the vocabulary's own default language.
- **FR-011**: Every concept and collection named on the page MUST link to its own page.
- **FR-012**: A concept in the list MUST show its label; its identifier, linking to that identifier;
  its broader concept where it has one; its definition, in the reader's language or else the
  vocabulary's default language, cut short; and each collection holding it. What a concept does not
  have MUST leave nothing in its place. Its alternative and hidden labels MUST NOT be shown.
- **FR-013**: The list of vocabularies MUST link each entry to that vocabulary's page, and MUST show
  the identifier it already displays as a link, replacing the plain text it displays today.
- **FR-014**: A vocabulary holding no concepts MUST say so, in wording distinct from a search that
  matched nothing; a search matching nothing MUST say so, repeat what was searched for, and offer
  the way back to the whole list.
- **FR-015**: The page MUST name every collection the vocabulary holds beside the list of concepts,
  with how many members each has, distinguishing one whose members carry a deliberate order, and
  showing a dash where the vocabulary holds none.
- **FR-016**: The list of concepts MUST be divided into pages of a fixed size where it is longer
  than one, navigable from one page to the next with any search in force preserved.
- **FR-017**: The page MUST be reachable by a name the package owns rather than a fixed path, so a
  project chooses the address it is mounted at.
- **FR-018**: The demonstration project MUST hold a vocabulary carrying both an ordered and an
  unordered collection, and concepts carrying alternative and hidden labels, so that every part of
  this page can be looked at rather than described.
- **FR-019**: The unattended check that already installs, seeds and serves the demonstration MUST
  additionally open a vocabulary's page and run a search inside it, failing if either does not work.
- **FR-020**: Beside the list of concepts, the page MUST show the vocabulary's identifier, its
  default language, how many concepts it holds, and, where its concepts form a hierarchy, the
  concepts with no broader concept, named as the list names them.

### Requirement → story

| Story | Requirements |
|---|---|
| US-1 — Open a vocabulary and know what it is | FR-001, FR-002, FR-003, FR-004, FR-005, FR-013, FR-017, FR-020 |
| US-2 — See every term the vocabulary holds | FR-006, FR-007, FR-010, FR-011, FR-012, FR-014, FR-016, FR-020 |
| US-3 — Find a term inside the vocabulary | FR-008, FR-009, FR-014, FR-016, FR-018, FR-019 |
| US-4 — See the groupings a curator made | FR-011, FR-015, FR-018 |

FR-018 lands across the two stories whose subject it makes visible — labels a search can match for
US-3, an ordered and an unordered collection for US-4. FR-019 lands with US-3, the last of the two
list stories, so that one extension of the unattended walk covers both.

### Key Entities

- **ConceptScheme (vocabulary)**: the record the page is about. Contributes its name, its
  description, its identifier, and whether that identifier was fixed by a publisher elsewhere.
- **Concept**: what the page lists. Named by its labels, linked to its own page, and described by its
  definition, its broader concept and the collections holding it.
- **ConceptLabel**: the alternative and hidden labels a search matches on, and the per-language
  preferred labels that decide what a visitor sees a concept called.
- **Collection**: named beside the list and on the entries of the concepts it holds, with its member
  count, marked as ordered or not, and linked to its own page.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person handed only a vocabulary's identifier can open it and say what the vocabulary
  covers and whether this site authored it.
- **SC-002**: A person can read every term a vocabulary holds from its page, without knowing any of
  their names in advance and without following anything.
- **SC-003**: A person who knows a term by a name that is not its preferred one finds it in a single
  search of the vocabulary.
- **SC-004**: The address of a narrowed list, opened fresh, produces the same concepts in the same
  order.
- **SC-005**: The number of database queries the page runs does not grow with the number of concepts
  it shows.
- **SC-006**: Every string the page shows a reader can be translated, and none is fixed in one
  language.
- **SC-007**: A person with a fresh clone can look at a populated vocabulary page and search inside
  it within the same documented commands that already serve the list of vocabularies, and the same
  walk runs unattended on every proposed change.

## Assumptions

- A vocabulary holds hundreds of concepts rather than tens of thousands. Keeping the page fast at a
  scale beyond that is R7, not this feature.
- How concepts relate to one another is shown in full on a concept's own page, which is #142's. This
  page reads the broader/narrower relations only to name a concept's broader concept and the
  vocabulary's top concepts.
- A named publisher is a genuine future need and not a gap this feature leaves by accident. It will
  be derived from a record or required on the data model when the maintainer decides which; until
  then provenance is the only claim the page makes about where a vocabulary came from.
- A concept's notation cannot be searched because nothing stores one. The ubiquitous language
  defines it, no field holds it, and adding one is a change to what the package records rather than
  to how it is browsed.
- Whether a vocabulary was published elsewhere is read from its identifier having been fixed by a
  publisher, which is the only signal the data carries. A vocabulary published from this site (R4)
  will also carry a fixed identifier, and distinguishing those two cases is R4's to settle.
- Rendering a vocabulary's identifier as a link is provisional, adopted because a linked-data record
  presented without its link makes little sense, and expected to be revisited once it has been seen
  working.
- A visitor's browser may not run JavaScript. Nothing on this page depends on it.
- Access control across the browsing interface remains a later decision, and this feature does not
  prejudge it. Showing the source only to someone who can change vocabularies decides what a reader
  sees, not whether they may read the page.
