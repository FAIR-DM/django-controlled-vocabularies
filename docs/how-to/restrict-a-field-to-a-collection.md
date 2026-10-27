# Restrict a field to a collection

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
