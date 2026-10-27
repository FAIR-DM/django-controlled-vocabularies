# Read a row back as RDF

`to_graph()` is the reverse of the import. A `ConceptScheme` or a `Record` returns an
`rdflib.Graph` built from its stored document:

```python
from controlled_vocabularies.models import Record

record = Record.objects.get(uri="http://example.org/rocks/granite")
print(record.to_graph().serialize(format="turtle"))
```

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<http://example.org/rocks/granite> a skos:Concept ;
    skos:broader <http://example.org/rocks/igneous> ;
    skos:prefLabel "Granite"@en .
```

The graph holds the row's own statements and nothing gathered from other rows: a concept's
graph does not include the labels of the concept it links to, and a vocabulary's graph does
not include its concepts. The subject is the row's `uri`, unchanged.

Every statement of the document is in the graph, in every language, and a `skos:memberList` is
written as one RDF list in its stored order. A row whose document states no `rdf:type` is given
one: `skos:ConceptScheme` for a vocabulary, and a record's `type` for a record. A record whose
document states no `skos:inScheme` is given its own vocabulary. A document that states either keeps
exactly what it states.

`to_graph()` calls `document_graph()`, from `controlled_vocabularies.exchange.graph`, which does
the same for any document in the stored shape, such as one not yet saved:
`document_graph(uri, document, rdf_class)`.

`controlled_vocabularies.exchange.serializations.Serialization` lists the formats the installed
rdflib can write a graph in faithfully, and writes a graph in one of them:

```python
from controlled_vocabularies.exchange.serializations import Serialization

turtle = Serialization.named("ttl")  # any name rdflib registers, such as "turtle" or "text/turtle"
data = turtle.serialize(record.to_graph())  # bytes
turtle.media_type, turtle.extension, turtle.label  # ("text/turtle", "ttl", "Turtle")
[s.name for s in Serialization.all()]  # every format offered
```

The list follows the installed rdflib. Two of its writers are left out: `patch`, whose output is a
change between graphs, and `pretty-xml`, which can repeat part of an RDF list (`xml` writes the
same syntax). A format that names graphs, such as TriG, N-Quads or TriX, holds the statements in
its default graph, so a reader expecting one graph finds them there. `serialize()` raises
`ValueError` when the format cannot express one of the graph's terms, as RDF/XML cannot a
property whose address ends in `/`.
