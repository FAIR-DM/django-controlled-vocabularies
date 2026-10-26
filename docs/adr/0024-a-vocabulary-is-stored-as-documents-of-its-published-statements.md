# 24. A vocabulary is stored as documents of its published statements

Date: 2026-10-26

## Status

Accepted

## Context

A vocabulary was stored across seven models: `ConceptScheme`, `Concept`, `ConceptLabel`,
`ConceptNote`, `ConceptRelation`, `Collection` and `CollectionMember`. Each SKOS property had one
fixed place in them, and a value with no place was dropped. An import discarded notations, mappings
to other vocabularies, and every statement outside SKOS (#181).

Most of the importer, about 2,200 lines of `exchange/skos.py`, existed to sort published values into
those places. The import report named 21 reasons a value could be set aside, and each reason was a
message that had to stay true on every path that reached it. Matching a published language tag
against the site's `LANGUAGES` added a further layer of rules, and some of them stored a value under
a language other than the one it was published in.

The package's purpose had also narrowed. It imports published vocabularies and lets a project's
models reference their concepts, and a vocabulary belongs to whoever published it (#218, #223). The
pages that created, edited and deleted a vocabulary, and the `managed` flag that told an imported
vocabulary from a local one, served a purpose the package no longer has.

## Decision

A vocabulary is stored as two models.

- **`ConceptScheme`**, the vocabulary: `uri`, `slug`, `default_language`, `pref_label` and `data`.
- **`Record`**, a concept or collection in it: `scheme`, `type` (its `rdf:type`, such as
  `skos:Concept`), `uri`, `slug`, `pref_label`, `search_text` and `data`.

`data` is a JSON document that holds every statement as it was published. Each key is a predicate,
written as a CURIE when its namespace has a known prefix, and as the full URI otherwise. The known
prefixes are `skos`, `dcterms`, `owl`, `rdf`, `rdfs` and `xsd`, and they are fixed, because every
stored key is written with them. Each value is a list of entries in the shape JSON-LD uses:
`{"@value": "Granite", "@language": "en"}`, `{"@value": "GR-01"}` or `{"@id": "https://…"}`.

`pref_label` and `search_text` are copies of what is in `data`, refreshed on every save, kept so that
sorting and searching need no lookup inside the document. A row's statements are read with
`values()`, `label()`, `display_label()`, `linked_uris()` and `first_value()`, and a collection's
members with `member_uris()`.

An import keeps every statement it reads, in every language, and replaces a record's document whole
when the file is read again. It is refused only for a subject with no usable identifier, or a file
whose vocabulary cannot be determined. The report has four buckets: `created`, `updated`,
`absent_from_source` and `fatal`.

The pages that create, edit and delete a vocabulary are removed, with the `managed` flag and the
curator role. The package's scope is importing and referencing published vocabularies, and the
browsing pages that read what an import stored stay.

Four earlier decisions carry on in this model, restated here because the records they were written
against no longer exist.

- A row has one `uri`. An imported row keeps its publisher's URI exactly. A row created without
  one is given a URI composed from the configured base address and its slugs, once, and it is not
  recomposed afterwards.
- A record is named by its label in the language being read, and where it has none in that
  language, by `pref_label`, the copy in the vocabulary's default language. Lists sort by
  `pref_label`, so their order is the same in every reading language.
- A record's slug is unique within its vocabulary, whatever its type, and a collection keeps its own
  address segment (`/<vocabulary>/collection/<slug>/`) beside a concept's.
- A concept field restricted to a collection must name exactly one vocabulary, because a collection's
  slug is unique only within its vocabulary.

## Consequences

This is a breaking change, released as 0.2.0.

- The migrations restart at a new `0001_initial`. No data migration is provided, because the
  package is before 1.0. A site on 0.1.0 imports its vocabularies again after upgrading.
- `ConceptField` and `ConceptsField` point at `Record`, limited to concepts. `vocabulary=` and
  `collection=` stay. `branch=` and `concepts=` are removed, so a field carries at most one
  restriction, `collection`, and the rule that a restriction names exactly one vocabulary still
  holds.
- The helpers on the old models (`add_label`, `add_broader`, `Collection.add`, `set_slug`,
  `static_uri` and the rest) are removed, and so are the publication-detail fields on a vocabulary.
  A vocabulary's publisher, creator, licence, version and modification date are read from its
  document.
- Statements are kept as published, so the package no longer enforces SKOS rules on them. A
  concept with two preferred labels in one language, or a broader link to a concept held nowhere
  here, is stored as the file says it.
- The import report's set-aside and normalised buckets, their reasons, language matching against
  `LANGUAGES`, and the `CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES` setting are removed. The three
  schemes that can carry executable content (`javascript`, `data` and `vbscript`) are always
  refused as an identifier.
- The pages that create, edit and delete a vocabulary are removed, with the Source facet on the
  list of vocabularies. A vocabulary changes by importing its source again.
- A question that crosses records, such as every concept with a given notation, reads inside JSON
  documents. It is slower than a query on a column and is left to the project that needs it.

This decision supersedes ADR 0001, ADR 0016, ADR 0017, ADR 0020 and ADR 0021.
