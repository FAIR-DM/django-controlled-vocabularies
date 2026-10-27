# Importing a published vocabulary

One command loads every vocabulary a site uses, and refreshes them on every deploy:

```bash
python manage.py sync_vocabularies
```

It loads two kinds of vocabulary:

- every vocabulary a concept field on one of the site's models names (see
  [vocabularies your models name](#vocabularies-your-models-name))
- every vocabulary declared in the `CONTROLLED_VOCABULARIES` setting, which covers a vocabulary no
  field names, and lets a site choose where a vocabulary a field names is read from (see
  [declaring vocabularies](#declaring-vocabularies))

```python
# settings.py
CONTROLLED_VOCABULARIES = {
    "rock-type": {"source": BASE_DIR / "vocabularies" / "rock-type.ttl"},
    "sample-status": {"source": "https://vocab.example.org/sample-status.ttl"},
}
```

Run the command on every deploy: each run updates every vocabulary in place and never deletes
anything.

**Ship the file with the project where you can.** A source can be a local path or an
`http://`/`https://` address, but a file checked in beside your code is loaded the same way on
every machine and does not make a deploy depend on a remote server being up. A vocabulary your
project publishes itself works the same way: ship it as a SKOS file and declare it like any other.

## Vocabularies your models name

A concept field names each vocabulary by its URI, and can say where it is published (see
[attaching concepts to your models](fields.md#attaching-a-concept-to-your-model)):

```python
ROCK_TYPE = Vocabulary(
    "https://vocab.example.org/rock-type",
    source="https://vocab.example.org/rock-type.ttl",
)
```

`sync_vocabularies` goes through every concrete model the site installs, including the fields a
model inherits from an abstract one, and loads each vocabulary their fields name:

- A vocabulary is read from the field's `source`, or from its URI when the field gives none.
  Fetching a URI asks for Turtle, RDF/XML or JSON-LD, which a publisher serving several formats
  at one address answers with the vocabulary rather than its web page.
- A vocabulary several fields name is loaded once. The first field giving a source is used, and
  the command names any other source it did not read.
- A vocabulary the site declares in `CONTROLLED_VOCABULARIES` is loaded from the declaration
  instead, and no field's source is read for it.
- A source that publishes a vocabulary other than the one the field names is refused, and nothing
  is loaded from it.

A vocabulary loaded this way takes the slug derived from its URI (see
[slugs and addresses](#slugs-and-addresses)).

## Declaring vocabularies

`CONTROLLED_VOCABULARIES` is a dict. Each key is the slug the vocabulary is given on this site,
and each value holds:

- `source` — a local path, as a string or a `Path`, or an `http://`/`https://` address. A URL is
  fetched exactly as [the `import_skos` command](#importing-a-single-file-from-the-command-line)
  fetches one.
- `format`, optional — the serialization (`turtle`, `xml` or `json-ld`), for a source whose name
  or `Content-Type` does not carry one.

Each key must be a valid slug: letters, digits, hyphens and underscores. The key becomes the
vocabulary's slug when the command first loads it, in place of the slug an
import would derive from its URI, and it is how every later run finds the vocabulary again.

- A source that declares a vocabulary other than the one already held under its key is refused,
  and nothing about either changes.
- A source that declares no vocabulary of its own loads into the one already held under its key.
  With nothing held there yet, it is refused, since there is nothing to load it into.
- A vocabulary already loaded under a different slug, by `import_skos` for example, is reported
  and left as it is. It is never renamed, because pages and links may already use its slug.
  Declare it under the slug it has.

`manage.py check` warns about a field naming a vocabulary that is not loaded yet
(`controlled_vocabularies.W001`). See
[attaching concepts to your models](fields.md#attaching-a-concept-to-your-model).

## Loading every vocabulary

```bash
python manage.py sync_vocabularies
python manage.py sync_vocabularies rock-type https://vocab.example.org/mineral
python manage.py sync_vocabularies --dry-run
```

The declared vocabularies load first, then the ones fields name. Each is imported in a
transaction of its own, through the same import the
rest of this page describes, and gets its own report: how many records were created, updated and
absent from the source, naming each absent one, as `import_skos` prints. A record the source no
longer lists is reported and left alone, never deleted.

- Naming vocabularies limits the run to them. Name a declared one by its key and one a field
  names by its URI. A name that is neither is refused before anything is loaded.
- `--dry-run` performs every import and prints every report, then leaves the database exactly
  as it was.
- A vocabulary that fails, because its source cannot be fetched or read or the import refuses
  it, is reported with the reason, and nothing of it is kept. The others still load. The command
  exits non-zero if any failed, so a deployment script stops there.

## Loading from Python

`import_skos()` reads a SKOS file — Turtle, RDF/XML, or JSON-LD — and creates or updates the
vocabulary it declares, along with every concept and collection it contains. It keeps every
statement the file makes about them, in every language. Each row is matched by its URI, never by
name, so importing the same file twice updates the same rows rather than duplicating them. Both
commands load through it.

```python
from controlled_vocabularies.exchange import import_skos

report = import_skos("rocks.ttl")
```

The caller may name a target `ConceptScheme` for a file that declares no vocabulary of its own, or
have it checked against one the file does declare:

```python
report = import_skos("rocks.ttl", scheme=my_scheme)
```

Re-running an import upserts rather than deleting and recreating. For a record the file still
contains, the file is authoritative: the record's statements end up matching the file exactly,
including the removal of a statement the file no longer carries. A record the file does not mention
at all is left completely untouched and named in the report instead, never deleted.

## Reading a row back as RDF

`to_graph()` is the reverse of the import. A `ConceptScheme` or a `Record` returns an
`rdflib.Graph` built from its stored document:

```python
from controlled_vocabularies.models import Record

record = Record.objects.get(uri="http://example.org/rocks/granite")
print(record.to_graph().serialize(format="turtle"))
```

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<http://example.org/rocks/granite> a skos:Concept ;
    skos:broader <http://example.org/rocks/igneous> ;
    skos:prefLabel "Granite"@en .
```

The graph holds the row's own statements and nothing gathered from other rows: a concept's
graph does not include the labels of the concept it links to, and a vocabulary's graph does
not include its concepts. The subject is the row's `uri`, unchanged.

Every statement of the document is in the graph, in every language, and a `skos:memberList` is
written as one RDF list in its stored order. A row whose document states no `rdf:type` is given
one: `skos:ConceptScheme` for a vocabulary, and a record's `type` for a record. A document that
states a type keeps exactly the types it states.

`to_graph()` calls `document_graph()`, from `controlled_vocabularies.exchange.graph`, which does
the same for any document in the stored shape, such as one not yet saved:
`document_graph(uri, document, rdf_class)`.

`controlled_vocabularies.exchange.serializations.Serialization` lists the formats the installed
rdflib can write a graph in faithfully, and writes a graph in one of them:

```python
from controlled_vocabularies.exchange.serializations import Serialization

turtle = Serialization.named("ttl")  # any name rdflib registers, such as "turtle" or "text/turtle"
data = turtle.serialize(record.to_graph())  # bytes
turtle.media_type, turtle.extension  # ("text/turtle", "ttl")
[s.name for s in Serialization.all()]  # every format offered
```

The list follows the installed rdflib. Two of its writers are left out: `patch`, whose output is a
change between graphs, and `pretty-xml`, which can repeat part of an RDF list (`xml` writes the
same syntax). A format that names graphs, such as TriG, N-Quads or TriX, holds the statements in
its default graph, so a reader expecting one graph finds them there. `serialize()` raises
`ValueError` when the format cannot express one of the graph's terms, as RDF/XML cannot a
property whose address ends in `/`.

## What an import keeps

A vocabulary is stored as one `ConceptScheme` row, and each concept and collection in it as one
`Record` row. The statements a file makes about a subject are kept together in that row's `data`, a
JSON document.

Each key of the document is a predicate, written as a CURIE when its namespace has a known prefix
and as the full URI otherwise. The known prefixes are fixed: `skos`, `dcterms`, `owl`, `rdf`, `rdfs`
and `xsd`. Each value is a list of entries in the shape JSON-LD uses:

```json
{
  "skos:prefLabel": [
    {"@value": "Granite", "@language": "en"},
    {"@value": "Granit", "@language": "de"}
  ],
  "skos:notation": [{"@value": "GR-01"}],
  "skos:broader": [{"@id": "https://example.org/rocks/igneous"}],
  "skos:exactMatch": [{"@id": "https://other.example/terms/granite"}],
  "dcterms:modified": [{"@value": "2026-03-01", "@type": "xsd:date"}]
}
```

- A literal is `{"@value": ...}`, with an `@language` when it has one, or an `@type` when it has a
  datatype other than a plain string.
- A link to another resource is `{"@id": ...}`.
- A blank node has no identifier that survives a re-import, so it is stored embedded in the entry,
  as an object holding its own statements in the same shape:
  `{"http://www.w3.org/2008/05/skos-xl#literalForm": [{"@value": "Granite", "@language": "en"}]}`.
  A concept's page shows it as one line of text.
- A list under `skos:memberList` keeps its sequence. Every other list is stored in a fixed order,
  so importing the same file again stores the same text.

Nothing is looked up in a published file and discarded. Preferred, alternative and hidden labels,
notes, notations, mappings to other vocabularies, links between concepts, and statements in
namespaces other than SKOS are all kept, in every language the file offers. The site's `LANGUAGES`
setting plays no part: a vocabulary published in sixty languages imports into all sixty.

A subject becomes a record when the file types it as `skos:Concept`, `skos:Collection` or
`skos:OrderedCollection`. A subject with no type that states `skos:inScheme` or `skos:topConceptOf`
towards the vocabulary, or that the vocabulary names with `skos:hasTopConcept`, becomes a concept.
Any other subject in the file is not a record, and the statements it makes are not kept.

A file often describes a concept of another vocabulary it maps to. A subject the file places in
another vocabulary, with `skos:inScheme`, `skos:topConceptOf` or that vocabulary's
`skos:hasTopConcept`, is left to that vocabulary's own import. So is a record another vocabulary
already holds, unless the file places it in this one. Both are named in the report's
`held_elsewhere`, and neither is changed.

Two columns are copies, filled in from the document each time a row is saved:

- `pref_label` holds the name in the vocabulary's default language. It is what lists sort by and
  what a name falls back to.
- `search_text` holds every preferred, alternative and hidden label of a record, one per line. It
  is what a search matches.

Sorting and searching use these copies, so they cost no lookup inside the document.

The links a record states are copied too, into the `Link` table, one row for each top-level
`{"@id": ...}` entry of the document: the `source` record, the `predicate` as stored (a CURIE such
as `skos:broader`, or a full URI) and the `target` URI. A target is a URI and not a foreign key,
because a link may point at a concept this site does not hold. A literal, and a link inside an
embedded blank node, give no row, and a link stated twice gives two. Pages that ask who links to a
concept, such as its inferred narrower concepts and the vocabulary's top concepts, read this table
instead of every document.

Every save of a record deletes its `Link` rows and builds them again from its document, in the
same transaction. A save that names `update_fields` without `"data"` leaves them alone. A write
that skips `save()`, such as `QuerySet.update()` or `bulk_create()`, leaves them as they were, so
call `record.refresh_links()` on each record afterwards, loaded again from the database.
`record.link_rows()` returns the unsaved rows a record's document states, which is what both build
from. The import saves each record, so it keeps them in line without help.

### Reading a row

A row is read with its methods rather than by indexing into `data`:

```python
record.values("skos:altLabel")      # the entries stored under a predicate, as dicts
record.label("de")                  # the name in one language, or None
record.display_label()              # the name in the active language, else pref_label
record.linked_uris("skos:broader")  # the URIs a predicate links to
record.first_value("skos:notation") # the first value as text, or an empty string
collection.member_uris()            # a collection's members, an ordered one in sequence
```

`values()`, `label()`, `display_label()`, `linked_uris()` and `first_value()` are on both
`ConceptScheme` and `Record`, which share them through their abstract base, `Resource`.
`member_uris()` is on `Record`.

A record's `type` is one of `Record.Type.CONCEPT`, `Record.Type.COLLECTION` and
`Record.Type.ORDERED_COLLECTION`. `Record.COLLECTION_TYPES` holds the last two, and
`record.is_collection` says whether a record is either. `Record.objects` is a `RecordQuerySet`,
whose `linking_to(uri, *curies)` narrows records to those whose document links to a URI, under
one of the given predicates when any are given. It reads the `Link` table, so a record that holds
the URI only as a literal is not returned and a record that links to it more than once is returned
once. A concept's page finds the collections holding it with
`linking_to(concept.uri, "skos:member", "skos:memberList")`.

A document is validated by `validate_document` when a row is cleaned. It must be an object that
maps each predicate to a list of entries, each a link or a literal as shown above.
`controlled_vocabularies.predicates` holds the six fixed prefixes as `PREFIXES`, and
`Namespaces.compact()` and `Namespaces.expand()` turn a full URI into a CURIE and back. The order the
pages show predicates in is `PREDICATE_ORDER`, and the predicates they show in one language are
`TRANSLATED_PREDICATES`.

## The vocabulary's own details

Besides its records, a file usually describes the vocabulary itself. Those statements are kept in
the vocabulary's own document in the same way. Its name comes from `skos:prefLabel`, else
`dcterms:title`, and its description from `dcterms:description`. The publisher, creator, licence,
version and last-modified date are the entries under `dcterms:publisher`, `dcterms:creator`,
`dcterms:license`, `owl:versionInfo` and `dcterms:modified`. The browsing pages read them from there.

A vocabulary the run creates takes the most common language among its records' preferred labels as
its default language, or the site's `LANGUAGE_CODE` when no label carries one. A vocabulary that
already exists keeps its default language, and so does one passed in with `scheme=`.

## Slugs and addresses

A vocabulary's slug and a record's slug are both derived from their own published identifier — its
fragment where it has one, otherwise the last segment of its path — assigned once, on first import,
and never recomputed by a later one. A vocabulary loaded from `CONTROLLED_VOCABULARIES` takes its
declared key instead. A vocabulary's name arriving in a different language on a later
import never moves its local address. Only the publisher reassigning the identifier itself does.

That permanence has a cost worth naming: a vocabulary published under opaque codes gets an opaque
local address — `/v-113/00123` rather than `/soil-types/clay`. It is accepted because the address
is correct and stays correct, which is what every consumer of a URL needs from it, and because a
readable address that can move under data already pointing at it is worse than a stable one that
cannot.

A record another vocabulary holds moves into the vocabulary being imported only when the file places
it there with `skos:inScheme`, `skos:topConceptOf` or `skos:hasTopConcept`. It takes a new slug in
its new vocabulary, because a URI is held once.

## The report

The call returns an `ImportReport`, a plain dataclass rather than rendered text, so a caller can
inspect what happened without parsing anything:

- `created` / `updated` — the URIs of every vocabulary and record the run wrote.
- `absent_from_source` — the URIs of records that exist here but that the file no longer mentions.
- `held_elsewhere` — the URIs of subjects the file describes that belong to another vocabulary, left
  untouched.
- `fatal` — populated only on a failed run: a `FatalFinding` per reason the whole import was
  refused. A failed run raises `SkosImportFailed`, carrying this same report, and leaves the
  database exactly as it was before the run started.

A run is refused for one of these reasons, each a member of `FatalReason`:

- `MISSING_IDENTITY` — a concept, a collection or the vocabulary is a blank node, which cannot be
  identified again on a re-import.
- `REFUSED_IDENTITY` — a concept, a collection or the vocabulary has an identifier that starts with
  `javascript:`, `data:` or `vbscript:`. A stored identifier is rendered as a link, and these can
  carry executable content.
- `IDENTIFIER_TOO_LONG` — an identifier is longer than the 500 characters the `uri` column holds.
- `VOCABULARY_UNDETERMINED` — the file declares no vocabulary of its own and none was named.
- `VOCABULARY_TARGET_MISMATCH` — the file declares a vocabulary other than the one named.
- `VOCABULARY_AMBIGUOUS` — the file declares more than one vocabulary and none was named.

Nothing else in this list refuses a run, and a file that cannot be read as SKOS at all raises
`SkosImportError` (below). A run either succeeds in full or changes nothing: every problem in a
file is collected before any of it is written, and a fatal one rolls the whole run back. The
`sync_vocabularies` and `import_skos` management commands wrap this for use from a terminal.
There is no web-facing entry point yet.

## Upgrading from 0.1.0

Version 0.2.0 stores a vocabulary in two tables, `ConceptScheme` and `Record`, in place of the seven
earlier ones. The migrations start again at a new `0001_initial`, and no data migration is provided,
because the package is before 1.0. A site on 0.1.0 imports its vocabularies again from their
published files after upgrading. A concept attached to a row of your own models referred to a row of
the earlier tables, so it is attached again once the vocabularies are back.

## Untrusted input

An imported file is treated as untrusted input. RDF/XML is scanned for entity expansion and
external references before a parser sees it. A JSON-LD document is refused rather than fetched if
its `@context` names a remote location, whether that is a plain string reference or an `@import`
reference tucked inside an inline object context. `import_skos()` itself never makes a network
request when reading a file — the command's own URL fetch (see below) happens first, and only the
fetched or local bytes ever reach this scan. An ordinary inline JSON-LD context, carrying no such
reference, imports normally.

`import_skos()` raises one of two exceptions, both `ValidationError` subclasses carrying a
translatable message. `SkosImportError` covers every reason a file cannot be turned into usable SKOS
at all: not found, not in a supported serialization, unparseable, a `skos:memberList` whose
`rdf:rest` chain loops back on itself, or refused by the safety scan above. `SkosImportFailed` covers the case where the file parses but the run collects one or more
fatal problems, and carries the same `ImportReport` its `fatal` bucket names them in.
`UnsafeRdfXmlError` and `UnsafeJsonLdError`, the two exceptions the safety scan itself raises, are
exported `SkosImportError` subclasses, so code that only catches `(SkosImportError,
SkosImportFailed)` already catches a file the safety scan refuses too.

## Importing a single file from the command line

The `import_skos` management command loads one source by hand, without declaring it:

```bash
python manage.py import_skos rocks.ttl
```

The vocabulary takes the slug derived from its URI (see
[Slugs and addresses](#slugs-and-addresses)). To manage it with `sync_vocabularies` afterwards,
declare it under that slug.

The source can be a local filesystem path or an `http://`/`https://` URL, told apart by the value
itself rather than by a flag. A URL is fetched under a fixed 30-second read timeout, a fixed 50 MiB
response ceiling and a fixed ten-minute deadline for the whole transfer, over a connection that
only ever speaks http and https. The fetched document's identifiers resolve against the address it
was served from, following any redirect — so a vocabulary published behind a PURL or a `/latest`
alias is stored under the URIs its publisher assigned, and a re-import updates the same concepts
the first import created rather than making a second copy.

- `--format` names the source's serialization (`turtle`, `xml`, or `json-ld`), for a source whose
  extension or `Content-Type` does not.
- `--dry-run` performs the entire import and reports the outcome exactly as a live run would,
  then leaves the database exactly as it was beforehand — useful for seeing what a file would
  create and update before running it for real.
- `--verbosity`, Django's own option, prints how many records were created, updated, and absent
  from the source, then names each absent record, then how many belong to another vocabulary and
  were left untouched, naming each. A dry run adds a line saying nothing was kept. At
  `0` nothing prints at all, as with any Django command.

A refusal exits non-zero and prints every reason the run was refused.
