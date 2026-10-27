# Research: Serve a vocabulary or record as RDF from its page

**Feature**: `018-serve-rdf-representations` · **Spec**: [`spec.md`](./spec.md)

There is no `planning-notes.md` and no sketch for this feature, so the research answers the spec
and the codebase alone.

## R1. Where the statements come from

Every row keeps its statements in `data`, the document (ADR 0024): predicate (CURIE or full URI) to
a list of entries shaped as JSON-LD writes them.

- `{"@id": "…"}` is a link.
- `{"@value": …}` is a literal, with at most one of `@language` and `@type`. The importer writes
  `@value` as a string and `@type` as a CURIE (`xsd:date`). A row written by hand may carry a
  JSON number or boolean.
- An entry with neither `@id` nor `@value` is an embedded blank node: a dict of the same shape.
- `skos:memberList` is a list of `{"@id": …}` in the publisher's sequence. The importer reads it
  from an RDF list and stores the sequence, not the list's nodes.

`Namespaces.expand()` in `controlled_vocabularies/predicates.py` turns a CURIE back into its URI and
leaves a full URI unchanged. It is the inverse of the `compact()` the importer stored keys with.

**The type is not always in the document.** An imported row carries `rdf:type` under its key, as
the importer keeps every statement. A row authored here does not: the demo's own vocabulary
`data-collection-methods` has a document with only `skos:prefLabel` and `dcterms:description`. A
record's class is recorded in its `type` column, and a vocabulary's is implied by its model. The
representation therefore states the row's class from the column (`skos:ConceptScheme` for a
vocabulary, the `type` value for a record) when the document does not already state it. That is a
statement the row records, not one gathered from elsewhere, so FR-003 holds. See D1.

## R2. The serializations rdflib can write

Checked against rdflib 7.6.0 (the locked version), by writing a one-triple graph in every
registered serializer, as a `Graph` and as a `Dataset` holding it in its default graph:

| Serializer | Names rdflib registers | Plain graph | Dataset |
|---|---|---|---|
| RDF/XML | `application/rdf+xml`, `xml` | yes | yes |
| Pretty RDF/XML | `pretty-xml` | adds statements for an RDF list under some hash seeds (D6) | same |
| N3 | `text/n3`, `n3` | yes | yes |
| Turtle | `text/turtle`, `turtle`, `ttl` | yes | yes |
| Long Turtle | `longturtle` | yes | yes |
| N-Triples | `application/n-triples`, `ntriples`, `nt` | yes | yes |
| N-Triples 1.1 | `nt11` | yes | yes |
| JSON-LD | `json-ld`, `application/ld+json` | yes | yes |
| N-Quads | `application/n-quads`, `nquads` | **refused** | yes |
| TriX | `application/trix`, `trix` | **refused** | yes |
| TriG | `application/trig`, `trig` | yes | yes |
| HexTuples | `hext` | yes | yes |
| Patch | `patch` | refused | yes, as a change set |

- **Offered:** every serializer but `patch` and `pretty-xml`. Its output is a set of additions and deletions, a
  change between graphs, which FR-002 excludes. N-Quads and TriX refuse a plain graph and are
  written from a `Dataset` whose default graph holds the statements. That is the "named set of
  graphs" case the spec allows.
- **Names:** every name rdflib registers for an offered serializer is accepted by `?format=`. The
  list is read from `rdflib.plugin.plugins(kind=Serializer)` at request time, so a serializer a
  later rdflib adds is offered with no change here (FR-002).
- **Media types:** a registered name containing `/` is a media type. Eight serializers register
  one, and those eight are what `Accept` can select. `pretty-xml`, `longturtle` and `nt11` write
  the same syntax as RDF/XML, Turtle and N-Triples, so a `?format=` response in one of them carries
  that sibling's media type. `hext` has no registered type and is served as
  `application/x-ndjson`, the line-delimited JSON it is.
- **Extensions:** `rdflib.util.SUFFIX_FORMAT_MAP` maps a file suffix to the format that parses it.
  Read backwards it gives each format's suffixes. Two formats have several, and the first rdflib
  lists is not the usual one: RDF/XML's are `xml`, `rdf` and `owl`, and JSON-LD's are `json`,
  `jsonld` and `json-ld`. One small table of overrides settles those (`rdf`, `jsonld`) and the four
  serializers with no suffix (`pretty-xml` → `rdf`, `longturtle` → `ttl`, `nt11` → `nt`,
  `hext` → `hext`). A format rdflib adds later with no suffix falls back to its own name.

## R3. Content negotiation

Django 5.2, the package's floor, has `HttpRequest.get_preferred_type(media_types)`, which parses
`Accept` with quality values and specificity. It returns the media type matching the client's most
preferred accepted type, taking the first of the offered list on a tie.

- **HTML first in the offered list.** A browser's header (`text/html,…,*/*;q=0.8`) selects
  `text/html`. A request with no `Accept` header is treated as `*/*` and also selects HTML.
- **Equal ranks.** `get_preferred_type` walks the client's accepted types in order, so
  `Accept: text/turtle, text/html` (equal quality) would select Turtle. The edge case in the spec
  asks for the page. After the call, if an RDF type was chosen and `text/html` is accepted at the
  same quality, the page is served. `HttpRequest.accepted_type(media_type)` returns the matching
  `MediaType`, whose quality is readable, so no header parsing is written here.
- **Nothing acceptable.** `get_preferred_type` returns `None` when no offered type is accepted.
  That is a 406 (FR-007).

## R4. Response details

- `django.utils.cache.patch_vary_headers(response, ["Accept"])` on every response from these views,
  the HTML page included (FR-008).
- `django.utils.http.content_disposition_header(as_attachment=True, filename=…)` builds the
  download header for a `?format=` response. Django has had it since 4.2. An `Accept` response
  carries no `Content-Disposition` and is read in place (FR-009).
- `HEAD` is dispatched to `get()` by Django's `View`, and the test client drops the body, so a
  `HEAD` asking for RDF answers with the same status and headers.
- An unknown `?format=` is a 400 and an unacceptable `Accept` a 406, each as a plain-text response
  whose message is translatable (FR-007, Article XII).

## R5. Where the pieces go

- **Building the graph is core, not UI.** The later whole-vocabulary export will need it, and so
  could any consumer holding a row. The `exchange` package already holds the RDF boundary for the
  import. A new module, `controlled_vocabularies/exchange/graph.py`, turns a row into an
  `rdflib.Graph`, and `Resource.to_graph()` on the model calls it, so a developer holding a row
  writes `scheme.to_graph()`. The core package installs on Python 3.11, and nothing here needs
  more.
- **The format table is core too.** It describes rdflib, not the pages, and the export will
  need it. `controlled_vocabularies/exchange/serializations.py`.
- **Negotiation and the response are UI.** A mixin in `controlled_vocabularies/ui/representations.py`
  is applied to the three detail views. `VocabularyDetailView` is a list view over records (its
  docstring says why). Its subject is `self.vocabulary`, resolved in `setup()`. The two record
  views resolve their subject with `get_object()`, so a missing record is a 404 before any format
  is read (FR-011).
- **Alternate links.** django-mvp's `mvp/base.html` has a `{% block head %}`. A Cotton component,
  `<c-controlled-vocabularies.rdf-alternates />`, writes the four `<link rel="alternate">`
  elements, and the three detail templates call it from that block with `{{ block.super }}` kept.

## What already exists

One line per piece of new code, with where the search stopped (`kit/checklists/existing-first.md`
order).

- **Parsing `Accept` and choosing a type:** Django, `HttpRequest.get_preferred_type()` and
  `accepted_type()`. No new code beyond the equal-rank rule.
- **The list of serializations, their names and media types:** an installed package, rdflib's
  plugin registry (`rdflib.plugin.plugins`). New code only for the table that groups names by
  serializer, and for the four media-type and extension gaps.
- **Extensions:** an installed package, `rdflib.util.SUFFIX_FORMAT_MAP`, read backwards.
- **Writing a graph in a format:** an installed package, `rdflib.Graph.serialize`.
- **Expanding a stored CURIE:** this repo, `Namespaces.expand()`.
- **An RDF list for `skos:memberList`:** an installed package, `rdflib.collection.Collection`,
  which the importer already uses to read one.
- **`Vary` and `Content-Disposition`:** Django, `patch_vary_headers` and
  `content_disposition_header`.
- **Turning a document back into triples:** new code. The importer only goes the other way
  (`SkosImporter.document()`), and rdflib's JSON-LD parser cannot read a document because its keys
  are CURIEs with no `@context`. Supplying a generated context and parsing as JSON-LD was
  considered and rejected: it would run the JSON-LD processor on every page view, and embedded
  nodes and `skos:memberList` would still need rewriting first.
- **The alternate links in the page head:** new code, a Cotton component. django-mvp ships no
  component for head links.
- **`Resource.to_graph()` and `rdf_class`:** new code on the models, a call into `exchange/graph.py`.
- **Proving the round trip in tests:** an installed package, `rdflib.compare.isomorphic`.
