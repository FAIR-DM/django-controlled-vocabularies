# Import a SKOS file from Python

`import_skos()` reads a SKOS file — Turtle, RDF/XML, or JSON-LD — and creates or updates the
vocabulary it declares, along with every concept and collection it contains. It keeps every
statement the file makes about them, in every language. Each row is matched by its URI, never by
name, so importing the same file twice updates the same rows rather than duplicating them. Both
commands load through it.

```python
from controlled_vocabularies.exchange import import_skos

report = import_skos("rocks.ttl")
```

The caller may name a target `ConceptScheme` for a file that declares no vocabulary of its own, or
have it checked against one the file does declare:

```python
report = import_skos("rocks.ttl", scheme=my_scheme)
```

Re-running an import upserts rather than deleting and recreating. For a record the file still
contains, the file is authoritative: the record's statements end up matching the file exactly,
including the removal of a statement the file no longer carries. A record the file does not mention
at all is left completely untouched and named in the report instead, never deleted.
