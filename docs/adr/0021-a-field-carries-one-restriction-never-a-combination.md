# ADR 0021 — A field carries one restriction, never a combination

**Status:** superseded by ADR 0024

## Decision

A `ConceptField` or `MultiConceptField` declaration may narrow its choices inside its vocabulary in
one of three ways — a collection, an explicit list of concepts, or a branch of the broader/narrower
hierarchy — and may use **at most one** of them. A declaration carrying two or more is refused with
a `TypeError` when the model is imported.

A restriction also requires the declaration to name **exactly one** vocabulary. Naming several, or
none, alongside a restriction is refused the same way.

## Why

Combining two restrictions has an intersection reading and a union reading, and nothing in the
source distinguishes them. `collection="core", branch="thermal"` could mean *members of `core` that
are also under `thermal`*, or *members of `core` plus everything under `thermal`*. A reader of the
declaration cannot tell which the author meant, and neither can the author six months later.

Choosing one of the two readings and documenting it does not fix that. The declaration would still
read ambiguously at the call site, which is where it is read most often, and the wrong guess would
be silent — a field quietly wider or narrower than intended, with no error and no failing test.

The exactly-one-vocabulary rule follows from how targets are named rather than from taste. A
collection slug and a concept slug are unique only within their vocabulary (see ADR 0022), so with
two vocabularies named there is no way to say which collection `collection="core"` means.

Nothing is foreclosed. If a real need for an intersection appears it can be added later with an
explicit spelling that says which operation it is. A default guessed now would have to be broken to
correct it, and this package's compatibility contract makes that expensive after 1.0.

## Revisit if

A consumer presents a case that genuinely needs two axes at once — most plausibly a branch narrowed
to the members of a collection. The answer then is a spelling that names the operation, not a
meaning assigned to the current syntax.
