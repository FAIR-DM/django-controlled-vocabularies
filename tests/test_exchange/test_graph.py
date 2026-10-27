"""Tests for controlled_vocabularies.exchange.graph."""

from pathlib import Path

import pytest
import rdflib
from rdflib.collection import Collection as RdfList
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD

from controlled_vocabularies.exchange.graph import document_graph
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.models import ConceptScheme, Record

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"

SUBJECT = "http://example.org/rocks/granite"
OTHER = "http://example.org/rocks/quartz"
CONCEPT = "skos:Concept"


def expected(*triples, subject=SUBJECT):
    """Return a graph of ``(predicate, object)`` pairs about the subject."""
    graph = rdflib.Graph()
    for predicate, obj in triples:
        graph.add((rdflib.URIRef(subject), predicate, obj))
    return graph


TYPE = (RDF.type, SKOS.Concept)


class TestDocumentGraph:
    def test_link_becomes_a_uri_object(self):
        graph = document_graph(SUBJECT, {"skos:broader": [{"@id": OTHER}]}, CONCEPT)

        assert isomorphic(graph, expected(TYPE, (SKOS.broader, rdflib.URIRef(OTHER))))

    def test_language_tagged_literal(self):
        graph = document_graph(
            SUBJECT,
            {"skos:prefLabel": [{"@value": "Granit", "@language": "de"}]},
            CONCEPT,
        )

        assert isomorphic(
            graph,
            expected(TYPE, (SKOS.prefLabel, rdflib.Literal("Granit", lang="de"))),
        )

    def test_typed_literal_stored_as_a_curie(self):
        graph = document_graph(
            SUBJECT,
            {"dcterms:modified": [{"@value": "2024-05-01", "@type": "xsd:date"}]},
            CONCEPT,
        )

        assert isomorphic(
            graph,
            expected(
                TYPE,
                (DCTERMS.modified, rdflib.Literal("2024-05-01", datatype=XSD.date)),
            ),
        )

    def test_plain_literal(self):
        graph = document_graph(SUBJECT, {"skos:notation": [{"@value": "G1"}]}, CONCEPT)

        assert isomorphic(graph, expected(TYPE, (SKOS.notation, rdflib.Literal("G1"))))

    def test_json_integer_and_boolean_keep_their_datatypes(self):
        graph = document_graph(
            SUBJECT,
            {
                "skos:notation": [{"@value": 7}],
                "skos:note": [{"@value": True}],
            },
            CONCEPT,
        )

        assert isomorphic(
            graph,
            expected(
                TYPE,
                (SKOS.notation, rdflib.Literal(7)),
                (SKOS.note, rdflib.Literal(True)),
            ),
        )

    def test_key_stored_as_a_full_uri(self):
        predicate = "http://example.org/vocab/hardness"
        graph = document_graph(SUBJECT, {predicate: [{"@value": "7"}]}, CONCEPT)

        assert isomorphic(
            graph,
            expected(TYPE, (rdflib.URIRef(predicate), rdflib.Literal("7"))),
        )

    def test_embedded_node_becomes_a_blank_node(self):
        graph = document_graph(
            SUBJECT,
            {"skos:note": [{"rdf:value": [{"@value": "hard"}]}]},
            CONCEPT,
        )

        node = rdflib.BNode()
        want = expected(TYPE, (SKOS.note, node))
        want.add((node, RDF.value, rdflib.Literal("hard")))
        assert isomorphic(graph, want)

    def test_embedded_node_inside_an_embedded_node(self):
        graph = document_graph(
            SUBJECT,
            {"skos:note": [{"rdf:value": [{"rdf:value": [{"@value": "deep"}]}]}]},
            CONCEPT,
        )

        outer, inner = rdflib.BNode(), rdflib.BNode()
        want = expected(TYPE, (SKOS.note, outer))
        want.add((outer, RDF.value, inner))
        want.add((inner, RDF.value, rdflib.Literal("deep")))
        assert isomorphic(graph, want)

    def test_member_list_is_one_rdf_list_in_stored_order(self):
        members = [OTHER, SUBJECT, "http://example.org/rocks/basalt"]
        graph = document_graph(
            "http://example.org/rocks/collection/seq",
            {"skos:memberList": [{"@id": uri} for uri in members]},
            "skos:OrderedCollection",
        )

        heads = list(graph.objects(None, SKOS.memberList))
        assert len(heads) == 1
        assert [str(m) for m in RdfList(graph, heads[0])] == members

    def test_member_links_stay_plain_triples(self):
        graph = document_graph(
            SUBJECT, {"skos:member": [{"@id": OTHER}]}, "skos:Collection"
        )

        assert len(list(graph.objects(None, SKOS.memberList))) == 0
        assert (rdflib.URIRef(SUBJECT), SKOS.member, rdflib.URIRef(OTHER)) in graph

    def test_type_is_added_from_rdf_class_when_the_document_states_none(self):
        graph = document_graph(SUBJECT, {}, "skos:Collection")

        assert list(graph.objects(rdflib.URIRef(SUBJECT), RDF.type)) == [
            SKOS.Collection
        ]

    def test_stated_type_is_kept_and_nothing_is_added(self):
        graph = document_graph(
            SUBJECT, {"rdf:type": [{"@id": str(SKOS.Concept)}]}, CONCEPT
        )

        assert list(graph.objects(rdflib.URIRef(SUBJECT), RDF.type)) == [SKOS.Concept]

    def test_stated_type_differing_from_rdf_class_wins(self):
        graph = document_graph(
            SUBJECT, {"rdf:type": [{"@id": str(SKOS.Collection)}]}, CONCEPT
        )

        assert list(graph.objects(rdflib.URIRef(SUBJECT), RDF.type)) == [
            SKOS.Collection
        ]

    def test_urn_identifier_is_the_subject_unchanged(self):
        graph = document_graph("urn:uuid:1234", {}, CONCEPT)

        assert list(graph.subjects()) == [rdflib.URIRef("urn:uuid:1234")]

    def test_empty_document_gives_exactly_the_type_triple(self):
        graph = document_graph(SUBJECT, {}, CONCEPT)

        assert isomorphic(graph, expected(TYPE))

    def test_prefixes_are_bound_for_readable_output(self):
        graph = document_graph(SUBJECT, {}, CONCEPT)

        assert "skos" in dict(graph.namespaces())


@pytest.mark.django_db
class TestImportedRowsRoundTrip:
    def test_every_stored_row_gives_the_subgraph_the_file_states(self):
        path = FIXTURES / "rocks.ttl"
        parsed = rdflib.Graph().parse(str(path), format="turtle")
        import_skos(path)

        rows = [*ConceptScheme.objects.all(), *Record.objects.all()]
        assert len(rows) > 1
        for row in rows:
            built = document_graph(row.uri, row.data, "skos:Concept")
            assert isomorphic(built, self.subgraph(parsed, rdflib.URIRef(row.uri)))

    @staticmethod
    def subgraph(graph, subject):
        """Return the triples about ``subject``, following blank-node objects."""
        found = rdflib.Graph()
        pending = [subject]
        while pending:
            node = pending.pop()
            for triple in graph.triples((node, None, None)):
                found.add(triple)
                if isinstance(triple[2], rdflib.BNode):
                    pending.append(triple[2])
        return found
