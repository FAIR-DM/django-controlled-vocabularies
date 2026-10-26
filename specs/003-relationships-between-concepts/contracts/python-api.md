# Public API contract — 003-relationships-between-concepts

The ORM surface a downstream developer touches. This is the tested contract (Article IV). A link is an
entry in a record's `data` document, so reading one never queries a second table.

## `Record` methods

```python
# --- reads (empty list when none) ---
record.linked_uris("skos:broader")   -> list[str]   # concepts the record states as one step broader
record.linked_uris("skos:narrower")  -> list[str]   # concepts the record states as one step narrower
record.linked_uris("skos:related")   -> list[str]   # concepts the record states as related
record.values("skos:broader")        -> list[dict]  # the same statements as {"@id": ...} entries

# --- writes: assign the document and save ---
record.data = {**record.data, "skos:broader": [{"@id": parent.uri}]}
record.save()
```

### Guarantees

- **Inverse pair.** After `granite.data["skos:broader"] = [{"@id": igneous.uri}]` and a save, the
  page of `igneous` lists `granite` as narrower and the page of `granite` lists `igneous` as broader,
  from the one statement. A narrower link need not be stated. (FR-001, FR-002 · SC-001)
- **Polyhierarchy.** A list of two `{"@id": ...}` entries under `skos:broader` is read back by
  `linked_uris("skos:broader")` as two URIs. (FR-001)
- **Symmetric related.** After `a` states `b` under `skos:related`, the page of `b` shows `a`. When `b`
  states `a` as well, each page shows the other once. (FR-003 · SC-002)
- **Removal.** Removing an entry from the list and saving clears it from both pages. (FR-005)

### Nothing is refused

| Statement | Result |
|---|---|
| a link from a record to its own URI | stored as stated (FR-006 · SC-003) |
| the same link listed twice, or a broader and a related link between one pair | stored as stated (FR-007 · SC-003) |
| a link to a record of another vocabulary, or to a URI no record holds | stored as stated and shown by its URI, linked when it is a record held here (FR-008 · SC-004) |
| a cyclic `skos:broader` chain (`a→b→c→a`) | stored without error; no traversal is performed (FR-009 · SC-005) |

A document is checked only for its shape: each predicate holds a list of `{"@id": ...}` or
`{"@value": ...}` entries (FS-001).

## Browsing

`PropertyRows` (`controlled_vocabularies.ui.rows`) builds the rows of a concept's page. For a concept
it adds, beside the links the concept states, the links other concepts of the same vocabulary state
towards it, turned around: `skos:broader` is shown as `skos:narrower` and the reverse, and
`skos:related` is shown as `skos:related`.

## Stability

Pre-1.0 (Article VIII): this Python API may still change to correct mistakes, recorded in the
CHANGELOG. Nothing here is a frozen data contract — the RDF projection of these links
(`skos:broader`/`skos:narrower`/`skos:related`) is a later feature (R4) and is where the data contract
will attach.
