# 26. A field names its vocabulary by URI, and may say where it is published

Date: 2026-10-27

## Status

Accepted. Supersedes ADR 0022.

## Context

A concept field named its vocabulary, and the collection it was restricted to, by slug (ADR 0022).
A site listed every vocabulary its fields named in `CONTROLLED_VOCABULARIES`, keyed by that slug,
and `sync_vocabularies` loaded them.

That breaks down for a model shipped in a reusable app (#233). An abstract model whose field names
`"rock-type"` gives every project inheriting it an empty choice list until the project finds out
which vocabulary was meant and where it is published, then declares it. A slug is a name one site
gives a vocabulary, so the package cannot know it. Two packages can both write `"rock-type"` and
mean different vocabularies, and the project cannot rename either.

ADR 0022 ruled URIs out because a vocabulary authored on the site carried a URI composed from the
site's base address, which differs between a developer machine and production. The package no
longer authors vocabularies (ADR 0024). Every vocabulary it holds arrives from a published file
that states its own URI.

## Decision

A concept field names each vocabulary by the URI of its concept scheme, and its collection
restriction by the collection's URI. A slug is refused when the field is declared.

A field may name a vocabulary with a `Vocabulary`, which carries the URI and, optionally, the
`source` it is published at and that source's `format`.

`sync_vocabularies` loads every vocabulary a field on an installed, concrete model names, after the
vocabularies declared in `CONTROLLED_VOCABULARIES`:

- A vocabulary the declarations loaded is not read again from any field.
- A vocabulary several fields name is loaded once, from the first field giving a source, and from
  its URI when none does.
- A source that publishes some other vocabulary is refused.

A field's migration records the URIs and never the source. A source says where a vocabulary can be
fetched and changes nothing in the schema.

## Consequences

A package can ship a model with concept fields that work in any project that installs it. The
project runs `sync_vocabularies` and declares nothing. A project that wants a different copy, one it
ships so deploys never fetch anything, declares the same vocabulary in settings and the package's
source is never read.

Identity is the URI throughout, as it already is for every row (ADR 0001). Two fields naming the
same URI name the same vocabulary, wherever each says it is published.

A field declaration is longer: a URI in place of a short slug. A package or project names each
vocabulary once, as a module constant, and uses the constant.

Every existing declaration naming a slug, including the ones in a project's migrations, must be
rewritten to the URI. Loading a migration that still names a slug raises the same `TypeError` as a
model does.

The check for a vocabulary that is neither declared nor loaded (`controlled_vocabularies.W006`) is
removed. A field's vocabulary can now always be loaded, so the one remaining warning,
`controlled_vocabularies.W001`, is for a vocabulary that has not been loaded yet.

A fetch of a URI sends an `Accept` header naming Turtle, RDF/XML and JSON-LD, so a publisher
serving several representations at one address answers with one the importer reads.
