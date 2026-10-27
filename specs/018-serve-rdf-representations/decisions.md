# Decisions: Serve a vocabulary or record as RDF from its page

## D1. A row's class is stated from its column when its document does not state it

A vocabulary or record authored on this site has no `rdf:type` in its document: the demo's own
vocabulary carries only a label and a description. Its class is recorded all the same, by the
`type` column on a record and by the model on a vocabulary. The representation states that class
when the document does not, and adds nothing when it does, so an imported row comes out exactly as
published. Without it, an authored vocabulary's RDF would not say it is a `skos:ConceptScheme`, and
the importer, which finds a vocabulary by that type, could not read it back. This is a statement
the row records, so FR-003's "nothing else" holds.

**ADR:** docs/adr/0028-a-rows-rdf-is-its-own-document-and-what-the-row-records.md

## D2. Every format is written from a dataset's default graph

N-Quads and TriX refuse a plain graph, and TriG accepts one but writes its statements into a graph
named by a random blank node, which a reader expecting one graph reads as empty. Every serializer
accepts a `Dataset`, so the graph is copied into a dataset's default graph and written from there
for every format: a format that names graphs then holds the statements in its default graph, and
the others write exactly what they wrote from the graph. `patch` is the one serializer left out,
because its output is a change set.

**ADR:** none — a detail of how rdflib's writers are called, local to the format table.

## D3. On an equal rank, the page wins

`HttpRequest.get_preferred_type()` breaks a tie by the order of the client's header, so
`Accept: text/turtle, text/html` would select Turtle. The spec gives the page for an equal rank, so
after negotiation an RDF choice is overruled when HTML is accepted at the same quality. Reading the
quality uses `HttpRequest.accepted_type()`, so no header parsing is written here.

**ADR:** none — local to the negotiation in one mixin, and documented in docs/how-to/ask-a-page-for-rdf.md.

## D4. Four serializers borrow a sibling's media type and extension

rdflib registers no media type for `pretty-xml`, `longturtle`, `nt11` or `hext`, and no file suffix
for them either. The first three write RDF/XML, Turtle and N-Triples, so they carry those types and
extensions. `hext` is line-delimited JSON (`application/x-ndjson`, `.hext`). They are reachable by
`?format=` only, because `Accept` names a media type and each type already belongs to the
serializer that registers it. Of the formats with several suffixes, RDF/XML takes `rdf` and
JSON-LD `jsonld`, where rdflib lists `xml` and `json` first.

**ADR:** none — a lookup table filling gaps in rdflib's registry, local to the format table.

## D5. The graph and the format table are core, the negotiation is the `ui` extra

Building a graph from a row and knowing which formats exist describe the data and rdflib, and the
later export of a whole vocabulary needs both without any page. They sit in `exchange/`, which
already holds the import, and run on the core package's Python 3.11. Only choosing a response for
a request belongs to the pages.

**ADR:** docs/adr/0028-a-rows-rdf-is-its-own-document-and-what-the-row-records.md (its last paragraph).

## D6. `pretty-xml` is not offered

rdflib 7.6.0's `pretty-xml` writer writes an ordered collection's member list correctly, as an
`rdf:parseType="Collection"` under `skos:memberList`, and in some runs also writes the list's
tail a second time as a free-standing blank node. Which runs depends on the order rdflib visits
blank nodes, which changes with every process. Read back, the second copy is two or three extra
list cells (`rdf:first`/`rdf:rest` statements on blank nodes nothing points at): four or six
statements the record does not hold. The collection, its members and their order are unchanged,
and a re-import ignores the fragment, but the output is not the record's statements and fails
FR-003 and FR-012. `xml` writes the same syntax faithfully and stays offered. This narrows FR-002
and was put to the maintainer as a change to the specification.

**ADR:** none — a fault of one rdflib writer, recorded in docs/how-to/read-a-row-back-as-rdf.md; revisit if rdflib fixes it.

## D7. A format's name is the shortest one rdflib registers

rdflib registers `ttl`, `turtle` and `text/turtle` for one serializer. The shortest name without a
`/` is the one the alternate links use and the refusal lists, so a reader sees one spelling
everywhere. Every registered name is still accepted.

**ADR:** none — a naming choice local to the format table.

## D8. The page path resolves nothing extra

When the outcome is the HTML page, the view renders as it did before, with no lookup of its own,
so a browser's request costs no extra query. The subject is resolved only on the paths that answer
with RDF or a refusal, before answering, so an address naming nothing is still a 404 there.

**ADR:** none — local to one view method.

## D9. Cleanup: the response is chosen in `get()`

The first build decided the outcome in a helper returning a serialization, `None`, `False` or the
string `"unknown"`, and `get()` branched on all four. `?format=` and `Accept` are now handled in
two plain branches of `get()`, and negotiation returns a media type or `None`. Behaviour and tests
are unchanged.

**ADR:** none — a cleanup with no change in behaviour.

## D10. Review fixes: an unwritable term is a 406, and Accept parameters are set aside

RDF/XML cannot write a property whose address ends in `/` or whose last part starts with a digit,
and an import keeps such properties. That request is refused with the same 406 as a type the site
cannot produce, and the row is served in every other format. An accepted type's parameters, such
as a JSON-LD `profile` or a `charset`, are set aside when matching, because Django's matching does
not let an accepted type with parameters match an offered type without them. Each offered type
takes the quality of the most specific entry it matches, and the page is offered first, so a tie
still gives the page. An entry with `q=0` is dropped by Django before matching, so it cannot be read
as a refusal of HTML. No known client sends one, and the limitation is documented.

**ADR:** none — local to the negotiation in one mixin, and documented in docs/how-to/ask-a-page-for-rdf.md.

## D11. A record names its vocabulary when its document does not

At the walkthrough, a demo concept's page showed `skos:inScheme` while its RDF did not: the page adds
the row from the record's link to its vocabulary, and the representation served only the document.
The maintainer chose to state it. A record whose document states no `skos:inScheme` gets one naming
its own vocabulary, by the same rule as D1, so a client fetching one concept can follow it to its
vocabulary and the importer can place it.

**ADR:** docs/adr/0028-a-rows-rdf-is-its-own-document-and-what-the-row-records.md

## D12. The downloads are listed in each page's side panel

The original interpretation offered a visible download link and it was dropped when a vocabulary's
representation was narrowed to its own statements. At the walkthrough the maintainer asked for it
back, first as a menu in the title row, then, having seen both, as a list under "Alternate
representations" in the side panel. Each of the three pages lists every serialization the site
offers there, under the name readers know it by (`Serialization.label`), sorted by that name. A
vocabulary's page adds it as the last section of its "About this vocabulary" panel. The concept
and collection pages gain a panel of their own, with a button to open it below the breakpoint.
All three panels start level with the page title. The section is a heading and a list, not a term
in a description list, because it states nothing about the record. django-mvp's side panel always
shows its label as a heading, and the maintainer chose to keep it.

**ADR:** none — a page layout choice, local to the three templates.
