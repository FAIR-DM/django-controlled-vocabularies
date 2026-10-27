# 27. A field may be restricted to a branch, read from the links table

Date: 2026-10-27

## Status

Accepted. Builds on ADR 0025. Reverses the removal of `branch=` in ADR 0024.

## Context

A concept field could be restricted to a branch of the broader and narrower hierarchy: the concept
it named and every concept below it. ADR 0024 removed `branch=` along with the other restrictions
that read the old relation tables. Under the document model a branch read meant reading every
record's document to find the links, which was too slow to run each time a choice was validated,
offered or searched.

The need did not go away. A publisher almost always ships broader and narrower links and rarely
ships collections, because a collection is a curator's own grouping. A project that imports a
vocabulary as published can name a collection only if the publisher made one, so it had the whole
vocabulary or nothing to offer.

ADR 0025 copied each record's links into a `Link` table, which a recursive query can walk. On
PostgreSQL 17 with a vocabulary of 37,840 concepts (GCMD Science Keywords, ten times over), the
query below answers a branch of 53 concepts in 10 to 16 milliseconds and a branch of 3,784 in about
240. Checking whether one value lies in that larger branch takes 170. That is fast enough to run
on every read.

## Decision

`ConceptField` and `MultiConceptField` take an optional `branch`, the URI of a concept. The field
admits that concept and every concept below it, at any depth, inside the one vocabulary it names.

- **Inclusive.** The root is a choice as well as everything below it. A branch names a subject
  area, and its own term is usually the right answer where nothing below it is more specific.
- **Downward only.** The root's broader concepts and its siblings are refused.
- **Concepts only.** The field's existing restriction to `skos:Concept` still applies, so a
  collection linked from a concept in the branch is never offered.
- **Either side states a link.** A concept is below another when its own document states
  `skos:broader` the other, or the other's document states `skos:narrower` it. The vocabulary's
  pages read the hierarchy the same way, so a field never disagrees with the page a person browsed
  to find the concept. Both directions are followed at every step.
- **One restriction.** A field carries a collection or a branch and never both, and a branch
  needs a declaration naming exactly one vocabulary (ADR 0021, as carried forward by ADR 0024).
  Either mistake raises a `TypeError` when the declaration is read.
- **Live.** The branch is resolved when a value is validated, a form is built or a search runs, as
  a collection is. Nothing is queried while the declaration is read, and a migration records the
  root's URI and nothing derived from it.

`RecordQuerySet.in_branch(scheme_uri, root_uri)` does the walk, and the field puts its result
inside the `Q` it already returns as `limit_choices_to`, so the choices, the search endpoint, the
validation and the write guard on a `MultiConceptField` all follow from it.

The walk is one recursive query over the `Link` table, written with model metadata for every table
and column name and with every value as a bound parameter.

- It joins `Link` to the records of the vocabulary in both directions and keeps only edges whose
  both ends are records of that vocabulary, so a link to a concept held elsewhere, or held nowhere,
  is not followed.
- It combines its rows with `UNION` and not `UNION ALL`, so a cycle in the stored links ends the
  walk and each concept appears once. A published vocabulary can contain a cycle, and a read that
  never ended on data the database accepted would be a defect.
- Both directions are one join with an `OR`, because PostgreSQL allows a recursive term to refer
  to the walk once. Each side of the `OR` starts from the records found so far, so every step is
  an indexed lookup.
- It runs on SQLite and PostgreSQL, the two databases the package supports.

`manage.py check` warns, with the id it already uses for a missing collection
(`controlled_vocabularies.W005`), when a branch root is not a concept of the named vocabulary. A
missing root makes the field offer nothing, which looks the same from outside as a vocabulary that
has not been imported.

### Indexing

No index is added (Article XIII).

- Walking from a parent to the children that state `skos:broader` it looks up links by `target`
  and `predicate`, which is the `(target, predicate)` index ADR 0025 added.
- Walking from a parent to the children it states as `skos:narrower` looks up links by `source`,
  which the foreign key's own index serves.
- Both directions end in a lookup of a record by its URI, which is unique and so indexed.

### Rejected alternatives

**Building the edges apart from the walk.** A subquery listing every parent and child pair in
both directions, which the recursive step then joins to, reads simpler, but it is evaluated whole on
every step. Measured on the same data, it took 650 milliseconds for the 53-concept branch and 2.8
seconds for the 3,784-concept one.

**A closure table.** Storing every ancestor and descendant pair would make a branch one flat
lookup, but ADR 0025 already rejected it: it is much larger than the links, and it must be
recomputed across a subtree whenever one link changes. A recursive query is fast enough at the
measured sizes.

**A tree library.** SKOS allows a concept several broader concepts, and a published vocabulary can
contain a cycle. A library that stores one parent per node keeps a second source of truth beside
the documents and breaks on both (ADR 0025).

**Following only `skos:broader`.** Many publishers state a hierarchy from one side only, and a few
state it from the other. A field that followed one direction would offer a different set from the
page that lists the concept's children.

**Combining a collection and a branch.** The result could be the overlap or the union, and nothing
in the declaration says which. It stays refused (ADR 0021).

## Consequences

- A project can narrow a field to a subject area of a vocabulary it imported as published, with no
  collection and no code of its own.
- A branch is evaluated each time a value is validated, a form is built or a search runs. It costs
  one query over the links, whose size grows with the vocabulary and with the depth of the branch.
- The field's choices follow the links as the last import stored them. A write that skips `save()`
  leaves the rows as they were until `refresh_links()` is called (ADR 0025), and the field follows.
- A root that is missing, is a collection, or belongs to another vocabulary leaves the field with
  no choices. The check reports it.
- The migration for a model records `branch` as it records `collection`, so adding or changing one
  needs a migration.
