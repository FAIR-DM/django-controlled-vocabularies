# Decisions: Serve a vocabulary or record as RDF from its page

## D1. A row's class is stated from its column when its document does not state it

A vocabulary or record authored on this site has no `rdf:type` in its document: the demo's own
vocabulary carries only a label and a description. Its class is recorded all the same, by the
`type` column on a record and by the model on a vocabulary. The representation states that class
when the document does not, and adds nothing when it does, so an imported row comes out exactly as
published. Without it, an authored vocabulary's RDF would not say it is a `skos:ConceptScheme`, and
the importer, which finds a vocabulary by that type, could not read it back. This is a statement
the row records, so FR-003's "nothing else" holds.

**ADR:** docs/adr/0028-a-rows-rdf-is-its-own-document-and-its-class.md

## D2. N-Quads and TriX are written from a dataset

Both refuse a plain graph. The spec offers a format that writes a named set of graphs when the one
graph can be written as such a set, and both can, from a `Dataset` whose default graph holds the
statements. Which serializers need that is found by asking each one once, not by a list, so a
later rdflib's context-only serializer is handled the same way. `patch` is the one serializer left
out, because its output is a change set.

**ADR:** none — a detail of how two rdflib writers are called, local to the format table.

## D3. On an equal rank, the page wins

`HttpRequest.get_preferred_type()` breaks a tie by the order of the client's header, so
`Accept: text/turtle, text/html` would select Turtle. The spec gives the page for an equal rank, so
after negotiation an RDF choice is overruled when HTML is accepted at the same quality. Reading the
quality uses `HttpRequest.accepted_type()`, so no header parsing is written here.

**ADR:** none — local to the negotiation in one mixin, and documented in docs/browsing.md.

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

**ADR:** docs/adr/0028-a-rows-rdf-is-its-own-document-and-its-class.md (its last paragraph).

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

**ADR:** none — a fault of one rdflib writer, recorded in docs/importing.md; revisit if rdflib fixes it.

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
