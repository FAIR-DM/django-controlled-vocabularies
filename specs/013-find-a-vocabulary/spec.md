# Feature Specification: Find a vocabulary

**Feature Branch**: `013-find-a-vocabulary`

**Created**: 2026-08-19

**Status**: Draft

**Input**: Issue [#140](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/140) — "Nothing on a site running this package tells a visitor which vocabularies it holds. A person who has not been handed a URL has no way in, and an administrator cannot check what was imported without opening a database shell. This gives the package a front door: a page listing every vocabulary held here, local and imported alike, that can be searched and filtered when the list grows past a screenful."

**Serves**: G7 (vocabulary browsing) · **Roadmap**: R6 · **Issue**: #140

> Scope note: this is the first of three slices of roadmap item R6, and the only one with no dependency of its own — [#141](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/141) (a vocabulary's own page) and [#142](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/142) (a page per record) follow it in that order. It owns **one page: a list of every vocabulary the site holds**, what each entry tells a reader, a search that narrows that list, and facets that narrow it by publisher, licence and language. **Out of scope:** opening a vocabulary and everything inside one, which is #141; a page for a concept, collection or ordered collection, which is #142; searching for a concept without knowing which vocabulary holds it, which no roadmap item currently covers; any access rule of the package's own; keeping the page fast at a scale the project has not yet met, which is R7; and publication and deprecation, which are R4.

## Clarifications

### Session 2026-08-19 (intake)

Four decisions were taken with the maintainer at intake, because each decides what the feature is rather than how it is built.

- **Q: Does the search box search the list of vocabularies, or does it search concepts across them?** → A: The list of vocabularies only. A person who knows the term but not which vocabulary holds it is not served by this feature. That is a genuine gap against the goal this feature serves, which names searching concepts across vocabularies, and no roadmap item currently fills it — recorded here, and raised at the spec gate, rather than widened into this page. Integrated into FR-006 and User Story 2.
- **Q: What can the list be filtered by?** → A: The publication details a vocabulary carries: its publisher, its licence and its language. Search stays the primary way in. The facets became worth having once vocabularies kept their publication details on import (#207), because a site holding several vocabularies from one publisher needs a way to see that set. Integrated into User Story 4 and FR-019 to FR-022.
- **Q: What does an entry tell a reader?** → A: Its publisher where it names one, its name, its description, how many concepts and collections it holds, when it was last updated, and its identifier. An entry is laid out as a concept is on a vocabulary's page, with the publisher above the name where the broader concept sits. Whether a vocabulary was imported is not shown on the entry. The languages a vocabulary carries were considered and deliberately left out: it is the most expensive thing to work out per entry and the least often needed. Integrated into FR-002 and FR-003.
- **Q: Who can see the page?** → A: Anyone who reaches it. The package carries no access rule of its own here, exactly as its concept search endpoint carries none (ADR 0008), and a project that needs the page restricted restricts it where it mounts the package's routes. The consequence was named and accepted: a vocabulary has no draft state, so one is visible from the moment it exists. Access control for the browsing interface is a later question, not this feature's. Integrated into FR-005 and Assumptions.

### Session 2026-08-19 (coverage scan)

Five further ambiguities surfaced by the structured coverage scan over the drafted specification, resolved here against the intake decisions, the shipped models, `CONTEXT.md` and the constitution.

- **Q: Is a vocabulary's name a link to the vocabulary?** → A: Yes, to the vocabulary's own page, which #141 serves. #141 depends on this feature rather than the other way round, and turned the name into a link in the same change that gave it somewhere to lead. Integrated into FR-013.
- **Q: In what order does the list appear?** → A: Alphabetically by name, case-insensitively, and the order does not change between requests. The alternatives — most recently imported first, largest first — each encode a guess about why a person came to the page, and alphabetical is the order a reader can predict well enough to scan. Integrated into FR-004.
- **Q: What happens when the list is longer than a page?** → A: It is paginated at a fixed size, and a search applies to every vocabulary the site holds rather than to the page being viewed. A search that only looked at the current page would be silently wrong exactly when the page is long enough to need one. Integrated into FR-008 and FR-010.
- **Q: Does the concept count include collections, and does it exclude anything?** → A: Concepts only, and nothing is excluded. Collections group concepts and are not concepts; counting them would overstate the size of a vocabulary. Nothing is excluded because there is nothing yet to exclude — the concept lifecycle that would make a deprecated concept a candidate for exclusion is not built (R4), so the count is simply how many concepts the vocabulary holds. Integrated into FR-002.
- **Q: What does a reader see when there is nothing to show?** → A: Two distinct messages, never the same one. An empty database says the site holds no vocabularies, which tells an administrator that an import has not run. A search matching nothing says so, repeats what was searched for, and offers the way back to the full list. Collapsing the two would tell someone whose search missed that the site is empty. Integrated into FR-009 and FR-011.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See every vocabulary the site holds (Priority: P1)

A person arrives at the site without having been handed a URL for anything. One page names every vocabulary held here, and tells them enough about each one — what it covers, how big it is, who published it — to know which one they want. An administrator who has just run an import opens the same page to confirm what landed.

**Why this priority**: This is the feature. Until this page exists, the only way to learn what a site holds is a database shell, and the package's entire browsing interface has nowhere to start from.

**Independent Test**: Load the page on a site holding several vocabularies, some naming a publisher and some not, and confirm every one of them appears exactly once, each showing its name, its description, how many concepts it holds, and its identifier.

**Acceptance Scenarios**:

1. **Given** a site holding several vocabularies, **When** the page is requested, **Then** every vocabulary appears, and none appears twice.
2. **Given** a vocabulary created on this site without an identifier, **When** its entry is read, **Then** the identifier composed for it is shown.
3. **Given** an imported vocabulary, **When** its entry is read, **Then** the identifier its publisher assigned it is shown, and its publisher is named where the vocabulary gives one.
4. **Given** any vocabulary, **When** its entry is read, **Then** it shows the vocabulary's name, its description, and how many concepts it holds.
5. **Given** a vocabulary holding no concepts, **When** its entry is read, **Then** it still appears, and its count reads as none rather than being left blank.
6. **Given** several vocabularies, **When** the page is requested twice, **Then** they appear in the same alphabetical order both times.
7. **Given** a site holding no vocabularies at all, **When** the page is requested, **Then** it loads and says the site holds none.
8. **Given** a vocabulary holding collections and giving the date it was last modified, **When** its entry is read, **Then** it shows how many collections it holds and that date. A vocabulary holding none, or giving no date, says nothing about either.

---

### User Story 2 - Narrow the list to the one you are after (Priority: P2)

A person looking at a site holding more vocabularies than fit on a screen types a word they associate with the one they want — part of its name, or something it covers — and the list narrows to the vocabularies matching it. They can send the narrowed list to a colleague as a link, and get back to everything from there.

**Why this priority**: The list alone is a complete front door for a site holding a handful of vocabularies, which is every site today. Search is what keeps it usable as sites grow, and the maintainer expects it to become the primary way in — but it is only worth anything once User Story 1 exists.

**Independent Test**: On a site holding vocabularies whose names and descriptions differ, search for a word appearing in one name and confirm only matching vocabularies remain; search for a word appearing only in one description and confirm the same; then confirm the resulting address, opened fresh, returns that same narrowed list.

**Acceptance Scenarios**:

1. **Given** several vocabularies, **When** a word from one vocabulary's name is searched for, **Then** that vocabulary remains and the ones not matching are gone.
2. **Given** a vocabulary whose name does not contain the searched word but whose description does, **When** that word is searched for, **Then** the vocabulary is among the results.
3. **Given** a search in one letter case, **When** the matching text is in another, **Then** it still matches.
4. **Given** a search matching nothing, **When** the results are shown, **Then** the page says nothing matched, repeats what was searched for, and offers the way back to the full list.
5. **Given** a narrowed list, **When** its address is opened in a new session, **Then** the same search is applied and the same vocabularies are shown.
6. **Given** more vocabularies than fit on one page, **When** a search is run from the second page of results, **Then** it is applied to every vocabulary the site holds and not only to the page being viewed.
7. **Given** an entry matching the search, **When** it is read, **Then** it shows everything it shows on the unsearched list.

---

### User Story 3 - Run the page and look at it (Priority: P1)

Someone with a fresh clone of the repository — the maintainer at a review, a contributor deciding
whether the package suits them — installs it, runs three commands, and has a browser open on a
populated vocabulary list. They did not write a settings module, wire up seven applications, or
find their own SKOS file first. They can search it and page through it.

**Why this priority**: P1 alongside the list itself. The page's own value is unverifiable without
it, and every later slice of the browsing interface — a vocabulary's own page, a record's page —
inherits the same running site the moment it exists.

**Independent Test**: from a clean checkout, follow the documented commands and confirm the list is
served and populated at the documented address. Confirm the same walk runs unattended, so the demo
cannot rot silently.

**Acceptance Scenarios**:

1. **Given** a fresh clone with dependencies installed, **When** the documented commands are run in
   order, **Then** a server is running and its documented address serves the vocabulary list with
   vocabularies on it.
2. **Given** the seeded demo, **When** the list is read, **Then** it holds both a vocabulary
   imported from a publisher and one created by the seed command, so the difference between the
   two entries is visible rather than described.
3. **Given** a seeded demo in any state, **When** the seed command is run again, **Then** the demo
   returns to the same state, whatever was added or removed before.
4. **Given** the demo, **When** its root address is opened, **Then** it leads to the list rather
   than to a missing page.
5. **Given** a change to the package or the demo, **When** it is proposed, **Then** an unattended
   check installs the demo, seeds it, serves it and reads the list back, and fails if any step
   does not work.

---

### User Story 4 - Narrow the list by publisher, licence or language (Priority: P3)

A researcher on a site holding dozens of vocabularies wants the ones a particular publisher maintains, or only the ones they may reuse under an open licence, or only the ones written in their language. Beside the list they tick the publisher, licence or language they are after, and the list narrows to the vocabularies carrying it. Each option says how many vocabularies it would leave, so they can see before ticking it whether it is worth doing.

They can also put the largest vocabularies first, or the most recently updated.

**Why this priority**: Search finds a vocabulary by a word it uses. It cannot find the set a publisher maintains, or the set under a given licence, because those words are not in the name or the description.

**Independent Test**: On a site holding vocabularies from several publishers under several licences, tick one publisher and confirm only its vocabularies remain and every other option's count follows; then sort by size and by last update.

**Acceptance Scenarios**:

1. **Given** vocabularies from several publishers, **When** one publisher is chosen, **Then** only its vocabularies remain.
2. **Given** two publishers chosen, **When** the list is read, **Then** the vocabularies of either remain.
3. **Given** vocabularies with different default languages, **When** a language is chosen, **Then** only the vocabularies whose default language it is remain.
4. **Given** a licence the package recognises, such as a Creative Commons licence given by its address, **When** its option is read, **Then** it is named by its short name.
5. **Given** a search or another facet in force, **When** a facet's options are read, **Then** each counts the vocabularies it would leave among those the search and the other facets leave, and not counting the facet's own choice.
6. **Given** every vocabulary sharing one publisher, or none naming one, **When** the page is read, **Then** no publisher facet is offered, because it could not narrow anything. The same holds for licence and language.
7. **Given** the sort by most concepts, **When** the list is read, **Then** the largest vocabulary comes first. **Given** the sort by most recently updated, **Then** the newest comes first and vocabularies giving no date come last.

---

### Edge Cases

- A vocabulary with no description at all — the entry still shows the rest, and the missing description leaves no stray punctuation or empty label behind.
- A description running to several paragraphs — the entry stays scannable rather than pushing every other vocabulary off the screen.
- A search string containing characters with a meaning in a query — `%`, `_`, a quote — is treated as text to look for, not as an instruction.
- A search string in a non-Latin script, and a search that differs from the text only by letter case in such a script — the second of these depends on the database, and what each one does is pinned by test and stated in the package's own documentation (FR-006).
- An imported vocabulary whose publisher identifier is not a web address — it is shown as given, not turned into a link that leads nowhere.
- A vocabulary name long enough to break the layout.
- No entry links to the vocabulary it names — until #141 serves a vocabulary's own address, a link would lead to a missing page.
- The page is requested by someone not signed in, on a site where nothing else is public.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST provide one page that lists every vocabulary the site holds, whether imported or created in code, with each appearing exactly once.
- **FR-002**: Each entry MUST show the vocabulary's name, its description, and how many concepts it holds — counting concepts only, excluding none, and reading as none rather than blank when there are no concepts.
- **FR-003**: Each entry MUST show the vocabulary's identifier, which is its publisher's for an imported one, and MUST name its publisher, show how many collections it holds and when it was last modified, each only where the vocabulary has one.
- **FR-004**: The list MUST appear in a stable alphabetical order by name that does not depend on letter case.
- **FR-005**: The page MUST carry no access rule of its own: every vocabulary the site holds is shown to whoever requests the page, leaving any restriction to the project mounting the package's routes.
- **FR-006**: A visitor MUST be able to narrow the list by searching text appearing in a vocabulary's name or its description, matching regardless of letter case, and treating the search string as text rather than as query syntax. Letter case is ignored for ASCII letters on every database. For letters outside ASCII it is ignored on PostgreSQL and is not ignored on SQLite, whose `LIKE` folds ASCII only. The limitation sits below the application — no query the ORM can express repairs it — so it MUST be disclosed to a reader of the package rather than left to be discovered.
- **FR-007**: A search MUST be carried in the page's own address, so that a narrowed list can be linked to, bookmarked and returned to.
- **FR-008**: A search MUST be applied to every vocabulary the site holds before the results are divided into pages, never to one page of them.
- **FR-009**: A search matching nothing MUST say so, repeat what was searched for, and offer a way back to the full list.
- **FR-010**: The list MUST be divided into pages of a fixed size, and MUST be navigable from one page to the next with any search in force preserved.
- **FR-011**: A site holding no vocabularies MUST get a page saying so, in wording distinct from a search that matched nothing.
- **FR-012**: The page MUST be reachable by a name the package owns rather than a fixed path, so a project chooses the address it is mounted at.
- **FR-013**: Each entry MUST link to the vocabulary's own page.
- **FR-014**: The repository MUST carry a runnable demonstration project that serves this page, configured the way the package's own documentation tells a project to configure it.
- **FR-015**: The demonstration MUST be reachable in three documented commands from a fresh clone with dependencies installed — build the database, load content, serve it — and its root address MUST lead to the list rather than to a missing page.
- **FR-016**: The demonstration's content MUST include both a vocabulary imported from a file that declares its own and one the seed command creates for a file that declares none, and loading it MUST be repeatable: running the command again returns the demonstration to the same state from any prior state.
- **FR-017**: The demonstration MUST be checked without a person: an unattended run installs it, loads its content, serves it, and reads the list back, failing if any step does not work.
- **FR-018**: The demonstration MUST be recognisable as one — a local database, an obviously throwaway secret, and documentation saying plainly that it is not a production configuration.

- **FR-019**: A visitor MUST be able to narrow the list by publisher, by licence and by language, choosing several options of one facet to keep the vocabularies matching any of them, and combining facets with each other and with the search.
- **FR-020**: A vocabulary's language MUST be its default language, which every vocabulary has.
- **FR-021**: Each facet option MUST show how many vocabularies it would leave among those the search and the other facets leave. A facet with fewer than two options MUST NOT be offered.
- **FR-022**: Facet choices MUST be carried in the page's address alongside the search and the sort, as FR-007 requires of the search.

### Key Entities

- **ConceptScheme (vocabulary)**: the record being listed. Contributes its name, its description, its identifier, and its publisher, licence, default language and last-modified date, each read from its document.
- **Concept**: not listed, and reached only as a count per vocabulary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person given only the site's address can name every vocabulary it holds, from one page, without being handed a URL and without a database shell.
- **SC-002**: An administrator can tell, from this page alone, which vocabularies name a publisher, and how many concepts each holds.
- **SC-003**: A person looking for a vocabulary by one word from its name or description reaches it in a single search, from any page of the list.
- **SC-004**: The address of a narrowed list, opened fresh, produces the same vocabularies in the same order.
- **SC-005**: The number of database queries the page runs does not grow with the number of vocabularies it shows.
- **SC-006**: Every string the page shows a reader can be translated, and none is fixed in one language.
- **SC-007**: A person who has never seen this repository can look at the working page within three commands of a fresh clone, and the same walk runs unattended on every proposed change.

## Assumptions

- A site holds tens of vocabularies rather than thousands. Keeping the page fast at a scale beyond that is R7, not this feature.
- A vocabulary being visible to everyone is acceptable at this stage. Access control across the browsing interface is a later decision, and this feature does not prejudge it.
- A visitor's browser may not run JavaScript. Nothing on this page depends on it.
