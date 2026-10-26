"""Tests for controlled_vocabularies.exchange.skos."""

from pathlib import Path

import pytest
import rdflib
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.functional import Promise

import controlled_vocabularies.exchange as exchange
from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
    UnsafeJsonLdError,
    UnsafeRdfXmlError,
)
from controlled_vocabularies.exchange.report import FatalReason
from controlled_vocabularies.exchange.skos import SkosImporter, import_skos
from controlled_vocabularies.models import ConceptScheme, Record
from tests.factories import ConceptSchemeFactory, RecordFactory, labelled

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"
SECURITY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "security"

SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
ROCKS = "http://example.org/rocks/"
GRANITE = "http://example.org/rocks/granite"
QUARTZ = "http://example.org/rocks/quartz"
BASALT = "http://example.org/rocks/basalt"
SEDIMENTARY = "http://example.org/rocks/sedimentary"
SILICA_BEARING = "http://example.org/rocks/collection/silica-bearing"
EXAMPLE_SEQUENCE = "http://example.org/rocks/collection/example-sequence"

BASE_SERIALIZATIONS = [
    ("rocks.ttl", "turtle"),
    ("rocks.rdf", "xml"),
    ("rocks.jsonld", "json-ld"),
]

PREFIXES = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

# Written per test rather than committed to tests/fixtures/skos/: an all-relative
# document can only be read against a base address.
RELATIVE_URIS_TURTLE = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<>
    a skos:ConceptScheme ;
    skos:prefLabel "Relative vocabulary"@en ;
    skos:hasTopConcept <concept-a> .

<concept-a>
    a skos:Concept ;
    skos:inScheme <> ;
    skos:topConceptOf <> ;
    skos:prefLabel "Concept A"@en .

<concept-b>
    a skos:Concept ;
    skos:inScheme <> ;
    skos:prefLabel "Concept B"@en ;
    skos:broader <concept-a> .
"""

RELATIVE_URIS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:skos="http://www.w3.org/2004/02/skos/core#">

  <skos:ConceptScheme rdf:about="">
    <skos:prefLabel xml:lang="en">Relative vocabulary</skos:prefLabel>
    <skos:hasTopConcept rdf:resource="concept-a"/>
  </skos:ConceptScheme>

  <skos:Concept rdf:about="concept-a">
    <skos:inScheme rdf:resource=""/>
    <skos:topConceptOf rdf:resource=""/>
    <skos:prefLabel xml:lang="en">Concept A</skos:prefLabel>
  </skos:Concept>

  <skos:Concept rdf:about="concept-b">
    <skos:inScheme rdf:resource=""/>
    <skos:prefLabel xml:lang="en">Concept B</skos:prefLabel>
    <skos:broader rdf:resource="concept-a"/>
  </skos:Concept>

</rdf:RDF>
"""

RELATIVE_URIS_JSONLD = """{
  "@context": {
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prefLabel": {"@id": "skos:prefLabel"},
    "inScheme": {"@id": "skos:inScheme", "@type": "@id"},
    "topConceptOf": {"@id": "skos:topConceptOf", "@type": "@id"},
    "hasTopConcept": {"@id": "skos:hasTopConcept", "@type": "@id"},
    "broader": {"@id": "skos:broader", "@type": "@id"}
  },
  "@graph": [
    {
      "@id": "",
      "@type": "skos:ConceptScheme",
      "prefLabel": {"@value": "Relative vocabulary", "@language": "en"},
      "hasTopConcept": "concept-a"
    },
    {
      "@id": "concept-a",
      "@type": "skos:Concept",
      "inScheme": "",
      "topConceptOf": "",
      "prefLabel": {"@value": "Concept A", "@language": "en"}
    },
    {
      "@id": "concept-b",
      "@type": "skos:Concept",
      "inScheme": "",
      "prefLabel": {"@value": "Concept B", "@language": "en"},
      "broader": "concept-a"
    }
  ]
}
"""

RELATIVE_SERIALIZATIONS = [
    ("relative-uris.ttl", "turtle", RELATIVE_URIS_TURTLE),
    ("relative-uris.rdf", "xml", RELATIVE_URIS_XML),
    ("relative-uris.jsonld", "json-ld", RELATIVE_URIS_JSONLD),
]


def write_turtle(tmp_path: Path, body: str, name: str = "vocabulary.ttl") -> Path:
    """Write a Turtle file that starts with the usual prefixes.

    Args:
        tmp_path: Directory to write the file into.
        body: The statements, after the prefixes.
        name: The file name.

    Returns:
        The path of the written file.
    """
    path = tmp_path / name
    path.write_text(PREFIXES + body)
    return path


def write_deeply_nested_jsonld(tmp_path: Path, depth: int) -> Path:
    """Write a JSON-LD document nesting one object inside another ``depth`` times.

    Built as raw text because ``json.dump`` hits Python's recursion limit before the
    file is written, at a depth well below what reproduces the parser's own recursion
    failure.

    Args:
        tmp_path: Directory to write the file into.
        depth: How many objects to nest.

    Returns:
        The path of the written file.
    """
    parts = ['{"@id":"http://example.org/deep/","nested":'] * depth
    parts.append('{"val":0}')
    parts.extend(["}"] * depth)
    path = tmp_path / "deep.jsonld"
    path.write_text("".join(parts))
    return path


def fatal_reasons(excinfo) -> set[FatalReason]:
    """Return the reasons recorded on a refused run's report."""
    return {finding.reason for finding in excinfo.value.report.fatal}


def stored_documents() -> dict[str, dict]:
    """Return every stored record's document, keyed by URI."""
    return {record.uri: record.data for record in Record.objects.all()}


class TestReadGraph:
    @pytest.mark.parametrize("filename", ["rocks.ttl", "rocks.rdf", "rocks.jsonld"])
    def test_each_supported_serialization_parses_by_extension(self, filename):
        graph = SkosImporter(FIXTURES / filename).read_graph()

        assert (rdflib.URIRef(ROCKS), rdflib.RDF.type, SKOS.ConceptScheme) in graph

    @pytest.mark.parametrize("filename,serialization", BASE_SERIALIZATIONS)
    def test_each_supported_serialization_parses_with_the_stated_format(
        self, filename, serialization
    ):
        graph = SkosImporter(
            FIXTURES / filename, serialization=serialization
        ).read_graph()

        assert len(graph) > 0

    def test_a_missing_file_fails_naming_the_file(self, tmp_path):
        missing = tmp_path / "does-not-exist.ttl"

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(missing).read_graph()

        assert excinfo.value.code == "skos_file_not_found"
        assert excinfo.value.params["file"] == str(missing)

    def test_an_unparseable_file_fails_naming_the_file(self, tmp_path):
        bad = tmp_path / "bad.ttl"
        bad.write_text("this is not turtle @@@ not even close {{{ ]][[ ")

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(bad).read_graph()

        assert excinfo.value.code == "skos_parse_failed"
        assert excinfo.value.params["file"] == str(bad)

    def test_a_serialization_that_cannot_be_determined_fails(self, tmp_path):
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(mystery).read_graph()

        assert excinfo.value.code == "skos_format_unsupported"

    def test_a_serialization_outside_the_three_supported_fails_even_when_named(self):
        # n3 is a real rdflib format, so naming it must not bypass the gate.
        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(FIXTURES / "rocks.ttl", serialization="n3").read_graph()

        assert excinfo.value.code == "skos_format_unsupported"

    def test_rdf_xml_is_scanned_before_rdflib_reads_it(self):
        # The scan's own error must come out unwrapped: wrapping it in a parse failure
        # would blur which stage refused the file.
        with pytest.raises(UnsafeRdfXmlError):
            SkosImporter(
                SECURITY_FIXTURES / "entity_bomb.rdf", serialization="xml"
            ).read_graph()

    def test_ordinary_rdf_xml_passes_the_scan(self):
        graph = SkosImporter(
            SECURITY_FIXTURES / "ordinary.rdf", serialization="xml"
        ).read_graph()

        assert len(graph) > 0

    def test_json_ld_is_scanned_before_rdflib_reads_it(self):
        # A string @context is a location rdflib would fetch with no allowlist; without
        # the scan this would fail with a connection error instead of this refusal.
        with pytest.raises(UnsafeJsonLdError):
            SkosImporter(
                SECURITY_FIXTURES / "remote_context_string.jsonld",
                serialization="json-ld",
            ).read_graph()

    def test_json_ld_with_an_inline_context_passes_the_scan(self):
        graph = SkosImporter(
            SECURITY_FIXTURES / "inline_context.jsonld", serialization="json-ld"
        ).read_graph()

        assert len(graph) > 0

    @pytest.mark.django_db
    def test_a_json_ld_context_import_cannot_pull_in_a_local_file(self):
        # An inline @context's "@import" was once resolved through urlopen, reading a
        # local file of the document's own choosing. Run through import_skos so the
        # whole pipeline is covered.
        with pytest.raises(UnsafeJsonLdError):
            import_skos(SECURITY_FIXTURES / "exfil_via_import.jsonld")

        assert not ConceptScheme.objects.exists()


class TestBaseUri:
    @pytest.mark.parametrize("filename,serialization,content", RELATIVE_SERIALIZATIONS)
    def test_a_given_base_uri_resolves_relative_identifiers_against_it(
        self, tmp_path, filename, serialization, content
    ):
        path = tmp_path / filename
        path.write_text(content)

        graph = SkosImporter(
            path, serialization=serialization, base_uri="https://example.org/vocab.ttl"
        ).read_graph()

        scheme = rdflib.URIRef("https://example.org/vocab.ttl")
        concept_a = rdflib.URIRef("https://example.org/concept-a")
        concept_b = rdflib.URIRef("https://example.org/concept-b")
        assert (scheme, rdflib.RDF.type, SKOS.ConceptScheme) in graph
        assert (concept_a, rdflib.RDF.type, SKOS.Concept) in graph
        assert (concept_b, SKOS.broader, concept_a) in graph

    @pytest.mark.parametrize("filename,serialization,content", RELATIVE_SERIALIZATIONS)
    def test_without_a_base_uri_relative_identifiers_resolve_against_the_file(
        self, tmp_path, filename, serialization, content
    ):
        path = tmp_path / filename
        path.write_text(content)

        graph = SkosImporter(path, serialization=serialization).read_graph()

        assert (
            rdflib.URIRef(path.as_uri()),
            rdflib.RDF.type,
            SKOS.ConceptScheme,
        ) in graph

    def test_absolute_identifiers_are_unaffected_by_a_base_uri(self):
        graph = SkosImporter(
            FIXTURES / "rocks.ttl", base_uri="https://example.org/vocab.ttl"
        ).read_graph()

        assert (rdflib.URIRef(ROCKS), rdflib.RDF.type, SKOS.ConceptScheme) in graph

    @pytest.mark.django_db
    @pytest.mark.parametrize("filename,serialization,content", RELATIVE_SERIALIZATIONS)
    def test_an_import_stores_records_under_the_addresses_the_base_uri_gives(
        self, tmp_path, filename, serialization, content
    ):
        path = tmp_path / filename
        path.write_text(content)

        import_skos(
            path, serialization=serialization, base_uri="https://example.org/vocab.ttl"
        )

        scheme = ConceptScheme.objects.get()
        assert scheme.uri == "https://example.org/vocab.ttl"
        assert set(scheme.records.values_list("uri", flat=True)) == {
            "https://example.org/concept-a",
            "https://example.org/concept-b",
        }

    @pytest.mark.parametrize("problem", ["missing", "unsupported", "unparseable"])
    def test_a_refusal_names_the_base_uri_instead_of_the_temporary_file(
        self, tmp_path, problem
    ):
        path = tmp_path / "fetched.ttl"
        if problem == "unsupported":
            path = tmp_path / "fetched.mysteryext"
        if problem != "missing":
            path.write_text("this is not turtle @@@ not even close {{{ ]][[ ")

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(path, base_uri="https://example.org/vocab.ttl").read_graph()

        assert excinfo.value.params["file"] == "https://example.org/vocab.ttl"


class TestCraftedFilesStayInsideTheExceptionContract:
    def test_a_turtle_file_renamed_to_rdf_fails_as_a_parse_failure(self, tmp_path):
        bad = tmp_path / "not_actually_xml.rdf"
        bad.write_text("@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n")

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(bad).read_graph()

        assert excinfo.value.code == "skos_parse_failed"
        assert excinfo.value.__cause__ is not None

    def test_a_deeply_nested_json_ld_document_fails_as_a_parse_failure(self, tmp_path):
        path = write_deeply_nested_jsonld(tmp_path, 3000)

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(path, serialization="json-ld").read_graph()

        assert excinfo.value.code == "skos_parse_failed"
        assert excinfo.value.__cause__ is not None

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "filename,serialization",
        [
            ("entity_bomb.rdf", "xml"),
            ("exfil_via_import.jsonld", "json-ld"),
        ],
    )
    def test_a_hostile_file_is_caught_by_the_documented_exception_pair(
        self, filename, serialization
    ):
        with pytest.raises((SkosImportError, SkosImportFailed)):
            import_skos(SECURITY_FIXTURES / filename, serialization=serialization)

    @pytest.mark.django_db
    def test_a_cyclic_member_list_fails_as_a_skos_import_error(self):
        with pytest.raises(SkosImportError) as excinfo:
            import_skos(FIXTURES / "cyclic_member_list.ttl")

        assert excinfo.value.code == "skos_cyclic_member_list"
        assert excinfo.value.__cause__ is not None

    @pytest.mark.django_db
    def test_a_cyclic_member_list_writes_nothing(self):
        with pytest.raises(SkosImportError):
            import_skos(FIXTURES / "cyclic_member_list.ttl")

        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()


class TestFailureMessagesUseOnlyNamedPlaceholders:
    def test_missing_file(self, tmp_path, uses_only_named_placeholders):
        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(tmp_path / "does-not-exist.ttl").read_graph()

        assert isinstance(excinfo.value.message, Promise)
        assert uses_only_named_placeholders(str(excinfo.value.message))

    def test_unsupported_serialization(self, uses_only_named_placeholders):
        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(FIXTURES / "rocks.ttl", serialization="n3").read_graph()

        assert isinstance(excinfo.value.message, Promise)
        assert uses_only_named_placeholders(str(excinfo.value.message))

    def test_unparseable_file(self, tmp_path, uses_only_named_placeholders):
        bad = tmp_path / "bad.ttl"
        bad.write_text("this is not turtle @@@ not even close {{{ ]][[ ")

        with pytest.raises(SkosImportError) as excinfo:
            SkosImporter(bad).read_graph()

        assert isinstance(excinfo.value.message, Promise)
        assert uses_only_named_placeholders(str(excinfo.value.message))

    @pytest.mark.django_db
    def test_refused_run(self, uses_only_named_placeholders):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "blank_node_concept.ttl")

        assert isinstance(excinfo.value.message, Promise)
        assert uses_only_named_placeholders(str(excinfo.value.message))
        assert excinfo.value.code == "skos_import_failed"


class TestExchangePackage:
    def test_the_safety_errors_are_skos_import_errors(self):
        assert issubclass(UnsafeRdfXmlError, SkosImportError)
        assert issubclass(UnsafeJsonLdError, SkosImportError)

    def test_a_refused_run_and_an_unreadable_file_are_siblings(self):
        assert not issubclass(SkosImportFailed, SkosImportError)
        assert not issubclass(SkosImportError, SkosImportFailed)
        assert issubclass(SkosImportFailed, ValidationError)

    @pytest.mark.parametrize(
        "name",
        [
            "FatalFinding",
            "FatalReason",
            "ImportReport",
            "SkosImportError",
            "SkosImportFailed",
            "UnsafeJsonLdError",
            "UnsafeRdfXmlError",
            "import_skos",
        ],
    )
    def test_the_documented_names_are_exported(self, name):
        assert name in exchange.__all__
        assert hasattr(exchange, name)


@pytest.mark.django_db
class TestImportCreatesTheVocabularyAndItsRecords:
    @pytest.mark.parametrize("filename,serialization", BASE_SERIALIZATIONS)
    def test_each_serialization_creates_the_vocabulary_and_every_record(
        self, filename, serialization
    ):
        report = import_skos(FIXTURES / filename, serialization=serialization)

        scheme = ConceptScheme.objects.get()
        assert scheme.uri == ROCKS
        assert set(scheme.records.values_list("uri", flat=True)) == {
            "http://example.org/rocks/igneous",
            GRANITE,
            BASALT,
            SEDIMENTARY,
            QUARTZ,
            SILICA_BEARING,
            EXAMPLE_SEQUENCE,
        }
        assert report.fatal == []
        assert report.updated == []
        assert set(report.created) == {
            ROCKS,
            *scheme.records.values_list("uri", flat=True),
        }

    def test_the_three_serializations_store_the_same_documents(self):
        stored = []
        for filename, serialization in BASE_SERIALIZATIONS:
            import_skos(FIXTURES / filename, serialization=serialization)
            stored.append(stored_documents())
            Record.objects.all().delete()
            ConceptScheme.objects.all().delete()

        assert stored[0] == stored[1] == stored[2]

    def test_a_record_takes_the_type_of_its_class(self):
        import_skos(FIXTURES / "rocks.ttl")

        assert Record.objects.get(uri=GRANITE).type == Record.Type.CONCEPT
        assert Record.objects.get(uri=SILICA_BEARING).type == Record.Type.COLLECTION
        assert (
            Record.objects.get(uri=EXAMPLE_SEQUENCE).type
            == Record.Type.ORDERED_COLLECTION
        )

    def test_a_record_keeps_the_uri_its_publisher_gave_it(self):
        import_skos(FIXTURES / "rocks.ttl")

        record = Record.objects.get(uri=GRANITE)
        assert record.slug == "granite"

    def test_a_record_shows_its_label_in_the_vocabulary_default_language(self):
        import_skos(FIXTURES / "rocks.ttl")

        assert Record.objects.get(uri=GRANITE).pref_label == "Granite"
        assert Record.objects.get(
            uri="http://example.org/rocks/igneous"
        ).pref_label == ("Igneous rock")

    def test_a_node_typed_only_by_scheme_membership_becomes_a_concept(self):
        import_skos(FIXTURES / "concept_implied_by_membership_no_rdf_type.ttl")

        records = Record.objects.filter(scheme__uri="http://example.org/implied/")
        assert {record.slug for record in records} == {"alpha", "beta", "gamma"}
        assert {record.type for record in records} == {Record.Type.CONCEPT}


@pytest.mark.django_db
class TestImportKeepsEveryStatement:
    def test_every_language_of_a_label_is_kept(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en, "Granit"@de, "Granito"@es, "Granit"@sv-se ;
                skos:definition "A rock."@en, "Ein Gestein."@de, "Una roca."@es .
            """,
        )

        import_skos(path)

        record = Record.objects.get(uri="http://example.org/s/granite")
        assert {entry["@language"] for entry in record.values("skos:prefLabel")} == {
            "en",
            "de",
            "es",
            "sv-se",
        }
        assert {entry["@language"] for entry in record.values("skos:definition")} == {
            "en",
            "de",
            "es",
        }

    def test_several_values_in_one_language_are_all_kept(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en, "Granite rock"@en ;
                skos:altLabel "Plutonic"@en, "Magma rock"@en .
            """,
        )

        import_skos(path)

        record = Record.objects.get(uri="http://example.org/s/granite")
        assert {entry["@value"] for entry in record.values("skos:prefLabel")} == {
            "Granite",
            "Granite rock",
        }
        assert {entry["@value"] for entry in record.values("skos:altLabel")} == {
            "Plutonic",
            "Magma rock",
        }

    def test_notations_and_untagged_literals_are_kept(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en ;
                skos:notation "GR-01" ;
                skos:altLabel "Untagged alternative" .
            """,
        )

        import_skos(path)

        record = Record.objects.get(uri="http://example.org/s/granite")
        assert record.values("skos:notation") == [{"@value": "GR-01"}]
        assert record.values("skos:altLabel") == [{"@value": "Untagged alternative"}]

    def test_mappings_are_kept_as_links(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en ;
                skos:exactMatch <http://other.example.com/granite> ;
                skos:closeMatch <http://other.example.com/plutonic>,
                    <http://third.example.com/granite> ;
                skos:broadMatch <http://other.example.com/rock> .
            """,
        )

        import_skos(path)

        record = Record.objects.get(uri="http://example.org/s/granite")
        assert record.linked_uris("skos:exactMatch") == [
            "http://other.example.com/granite"
        ]
        assert sorted(record.linked_uris("skos:closeMatch")) == [
            "http://other.example.com/plutonic",
            "http://third.example.com/granite",
        ]
        assert record.linked_uris("skos:broadMatch") == [
            "http://other.example.com/rock"
        ]

    def test_relations_are_kept_as_links(self):
        import_skos(FIXTURES / "rocks.ttl")

        granite = Record.objects.get(uri=GRANITE)
        assert granite.linked_uris("skos:broader") == [
            "http://example.org/rocks/igneous"
        ]
        assert granite.linked_uris("skos:related") == [QUARTZ]

    def test_predicates_outside_skos_are_kept(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en ;
                dcterms:creator "A. Geologist" ;
                rdfs:comment "Untagged comment" ;
                dcterms:modified "2026-01-02"^^xsd:date ;
                <http://example.org/ns#custom> "custom value"@en .
            """,
        )

        import_skos(path)

        record = Record.objects.get(uri="http://example.org/s/granite")
        assert record.first_value("dcterms:creator") == "A. Geologist"
        assert record.first_value("rdfs:comment") == "Untagged comment"
        assert record.values("dcterms:modified") == [
            {"@value": "2026-01-02", "@type": "xsd:date"}
        ]
        assert record.values("http://example.org/ns#custom") == [
            {"@value": "custom value", "@language": "en"}
        ]

    def test_the_vocabulary_keeps_its_own_statements(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ;
                skos:prefLabel "Survey rocks"@en, "Gesteine"@de ;
                dcterms:publisher "Example Survey" ;
                dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
                owl:versionInfo "2.1" ;
                dcterms:modified "2026-01-02"^^xsd:date ;
                skos:hasTopConcept <http://example.org/s/granite> .
            <http://example.org/s/granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "Granite"@en .
            """,
        )

        import_skos(path)

        scheme = ConceptScheme.objects.get()
        assert scheme.label("de") == "Gesteine"
        assert scheme.first_value("dcterms:publisher") == "Example Survey"
        assert scheme.linked_uris("dcterms:license") == [
            "https://creativecommons.org/licenses/by/4.0/"
        ]
        assert scheme.first_value("owl:versionInfo") == "2.1"
        assert scheme.first_value("dcterms:modified") == "2026-01-02"
        assert scheme.linked_uris("skos:hasTopConcept") == [
            "http://example.org/s/granite"
        ]

    def test_a_label_in_every_language_of_the_file_is_kept_on_a_real_vocabulary(self):
        import_skos(FIXTURES / "rocks.ttl")

        granite = Record.objects.get(uri=GRANITE)
        assert {
            (entry["@language"], entry["@value"])
            for entry in granite.values("skos:prefLabel")
        } == {("en", "Granite"), ("de", "Granit"), ("fr", "Granite")}
        assert granite.values("skos:hiddenLabel") == [
            {"@value": "Granit rock", "@language": "en"}
        ]

    def test_every_note_kind_is_kept(self):
        import_skos(FIXTURES / "rocks.ttl")

        quartz = Record.objects.get(uri=QUARTZ)
        for curie in ("skos:historyNote", "skos:changeNote", "skos:note"):
            assert len(quartz.values(curie)) == 1


BLANK_NODE_OBJECTS = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix skosxl: <http://www.w3.org/2008/05/skos-xl#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
<http://example.org/blank/vocab> a skos:ConceptScheme ;
    skos:prefLabel "Blank"@en ;
    dcterms:creator [ foaf:name "Jane" ] .
<http://example.org/blank/granite> a skos:Concept ;
    skos:inScheme <http://example.org/blank/vocab> ;
    skos:prefLabel "Granite"@en ;
    skosxl:prefLabel [ skosxl:literalForm "Granite"@en ] .
"""


@pytest.mark.django_db
class TestBlankNodeObjects:
    GRANITE = "http://example.org/blank/granite"

    def write(self, tmp_path, text=BLANK_NODE_OBJECTS):
        path = tmp_path / "blank.ttl"
        path.write_text(text)
        return path

    def test_a_blank_nodes_statements_are_kept_embedded_in_the_entry(self, tmp_path):
        import_skos(self.write(tmp_path))

        granite = Record.objects.get(uri=self.GRANITE)
        assert granite.values("http://www.w3.org/2008/05/skos-xl#prefLabel") == [
            {
                "http://www.w3.org/2008/05/skos-xl#literalForm": [
                    {"@value": "Granite", "@language": "en"}
                ]
            }
        ]
        scheme = ConceptScheme.objects.get(uri="http://example.org/blank/vocab")
        assert scheme.values("dcterms:creator") == [
            {"http://xmlns.com/foaf/0.1/name": [{"@value": "Jane"}]}
        ]

    def test_reimporting_a_file_with_blank_nodes_stores_the_same_documents(
        self, tmp_path
    ):
        path = self.write(tmp_path)
        import_skos(path)
        first = Record.objects.get(uri=self.GRANITE).data

        import_skos(path)

        assert Record.objects.get(uri=self.GRANITE).data == first

    def test_a_cycle_of_blank_nodes_ends(self, tmp_path):
        path = self.write(
            tmp_path,
            BLANK_NODE_OBJECTS
            + "<http://example.org/blank/granite> skos:note _:a .\n"
            + "_:a skos:related _:b .\n_:b skos:related _:a .\n",
        )

        import_skos(path)

        note = Record.objects.get(uri=self.GRANITE).values("skos:note")
        assert note == [{"skos:related": [{"skos:related": [{}]}]}]


@pytest.mark.django_db
class TestOrderedCollections:
    def test_a_collection_lists_its_members(self):
        import_skos(FIXTURES / "rocks.ttl")

        collection = Record.objects.get(uri=SILICA_BEARING)
        assert sorted(collection.member_uris()) == [GRANITE, QUARTZ]

    def test_an_ordered_collection_keeps_the_order_of_its_member_list(self):
        import_skos(FIXTURES / "rocks.ttl")

        collection = Record.objects.get(uri=EXAMPLE_SEQUENCE)
        assert collection.member_uris() == [BASALT, GRANITE, SEDIMENTARY]

    def test_a_reimport_with_a_new_order_stores_the_new_order(self):
        import_skos(FIXTURES / "rocks.ttl")

        import_skos(FIXTURES / "rocks_updated.ttl")

        collection = Record.objects.get(uri=EXAMPLE_SEQUENCE)
        assert collection.member_uris() == [GRANITE, SEDIMENTARY, BASALT]

    def test_members_named_only_by_skos_member_are_kept_beside_the_member_list(self):
        import_skos(FIXTURES / "ordered_collection_member_and_memberlist.ttl")

        collection = Record.objects.get(
            uri="http://example.org/ordered-mixed/collection/group"
        )
        base = "http://example.org/ordered-mixed/"
        assert collection.linked_uris("skos:memberList") == [
            f"{base}gamma",
            f"{base}alpha",
        ]
        assert sorted(collection.linked_uris("skos:member")) == [
            f"{base}alpha",
            f"{base}beta",
            f"{base}gamma",
        ]

    def test_the_cells_of_a_member_list_are_not_records(self):
        report = import_skos(FIXTURES / "rocks.ttl")

        assert report.fatal == []
        assert Record.objects.count() == 7


@pytest.mark.django_db
class TestReimportUpsertsByUri:
    def test_importing_the_same_file_again_creates_nothing(self):
        import_skos(FIXTURES / "rocks.ttl")

        report = import_skos(FIXTURES / "rocks.ttl")

        assert report.created == []
        assert len(report.updated) == 8
        assert ConceptScheme.objects.count() == 1
        assert Record.objects.count() == 7

    def test_importing_the_same_file_again_changes_no_document(self):
        import_skos(FIXTURES / "rocks.ttl")
        before = stored_documents()

        import_skos(FIXTURES / "rocks.ttl")

        assert stored_documents() == before

    def test_a_reimport_keeps_each_row_it_matches_rather_than_recreating_it(self):
        import_skos(FIXTURES / "rocks.ttl")
        scheme_pk = ConceptScheme.objects.get().pk
        pks = dict(Record.objects.values_list("uri", "pk"))

        import_skos(FIXTURES / "rocks_updated.ttl")

        assert ConceptScheme.objects.get().pk == scheme_pk
        for uri, pk in pks.items():
            assert Record.objects.get(uri=uri).pk == pk

    def test_a_reimport_replaces_the_statements_of_a_record_it_matches(self):
        import_skos(FIXTURES / "rocks.ttl")

        import_skos(FIXTURES / "rocks_updated.ttl")

        granite = Record.objects.get(uri=GRANITE)
        assert granite.label("en") == "Granite (revised)"
        assert granite.pref_label == "Granite (revised)"
        assert granite.values("skos:altLabel") == []
        assert granite.linked_uris("skos:related") == []

    def test_a_reimport_keeps_the_slug_a_record_was_given(self):
        import_skos(FIXTURES / "rocks.ttl")

        import_skos(FIXTURES / "rocks_updated.ttl")

        assert Record.objects.get(uri=GRANITE).slug == "granite"

    def test_a_reimport_reports_the_records_it_updated(self):
        import_skos(FIXTURES / "rocks.ttl")

        report = import_skos(FIXTURES / "rocks_updated.ttl")

        assert report.created == []
        assert {ROCKS, GRANITE, BASALT, SEDIMENTARY} <= set(report.updated)

    def test_a_reimport_does_not_touch_a_record_of_another_vocabulary(self):
        other = RecordFactory()
        before = (other.pk, other.data)
        import_skos(FIXTURES / "rocks.ttl")

        import_skos(FIXTURES / "rocks_updated.ttl")

        other.refresh_from_db()
        assert (other.pk, other.data) == before


@pytest.mark.django_db
class TestRecordsAbsentFromTheSource:
    def test_a_record_the_file_no_longer_mentions_is_reported(self):
        import_skos(FIXTURES / "rocks.ttl")

        report = import_skos(FIXTURES / "rocks_updated.ttl")

        assert report.absent_from_source == [QUARTZ]

    def test_a_record_the_file_no_longer_mentions_is_left_as_it_was(self):
        import_skos(FIXTURES / "rocks.ttl")
        before = Record.objects.get(uri=QUARTZ)

        import_skos(FIXTURES / "rocks_updated.ttl")

        after = Record.objects.get(uri=QUARTZ)
        assert (after.pk, after.data, after.scheme_id) == (
            before.pk,
            before.data,
            before.scheme_id,
        )

    def test_a_first_import_reports_nothing_absent(self):
        report = import_skos(FIXTURES / "rocks.ttl")

        assert report.absent_from_source == []

    def test_a_record_added_by_hand_is_reported_and_kept(self):
        import_skos(FIXTURES / "rocks.ttl")
        scheme = ConceptScheme.objects.get()
        added = RecordFactory(scheme=scheme, label="Added by hand")

        report = import_skos(FIXTURES / "rocks.ttl")

        assert report.absent_from_source == [added.uri]
        assert Record.objects.filter(pk=added.pk).exists()

    def test_a_collection_the_file_no_longer_mentions_is_reported_and_kept(self):
        import_skos(FIXTURES / "collection_absent_from_source.ttl")

        report = import_skos(FIXTURES / "collection_absent_from_source_updated.ttl")

        assert len(report.absent_from_source) == 1
        assert Record.objects.filter(
            uri=report.absent_from_source[0], type=Record.Type.COLLECTION
        ).exists()


@pytest.mark.django_db
class TestRecordMovingBetweenVocabularies:
    A = "http://example.org/reassignment/a"
    B = "http://example.org/reassignment/b"

    @staticmethod
    def placed_in(scheme, tmp_path):
        """Write the reassignment file with both concepts stating ``scheme``."""
        path = tmp_path / "placed.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f"<{TestRecordMovingBetweenVocabularies.A}> a skos:Concept ;\n"
            f'    skos:prefLabel "A"@en ; skos:inScheme <{scheme.uri}> .\n'
            f"<{TestRecordMovingBetweenVocabularies.B}> a skos:Concept ;\n"
            f'    skos:prefLabel "B"@en ; skos:inScheme <{scheme.uri}> .\n'
        )
        return path

    def test_a_record_held_elsewhere_is_left_untouched_when_the_file_does_not_place_it(
        self,
    ):
        first = ConceptSchemeFactory()
        second = ConceptSchemeFactory()
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)
        before = Record.objects.get(uri=self.A)

        report = import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=second)

        after = Record.objects.get(uri=self.A)
        assert (after.scheme, after.slug, after.data) == (
            first,
            before.slug,
            before.data,
        )
        assert self.A in report.held_elsewhere
        assert self.A not in report.updated
        assert not second.records.exists()

    def test_a_record_the_file_places_in_this_vocabulary_moves_to_it(self, tmp_path):
        first = ConceptSchemeFactory()
        second = ConceptSchemeFactory()
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)
        pk = Record.objects.get(uri=self.A).pk

        report = import_skos(self.placed_in(second, tmp_path), scheme=second)

        moved = Record.objects.get(uri=self.A)
        assert (moved.pk, moved.scheme) == (pk, second)
        assert self.A in report.updated
        assert not first.records.exists()

    def test_a_moved_record_gets_a_slug_unused_in_its_new_vocabulary(self, tmp_path):
        first = ConceptSchemeFactory()
        second = ConceptSchemeFactory()
        RecordFactory(
            scheme=second, uri="http://example.org/elsewhere/a", data=labelled("A")
        )
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)

        import_skos(self.placed_in(second, tmp_path), scheme=second)

        slugs = list(second.records.values_list("slug", flat=True))
        assert len(slugs) == len(set(slugs)) == 3
        assert Record.objects.get(uri=self.A).slug

    def test_a_concept_the_file_places_in_another_vocabulary_is_not_imported(
        self, tmp_path
    ):
        held = RecordFactory(uri="http://a.org/granite", data=labelled("Granite"))
        path = tmp_path / "maps.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://b.org/vocab> a skos:ConceptScheme ;\n"
            '    skos:prefLabel "B"@en .\n'
            "<http://b.org/rock> a skos:Concept ; "
            "skos:inScheme <http://b.org/vocab> ;\n"
            '    skos:prefLabel "Rock"@en ; skos:exactMatch <http://a.org/granite> .\n'
            "<http://a.org/granite> a skos:Concept ;\n"
            "    skos:inScheme <http://a.org/vocab> ;\n"
            '    skos:prefLabel "Granit"@de .\n'
            "<http://a.org/basalt> a skos:Concept ;\n"
            "    skos:inScheme <http://a.org/vocab> ;\n"
            '    skos:prefLabel "Basalt"@en .\n'
        )

        report = import_skos(path)

        held.refresh_from_db()
        assert held.data == labelled("Granite")
        assert held.scheme.uri != "http://b.org/vocab"
        assert not Record.objects.filter(uri="http://a.org/basalt").exists()
        assert sorted(report.held_elsewhere) == [
            "http://a.org/basalt",
            "http://a.org/granite",
        ]
        assert Record.objects.filter(uri="http://b.org/rock").exists()

    def test_a_record_that_stays_in_its_vocabulary_keeps_its_slug(self):
        scheme = ConceptSchemeFactory()
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=scheme)
        slug = Record.objects.get(uri=self.A).slug

        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=scheme)

        assert Record.objects.get(uri=self.A).slug == slug


@pytest.mark.django_db
class TestImportIntoANamedVocabulary:
    def test_a_file_declaring_no_vocabulary_imports_into_the_one_named(self):
        scheme = ConceptSchemeFactory()

        report = import_skos(FIXTURES / "no_scheme_declared.ttl", scheme=scheme)

        assert set(scheme.records.values_list("uri", flat=True)) == {
            "http://example.org/loose/basalt",
            "http://example.org/loose/granite",
        }
        assert report.fatal == []
        assert scheme.uri not in report.created

    def test_the_named_vocabulary_keeps_its_own_document(self):
        scheme = ConceptSchemeFactory(name="Mine")
        before = scheme.data

        import_skos(FIXTURES / "no_scheme_declared.ttl", scheme=scheme)

        scheme.refresh_from_db()
        assert scheme.data == before

    def test_a_file_declaring_the_named_vocabulary_updates_it(self):
        scheme = ConceptSchemeFactory(
            data=labelled("Old name"),
            uri=ROCKS,
            slug="rocks",
        )

        report = import_skos(FIXTURES / "rocks.ttl", scheme=scheme)

        scheme.refresh_from_db()
        assert scheme.label("en") == "Rock types"
        assert ROCKS in report.updated
        assert ROCKS not in report.created
        assert ConceptScheme.objects.count() == 1


@pytest.mark.django_db
class TestDefaultLanguageOfANewVocabulary:
    def test_it_is_the_commonest_language_of_the_preferred_labels(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/s/a> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "A"@en, "Ah"@de .
            <http://example.org/s/b> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "B"@de .
            <http://example.org/s/c> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "C"@de .
            """,
        )

        import_skos(path)

        assert ConceptScheme.objects.get().default_language == "de"

    def test_a_vocabulary_published_in_one_language_takes_that_language(self):
        import_skos(FIXTURES / "french_vocabulary.ttl")

        scheme = ConceptScheme.objects.get()
        assert scheme.default_language == "fr"
        assert Record.objects.get().pref_label == "Roche ignée"

    def test_a_regional_variant_is_kept_as_published(self):
        import_skos(FIXTURES / "declares-de-at.ttl")

        assert ConceptScheme.objects.get().default_language == "de-at"

    def test_a_file_with_no_language_tagged_label_takes_the_site_language(
        self, tmp_path
    ):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S" .
            <http://example.org/s/a> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ;
                skos:prefLabel "A" .
            """,
        )

        import_skos(path)

        assert ConceptScheme.objects.get().default_language == settings.LANGUAGE_CODE

    def test_a_vocabulary_that_already_exists_keeps_its_default_language(self):
        ConceptSchemeFactory(uri=ROCKS, slug="rocks", default_language="de")

        import_skos(FIXTURES / "rocks.ttl")

        assert ConceptScheme.objects.get().default_language == "de"

    def test_a_vocabulary_named_as_the_target_keeps_its_default_language(self):
        scheme = ConceptSchemeFactory(default_language="de")

        import_skos(FIXTURES / "no_scheme_declared.ttl", scheme=scheme)

        scheme.refresh_from_db()
        assert scheme.default_language == "de"


@pytest.mark.django_db
class TestRefusedRuns:
    def test_a_blank_node_concept_refuses_the_run(self):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "blank_node_concept.ttl")

        assert fatal_reasons(excinfo) == {FatalReason.MISSING_IDENTITY}

    def test_a_blank_node_collection_refuses_the_run_and_writes_nothing(self):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "blank_node_collection.ttl")

        assert fatal_reasons(excinfo) == {FatalReason.MISSING_IDENTITY}
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    @pytest.mark.parametrize(
        "identifier",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,hello",
            "vbscript:msgbox(1)",
        ],
    )
    def test_a_refused_scheme_refuses_the_run_and_writes_nothing(
        self, tmp_path, identifier
    ):
        path = write_turtle(
            tmp_path,
            f"""
            <http://example.org/js/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <http://example.org/js/ordinary> a skos:Concept ;
                skos:inScheme <http://example.org/js/> ; skos:prefLabel "Ordinary"@en .
            <{identifier}> a skos:Concept ;
                skos:inScheme <http://example.org/js/> ; skos:prefLabel "Refused"@en .
            """,
        )

        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(path)

        assert fatal_reasons(excinfo) == {FatalReason.REFUSED_IDENTITY}
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_an_identifier_longer_than_its_column_refuses_the_run_and_writes_nothing(
        self, tmp_path
    ):
        long_uri = "http://example.org/js/" + "x" * 500
        path = write_turtle(
            tmp_path,
            f"""
            <http://example.org/js/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <{long_uri}> a skos:Concept ;
                skos:inScheme <http://example.org/js/> ; skos:prefLabel "Long"@en .
            """,
        )

        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(path)

        assert fatal_reasons(excinfo) == {FatalReason.IDENTIFIER_TOO_LONG}
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_other_schemes_are_imported(self, tmp_path):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/s/> a skos:ConceptScheme ; skos:prefLabel "S"@en .
            <urn:example:granite> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ; skos:prefLabel "Granite"@en .
            <ftp://mirror.example.org/s/basalt> a skos:Concept ;
                skos:inScheme <http://example.org/s/> ; skos:prefLabel "Basalt"@en .
            """,
        )

        report = import_skos(path)

        assert report.fatal == []
        assert set(Record.objects.values_list("uri", flat=True)) == {
            "urn:example:granite",
            "ftp://mirror.example.org/s/basalt",
        }

    def test_every_problem_in_a_file_is_reported_and_none_of_it_is_written(
        self, tmp_path
    ):
        path = write_turtle(
            tmp_path,
            """
            <http://example.org/mixed/> a skos:ConceptScheme ; skos:prefLabel "M"@en .
            <http://example.org/mixed/ordinary> a skos:Concept ;
                skos:inScheme <http://example.org/mixed/> ;
                skos:prefLabel "Ordinary"@en .
            [] a skos:Concept ;
                skos:inScheme <http://example.org/mixed/> ;
                skos:prefLabel "Nameless"@en .
            <javascript:alert(1)> a skos:Concept ;
                skos:inScheme <http://example.org/mixed/> ;
                skos:prefLabel "Refused"@en .
            """,
        )

        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(path)

        assert fatal_reasons(excinfo) == {
            FatalReason.MISSING_IDENTITY,
            FatalReason.REFUSED_IDENTITY,
        }
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_a_refused_reimport_leaves_what_was_stored_unchanged(self, tmp_path):
        import_skos(FIXTURES / "rocks.ttl")
        before = stored_documents()
        path = write_turtle(
            tmp_path,
            f"""
            <{ROCKS}> a skos:ConceptScheme ; skos:prefLabel "Rock types"@en .
            <{GRANITE}> a skos:Concept ;
                skos:inScheme <{ROCKS}> ; skos:prefLabel "Granite (changed)"@en .
            [] a skos:Concept ;
                skos:inScheme <{ROCKS}> ; skos:prefLabel "Nameless"@en .
            """,
        )

        with pytest.raises(SkosImportFailed):
            import_skos(path)

        assert stored_documents() == before

    def test_a_file_declaring_no_vocabulary_and_naming_none_is_refused(self):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "no_scheme_declared.ttl")

        assert fatal_reasons(excinfo) == {FatalReason.VOCABULARY_UNDETERMINED}
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_a_file_declaring_two_vocabularies_and_naming_none_is_refused(self):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "two_vocabularies.ttl")

        assert fatal_reasons(excinfo) == {FatalReason.VOCABULARY_AMBIGUOUS}
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_a_file_declaring_a_different_vocabulary_than_the_one_named_is_refused(
        self,
    ):
        target = ConceptSchemeFactory()

        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "rocks.ttl", scheme=target)

        assert fatal_reasons(excinfo) == {FatalReason.VOCABULARY_TARGET_MISMATCH}
        finding = excinfo.value.report.fatal[0]
        assert finding.subject == ROCKS
        assert finding.params == {"target": target.uri}
        assert not target.records.exists()
        assert ConceptScheme.objects.count() == 1
