# ADR 0022 — A restriction names its target by slug

**Status:** accepted

## Decision

Every restriction on a concept field names what it points at by **slug**, resolved inside the one
vocabulary the declaration names: a collection's slug, a concept's slug, or the slug of the concept
at the root of a branch. Nothing is named by URI, by notation, or by a reference to a database row.

Because a slug is unique only within its vocabulary, resolution is always scoped to the declared
vocabulary. A target whose slug exists only in some other vocabulary is absent here, and is reported
as absent rather than silently resolved.

## Why

The vocabulary itself is already named by slug, so one rule now covers every argument these fields
take, and a reader learns it once.

A URI was the main alternative and is ruled out by this package's own identity model. A vocabulary
authored on this site carries a *dynamic* URI, composed from the site's configured address, so the
same record has a different identifier on a developer machine and in production — a declaration
naming one would be correct in one environment and wrong in the other. A reference to the row is
ruled out because a declaration must resolve without a database (ADR 0010 and the check that
supports it): the model is imported long before any vocabulary has been imported.

The known weakness is inherited rather than introduced. A locally authored record re-derives its
slug from its name on save, so renaming one breaks declarations naming it. That failure is not
silent: the system check reports the target as absent, and a curator who does not want a slug to
move sets it explicitly.

## Revisit if

Vocabularies routinely arrive with opaque published identifiers as slugs — `c0041`, `c0072` — often
enough that declarations become unreviewable. Accepting a notation alongside the slug would be the
smaller answer. Accepting a URI would reopen the dynamic-identifier problem above.

## Depends on

ADR 0010, which establishes that a restriction is derived on every path rather than resolved once,
and so never at declaration time.
