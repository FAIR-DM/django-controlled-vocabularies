# Decisions: Serve a vocabulary or record as RDF from its page

## D1. A row's class is stated from its column when its document does not state it

A vocabulary or record authored on this site has no `rdf:type` in its document: the demo's own
vocabulary carries only a label and a description. Its class is recorded all the same, by the
`type` column on a record and by the model on a vocabulary. The representation states that class
when the document does not, and adds nothing when it does, so an imported row comes out exactly as
published. Without it, an authored vocabulary's RDF would not say it is a `skos:ConceptScheme`, and
the importer, which finds a vocabulary by that type, could not read it back. This is a statement
the row records, so FR-003's "nothing else" holds.

## D2. N-Quads and TriX are written from a dataset

Both refuse a plain graph. The spec offers a format that writes a named set of graphs when the one
graph can be written as such a set, and both can, from a `Dataset` whose default graph holds the
statements. Which serializers need that is found by asking each one once, not by a list, so a
later rdflib's context-only serializer is handled the same way. `patch` is the one serializer left
out, because its output is a change set.

## D3. On an equal rank, the page wins

`HttpRequest.get_preferred_type()` breaks a tie by the order of the client's header, so
`Accept: text/turtle, text/html` would select Turtle. The spec gives the page for an equal rank, so
after negotiation an RDF choice is overruled when HTML is accepted at the same quality. Reading the
quality uses `HttpRequest.accepted_type()`, so no header parsing is written here.

## D4. Four serializers borrow a sibling's media type and extension

rdflib registers no media type for `pretty-xml`, `longturtle`, `nt11` or `hext`, and no file suffix
for them either. The first three write RDF/XML, Turtle and N-Triples, so they carry those types and
extensions. `hext` is line-delimited JSON (`application/x-ndjson`, `.hext`). They are reachable by
`?format=` only, because `Accept` names a media type and each type already belongs to the
serializer that registers it. Of the formats with several suffixes, RDF/XML takes `rdf` and
JSON-LD `jsonld`, where rdflib lists `xml` and `json` first.

## D5. The graph and the format table are core, the negotiation is the `ui` extra

Building a graph from a row and knowing which formats exist describe the data and rdflib, and the
later export of a whole vocabulary needs both without any page. They sit in `exchange/`, which
already holds the import, and run on the core package's Python 3.11. Only choosing a response for
a request belongs to the pages.
