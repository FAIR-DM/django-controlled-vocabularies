# 20. The curator's pages sit behind a `-` segment

Date: 2026-10-24

## Status

Accepted

## Context

The browsing pages address a vocabulary at its slug (`/<vocabulary>/`) and a concept at the
vocabulary's slug followed by its own (`/<vocabulary>/<concept>/`). Creating, editing and deleting a
vocabulary need addresses of their own in the same space.

Plain segments would collide. `/new/` is also the address of a vocabulary whose slug is `new`, and
`/<vocabulary>/edit/` is also the address of a concept whose slug is `edit`. Slugs are derived from
names and from published identifiers that this package does not choose, so any reserved word could
turn up as one. Refusing those words as slugs would mean renaming an imported concept against its
publisher's identifier, which ADR 0002 rules out.

## Decision

Every page that acts on a record, rather than shows it, sits behind a `-` segment: `/-/new/` creates
a vocabulary, and `/<vocabulary>/-/edit/` and `/<vocabulary>/-/delete/` edit and delete one. Later
editing pages follow the same pattern.

`-` can never be a slug. Every slug this package mints goes through `slugify()`, which strips
leading and trailing hyphens, so a slug is never a lone `-`. GitLab separates its own routes from
user-chosen names with the same segment for the same reason.

## Consequences

No vocabulary or concept, imported or authored here, can ever be shadowed by an editing page, and no
word has to be reserved. The cost is an address that reads slightly oddly. These pages are for
curators, never published as identifiers, so the oddness never reaches a linked-data consumer.
