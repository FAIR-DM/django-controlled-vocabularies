# Tasks: Serve a vocabulary or record as RDF from its page

**Feature**: `018-serve-rdf-representations` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

Every task is test-first per Article I: the test is written and seen to fail before the production
change that makes it pass. Test scope per task is one class or one file; the full suite runs once per
group, at its report.

**Nothing in this feature adds a model field, a migration, a setting or a URL.** A task that finds
itself editing `migrations/` or `urls.py` has gone wrong.

**A test never asserts wording or appearance** (`docs/contributing/standards/testing.md` §1). The
refusal messages are asserted to name the formats, never to read a given sentence.

---

## Foundational — the graph and the serialization table (core)

### Group 1

#### T001 — A document becomes a graph

**Files**: `controlled_vocabularies/exchange/graph.py` (new), `tests/test_exchange/test_graph.py` (new)

`document_graph(uri, document, rdf_class)` as plan.md §1. Tests, each a small hand-written document
compared with `rdflib.compare.isomorphic` against the graph it must give:

- a link, a language-tagged literal, a typed literal (`xsd:date` stored as a CURIE), a plain
  literal, a JSON integer and a JSON boolean;
- a key stored as a full URI rather than a CURIE;
- an embedded node, and an embedded node inside an embedded node;
- `skos:memberList` as one RDF list in stored order (read back with `Collection`, compare the
  sequence), and no `skos:memberList` triple per member;
- `rdf:type` added from `rdf_class` when the document states none, and not added when it does
  (an imported record whose document states `skos:Concept` keeps exactly that one type triple);
- a `urn:` identifier as the subject, unchanged;
- an empty document gives exactly the one type triple.

Plus the round trip the importer guarantees: import a fixture under `tests/fixtures/skos/` whose
rows all state `rdf:type` (such as `rocks.ttl`, not a fixture relying on implied types, which
would gain the D1 type triple by design) with the existing importer, and for every row the importer stored, the graph built from its document is
isomorphic to the subgraph of the parsed fixture about that subject (its triples, with blank-node
objects followed). That is FR-012 at the source.

#### T002 — A row hands back its graph

**Files**: `controlled_vocabularies/models.py`, `tests/test_models.py`, `docs/importing.md`

`Resource.to_graph()`, `ConceptScheme.rdf_class = "skos:ConceptScheme"`, and `Record.rdf_class` as a
property returning `self.type` (plan.md §1). Tests: a vocabulary authored with no `rdf:type` in its
document gives a `skos:ConceptScheme` type triple; an ordered collection's graph carries its
`skos:OrderedCollection` type; the graph's subject is the row's `uri`.

Docs: a short section in `docs/importing.md`, after the import, showing `scheme.to_graph()` and
`record.to_graph()` serialized to Turtle, and saying what the graph holds (the row's own statements
and nothing gathered from other rows).

#### T003 — The serializations rdflib can write

**Files**: `controlled_vocabularies/exchange/serializations.py` (new),
`tests/test_exchange/test_serializations.py` (new)

As plan.md §2. Tests:

- `patch` and `pretty-xml` are not offered; Turtle, RDF/XML, JSON-LD and N-Triples are, by their short names and
  by their media types;
- every offered serialization writes a graph holding a language-tagged literal, a plain literal,
  a blank node and an RDF list, and its output reads back to the same statements. **The read-back
  rule, one helper in `tests/conftest.py` that T006 and T008 reuse:** parse into a `Dataset` with
  the serialization's name when rdflib registers a parser under it, otherwise with its media
  type; take the statements of all its graphs; treat an `xsd:string` literal as the plain literal
  on both sides; then `isomorphic`. Run it under several hash seeds
  (`PYTHONHASHSEED` in a subprocess, or a loop over shuffled insertion orders), because a
  serializer's output order can depend on the seed (D6);
- `nquads` and `trix` are marked as written from a dataset, Turtle is not;
- short names: Turtle `ttl`, RDF/XML `xml`, N-Triples `nt`, JSON-LD `json-ld`;
- extensions: Turtle `ttl`, RDF/XML `rdf`, JSON-LD `jsonld`, N-Triples `nt`, `longturtle` `ttl`;
- every serialization has a media type; exactly those rdflib registers a `/` name for are
  negotiable;
- a serializer registered at test time with `rdflib.plugin.register` and removed afterwards is
  offered without any change to the module, which is what makes the list follow rdflib (FR-002).
  Clear the table's cache before and after. rdflib has no public way to unregister a plugin, so the
  test removes it from `rdflib.plugin._plugins` in its teardown, with a comment saying so.

---

## Phase: User Story 1 — A developer's software fetches RDF from a record's identifier (P1)

### Group 2

#### T004 — The three pages answer `Accept`

**Files**: `controlled_vocabularies/ui/representations.py` (new), `controlled_vocabularies/ui/views.py`,
`tests/test_ui/test_representations.py` (new)

The mixin's negotiation path (plan.md §3, steps 1, 3 and 4 without the download header), applied
to `ConceptDetailView`, `CollectionDetailView` and `VocabularyDetailView`. Tests, run against each
of the three addresses where the scenario is not specific to one:

- `Accept: text/turtle` gives Turtle (by `Content-Type`) that parses to a graph isomorphic to
  `subject.to_graph()`, with no `Content-Disposition` (US-1 scenarios 1 and 2, FR-009);
- a concept with labels in two languages, a definition and a broader concept: every one of those
  statements is in the parsed response (scenario 1);
- the vocabulary's response holds no triple whose subject is one of its records (scenario 2);
- an ordered collection's members come back as an RDF list in stored order (scenario 3);
- a concept that another concept names `skos:narrower` gets no `skos:broader` it does not itself
  state, and no triple about the collections gathering it (scenario 4);
- hidden labels are present (scenario 5);
- a browser's header (`text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8`), no
  `Accept` header, and `*/*` each give the HTML page with status 200 (scenario 6, FR-006);
- `Accept: text/turtle, text/html` (equal quality) gives the page; `text/html;q=0.5, text/turtle`
  gives Turtle (edge case, FR-006); `text/turtle, */*` gives the page, deliberately, because HTML is
  accepted at the same quality (D3);
- a concept view behind a login requirement (a test subclass with `LoginRequiredMixin` on a test
  URL): an anonymous request with `Accept: text/turtle` gets the same redirect as one with a
  browser's header (FR-014);
- a browser request for a concept page runs no more queries than before the feature;
- `Accept: application/json` alone gives 406 and the response is not HTML (scenario 7, FR-007);
- a record of a vocabulary imported with identifiers on another site is described by that
  identifier (scenario 9, FR-004);
- every response, HTML included, has `Accept` in `Vary` (FR-008);
- `HEAD` with `Accept: text/turtle` gives the same status and `Content-Type` with an empty body;
- an address naming no vocabulary, no concept, or a collection's slug at a concept's address is
  404 with `Accept: text/turtle` (FR-011);
- the HTML page's status and the template it renders are unchanged for a browser request (FR-013).
  The existing `tests/test_ui/test_views.py` stays green untouched.

#### T005 — The pages name their RDF alternatives

**Files**: `controlled_vocabularies/ui/templates/cotton/controlled_vocabularies/rdf_alternates.html`
(new), the three detail templates, `controlled_vocabularies/ui/representations.py` (the
`rdf_alternates` context), `tests/test_ui/test_templates.py`, `tests/test_ui/test_representations.py`

Tests: each of the three pages' `<head>` has exactly four `<link rel="alternate">` elements, with
the media types of Turtle, RDF/XML, JSON-LD and N-Triples; following each `href` from the page's
address returns that media type (scenario 8, FR-010). The page's existing head content is still
there (`block.super`).

#### T006 — Every demo row survives every format

**Files**: `tests/test_ui/test_representations.py`

SC-001: seed the demo (`seed_demo`, as `tests/test_demo/test_seed.py` does), then for every
vocabulary and record, and every offered serialization requested by `?format=` once T008 exists,
or by its media type for the negotiable ones now, the response parses back isomorphic to
`to_graph()`. Parameterise over serializations, loop over rows inside, so a failure names the
format. In this group, the negotiable formats only. T008 widens it to all of them.

#### T007 — Documentation for `Accept`

**Files**: `docs/browsing.md`, `CONTEXT.md`

`docs/browsing.md`: a section on the RDF a page returns when asked through `Accept`: which pages,
which media types, what the RDF holds and what it leaves out, the HTML default, the 406, the
`Vary` header, and the alternate links. Say that N-Triples is negotiated as
`application/n-triples`, so a client asking for `text/plain` gets the page. A `curl -H 'Accept: text/turtle'` example against the
demo's address. `CONTEXT.md`: the **Representation** entry, as the spec's Key Entities give it.

---

## Phase: User Story 2 — A user downloads a vocabulary or record as an RDF file (P2)

### Group 3

#### T008 — `?format=` downloads a file

**Files**: `controlled_vocabularies/ui/representations.py`, `tests/test_ui/test_representations.py`

The mixin's `?format=` path (plan.md §3, step 2 and the download header). Tests:

- `?format=ttl` on a concept gives Turtle as an attachment named `<concept slug>.ttl`
  (scenario 1, FR-009);
- `?format=` with every offered short name on the vocabulary page gives that serialization's
  `Content-Type` (scenario 2). Widen T006 to every serialization here;
- `?format=xml` with `Accept: text/turtle` gives RDF/XML (scenario 3, FR-005);
- `?format=nonsense` is 400, not HTML, and the body names `ttl`, `xml`, `json-ld` and `nt`
  (scenario 4, FR-007);
- `?format=ttl` on an address naming no record is 404, and so is `?format=nonsense` there
  (scenario 5, FR-011);
- a media-type name (`?format=text/turtle`) is accepted, since rdflib registers it;
- the vocabulary page's `?format=` coexists with `?q=`: the representation ignores the search.

#### T009 — Documentation for `?format=`, and the roadmap

**Files**: `docs/browsing.md`, `docs/ROADMAP.md`

`docs/browsing.md`: the `?format=` parameter, the names it takes, the download name, its precedence
over `Accept`, the 400. `docs/ROADMAP.md`, R4: the content-negotiation deliverable is recorded as
delivered for a record's and a vocabulary's own statements, with the whole-vocabulary export that
re-imports cleanly and publication still to come. Edit the item to read as current state, with no
annotation of what it used to say.

---

## Dependencies

Group 1 → Group 2 → Group 3. Within a group, tasks run in order.
