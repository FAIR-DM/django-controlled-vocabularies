# Attaching concepts to your models

Two model fields attach concepts to your own records: `ConceptField` for one concept, and
`MultiConceptField` for several. Both can be restricted to the vocabularies you name, and narrowed
further to the members of a collection.

Both fields point at `Record`, the model that holds every concept and collection of a vocabulary
(see [importing](importing.md#what-an-import-keeps)). They are limited to the records whose type is
`skos:Concept`, so a collection is never offered or accepted as a choice.

## Attaching a concept to your model

`ConceptField` is a `ForeignKey` to `Record`, optionally restricted to the vocabularies you name.
`vocabulary` takes three shapes:

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField


class Specimen(models.Model):
    name = models.CharField(max_length=200)
    rock_type = ConceptField(vocabulary="rock-type")                     # one vocabulary
    dominant_material = ConceptField(vocabulary=["igneous", "mineral"])  # several
    keyword = ConceptField(null=True, blank=True)                        # no vocabulary named
```

The column the field adds holds the concept's URI, not a database id: `rock_type_id` reads
`https://example.org/rocks/granite`. A database dump, a CSV export or an API response can be read
without a join, and the value keeps its meaning when the rows move to another database. It is
still a foreign key, so the database refuses a URI no concept holds. Because the value is the URI,
a default is written as one, with no lookup:

```python
status = ConceptField(
    vocabulary="sample-status",
    default="https://example.org/sample-status/unknown",
)
```

`vocabulary` names the owning `ConceptScheme` by its slug rather than by a database relation. A
field declaration is read when Python imports the module, and a vocabulary is rows in a table that
may not exist yet, so the slug is all the field can carry.

`vocabulary="rock-type"` restricts to one vocabulary. A list restricts to the union of the named
vocabularies, and the refusal names every vocabulary the field accepts. Leaving `vocabulary` out
entirely restricts nothing: any concept in the database is a valid choice. That last shape is for a
field drawing on whatever a project has imported rather than one fixed list.

When the field names at least one vocabulary, only a concept whose `scheme.slug` matches is offered
as a form choice or accepted by `full_clean()`. A concept from any other vocabulary is refused.
Deleting a concept a row still references is refused whichever shape you declare
(`on_delete=PROTECT`), whether the delete reaches it directly or cascades down from its vocabulary.

Reading a concept back:

```python
specimen.rock_type              # the attached Record, or None
specimen.get_rock_type_label()  # its name in the active language, falling back to its
                                # preferred label in the vocabulary's default language
specimen.get_rock_type_uri()    # its URI, read from the column with no query
```

If `"rock-type"` has not been loaded yet, which is the state of a fresh install before
`manage.py sync_vocabularies` has run, nothing about the field declaration fails. `manage.py check`
reports a warning naming the model, the field, and the missing slug:

- `controlled_vocabularies.W001` when the vocabulary is declared in `CONTROLLED_VOCABULARIES` and
  has not been loaded yet. Run `sync_vocabularies`.
- `controlled_vocabularies.W006` when it is neither declared nor loaded. Declare it (see
  [importing a published vocabulary](importing.md#declaring-vocabularies)).

A vocabulary loaded some other way, with `import_skos` for example, is not reported whether or not
it is declared. If the vocabulary genuinely arrives in a later deployment step, silence the warning
with `SILENCED_SYSTEM_CHECKS`.

Reading `get_<field>_label()` on every row of a list costs a query for the concept, per row.
`get_<field>_uri()` costs nothing, because the URI is the column's own value.
`select_related("rock_type")` collapses that back to one query for the whole list.

## Attaching several concepts to your model

`MultiConceptField` is the many-to-many counterpart: several concepts on one record instead of one.
`vocabulary` takes the same three shapes it takes on `ConceptField`, and means the same thing by
each:

```python
from django.db import models

from controlled_vocabularies.fields import MultiConceptField


class Sample(models.Model):
    name = models.CharField(max_length=200)
    rock_types = MultiConceptField(vocabulary=["igneous", "sedimentary"])  # several vocabularies
    keywords = MultiConceptField(blank=True)  # no vocabulary named
```

The table linking a row to its concepts holds each concept's URI too, the same way.

One slug restricts to that vocabulary, a list restricts to the union of the named vocabularies, and
leaving `vocabulary` out — as `keywords` does above — restricts nothing. A concept outside the
named vocabularies is refused, and the refusal names every vocabulary the field accepts.

Reading concepts back:

```python
sample.rock_types                    # the many-to-many manager
sample.get_rock_types_labels()       # a list of names, active language with fallback
sample.get_rock_types_uris()         # a list of URIs, same order
```

Both accessors return an empty list for a row holding nothing, including one that has not been
saved yet, rather than raising.

**Required and optional.** `blank=True`, as on `keywords` above, makes the field optional: a row
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

## Restricting a field to a collection

Naming a vocabulary offers every concept it holds. Large vocabularies are often too much to put in
front of someone filling in one field. `ConceptField` and `MultiConceptField` both take one more
argument on top of `vocabulary` for this: `collection`, the slug of a collection the publisher
defined in that vocabulary. Both fields accept it with the same effect.

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField


class CoreSample(models.Model):
    name = models.CharField(max_length=200)

    # Only concepts in the "core-samples" collection of "rock-type".
    rock_type = ConceptField(vocabulary="rock-type", collection="core-samples")
```

Use `collection` where the publisher has already grouped the concepts the field should offer. The
group is then kept in the vocabulary rather than in your code, and a later import of the vocabulary
updates it.

A collection restriction narrows one vocabulary and never several, so declaring `collection`
alongside more than one `vocabulary` slug, or alongside none, is refused when the module is
imported, before the app starts. `collection` must also be a non-empty string.

A collection's members are the concepts its `skos:member` and `skos:memberList` statements link
to. They are read from the collection each time a choice is validated or searched, so an import that
changes the collection changes the field at once.

The collection a restriction names does not have to exist when the field is declared, any more than
an unrestricted field's own `vocabulary` does. If it never arrives, or arrives misspelled, the field
offers nothing at all rather than raising. Every choice and every search comes back empty, which
looks the same from outside as a vocabulary that has not been imported. `manage.py check` catches
it: `controlled_vocabularies.W005` names the model, the field and the missing collection, the way
`controlled_vocabularies.W001` and `controlled_vocabularies.W006` already do for an absent
vocabulary.

A collection the publisher marked as ordered (`skos:OrderedCollection`) buys a field restricted to
it one more thing. The concept search offers the collection's members in the publisher's sequence
while the search box is still empty, then falls back to relevance order as soon as someone types.
No order is promised anywhere else, including a `ModelForm`'s rendered choices and any unordered
collection.

---

Next: [choosing a concept](search.md).
