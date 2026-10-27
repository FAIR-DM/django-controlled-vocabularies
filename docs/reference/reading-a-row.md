# Reading a row

A row is read with its methods rather than by indexing into `data`:

```python
record.values("skos:altLabel")      # the entries stored under a predicate, as dicts
record.label("de")                  # the name in one language, or None
record.display_label()              # the name in the active language, else pref_label
record.linked_uris("skos:broader")  # the URIs a predicate links to
record.first_value("skos:notation") # the first value as text, or an empty string
collection.member_uris()            # a collection's members, an ordered one in sequence
```

`values()`, `label()`, `display_label()`, `linked_uris()` and `first_value()` are on both
`ConceptScheme` and `Record`, which share them through their abstract base, `Resource`.
`member_uris()` is on `Record`.

A record's `type` is one of `Record.Type.CONCEPT`, `Record.Type.COLLECTION` and
`Record.Type.ORDERED_COLLECTION`. `Record.COLLECTION_TYPES` holds the last two, and
`record.is_collection` says whether a record is either. `Record.objects` is a `RecordQuerySet`,
whose `linking_to(uri, *curies)` narrows records to those whose document links to a URI, under
one of the given predicates when any are given. It reads the `Link` table, so a record that holds
the URI only as a literal is not returned and a record that links to it more than once is returned
once. A concept's page finds the collections holding it with
`linking_to(concept.uri, "skos:member", "skos:memberList")`.

A document is validated by `validate_document` when a row is cleaned. It must be an object that
maps each predicate to a list of entries, each a link or a literal as shown above.
`controlled_vocabularies.predicates` holds the six fixed prefixes as `PREFIXES`, and
`Namespaces.compact()` and `Namespaces.expand()` turn a full URI into a CURIE and back. The order the
pages show predicates in is `PREDICATE_ORDER`, and the predicates they show in one language are
`TRANSLATED_PREDICATES`.
