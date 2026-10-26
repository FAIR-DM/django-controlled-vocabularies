# Python API contract — 005-concepts-keep-identifier

The surface this feature fixes. A vocabulary and a record each have one `uri`.

## The identifier

```python
scheme.uri            # -> str   the vocabulary's identity
record.uri            # -> str   the concept's or collection's identity

Record.objects.get(uri=uri)           # -> Record, raises Record.DoesNotExist
ConceptScheme.objects.get(uri=uri)    # -> ConceptScheme, raises ConceptScheme.DoesNotExist
```

`uri` is a `CharField` of at most 500 characters, unique for each model, and indexed by that
constraint. It may hold a publisher's identifier, which is kept as given, or an identifier composed on
the first save.

## Behaviour contract

```python
# A row that arrived from elsewhere keeps its identifier, verbatim and forever.
c = Record.objects.create(scheme=s, type=Record.Type.CONCEPT,
                          uri="http://vocabs.example.org/rock/granite",
                          data={"skos:prefLabel": [{"@value": "Granite", "@language": "en"}]})
c.uri                      # "http://vocabs.example.org/rock/granite"
c.slug                     # "granite" — from the last segment of the URI, once
c.data = {"skos:prefLabel": [{"@value": "Granite (coarse)", "@language": "en"}]}; c.save()
c.uri                      # unchanged
# and unchanged again after settings.CONTROLLED_VOCABULARIES_BASE_URI changes.

# A row created without one is given its identifier once, on the first save.
d = Record.objects.create(scheme=s, type=Record.Type.CONCEPT,
                          data={"skos:prefLabel": [{"@value": "Basalt", "@language": "en"}]})
d.uri                      # "{base}/{scheme-slug}/basalt"
d.slug                     # "basalt"
# renaming it, or changing the configured base address, and saving does not move d.uri.

# An imported row still has a place on this site.
reverse("controlled_vocabularies_ui:concept-detail",
        kwargs={"slug": s.slug, "concept_slug": c.slug})   # "{mount}/{scheme-slug}/granite"

# Lookup answers for both kinds.
Record.objects.get(uri="http://vocabs.example.org/rock/granite")   # -> c
Record.objects.get(uri=d.uri)                                      # -> d
Record.objects.get(uri="http://vocabs.example.org/nothing")        # raises Record.DoesNotExist
```

## Import refusals

`import_skos()` refuses the whole run, with `SkosImportFailed`, writing nothing, when a subject it would
store has no usable identifier:

| Subject | Reason |
|---|---|
| a blank node | `FatalReason.MISSING_IDENTITY` |
| an identifier beginning `javascript:`, `data:` or `vbscript:` | `FatalReason.REFUSED_IDENTITY` |

Every other scheme is accepted, including `urn:`, `doi:` and `ark:`.

## Guarantees the tests assert

- The application never rewrites, normalises, re-cases, recomputes, or clears an externally assigned
  identifier, including on a re-import that matched the record by it (FR-002). This is a statement about
  what the package does, not a guarantee enforced against a caller who assigns a different value
  deliberately: no write path is defended, and that is the decision, not a gap.
- No two rows of the same model may hold the same `uri`, and the refusal comes from the database
  constraint (FR-005). Across models there is no constraint and none is wanted.
- A collection's address on this site can never equal a concept's, because the `collection` segment
  separates them (FR-007).
