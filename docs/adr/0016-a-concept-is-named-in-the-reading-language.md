# 16. A concept is named in the reading language, and falls back to its vocabulary's own

Date: 2026-08-24

## Status

Superseded by ADR 0024

## Context

A concept carries a preferred label in its vocabulary's default language, stored on the concept
itself, plus one row per additional language for every other name it goes by. Anywhere a concept is
shown to a person, something has to choose which of those names to print.

Two of the languages in play are rarely the same one. The site is being read in whatever language
the visitor asked for. A vocabulary imported from a publisher carries whatever languages that
publisher happened to write in, and a publisher has no reason to have covered the reader's.

So there are three plausible rules. Always print the stored default, which is predictable and often
in a language the reader does not read. Print the reading language and nothing when it is missing,
which leaves unnamed rows on the page for exactly the imported vocabularies this package exists to
support. Or print the reading language and fall back — and if it falls back, to what.

## Decision

A concept is named by its preferred label in the language the site is being read in. Where the
concept carries no preferred label in that language, it is named by its vocabulary's own default
language instead.

The fallback is to the vocabulary's default specifically, never to whichever other language happens
to be available.

This governs every surface that prints a concept's name, and it governs sorting too: a list of
concepts is ordered by the name actually shown, not by the stored one.

## Consequences

A page never shows an unnamed concept, whatever languages its vocabulary was written in.

The fallback is a single predictable language rather than an arbitrary one. A vocabulary's default
language is the one its identity is anchored in, so it is the one a curator has guaranteed exists
for every concept, which is what makes it safe to fall back to. Falling back to any available
language would mean two concepts in the same list could be named in two different languages, with
nothing on the page explaining why.

Ordering by the displayed name has a cost worth naming: the same list, read in two languages, comes
back in two different orders. That is correct, because an alphabetical list a reader cannot follow
alphabetically is not sorted for them, but it does mean the position of a concept in a list is not
a stable property of the concept.

Sorting by a name resolved per request also rules out sorting in the database on a stored column
alone. The resolved name has to be composed as part of the query, which is a constraint on any
future view that lists concepts.
