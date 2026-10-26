# ADR 0001 — A record's URI is dynamic until it turns static, and its local address is a separate thing

**Status:** superseded by ADR 0024

## Decision

Every vocabulary, concept and collection has a URI, read from `uri`, and it always answers.

- While the record is authored on this site and unpublished, `uri` is **dynamic**. It is composed on read from `CONTROLLED_VOCABULARIES_BASE_URI` and the record's slugs, and it moves when those move.
- The URI turns **static** when the record arrives from an outside publisher, and later when the record's vocabulary is published. A static URI is stored in the `static_uri` column and is returned verbatim. The application never rewrites or clears it. It also makes no attempt to stop a caller who does, because keeping a published identifier still is an interface concern, met by making the field non-editable once the record is published (decisions.md D18).
- `has_static_uri` reports which of the two states a record is in, read from the column's presence and never inferred by comparing the URI against the configured site address.
- `local_url` is where the record is viewed on this site. It is always composed from the site's address and the record's slugs, including for a record whose URI belongs to somebody else, and a child never composes it through its parent's URI.

`Model.objects.get_by_uri()` resolves both kinds: an exact match on the stored column first, then a read of this site's own address back into its slugs.

## Why

A single composed string was doing two jobs, and importing a published vocabulary pulls them apart. An imported concept's identity is its publisher's address for it, which this package must hold verbatim and must never mint. That concept still has to be viewable here, which needs an address this site owns. Both are needed, so both exist.

Three alternatives were weighed and rejected.

- **Store the URI for every record and recompute it on save.** A column named for the whole concept reads more naturally, but the value then goes stale. Renaming a vocabulary would have to rewrite every concept and collection under it, and changing the configured site address would have to rewrite the whole table, which is a bulk write and bypasses every rule this package enforces in `save()`. Composition on read is instantly correct after a rename and needs no data migration.
- **Infer fixedness by testing whether the URI sits under the configured base address.** This makes identity depend on a setting. Changing the setting would silently reclassify every record, and an outside publisher may legitimately publish under the same base. Article IX of the constitution forbids exactly this.
- **Move identity into one shared table with a row per record.** It would let a single unique index span all three models. It costs a join on every read of a record's identity, and it prevents a collision that needs a source file to hand two different kinds of record the same URI. In RDF that asserts the two are the same resource, so such a file is malformed, and #50's importer reports it while reading. Rejected, and since withdrawn as a requirement altogether (decisions.md D18). Uniqueness within a model is a database constraint, and identity is unique by construction anyway, because a vocabulary's slug is unique site-wide and a concept's or collection's slug is unique within its vocabulary.

The split also matches SKOS, where a concept's URI is a global identifier rather than a path on whichever site happens to be serving it.

## Revisit if

Cross-model URI collisions turn out to be common rather than pathological, or a second thing needs to resolve a URI to a record. Either would make the shared identity table worth its join.
