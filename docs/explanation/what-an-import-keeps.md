# What an import keeps

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

## The vocabulary's own details

Besides its records, a file usually describes the vocabulary itself. Those statements are kept in
the vocabulary's own document in the same way. Its name comes from `skos:prefLabel`, else
`dcterms:title`, and its description from `dcterms:description`. The publisher, creator, licence,
version and last-modified date are the entries under `dcterms:publisher`, `dcterms:creator`,
`dcterms:license`, `owl:versionInfo` and `dcterms:modified`. The browsing pages read them from there.

A vocabulary the run creates takes the most common language among its records' preferred labels as
its default language, or the site's `LANGUAGE_CODE` when no label carries one. A vocabulary that
already exists keeps its default language, and so does one passed in with `scheme=`.
