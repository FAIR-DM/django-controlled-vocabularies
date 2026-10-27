# Attach several concepts to a model

`MultiConceptField` is the many-to-many counterpart: several concepts on one record instead of one.
`vocabulary` takes the same three shapes it takes on `ConceptField`, and means the same thing by
each:

```python
from django.db import models

from controlled_vocabularies.fields import MultiConceptField

IGNEOUS = "https://vocab.example.org/igneous"
SEDIMENTARY = "https://vocab.example.org/sedimentary"


class Sample(models.Model):
    name = models.CharField(max_length=200)
    rock_types = MultiConceptField(vocabulary=[IGNEOUS, SEDIMENTARY])  # several vocabularies
    keywords = MultiConceptField(blank=True)  # no vocabulary named
```

The table linking a row to its concepts holds each concept's URI too, the same way.

One vocabulary restricts to that vocabulary, a list restricts to the union of the named vocabularies, and
leaving `vocabulary` out — as `keywords` does in the example — restricts nothing. A concept outside the
named vocabularies is refused, and the refusal names every vocabulary the field accepts.

Reading concepts back:

```python
sample.rock_types                    # the many-to-many manager
sample.get_rock_types_labels()       # a list of names, active language with fallback
sample.get_rock_types_uris()         # a list of URIs, same order
```

Both accessors return an empty list for a row holding nothing, including one that has not been
saved yet, rather than raising.

**Required and optional.** `blank=True`, as on `keywords` in the example, makes the field optional: a row
can hold zero concepts. Without it, as on `rock_types`, the field is required, and required means at
least one concept attached. Django gives a many-to-many field no hook into ordinary field
validation, so this is enforced when `full_clean()` runs rather than by the database. A
`ModelForm` or an explicit `full_clean()` call catches an empty required field, and a plain `.save()`
does not. A row cannot hold any concepts before it has a primary key, so the check is skipped on
an unsaved instance. If your own model overrides `full_clean()` after declaring the field, your
override shadows this check, and you'll need to call it yourself or reproduce it.

**Query cost.** `get_<field>_labels()` and `get_<field>_uris()` issue one query for the field's
concepts. Over a list of rows that is one query per row.
`prefetch_related("rock_types")` collapses that back to a fixed number of queries for the whole
list.

**What every shape guarantees, and what the unrestricted one gives up.** Naming one vocabulary,
several, or none all give a row the same three things: a concept it already holds cannot be
deleted out from under it, its attached concepts read back by name and by URI, and required still
means at least one. Naming one or several vocabularies adds a fourth guarantee on top: a concept
outside those vocabularies is refused, both by a form built from the model and by the relation
itself, in either direction, at the moment the membership is written.

A field naming no vocabulary gives up only that fourth guarantee, and nothing else. Said plainly, so
it needn't be inferred:

- It places **no restriction** on which concepts a row can hold. Any concept in the database is
  accepted.
- A form built from the model offers **every concept in the database** as a choice, not a filtered
  subset. On an installation with several vocabularies imported, that can be a genuinely long list
  of choices in an ordinary select widget, sooner than a restricted field would ever reach.
- `manage.py check` has no named vocabulary that could be missing, so it reports **nothing** for
  this field.

It still deletes-protects, reads back, and enforces "required" exactly as a restricted field does.

**The delete guarantee's real boundary.** "Cannot be deleted out from under it" holds for anything
that goes through the Django ORM: a single instance, and a bulk queryset `.delete()` alike, since
Django applies `on_delete=PROTECT` to both the same way. It does not hold for a `DELETE` issued
directly against the database outside Django — raw SQL, a database console, a migration that drops
rows without going through the ORM — because Django never writes an `ON DELETE` clause into the
schema for any relation. The protection lives in application code, not in a database constraint.
