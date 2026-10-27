"""Turn a stored document back into an RDF graph (FS-018)."""

import rdflib
from rdflib.collection import Collection as RdfList
from rdflib.namespace import RDF, SKOS

from controlled_vocabularies.predicates import PREFIXES, Namespaces


def document_graph(uri: str, document: dict, rdf_class: str) -> rdflib.Graph:
    """Build the graph a row's document states about its own subject.

    Args:
        uri: The row's identifier, used unchanged as the subject.
        document: The row's stored document: predicate to a list of entries.
        rdf_class: The CURIE of the class to state when the document states no
            ``rdf:type`` of its own, such as ``skos:ConceptScheme``.

    Returns:
        A graph holding every statement of the document, with ``skos:memberList`` as one
        RDF list in stored order and each embedded node as a blank node. It binds the
        prefixes the documents use, so a serialization comes out readable.
    """
    graph = rdflib.Graph()
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace)

    def add_statements(subject: rdflib.term.Node, statements: dict) -> None:
        """Add the statements of one subject, recursing into embedded nodes.

        Args:
            subject: The URI or blank node the statements are about.
            statements: Predicate to a list of entries.
        """
        for key, entries in statements.items():
            predicate = rdflib.URIRef(Namespaces.expand(key))
            if predicate == SKOS.memberList:
                head = RdfList(
                    graph, rdflib.BNode(), [rdflib.URIRef(e["@id"]) for e in entries]
                ).uri
                graph.add((subject, predicate, head))
                continue
            for entry in entries:
                if "@id" in entry:
                    obj: rdflib.term.Node = rdflib.URIRef(entry["@id"])
                elif "@value" in entry:
                    obj = literal(entry)
                else:
                    obj = rdflib.BNode()
                    add_statements(obj, entry)
                graph.add((subject, predicate, obj))

    def literal(entry: dict) -> rdflib.Literal:
        """Return the literal an ``@value`` entry states.

        Args:
            entry: An entry holding ``@value`` and at most a language or a datatype.

        Returns:
            The literal; a JSON number or boolean keeps rdflib's own datatype for it.
        """
        if "@language" in entry:
            return rdflib.Literal(entry["@value"], lang=entry["@language"])
        if "@type" in entry:
            return rdflib.Literal(
                str(entry["@value"]),
                datatype=rdflib.URIRef(Namespaces.expand(entry["@type"])),
            )
        return rdflib.Literal(entry["@value"])

    subject = rdflib.URIRef(uri)
    add_statements(subject, document)
    if (subject, RDF.type, None) not in graph:
        graph.add((subject, RDF.type, rdflib.URIRef(Namespaces.expand(rdf_class))))
    return graph
