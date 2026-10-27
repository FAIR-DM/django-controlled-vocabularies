# Attaching concepts to your models

Two model fields attach concepts to your own records: `ConceptField` for one concept, and
`MultiConceptField` for several. Both can be restricted to the vocabularies you name, and narrowed
further to the members of a collection or to a branch of the vocabulary's hierarchy.

Both fields point at `Record`, the model that holds every concept and collection of a vocabulary
(see [importing](importing.md#what-an-import-keeps)). They are limited to the records whose type is
`skos:Concept`, so a collection is never offered or accepted as a choice.

## Attaching a concept to your model

`ConceptField` is a `ForeignKey` to `Record`, optionally restricted to the vocabularies you name.
A field names a vocabulary by its URI, the identifier its publisher gave the concept scheme.
`vocabulary` takes three shapes:

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField, Vocabulary

ROCK_TYPE = Vocabulary(
    "https://vocab.example.org/rock-type",
    source="https://vocab.example.org/rock-type.ttl",
)
MINERAL = "https://vocab.example.org/mineral"


class Specimen(models.Model):
    name = models.CharField(max_length=200)
    rock_type = ConceptField(vocabulary=ROCK_TYPE)                      # one vocabulary
    dominant_material = ConceptField(vocabulary=[ROCK_TYPE, MINERAL])  # several
    keyword = ConceptField(null=True, blank=True)                      # no vocabulary named
```

The column the field adds holds the concept's URI, not a database id: `rock_type_id` reads
`https://vocab.example.org/rock-type/granite`. A database dump, a CSV export or an API response
can be read without a join, and the value keeps its meaning when the rows move to another
database. It is still a foreign key, so the database refuses a URI no concept holds. Because the
value is the URI, a default is written as one, with no lookup:

```python
status = ConceptField(
    vocabulary="https://vocab.example.org/sample-status",
    default="https://vocab.example.org/sample-status/unknown",
)
```

Each vocabulary is named either by its URI as a string, or by a `Vocabulary`, which carries the URI
and where the vocabulary is published:

- `uri` — the URI of the vocabulary's concept scheme, exactly as the publisher wrote it.
- `source`, optional — a local path, as a string or a `Path`, or an `http://`/`https://` address
  the vocabulary can be read from.
- `format`, optional — the serialization (`turtle`, `xml` or `json-ld`), for a source whose name
  or `Content-Type` does not carry one.

`manage.py sync_vocabularies` loads every vocabulary a field names, from its `source`, or from the
URI itself when there is none (see
[importing a published vocabulary](importing.md#vocabularies-your-models-name)). A field naming a
vocabulary by URI alone suits a publisher whose URIs answer with the vocabulary, or a vocabulary
the site declares in `CONTROLLED_VOCABULARIES`.

A slug is refused with a `TypeError` when the module is imported. A slug is a name this site
gives a vocabulary, so a field naming one would mean something different on another site.

`vocabulary=ROCK_TYPE` restricts to one vocabulary. A list restricts to the union of the named
vocabularies, and the refusal names every vocabulary the field accepts. Leaving `vocabulary` out
entirely restricts nothing: any concept in the database is a valid choice. That last shape is for a
field drawing on whatever a project has imported rather than one fixed list.

When the field names at least one vocabulary, only a concept whose vocabulary's URI matches is
offered as a form choice or accepted by `full_clean()`. A concept from any other vocabulary is
refused. Deleting a concept a row still references is refused whichever shape you declare
(`on_delete=PROTECT`), whether the delete reaches it directly or cascades down from its vocabulary.

A migration records each vocabulary's URI and nothing else, so changing a `source` never needs a
new migration.

Reading a concept back:

```python
specimen.rock_type              # the attached Record, or None
specimen.get_rock_type_label()  # its name in the active language, falling back to its
                                # preferred label in the vocabulary's default language
specimen.get_rock_type_uri()    # its URI, read from the column with no query
```

If a named vocabulary has not been loaded yet, which is the state of a fresh install before
`manage.py sync_vocabularies` has run, nothing about the field declaration fails. `manage.py check`
reports a warning, `controlled_vocabularies.W001`, naming the model, the field, and the missing
vocabulary's URI. Run `sync_vocabularies`. If the vocabulary genuinely arrives in a later
deployment step, silence the warning with `SILENCED_SYSTEM_CHECKS`.

Reading `get_<field>_label()` on every row of a list costs a query for the concept, per row.
`get_<field>_uri()` costs nothing, because the URI is the column's own value.
`select_related("rock_type")` collapses that back to one query for the whole list.

### Shipping a model in a reusable app

An abstract model in a package of your own can carry concept fields, and every project that
inherits from it gets a working field without declaring anything:

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField, Vocabulary

SAMPLE_STATUS = Vocabulary(
    "https://vocab.example.org/sample-status",
    source="https://vocab.example.org/sample-status.ttl",
)


class SampleBase(models.Model):
    status = ConceptField(vocabulary=SAMPLE_STATUS)

    class Meta:
        abstract = True
```

The project runs `sync_vocabularies`, and the vocabulary is loaded from the source the package
gave. A source can also be a file the package ships, read with a path such as
`Path(__file__).parent / "sample-status.ttl"`. Only a model the project actually installs counts,
so an abstract model nothing inherits from loads nothing.

A project that wants the vocabulary from somewhere else, a copy it ships so deploys never fetch
anything, declares the same vocabulary in `CONTROLLED_VOCABULARIES`. The declared source is loaded
instead, and the package's is never read.

## Attaching several concepts to your model

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
argument on top of `vocabulary` for this: `collection`, the URI of a collection the publisher
defined in that vocabulary. Both fields accept it with the same effect.

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField

ROCK_TYPE = "https://vocab.example.org/rock-type"
CORE_SAMPLES = "https://vocab.example.org/rock-type/core-samples"


class CoreSample(models.Model):
    name = models.CharField(max_length=200)

    # Only concepts in the core-samples collection of the rock-type vocabulary.
    rock_type = ConceptField(vocabulary=ROCK_TYPE, collection=CORE_SAMPLES)
```

Use `collection` where the publisher has already grouped the concepts the field should offer. The
group is then kept in the vocabulary rather than in your code, and a later import of the vocabulary
updates it.

A collection restriction narrows one vocabulary and never several, so declaring `collection`
alongside more than one vocabulary, or alongside none, is refused when the module is imported,
before the app starts. `collection` must also be a URI, and a slug is refused.

A collection's members are the concepts its `skos:member` and `skos:memberList` statements link
to. They are read from the collection each time a choice is validated or searched, so an import that
changes the collection changes the field at once.

The collection a restriction names does not have to exist when the field is declared, any more than
an unrestricted field's own `vocabulary` does. If it never arrives, or arrives misspelled, the field
offers nothing at all rather than raising. Every choice and every search comes back empty, which
looks the same from outside as a vocabulary that has not been imported. `manage.py check` catches
it: `controlled_vocabularies.W005` names the model, the field and the missing collection, the way
`controlled_vocabularies.W001` already does for an absent vocabulary.

A collection the publisher marked as ordered (`skos:OrderedCollection`) buys a field restricted to
it one more thing. The concept search offers the collection's members in the publisher's sequence
while the search box is still empty, then falls back to relevance order as soon as someone types.
No order is promised anywhere else, including a `ModelForm`'s rendered choices and any unordered
collection.

## Restricting a field to a branch

Most published vocabularies state a hierarchy, with `skos:broader` and `skos:narrower` links, and
few publish collections. `branch` narrows a field to one concept and everything below it. Both
fields accept it with the same effect. It takes the URI of the concept the branch grows from, its
root:

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField

ROCK_TYPE = "https://vocab.example.org/rock-type"
IGNEOUS = "https://vocab.example.org/rock-type/igneous"


class IgneousSample(models.Model):
    name = models.CharField(max_length=200)

    # Igneous, and every concept below it in the rock-type vocabulary.
    rock_type = ConceptField(vocabulary=ROCK_TYPE, branch=IGNEOUS)
```

The branch includes its root, so `igneous` is a choice as well as the concepts below it, however
deep. A concept's broader concept and its siblings are not choices: the branch runs downward only.
A root with nothing below it admits exactly itself.

A concept is below another when its own document states `skos:broader` the other, or when the
other's document states `skos:narrower` it. Either statement counts, at every level, which is the
hierarchy the vocabulary's pages show. Only concepts of the one named vocabulary are followed, so a
link to a concept held elsewhere leads nowhere, and a collection is never a choice.

Some rules apply when the module is imported, and each raises a `TypeError`:

- `branch` must be a URI, and a slug is refused.
- A branch restriction narrows one vocabulary, so `vocabulary` must name exactly one.
- A field carries at most one restriction, so `branch` cannot be combined with `collection`. They
  narrow in different ways, and a declaration that gave both would not say whether the field offers
  their overlap or their union.

The branch is read each time a value is validated, a form is built or a search runs, so an import
that adds a concept below the root changes the field at once, with no code change and no restart.
The read is one query over the links of the vocabulary, and it ends if the links ever form a cycle.

The root does not have to exist when the field is declared. If it never arrives, arrives
misspelled, or is a collection and not a concept, the field offers nothing at all. Every choice and
every search comes back empty, which looks the same from outside as a vocabulary that has not been
imported. `manage.py check` catches it: `controlled_vocabularies.W005`, the warning that already
reports a missing collection, names the model, the field, the root and the vocabulary.

---

Next: [choosing a concept](choosing-a-concept.md).
