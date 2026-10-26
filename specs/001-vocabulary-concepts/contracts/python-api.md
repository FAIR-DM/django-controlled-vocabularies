# Contract: Public Python / ORM API

The surface this feature exposes to downstream code. This is a library, so the "contract" is the
importable models and their behaviour. Semantic-versioned under Article VIII.

## Imports

```python
from controlled_vocabularies.models import ConceptScheme, Record
```

## ConceptScheme

- `ConceptScheme.objects.create(default_language="en", data={"skos:prefLabel": [{"@value":
  "Geothermics", "@language": "en"}]})` → saved scheme with `pref_label == "Geothermics"` and
  `slug == "geothermics"`.
- `scheme.uri` → `"{CONTROLLED_VOCABULARIES_BASE_URI}/geothermics"` when it was created without one,
  and exactly the given value when it was created with one.
- `scheme.slug` is made once, on the first save, and is unchanged by later saves.
- `scheme.records.all()` → the scheme's records.
- `scheme.delete()` → removes the scheme and its records.
- A second scheme whose name slugifies to an existing slug is given a numeric suffix
  (`geothermics-2`), and the database refuses two schemes with one slug.

## Record

- `Record.objects.create(scheme=scheme, type=Record.Type.CONCEPT, data={"skos:prefLabel":
  [{"@value": "Heat flow", "@language": "en"}]})` → saved record with `slug == "heat-flow"`,
  `scheme == scheme`, `pref_label == "Heat flow"` and `search_text == "Heat flow"`.
- `record.uri` → `"{scheme.uri}/heat-flow"` when created without one, and exactly the given value
  when created with one. A record created with the URI `https://publisher.example/rocks/granite`
  has the slug `granite`.
- Changing `record.data` and saving refreshes `pref_label` and `search_text`. It does not change
  `uri` or `slug`.
- `Record.objects.get(uri=record.uri)` → returns exactly that record.
- Two records in one scheme whose names slugify equally → the second takes a numeric suffix, and the
  database refuses two records of one scheme with one slug.
- Records in *different* schemes may share a slug (the scheme's slug disambiguates the URI).
- `Record.Type` holds `CONCEPT` (`skos:Concept`), `COLLECTION` (`skos:Collection`) and
  `ORDERED_COLLECTION` (`skos:OrderedCollection`).

## Reading a row

Both models read their document with `values(curie)`, `label(language)`, `display_label()`,
`linked_uris(curie)` and `first_value(curie)`. A document is validated by `validate_document`
as an object that maps each predicate to a list of entries.

## Guarantees (asserted by tests)

- A row's URI does not depend on its name beyond the slug it was derived from at creation, and no
  later change to the name moves it.
- No two rows of one model share a URI.
- Identity is the URI; the database primary key is never the identity.

## Configuration

- `settings.CONTROLLED_VOCABULARIES_BASE_URI` (str) — full base, e.g. `https://example.org/vocabularies`.
  Optional; defaults to a documented value. Trailing slash ignored. Used only for a row created
  without a URI.

## Not in this contract (other features)

Multilingual names, links between concepts, collections, RDF import, served URLs, the browsing
pages. Each reads the document this contract describes.
