# Public ORM contract — 004-collections-group-concepts

The programmatic surface a downstream developer touches. Acceptance tests drive exactly this
(Integration-First). A collection is a `Record`, and its members are entries in its `data` document.

## Collection

```python
c = Record.objects.create(
    scheme=vocab,
    type=Record.Type.COLLECTION,  # unordered
    data={
        "skos:prefLabel": [{"@value": "Common igneous rocks", "@language": "en"}],
        "skos:member": [{"@id": granite.uri}, {"@id": basalt.uri}],
    },
)
o = Record.objects.create(
    scheme=vocab,
    type=Record.Type.ORDERED_COLLECTION,  # ordered
    data={
        "skos:prefLabel": [{"@value": "Reading order", "@language": "en"}],
        "skos:memberList": [{"@id": basalt.uri}, {"@id": granite.uri}],
    },
)
c.uri  # "{scheme.uri}/{slug}" when created without one — composed once, on the first save
c.slug  # derived from its name on the first save; unique among the scheme's records
c.is_collection  # True for either collection type
```

- Creating two records of one scheme whose names slugify to the same value takes a numeric suffix for
  the second, and the database refuses a duplicate slug within a scheme — the behaviour every record
  has.
- A collection is addressed at `/<scheme>/collection/<slug>/`, beside a concept's `/<scheme>/<slug>/`.

### `Record.member_uris() -> list[str]`

The URIs a collection lists as members: its `skos:member` entries, then its `skos:memberList` entries.

- For an ordered collection, the `skos:memberList` entries are returned in the sequence they are
  listed (FR-004). Removing a member leaves the survivors in their original relative order (FR-005).
- For an unordered collection, a set: no promised sequence.
- Empty when the collection has no members — never an error.

Members are stored as stated. Nothing refuses a member held by another vocabulary, a URI no record
holds, or a member listed twice (FR-007).

### Changing membership

Assign a new `data` and save. Adding, removing and reordering members are edits to the list under
`skos:member` or `skos:memberList`.

## Concept

### The collections that list a concept

A concept's page names the collections of its vocabulary whose `member_uris()` contain its `uri`.
Reading or changing membership never alters the concept's `slug`, `uri`, labels or links (FR-006).

## Orthogonality to relations (FS-003)

Listing two concepts in a collection creates no `skos:broader`, `skos:narrower` or `skos:related`
statement between them, and leaves any existing link between two members unchanged. Membership and
links are separate predicates of separate documents and share no state (FR-006).

## Factories

`collection_with_members(scheme=None, labels=(...), ordered=False, name=None)` returns a
`(collection, members)` tuple. Members are saved concepts of the collection's own vocabulary, and an
ordered collection lists them under `skos:memberList` in order (FR-010).
