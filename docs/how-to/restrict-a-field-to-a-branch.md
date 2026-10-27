# Restrict a field to a branch

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
