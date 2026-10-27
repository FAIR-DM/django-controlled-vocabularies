"""Tests for controlled_vocabularies.exchange.serializations."""

import pytest
import rdflib
import rdflib.plugin
from rdflib.serializer import Serializer

from controlled_vocabularies.exchange.graph import document_graph
from controlled_vocabularies.exchange.serializations import Serialization

SUBJECT = "http://example.org/rocks/granite"

#: A document with a language-tagged literal, a plain literal, an embedded (blank) node
#: and an RDF list.
DOCUMENT = {
    "skos:prefLabel": [{"@value": "Granit", "@language": "de"}],
    "skos:notation": [{"@value": "G1"}],
    "skos:note": [{"rdf:value": [{"@value": "hard"}]}],
    "skos:memberList": [
        {"@id": "http://example.org/rocks/a"},
        {"@id": "http://example.org/rocks/b"},
    ],
}


class ProbeSerializer(Serializer):
    """A serializer a test registers with rdflib to prove the table follows it."""

    def serialize(self, stream, base=None, encoding=None, **args):
        stream.write(b"probe")


@pytest.fixture
def fresh_table():
    Serialization.all.cache_clear()
    yield
    Serialization.all.cache_clear()


def by_name(name):
    found = Serialization.named(name)
    assert found is not None, name
    return found


@pytest.mark.usefixtures("fresh_table")
class TestSerializationTable:
    def test_patch_and_pretty_xml_are_not_offered(self):
        names = {name for s in Serialization.all() for name in s.names}

        assert not names & {"patch", "pretty-xml"}

    @pytest.mark.parametrize(
        ("name", "media_type"),
        [
            ("ttl", "text/turtle"),
            ("xml", "application/rdf+xml"),
            ("json-ld", "application/ld+json"),
            ("nt", "application/n-triples"),
        ],
    )
    def test_core_formats_are_offered_by_short_name_and_media_type(
        self, name, media_type
    ):
        assert by_name(name).media_type == media_type
        assert Serialization.for_media_type(media_type) is by_name(name)

    @pytest.mark.parametrize(
        ("alias", "name"),
        [("turtle", "ttl"), ("ntriples", "nt"), ("text/turtle", "ttl")],
    )
    def test_every_registered_name_is_accepted(self, alias, name):
        assert Serialization.named(alias) is by_name(name)

    def test_unknown_name_is_none(self):
        assert Serialization.named("no-such-format") is None
        assert Serialization.for_media_type("text/x-nothing") is None

    @pytest.mark.parametrize("name", ["nquads", "trix"])
    def test_dataset_serializers_are_marked_quads(self, name):
        assert by_name(name).quads is True

    def test_turtle_is_not_written_from_a_dataset(self):
        assert by_name("ttl").quads is False

    @pytest.mark.parametrize(
        ("name", "extension"),
        [
            ("ttl", "ttl"),
            ("xml", "rdf"),
            ("json-ld", "jsonld"),
            ("nt", "nt"),
            ("longturtle", "ttl"),
        ],
    )
    def test_extension(self, name, extension):
        assert by_name(name).extension == extension

    def test_every_serialization_has_a_media_type(self):
        assert all(s.media_type for s in Serialization.all())

    def test_negotiable_exactly_when_rdflib_registers_a_slash_name(self):
        for s in Serialization.all():
            assert s.negotiable == any("/" in name for name in s.names), s.name

    def test_formats_without_a_registered_media_type_reuse_a_neighbours(self):
        assert by_name("longturtle").media_type == "text/turtle"
        assert by_name("nt11").media_type == "application/n-triples"
        assert by_name("hext").media_type == "application/x-ndjson"

    def test_a_serializer_registered_at_test_time_is_offered(self):
        rdflib.plugin.register("x-probe", Serializer, __name__, "ProbeSerializer")
        rdflib.plugin.register("text/x-probe", Serializer, __name__, "ProbeSerializer")
        try:
            Serialization.all.cache_clear()
            offered = Serialization.for_media_type("text/x-probe")
        finally:
            # rdflib has no public way to unregister a plugin.
            for name in ("x-probe", "text/x-probe"):
                rdflib.plugin._plugins.pop((name, Serializer), None)

        assert offered is not None
        assert offered.name == "x-probe"
        assert offered.negotiable


@pytest.mark.usefixtures("fresh_table")
class TestSerialize:
    @pytest.mark.parametrize("serialization", Serialization.all(), ids=lambda s: s.name)
    def test_output_reads_back_to_the_same_statements(
        self, serialization, rdf_read_back
    ):
        # Fresh blank nodes each time: some serializers' output depends on the order
        # they visit blank nodes, which changes from run to run.
        for _ in range(8):
            graph = document_graph(SUBJECT, DOCUMENT, "skos:Concept")

            assert rdf_read_back.survives(serialization, graph)

    def test_serialize_returns_bytes(self):
        graph = document_graph(SUBJECT, DOCUMENT, "skos:Concept")

        assert isinstance(by_name("ttl").serialize(graph), bytes)
