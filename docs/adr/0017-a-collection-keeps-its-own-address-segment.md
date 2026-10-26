# 17. A collection keeps its own address segment

Date: 2026-08-25

## Status

Superseded by ADR 0024

## Context

A vocabulary holds both concepts and collections, and both are addressed at the
vocabulary's own path followed by a slug. A concept's slug is unique among the concepts
in its vocabulary. A collection's slug is unique among the collections in its
vocabulary. Nothing ties the two together, so a concept and a collection in the same
vocabulary can legitimately carry the same slug.

SKOS does not settle the shape of the address on its own. The SKOS Reference declines to
require any particular dereferencing behaviour for a concept, scheme, or collection URI,
and defers the question to the Cool URIs and Best Practice Recipes notes. The one rule
it insists on is that one URI identifies one resource — the shape is left to whoever
publishes the vocabulary.

Two published vocabularies were checked for how they already handle this. AGROVOC
distinguishes its concepts (`.../agrovoc/c_1234`) from its collections
(`.../agrovoc/skosCollection_cb7b7c4a`) with a discriminator built into the local name.
GEMET distinguishes its concepts (`.../gemet/concept/95`) from its groups
(`.../gemet/group/96`) with a path segment — the same pattern used here.

## Decision

A concept and a collection occupy disjoint address spaces. A concept is addressed at its
vocabulary's path, a segment marking it as a concept, and its own slug. A collection is
addressed the same way, with a segment marking it as a collection instead. The segment,
not the slug alone, is what keeps a concept and a collection from being mistaken for one
another.

## Consequences

A concept and a collection in the same vocabulary may share a slug without any
ambiguity, because the segment before it says which table is being addressed. Slug
uniqueness stays a single per-model database constraint — one on concepts, one on
collections — rather than a rule that has to reach across two tables.

That is the cost this decision avoids: a uniqueness rule spanning two tables cannot be
expressed as one database constraint, so it would have to live in application code
instead, where a race between two writers, or a bulk import, can still mint two records
that answer to the same address. Two different resources answering to one identifier is
not a failure a linked-data consumer can recover from once its own store has cached the
wrong one against it.

The cost accepted here is a longer address: one extra segment beyond the flattened
alternative. That is a small price given that SKOS imposes no shape of its own, and that
published vocabularies already in wide use carry a comparable segment.
