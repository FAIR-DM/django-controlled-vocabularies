# 25. A record's links are copied into a table

Date: 2026-10-27

## Status

Accepted

## Context

A record holds its statements as a JSON document (ADR 0024), and a link to another record is a
`{"@id": ...}` entry in it. Three pages ask who links to a record, and each answered by reading
documents:

- A vocabulary's page loaded every concept's document to find its top concepts and each row's
  broader concept.
- A concept's page found the collections holding the concept with a text search over every
  collection's document.
- A concept's property rows found the concepts stating a broader, narrower or related link to it
  with a text search over every concept's document, then checked each match in Python.

On PostgreSQL 17 with a vocabulary of 37,840 concepts (GCMD Science Keywords, ten times over), the
vocabulary page took 5.3 to 5.6 seconds and a concept page 1.7 to 1.9 seconds. A links table built
by hand answered a recursive query over a whole branch of the same data in 96 milliseconds.

## Decision

A record's links are copied into a `Link` table, one row for each top-level `{"@id": ...}` entry of
its document, and the pages read that table.

- `source` is a foreign key to the record, deleted with it.
- `predicate` is the key as stored in the document, a CURIE such as `skos:broader` or a full URI,
  so every predicate is indexed and not a list of them.
- `target` is the entry's `@id`, as stored. It is a URI and not a foreign key, because a link may
  point at a concept this site does not hold, or one that lives in another vocabulary.

Only top-level entries are copied, exactly what `linked_uris()` reads. A link inside an embedded
blank node and a literal give no row, and a link stated twice gives two rows, because the table
reports what the document says and carries no constraint of its own.

The document stays the only source of truth, as with `pref_label` and `search_text`. Saving a
record deletes its rows and builds them again from its document, in the same transaction as the
save, unless a partial save leaves `data` out. `Record.refresh_links()` does the rebuild, so a
project that writes documents with `QuerySet.update()` or `bulk_create()`, which skip `save()`, can
bring the rows back in line. A migration builds the rows for the records a site already holds.

Indexing is a deliberate decision for every field (Article XIII of the constitution):

- One composite index on `(target, predicate)`. Every question the pages ask has a target and
  usually predicates: who links to this URI, under which of these predicates. The leading `target`
  narrows to the few rows naming it, and `predicate` serves both the filter by predicate and the
  query that wants any predicate, which reads only the leading column.
- The index the foreign key already carries on `source` serves rebuilding one record's rows, and
  asking whether a record states a link.
- No index on `predicate` alone. Nothing asks for every link of a predicate without a target.
- No unique constraint, so a document that states a link twice stays representable.

`RecordQuerySet.mentioning()`, a text search over the stored documents that could return a record
holding the URI only as a literal, is replaced by `RecordQuerySet.linking_to()`, which reads the
table and is exact.

### Rejected alternatives

**A tree library such as django-treebeard or django-mptt.** These store one parent for each node,
and SKOS allows a concept several broader concepts (spec 003, FR-001). They keep a second source of
truth beside the documents, which then disagree. They also break on a cycle, which a published
vocabulary can contain, and on a link to a concept not held here.

**A closure table.** A table of every ancestor and descendant pair makes a branch one flat lookup,
but it is much larger than the links themselves and has to be recomputed across a whole subtree
when one link changes. At the measured sizes a recursive query over the links table answers a
branch fast enough, so the cost is not earned.

## Consequences

- An import writes one more insert for each record it creates, and one more delete and insert
  for each record it updates. Measured on PostgreSQL 17 with GCMD Science Keywords (3,784
  concepts), a first import went from 13 to 19 seconds, and importing it again from 8 to 17.5. An
  import is a batch job and a page is read on every request, so the pages are what the cost buys.
- A write that skips `save()`, such as `QuerySet.update()` or `bulk_create()`, leaves the rows as
  they were until `refresh_links()` is called on each record.
- A branch of a hierarchy can now be one recursive query over the table. Nothing in the package
  does that yet, so no method for it is added.
- `RecordQuerySet.mentioning()` is removed, with no alias. This is a breaking change to a public
  method of a package before 1.0, recorded in the changelog.
- Upgrading runs a migration that builds the rows for the records already held, which reads every
  record once.
