# Importing a published vocabulary

`import_skos()` reads a SKOS file — Turtle, RDF/XML, or JSON-LD — and creates or updates the
vocabulary it declares, along with every concept and collection it contains. It keeps every
statement the file makes about them, in every language. Each row is matched by its URI, never by
name, so importing the same file twice updates the same rows rather than duplicating them.

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
whose `mentioning(uri)` narrows
records to those whose document may link to a URI, which is how a concept's page finds the links
other concepts make to it. It matches on the stored text, so it can return a record that holds the
URI as a plain literal, and callers check the links with `linked_uris()`.

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
and never recomputed by a later one. A vocabulary's name arriving in a different language on a later
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
`import_skos` management command wraps this for use from a terminal (see below). There is no
web-facing entry point yet.

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

## Importing from the command line

The `import_skos` management command wraps `import_skos()` for use from a terminal or a
deployment script:

```bash
python manage.py import_skos rocks.ttl
```

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
