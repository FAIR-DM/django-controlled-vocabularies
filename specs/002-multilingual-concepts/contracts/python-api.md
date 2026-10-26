# Public ORM contract — Multilingual names and descriptions

The programmatic surface a downstream developer uses. This is the contract acceptance tests exercise;
the behaviour below is fixed by the spec. Builds on FS-001's contract (`ConceptScheme`, `Record`),
which is unchanged.

## ConceptScheme

- `default_language: str` — required; a language tag such as `en`. It decides which preferred label
  is copied into each record's `pref_label`.

## Record

Names and descriptions live in `record.data`, a mapping of predicate to a list of entries:

```python
{
    "skos:prefLabel": [
        {"@value": "Heat flow", "@language": "en"},
        {"@value": "Wärmefluss", "@language": "de"},
    ],
    "skos:altLabel": [{"@value": "Terrestrial heat flow", "@language": "en"}],
    "skos:definition": [{"@value": "The rate of heat loss through the Earth's surface.", "@language": "en"}],
}
```

Identity and the copied columns:

- `pref_label: str` — a copy of the name in the vocabulary's `default_language`, else the first
  `skos:prefLabel` value in any language. Refreshed on every save.
- `search_text: str` — every `skos:prefLabel`, `skos:altLabel` and `skos:hiddenLabel` value, in every
  language, one per line. Refreshed on every save.
- `slug: str` — derived once, on the first save, from the published `uri` or else from `pref_label`.
  A slug supplied when the record is created is kept as given. Unique within the scheme (from FS-001).

Read API (language-filtered):

- `values(curie) -> list[dict]` — every entry under a predicate, in every language. Empty when there
  are none.
- `label(language) -> str | None` — the first `skos:prefLabel` value whose `@language` equals
  `language`, ignoring case, or `None`.
- `display_label() -> str` — `label()` in the active language, else `pref_label`.
- `first_value(curie) -> str` — the first value under a predicate as text, or an empty string.

Alternative labels, hidden labels, definitions and notes are read with `values("skos:altLabel")`,
`values("skos:hiddenLabel")`, `values("skos:definition")`, `values("skos:scopeNote")`,
`values("skos:example")`, `values("skos:editorialNote")`, `values("skos:historyNote")`,
`values("skos:changeNote")` and `values("skos:note")`, and filtered on each entry's `@language`.

Write API: a record is written by assigning its `data` and saving. One language's entries are added,
changed or removed by editing the list under a predicate and leaving the rest of the document alone.

Validation (`full_clean()`, translatable messages with named placeholders — Article XII):

- A document that is not an object, or whose predicate does not hold a list of entries each shaped as
  `{"@id": ...}` or `{"@value": ...}` with at most an `@language` or an `@type` → `ValidationError`.
- A supplied slug another record of the scheme holds → `ValidationError` (from FS-001).

Nothing about a language is validated: any language tag is accepted, and `settings.LANGUAGES` plays no
part.

## Invariants the contract guarantees

- **Identity stability (FR-004/SC-003)**: `record.uri` and `record.slug` are unchanged by any
  addition, change or removal of a label or note, in any language, after the first save.
- **Name copy (FR-002)**: `pref_label` is the vocabulary's default-language preferred label whenever
  the record has one.
- **Slug provenance (FR-010)**: a supplied slug never moves when the preferred label changes.
