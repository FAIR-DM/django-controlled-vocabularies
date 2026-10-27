# Feature Specification: Serve a vocabulary or record as RDF from its page

**Feature Branch**: `018-serve-rdf-representations`

**Created**: 2026-10-27

**Status**: Draft

**Input**: Issue [#231](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/231) — "A vocabulary's page and a record's page show what they hold to a person, and nothing serves the same content to software. Each should also answer with RDF: a `?format=` parameter on the page's address returns it as a file in any serialization rdflib can write, and a linked-data client asking for an RDF type through the `Accept` header gets that serialization at the same address. The RDF covers only what the page is about, the vocabulary's own statements or the record's own statements, describes it by its original identifier, and keeps every statement in every language. A browser keeps getting the page it gets now, and a format nobody can serve is refused rather than answered with HTML. Every vocabulary the site displays offers this, whether it was imported or authored here."

**Serves**: G3 (standards-compliant publishing) · **Roadmap**: R4 · **Issue**: #231

> Scope note: this is the first slice of roadmap item R4. It owns **the RDF a vocabulary's page or
> a record's page returns when asked for it**, by a `?format=` parameter or by content negotiation,
> at the addresses those pages already have. FS-015 left this out of the record pages on purpose,
> as belonging with export rather than with browsing.
> **Out of scope:** a whole vocabulary in one file, with its concepts and collections, which is the
> export that re-imports cleanly and a later feature; publishing a vocabulary as a deliberate
> release that freezes its identifiers, and deprecation, which stay in R4; statements other records
> make about this one, such as the narrower concepts a concept's page lists or the collections that
> gather it; the vocabulary list page; the concept search endpoint; any access rule of the
> package's own; and keeping these responses fast at a scale the project has not yet met, which is
> R7.

## Clarifications

### Session 2026-10-27 (intake)

Three decisions were taken with the maintainer at intake.

- **Q: Which serializations are offered?** → A: Every serialization the installed rdflib can write a graph in. The list follows rdflib rather than a list this package maintains, so a format rdflib adds reaches the site without a change here. Integrated into FR-002.
- **Q: Does a vocabulary's representation include its concepts and collections?** → A: Not in this feature. A vocabulary's representation is the vocabulary's own statements only, the same rule as a record's. The whole vocabulary in one file is the export, and it is a later feature. Integrated into FR-003 and the scope note.
- **Q: Which vocabularies offer it?** → A: Every vocabulary the site displays, imported or authored here. The RDF describes each subject by its original identifier, including when that identifier is an address on its publisher's site rather than this one. Integrated into FR-001 and FR-004.

### Session 2026-10-27 (drafting)

Ambiguities the intake decisions left open, resolved while drafting against the shipped models,
`CONTEXT.md` and the constitution.

- **Q: A concept's page lists its narrower concepts and the collections that gather it, which are statements other records make. Does its RDF include them?** → A: No. The representation is the record's own document, exactly as published, and nothing inferred or gathered from elsewhere. Adding the inverse statements would put statements in the output that the publisher never made, and a later re-import of that output would store them as though they had. Integrated into FR-003.
- **Q: Hidden labels are kept off the record pages. Are they in the RDF?** → A: Yes. They are kept out of sight on a page because a person should not read them, and they exist precisely for software to match on. The representation carries every statement in the document. Integrated into FR-003.
- **Q: The page shows one language. Which languages does the RDF carry?** → A: Every language each value was recorded in, whatever language the site is being read in. Integrated into FR-003.
- **Q: What does a client get when its `Accept` header names only types the site cannot produce?** → A: A refusal saying the type is not available, never the HTML page. A client that names an RDF type is software that will try to parse the answer, and HTML handed to an RDF parser fails somewhere far from the cause. A header that accepts anything (`*/*`), as every browser's does, still gets the page. Integrated into FR-006 and FR-007.
- **Q: An unknown `?format=` value?** → A: Refused with a message naming the formats that are available. The parameter is typed by a person, so the answer should tell them what to type instead. Integrated into FR-007.
- **Q: How does software find out that a page has RDF behind it?** → A: The page names its RDF alternatives in its document head, the conventional way for a crawler or linked-data tool to discover them. It names the four serializations the import reads (Turtle, RDF/XML, JSON-LD and N-Triples), not all of them. They are the ones a consumer is most likely to want, and the rest stay reachable by name. Integrated into FR-010.
- **Q: A record whose document embeds a blank node, such as a structured note: what does it look like in the RDF?** → A: As a blank node carrying the same statements. The document keeps an embedded node because a blank node has no identifier that survives storage, so it comes out as a new blank node with the same content. Integrated into FR-003 and Edge Cases.

### Session 2026-10-27 (design review)

- **Q: rdflib's `pretty-xml` writer adds statements to a graph holding an RDF list, in some processes and not others. Is it offered?** → A: No. An ordered collection's member list is an RDF list, so it would serve statements the record does not hold, against FR-003 and FR-012. The plain RDF/XML writer produces the same syntax faithfully and stays offered. Integrated into FR-002.

### Session 2026-10-27 (walkthrough)

- **Q: A concept's page shows the vocabulary that holds it, from the record's own link to it, even when the stored statements do not name it. Does the RDF name it too?** → A: Yes. A record whose document states no `skos:inScheme` has its own vocabulary stated, as its class is stated when the document gives none. A document that states one keeps exactly what it states. Integrated into FR-003.

- **Q: A person can reach `?format=` only by typing it. Should the page offer the formats itself?** → A: Yes. Each vocabulary page and record page has a download menu offering Turtle, RDF/XML, JSON-LD and N-Triples, the same four its head names, each downloading the file. Integrated into User Story 2 and FR-015.

### Session 2026-10-27 (coverage scan)

Ambiguities surfaced by the structured coverage scan over the drafted specification. The scan found
the actors, the scope, the domain model and the glossary covered. These four were not.

- **Q: A cache between the site and its readers could store the Turtle answer and hand it to a browser.** → A: Every response at these addresses, the HTML page included, states that it varies with the `Accept` header. Integrated into FR-008.
- **Q: Some serializations rdflib registers cannot write a plain graph. Which ones are offered?** → A: Those that can describe one graph. A format whose output is a change between two graphs, rather than a graph, is not a representation of anything and is not offered. A format that writes a named set of graphs is offered when the one graph can be written as such a set. Which formats fall where is settled when the feature is planned, against the rdflib version the package supports. Integrated into FR-002 and Assumptions.
- **Q: What is a downloaded file called?** → A: The subject's slug with the format's usual file extension, so a downloaded concept and its vocabulary do not overwrite each other in the same folder. A record's file is named by its own slug, and the vocabulary slug is not added to it. Integrated into FR-009.
- **Q: An address naming no vocabulary or no record, asked for RDF?** → A: Not found, the same as for the page, whatever format is asked for. The refusal of an unknown format applies only to an address that names something. Integrated into FR-011.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A developer's software fetches RDF from a record's identifier (Priority: P1)

A developer whose software holds the identifier of a concept served here, stored in their own
database or taken from another dataset, dereferences it with an `Accept` header asking for an RDF
serialization. They get the concept's statements in that serialization at the same address a
person would open as a page, so their software can read the concept's labels, definition and links
without scraping HTML. The same works for a collection, an ordered collection and a vocabulary.

**Why this priority**: It is the feature. A vocabulary published as linked data promises that its
identifiers answer software as well as people, and G3 asks for exactly that: valid SKOS at stable
identifiers, with content negotiation.

**Independent Test**: Request a concept's address with `Accept: text/turtle`, parse the answer, and
confirm it holds exactly the statements stored for that concept. Request the same address as a
browser does and confirm the page is unchanged.

**Acceptance Scenarios**:

1. **Given** a concept with labels in two languages, a definition and a broader concept, **When** a
   client requests its address with an `Accept` header asking for Turtle, **Then** the response is
   Turtle describing the concept by its identifier, holding every one of those statements in every
   language.
2. **Given** a vocabulary held here, **When** a client requests the vocabulary's address asking for
   JSON-LD, **Then** the response describes the vocabulary by its identifier with its own
   statements, and with no statement about any concept or collection it holds.
3. **Given** an ordered collection, **When** a client requests its address asking for RDF, **Then**
   its members come back as a list in the publisher's sequence.
4. **Given** a concept whose page lists narrower concepts that other concepts point at, **When** a
   client requests its RDF, **Then** the response holds no statement the concept's own document
   does not.
5. **Given** a concept carrying hidden labels, **When** a client requests its RDF, **Then** the
   hidden labels are in it.
6. **Given** any record's or vocabulary's address, **When** a browser requests it with the header
   it normally sends, **Then** it gets the HTML page it gets today.
7. **Given** a client whose `Accept` header names only types the site cannot produce, **When** it
   requests a record's address, **Then** it is refused as not acceptable and is not given the HTML
   page.
8. **Given** a record's page, **When** software reads the page's document head, **Then** it finds
   the RDF alternatives for that record, each with its media type.
9. **Given** a vocabulary imported from a publisher whose identifiers are addresses on their own
   site, **When** a client requests one of its concepts here asking for RDF, **Then** the response
   describes the concept by the publisher's identifier.

---

### User Story 2 - A user downloads a vocabulary or record as an RDF file (Priority: P2)

A user reading a vocabulary's page or a record's page wants the same thing as a file, to open in an
RDF tool, attach to a paper or hand to a colleague. They add `?format=` with the name of a
serialization to the address in their browser and the browser saves a file in that serialization,
named after what it describes.

**Why this priority**: It reaches the same statements as User Story 1 by a means a person can type
in a browser's address bar, which cannot set an `Accept` header. It ranks below it because the
software path is what makes the identifiers linked data.

**Independent Test**: Open a concept's address with `?format=ttl` and confirm a Turtle file is
downloaded, named after the concept, holding the concept's statements. Open it with an unknown
format and confirm the refusal lists the formats that are available.

**Acceptance Scenarios**:

1. **Given** a concept's page, **When** a user opens its address with `?format=` naming Turtle,
   **Then** the browser downloads a Turtle file named with the concept's slug and the Turtle
   extension, holding the concept's statements.
2. **Given** a vocabulary's page, **When** a user opens its address with `?format=` naming any
   serialization rdflib can write a graph in, **Then** they get the vocabulary's own statements in
   that serialization.
3. **Given** a request carrying both `?format=` and an `Accept` header that asks for something
   else, **When** it reaches a record's address, **Then** the format named by the parameter is
   returned.
4. **Given** a record's address, **When** a user opens it with `?format=` naming a format that does
   not exist, **Then** the request is refused with a message naming the formats that do, and no
   HTML page is returned.
5. **Given** an address naming no record, **When** a user opens it with `?format=` naming Turtle,
   **Then** it is reported as not found.
6. **Given** a vocabulary's, concept's or collection's page, **When** a user opens its download
   menu, **Then** it offers Turtle, RDF/XML, JSON-LD and N-Triples, and choosing one downloads the
   subject's statements in that format.

---

### Edge Cases

- **A document holding an embedded node** (a blank node in the published file): the RDF carries a
  blank node with the same statements.
- **A document key stored as a full URI rather than a CURIE**: the statement comes out under that
  full URI.
- **A literal carrying a datatype** (a date, a number): the datatype is kept. A plain literal with
  no language and no datatype stays plain.
- **A record whose identifier is not a web address** (a `urn:`): the RDF describes it by that
  identifier unchanged.
- **A vocabulary carrying no statements beyond its type**: the response is valid RDF holding that
  one statement, not an error and not an empty body.
- **An `Accept` header that ranks HTML and an RDF type equally**: the page is returned, so a browser
  that also lists an RDF type never gets a file it did not ask for.
- **A `HEAD` request asking for RDF**: answered with the same status and headers as the
  corresponding `GET`, with no body.
- **A record served at the address of the wrong type** (a collection's slug at a concept's address):
  not found, as the page already is, whatever format is asked for.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A vocabulary's page and every record's page (concept, collection and ordered
  collection) MUST answer a request for RDF at the address the page is already served at. Every
  vocabulary the site displays MUST offer it, whether it was imported or authored here.
- **FR-002**: The serializations offered MUST be every one the installed rdflib can write a single
  graph in, reachable by rdflib's name for it through `?format=` and by its media type through
  `Accept`. A serialization whose output describes a change between graphs rather than a graph, or
  whose output does not read back to exactly the graph's statements, MUST NOT be offered.
- **FR-003**: The RDF MUST hold exactly the statements in the subject's stored document and nothing
  else: every statement, in every language, with its datatype, including hidden labels, an ordered
  collection's member list in sequence, and embedded nodes as blank nodes. It MUST NOT add
  statements other records make about the subject, inverse statements, labels of records it links
  to, or, for a vocabulary, the concepts and collections it holds. The row's class, and a
  record's vocabulary, are stated from the row when its document states none.
- **FR-004**: The RDF MUST describe its subject by the subject's own identifier, unchanged, whether
  or not that identifier is an address on this site.
- **FR-005**: When a request carries `?format=`, the format it names MUST be returned, whatever the
  `Accept` header asks for.
- **FR-006**: Without `?format=`, the response MUST be chosen from the `Accept` header by the
  client's stated preference: an RDF serialization when the client ranks one above HTML, and the
  HTML page otherwise, including for a header that accepts anything and for a request with no
  `Accept` header.
- **FR-007**: A request the site cannot answer in the format asked for MUST be refused and MUST NOT
  be answered with the HTML page: an unknown `?format=` value as a bad request with a message naming
  the available formats, and an `Accept` header naming only types the site cannot produce as not
  acceptable. The messages MUST be translatable.
- **FR-008**: Every response at these addresses, the HTML page included, MUST state that it varies
  with the `Accept` header.
- **FR-009**: A response to `?format=` MUST be offered as a download named with the subject's slug
  and the format's usual file extension. A response chosen through `Accept` MUST be served for the
  client to read in place. Every RDF response MUST carry the serialization's media type.
- **FR-010**: Each vocabulary page and record page MUST name, in its document head, its RDF
  alternatives in Turtle, RDF/XML, JSON-LD and N-Triples, each with its media type and an address
  that returns it.
- **FR-011**: An address naming no vocabulary, or no record of the type its shape names, MUST be
  reported as not found whatever format is asked for.
- **FR-012**: Reading any RDF response back into a graph MUST yield the same statements as the
  subject's stored document, blank nodes compared by structure.
- **FR-013**: The HTML pages, their addresses, the vocabulary list page and the concept search
  endpoint MUST behave as they do today for every request that does not ask for RDF.
- **FR-014**: The RDF responses MUST be subject to exactly the access the HTML page is subject to,
  with no access rule of the package's own.

- **FR-015**: Each vocabulary page and record page MUST offer a download menu with the same four
  serializations FR-010 names, each downloading the subject as FR-009 describes.

### Key Entities

- **Representation**: one serialization of a vocabulary's or a record's own statements, returned at
  the address of its page when a request asks for it through `?format=` or `Accept`. Built from the
  stored document, never stored itself.
- **ConceptScheme** and **Record**: unchanged. Their documents are the only source of the
  statements a representation carries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every vocabulary and record in the demo data, and for every serialization
  offered, the response parses back into a graph holding the same statements as the stored
  document.
- **SC-002**: A request sent with a browser's default `Accept` header returns the same HTML page as
  before the feature, at every vocabulary and record address.
- **SC-003**: For a record whose identifier is its address on this site, a client that knows
  nothing but that identifier gets the record's RDF in one request, with no prior request to
  discover where it lives.
- **SC-004**: No request that asks for RDF, by parameter or by header, is ever answered with an HTML
  page and a success status.
- **SC-005**: A user who mistypes a format learns which formats exist from the refusal alone.

## Assumptions

- The package already keeps every statement it imports in each row's document, so a representation
  needs nothing stored that is not stored today (Article XI).
- Statements come out as they are stored. A normalisation the import applied and surfaced, such as a
  description stored under the definition predicate, comes out in its stored form.
- The four serializations named in FR-010 are the ones the import reads. Which other formats
  rdflib can write a single graph in, against the rdflib version the package supports, is settled
  at planning.
- The package keeps no status of its own for a record. A concept its publisher marked deprecated
  carries that statement in its document and in its RDF. A lifecycle of the package's own belongs
  to publication, later in R4.
- A vocabulary's representation stays small, because it holds only the vocabulary's own
  statements. Serving a whole vocabulary at scale is the later export feature's concern, and R7's.
