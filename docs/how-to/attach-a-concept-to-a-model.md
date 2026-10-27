# Attach a concept to a model

Two model fields attach concepts to your own records: `ConceptField` for one concept, and
`MultiConceptField` for several. Both can be restricted to the vocabularies you name, and narrowed
further to the members of a collection or to a branch of the vocabulary's hierarchy.

Both fields point at `Record`, the model that holds every concept and collection of a vocabulary
(see [importing](../explanation/what-an-import-keeps.md)). They are limited to the records whose type is
`skos:Concept`, so a collection is never offered or accepted as a choice.

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
[importing a published vocabulary](load-the-vocabularies-your-site-uses.md#vocabularies-your-models-name)). A field naming a
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

## Shipping a model in a reusable app

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
