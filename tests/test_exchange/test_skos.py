"""Tests for controlled_vocabularies.exchange.skos."""

import re
import threading
from pathlib import Path

import pytest
import rdflib
from django.conf import global_settings
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils.functional import Promise

import controlled_vocabularies.exchange as exchange
from controlled_vocabularies import conf
from controlled_vocabularies.exchange.languages import LanguageMatcher
from controlled_vocabularies.exchange.report import (
    FatalReason,
    NormalizedReason,
    SetAsideReason,
)
from controlled_vocabularies.exchange.safety import UnsafeJsonLdError, UnsafeRdfXmlError
from controlled_vocabularies.exchange.skos import (
    ConceptImporter,
    SchemeResolver,
    SkosGraph,
    SkosImportError,
    SkosImportFailed,
    import_skos,
    unique_slug_for_identifier,
)
from controlled_vocabularies.models import (
    Collection,
    CollectionMember,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
)
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptRelationFactory,
    ConceptSchemeFactory,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"
SECURITY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "security"

SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
ROCKS_URI = "http://example.org/rocks/"
ROCKS_SCHEME_URI = rdflib.URIRef(ROCKS_URI)

BASE_SERIALIZATIONS = [
    ("rocks.ttl", "turtle"),
    ("rocks.rdf", "xml"),
    ("rocks.jsonld", "json-ld"),
]

# Walked rather than listed, so a fixture added later is covered without registering it.
SUFFIX_FORMATS = {".ttl": "turtle", ".rdf": "xml", ".jsonld": "json-ld"}
ALL_FIXTURES = sorted(
    (path.name, SUFFIX_FORMATS[path.suffix])
    for path in FIXTURES.iterdir()
    if path.is_file()
)


class TestReadGraph:
    @pytest.mark.parametrize(
        "filename,fmt",
        [("rocks.ttl", None), ("rocks.rdf", None), ("rocks.jsonld", None)],
    )
    def test_each_supported_serialization_parses_by_extension(self, filename, fmt):
        graph = SkosGraph.from_file(FIXTURES / filename, serialization=fmt).graph
        assert len(graph) > 0
        assert (
            rdflib.URIRef("http://example.org/rocks/"),
            rdflib.RDF.type,
            SKOS.ConceptScheme,
        ) in graph

    @pytest.mark.parametrize("fmt", ["turtle", "xml", "json-ld"])
    def test_each_supported_serialization_parses_with_stated_format(self, fmt):
        filename = {
            "turtle": "rocks.ttl",
            "xml": "rocks.rdf",
            "json-ld": "rocks.jsonld",
        }[fmt]
        graph = SkosGraph.from_file(FIXTURES / filename, serialization=fmt).graph
        assert len(graph) > 0

    def test_missing_file_fails_with_a_translatable_message(self, tmp_path):
        missing = tmp_path / "does-not-exist.ttl"
        with pytest.raises(SkosImportError) as exc_info:
            SkosGraph.from_file(missing)
        assert str(missing) in str(exc_info.value)

    def test_unparseable_file_fails_with_a_translatable_message(self, tmp_path):
        bad = tmp_path / "bad.ttl"
        bad.write_text("this is not turtle @@@ not even close {{{ ]][[ ")
        with pytest.raises(SkosImportError) as exc_info:
            SkosGraph.from_file(bad)
        assert "bad.ttl" in str(exc_info.value)

    def test_serialization_that_cannot_be_determined_fails(self, tmp_path):
        # A real vocabulary under an extension guess_format does not recognise.
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with pytest.raises(SkosImportError):
            SkosGraph.from_file(mystery)

    def test_serialization_not_among_the_three_supported_fails_even_if_named_explicitly(
        self,
    ):
        # "n3" is a real rdflib format but not a supported one; naming it explicitly
        # must not bypass the gate.
        with pytest.raises(SkosImportError):
            SkosGraph.from_file(FIXTURES / "rocks.ttl", serialization="n3")

    def test_rdf_xml_is_routed_through_the_safety_scan_before_rdflib_sees_it(self):
        # The scan's UnsafeRdfXmlError must propagate as-is: both it and SkosImportError
        # are ValidationErrors, and wrapping one in the other would blur which stage
        # refused the file.
        with pytest.raises(UnsafeRdfXmlError):
            SkosGraph.from_file(
                SECURITY_FIXTURES / "entity_bomb.rdf", serialization="xml"
            )

    def test_ordinary_rdf_xml_is_unaffected_by_the_safety_scan(self):
        graph = SkosGraph.from_file(
            SECURITY_FIXTURES / "ordinary.rdf", serialization="xml"
        ).graph
        assert len(graph) > 0

    def test_json_ld_is_routed_through_the_safety_scan_before_rdflib_sees_it(self):
        # A string @context is a location rdflib would fetch via urlopen with no
        # allowlist. Without the scan wired in, this would fail with a connection error
        # rather than this refusal.
        with pytest.raises(UnsafeJsonLdError):
            SkosGraph.from_file(
                SECURITY_FIXTURES / "remote_context_string.jsonld",
                serialization="json-ld",
            )

    def test_json_ld_with_an_inline_context_is_unaffected_by_the_safety_scan(self):
        graph = SkosGraph.from_file(
            SECURITY_FIXTURES / "inline_context.jsonld", serialization="json-ld"
        ).graph
        assert len(graph) > 0

    def test_json_ld_context_import_cannot_exfiltrate_a_local_file(self, db):
        # An inline object @context's "@import" key was once resolved by rdflib through
        # urlopen, pulling in a local file of the document's own choosing. Exercised
        # through import_skos() so the whole pipeline is covered.
        with pytest.raises(UnsafeJsonLdError):
            import_skos(SECURITY_FIXTURES / "exfil_via_import.jsonld")
        assert not ConceptScheme.objects.filter(
            static_uri__startswith="http://example.org/SECRET-FROM-LOCAL-FILE/"
        ).exists()


# Written per test rather than committed to tests/fixtures/skos/, which
# TestFixtureCorpus and TestEverySkosPredicateIsReadOrReported walk wholesale: an
# all-relative document can only fail their plain import with REFUSED_IDENTITY.
_RELATIVE_URIS_TURTLE = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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

_RELATIVE_URIS_XML = """<?xml version="1.0" encoding="utf-8"?>
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

_RELATIVE_URIS_JSONLD = """{
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


class TestBaseUriThread:
    RELATIVE_SERIALIZATIONS = [
        ("relative-uris.ttl", "turtle", _RELATIVE_URIS_TURTLE),
        ("relative-uris.rdf", "xml", _RELATIVE_URIS_XML),
        ("relative-uris.jsonld", "json-ld", _RELATIVE_URIS_JSONLD),
    ]

    @pytest.mark.parametrize("filename,fmt,content", RELATIVE_SERIALIZATIONS)
    def test_a_given_base_uri_resolves_relative_identifiers_against_it(
        self, tmp_path, filename, fmt, content
    ):
        path = tmp_path / filename
        path.write_text(content)
        graph = SkosGraph.from_file(
            path, serialization=fmt, base_uri="https://example.org/vocab.ttl"
        ).graph
        assert (
            rdflib.URIRef("https://example.org/vocab.ttl"),
            rdflib.RDF.type,
            SKOS.ConceptScheme,
        ) in graph
        assert (
            rdflib.URIRef("https://example.org/concept-a"),
            rdflib.RDF.type,
            SKOS.Concept,
        ) in graph
        assert (
            rdflib.URIRef("https://example.org/concept-b"),
            SKOS.broader,
            rdflib.URIRef("https://example.org/concept-a"),
        ) in graph

    @pytest.mark.parametrize("filename,fmt,content", RELATIVE_SERIALIZATIONS)
    def test_no_base_uri_resolves_relative_identifiers_against_the_file(
        self, tmp_path, filename, fmt, content
    ):
        path = tmp_path / filename
        path.write_text(content)
        graph = SkosGraph.from_file(path, serialization=fmt).graph
        assert (
            rdflib.URIRef(path.as_uri()),
            rdflib.RDF.type,
            SKOS.ConceptScheme,
        ) in graph
        assert (
            rdflib.URIRef(path.parent.as_uri() + "/concept-a"),
            rdflib.RDF.type,
            SKOS.Concept,
        ) in graph

    def test_absolute_identifiers_are_unaffected_by_a_given_base_uri(self):
        with_base = SkosGraph.from_file(
            FIXTURES / "rocks.ttl", base_uri="https://example.org/vocab.ttl"
        ).graph
        without_base = SkosGraph.from_file(FIXTURES / "rocks.ttl").graph
        assert (ROCKS_SCHEME_URI, rdflib.RDF.type, SKOS.ConceptScheme) in with_base
        assert (ROCKS_SCHEME_URI, rdflib.RDF.type, SKOS.ConceptScheme) in without_base

    def test_missing_file_refusal_names_the_base_uri_when_given(self, tmp_path):
        missing = tmp_path / "does-not-exist.ttl"
        with pytest.raises(SkosImportError) as exc_info:
            SkosGraph.from_file(missing, base_uri="https://example.org/vocab.ttl")
        assert "https://example.org/vocab.ttl" in str(exc_info.value)
        assert str(missing) not in str(exc_info.value)

    def test_unsupported_serialization_refusal_names_the_base_uri_when_given(
        self, tmp_path
    ):
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with pytest.raises(SkosImportError) as exc_info:
            SkosGraph.from_file(mystery, base_uri="https://example.org/vocab.ttl")
        assert "https://example.org/vocab.ttl" in str(exc_info.value)
        assert str(mystery) not in str(exc_info.value)

    def test_unparseable_file_refusal_names_the_base_uri_when_given(self, tmp_path):
        bad = tmp_path / "bad.ttl"
        bad.write_text("this is not turtle @@@ not even close {{{ ]][[ ")
        with pytest.raises(SkosImportError) as exc_info:
            SkosGraph.from_file(bad, base_uri="https://example.org/vocab.ttl")
        assert "https://example.org/vocab.ttl" in str(exc_info.value)
        assert str(bad) not in str(exc_info.value)


class TestPreferredLabelTagCounts:
    def test_counts_reflect_the_whole_file_not_any_one_concept(self, tmp_path):
        path = tmp_path / "counts.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/v/> a skos:ConceptScheme ;
                skos:prefLabel "V"@en .

            <http://example.org/v/a> a skos:Concept ;
                skos:inScheme <http://example.org/v/> ;
                skos:prefLabel "A"@en-gb .

            <http://example.org/v/b> a skos:Concept ;
                skos:inScheme <http://example.org/v/> ;
                skos:prefLabel "B"@en-gb, "B2"@en-us .
            """
        )
        skos_graph = SkosGraph.from_file(path)
        concept_nodes = sorted(
            skos_graph.graph.subjects(rdflib.RDF.type, SKOS.Concept), key=str
        )
        counts = skos_graph.preferred_label_tag_counts(concept_nodes)
        assert counts == {"en-gb": 2, "en-us": 1}

    def test_case_varying_tags_for_one_language_fold_into_one_count(self, tmp_path):
        # A re-cased tag is not a different language (RFC 5646), so "en-GB" and "en-gb"
        # are one population.
        path = tmp_path / "case_counts.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/v/> a skos:ConceptScheme ;
                skos:prefLabel "V"@en .

            <http://example.org/v/a> a skos:Concept ;
                skos:inScheme <http://example.org/v/> ;
                skos:prefLabel "A"@en-GB .

            <http://example.org/v/b> a skos:Concept ;
                skos:inScheme <http://example.org/v/> ;
                skos:prefLabel "B"@en-gb .
            """
        )
        skos_graph = SkosGraph.from_file(path)
        concept_nodes = sorted(
            skos_graph.graph.subjects(rdflib.RDF.type, SKOS.Concept), key=str
        )
        counts = skos_graph.preferred_label_tag_counts(concept_nodes)
        assert counts == {"en-gb": 2}

    def test_counts_exclude_the_scheme_and_collection_nodes_own_labels(self, tmp_path):
        # Counting graph-wide would also sweep the scheme's and collection's own
        # prefLabels and change the default-language rule.
        path = tmp_path / "scope.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/v/> a skos:ConceptScheme ;
                skos:prefLabel "V"@de .

            <http://example.org/v/collection/x> a skos:Collection ;
                skos:prefLabel "X"@de ;
                skos:member <http://example.org/v/a> .

            <http://example.org/v/a> a skos:Concept ;
                skos:inScheme <http://example.org/v/> ;
                skos:prefLabel "A"@en-gb .
            """
        )
        skos_graph = SkosGraph.from_file(path)
        concept_nodes = sorted(
            skos_graph.graph.subjects(rdflib.RDF.type, SKOS.Concept), key=str
        )
        counts = skos_graph.preferred_label_tag_counts(concept_nodes)
        assert counts == {"en-gb": 1}


class TestSkosImporterWiresOneMatcherToBothResolvers:
    def test_scheme_resolver_and_concept_importer_share_the_same_matcher_instance(
        self, db, monkeypatch
    ):
        captured = {}
        original_scheme_resolver_init = SchemeResolver.__init__
        original_concept_importer_init = ConceptImporter.__init__

        def spy_scheme_resolver_init(self, *args, **kwargs):
            captured["scheme_resolver"] = kwargs["matcher"]
            original_scheme_resolver_init(self, *args, **kwargs)

        def spy_concept_importer_init(self, *args, **kwargs):
            captured["concept_importer"] = kwargs["matcher"]
            original_concept_importer_init(self, *args, **kwargs)

        monkeypatch.setattr(SchemeResolver, "__init__", spy_scheme_resolver_init)
        monkeypatch.setattr(ConceptImporter, "__init__", spy_concept_importer_init)

        report = import_skos(FIXTURES / "rocks.ttl")

        assert report.fatal == []
        assert isinstance(captured["scheme_resolver"], LanguageMatcher)
        assert captured["scheme_resolver"] is captured["concept_importer"]


class TestImportSkosVocabulary:
    def test_a_declared_vocabulary_is_created_when_not_already_held(self, db):
        report = import_skos(FIXTURES / "rocks.ttl")
        scheme = ConceptScheme.objects.get(static_uri=ROCKS_URI)
        assert scheme.name == "Rock types"
        assert ROCKS_URI in report.created
        assert ROCKS_URI not in report.updated
        assert report.fatal == []

    def test_a_declared_vocabulary_already_held_is_updated_not_duplicated(self, db):
        existing = ConceptSchemeFactory(name="Old name", static_uri=ROCKS_URI)
        report = import_skos(FIXTURES / "rocks.ttl")
        existing.refresh_from_db()
        assert existing.name == "Rock types"
        assert ConceptScheme.objects.filter(static_uri=ROCKS_URI).count() == 1
        assert ROCKS_URI in report.updated
        assert ROCKS_URI not in report.created

    def test_a_named_target_that_matches_the_file_succeeds(self, db):
        target = ConceptSchemeFactory(name="Old name", static_uri=ROCKS_URI)
        report = import_skos(FIXTURES / "rocks.ttl", scheme=target)
        target.refresh_from_db()
        assert target.name == "Rock types"
        assert report.fatal == []

    def test_a_named_target_that_contradicts_the_file_fails_and_writes_nothing(
        self, db
    ):
        target = ConceptSchemeFactory(name="Unrelated vocabulary", external=True)
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "rocks.ttl", scheme=target)
        assert (
            exc_info.value.report.fatal[0].reason
            is FatalReason.VOCABULARY_TARGET_MISMATCH
        )
        target.refresh_from_db()
        assert target.name == "Unrelated vocabulary"
        assert not ConceptScheme.objects.filter(static_uri=ROCKS_URI).exists()

    def test_a_file_declaring_no_vocabulary_fails_without_a_named_target(self, db):
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "no_scheme_declared.ttl")
        assert (
            exc_info.value.report.fatal[0].reason is FatalReason.VOCABULARY_UNDETERMINED
        )
        assert ConceptScheme.objects.count() == 0

    def test_a_file_declaring_no_vocabulary_succeeds_with_a_named_target(self, db):
        target = ConceptSchemeFactory(name="Loose concepts")
        report = import_skos(FIXTURES / "no_scheme_declared.ttl", scheme=target)
        assert report.fatal == []

    def test_a_refusal_names_the_base_uri_when_given(self, db):
        # A fetched document's refusals name where it came from, not the temporary file
        # it was written to for the parse.
        path = FIXTURES / "no_scheme_declared.ttl"
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path, base_uri="https://example.org/loose.ttl")
        finding = exc_info.value.report.fatal[0]
        assert finding.reason is FatalReason.VOCABULARY_UNDETERMINED
        assert "https://example.org/loose.ttl" in finding.render()
        assert str(path) not in finding.render()


class TestChoosingBetweenDeclaredVocabularies:
    def test_the_vocabulary_most_of_the_concepts_belong_to_is_the_one_imported(
        self, db
    ):
        report = import_skos(FIXTURES / "mixed_scheme_membership.ttl")
        assert ConceptScheme.objects.get().static_uri == "http://example.org/minerals/"
        assert report.fatal == []

    def test_the_choice_does_not_depend_on_the_order_of_the_identifiers(
        self, db, tmp_path
    ):
        # The same file with the two vocabularies' identifiers swapped so the
        # foreign one now sorts first. Sorted-first selection would import it.
        source = (FIXTURES / "mixed_scheme_membership.ttl").read_text()
        swapped = source.replace(
            "http://example.org/other/", "http://example.org/aaa-other/"
        )
        renamed = tmp_path / "swapped.ttl"
        renamed.write_text(swapped)
        import_skos(renamed)
        assert ConceptScheme.objects.get().static_uri == "http://example.org/minerals/"

    def test_two_vocabularies_with_an_equal_claim_fail_without_a_named_target(self, db):
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "two_vocabularies.ttl")
        finding = exc_info.value.report.fatal[0]
        assert finding.reason is FatalReason.VOCABULARY_AMBIGUOUS
        assert "http://example.org/alpha/" in finding.render()
        assert "http://example.org/beta/" in finding.render()
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0

    def test_a_named_target_decides_between_them(self, db):
        target = ConceptSchemeFactory(
            name="Beta vocabulary", static_uri="http://example.org/beta/"
        )
        report = import_skos(FIXTURES / "two_vocabularies.ttl", scheme=target)
        assert report.fatal == []
        assert ConceptScheme.objects.count() == 1
        assert (
            Concept.objects.get(scheme=target).static_uri
            == "http://example.org/beta/two"
        )


class TestImportedVocabularyDefaultLanguage:
    def test_a_vocabulary_declared_in_a_configured_non_default_language_uses_it(
        self, db
    ):
        import_skos(FIXTURES / "french_vocabulary.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/geology/")
        assert scheme.default_language == "fr"
        assert scheme.effective_default_language == "fr"
        assert scheme.name == "Types de roches"

    def test_a_vocabulary_declared_in_an_unconfigured_language_falls_back_to_the_site_default(
        self, db
    ):
        import_skos(FIXTURES / "unconfigured_language_vocabulary.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/geology2/")
        # Neither "es" (declared) nor "es" (commonest concept label language)
        # is configured, so nothing overrides the site default.
        assert scheme.effective_default_language == "en"

    def test_default_language_is_not_recomputed_for_a_scheme_that_already_has_concepts(
        self, db
    ):
        # ConceptScheme.save() refuses to change default_language once concepts exist,
        # so a re-run must not trip that guard by recomputing it from the file.
        scheme = ConceptSchemeFactory(
            name="Geology",
            static_uri="http://example.org/geology/",
            default_language="",
        )
        ConceptFactory(scheme=scheme, label="Existing concept")
        report = import_skos(FIXTURES / "french_vocabulary.ttl")
        assert report.fatal == []
        scheme.refresh_from_db()
        assert scheme.default_language == ""


class TestDefaultLanguageResolvesThroughTheMatcher:
    def test_a_vocabulary_declaring_itself_in_a_variant_of_a_configured_language_resolves_to_it(
        self, db
    ):
        import_skos(FIXTURES / "declares-de-at.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/farben/")
        assert scheme.default_language == "de"
        assert scheme.effective_default_language == "de"

    def test_the_commonest_concept_language_fallback_also_resolves_through_the_matcher(
        self, db, tmp_path
    ):
        # The scheme's own prefLabel carries two tags, so determine_default_language
        # falls back to the commonest concept language, which must also resolve through
        # the matcher.
        path = tmp_path / "commonest.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/hues/> a skos:ConceptScheme ;
                skos:prefLabel "Hues"@en-gb, "Farben"@de .

            <http://example.org/hues/a> a skos:Concept ;
                skos:inScheme <http://example.org/hues/> ;
                skos:prefLabel "Red"@en-gb .

            <http://example.org/hues/b> a skos:Concept ;
                skos:inScheme <http://example.org/hues/> ;
                skos:prefLabel "Blue"@en-gb .
            """
        )
        import_skos(path)
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/hues/")
        assert scheme.default_language == "en"
        assert scheme.effective_default_language == "en"

    def test_a_vocabulary_whose_declared_language_shares_no_base_with_any_configured_language_still_falls_back(
        self, db
    ):
        # A declared language with no configured base at all still falls back to the
        # site default (#50).
        import_skos(FIXTURES / "unconfigured_language_vocabulary.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/geology2/")
        assert scheme.effective_default_language == "en"


class TestDefaultLanguageCommonestFallbackFoldsCaseLikeThePreferredLabelTally:
    def _write(self, tmp_path: Path) -> Path:
        """Write a vocabulary whose concept language tags differ only by case.

        Args:
            tmp_path: Directory to write the file into.

        Returns:
            The path of the written file.
        """
        lines = [
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
            # Two languages on the scheme's own prefLabel so declared_languages has len != 1
            # and determine_default_language falls through to the commonest-concept branch.
            '<http://example.org/casetally/> a skos:ConceptScheme ; skos:prefLabel "Hues"@en-gb, "Farben"@de .',
        ]
        for i in range(4):
            lines.append(
                f"<http://example.org/casetally/fr{i}> a skos:Concept ; "
                f'skos:inScheme <http://example.org/casetally/> ; skos:prefLabel "Rouge {i}"@fr .'
            )
        for i in range(3):
            lines.append(
                f"<http://example.org/casetally/upper{i}> a skos:Concept ; "
                f'skos:inScheme <http://example.org/casetally/> ; skos:prefLabel "Red {i}"@EN-GB .'
            )
        for i in range(3):
            lines.append(
                f"<http://example.org/casetally/lower{i}> a skos:Concept ; "
                f'skos:inScheme <http://example.org/casetally/> ; skos:prefLabel "Red {i}"@en-gb .'
            )
        path = tmp_path / "case_tally.ttl"
        path.write_text("\n".join(lines))
        return path

    def test_a_published_tag_split_across_two_cases_is_counted_as_one_population(
        self, db, tmp_path
    ):
        path = self._write(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/casetally/")
        # en-gb (3 + 3 = 6, folded) outnumbers fr (4); en-gb shares its base with the
        # configured "en", so the vocabulary's default language resolves to "en" — not "fr",
        # which is where the unfolded tally's 4-vs-3-vs-3 split would send it.
        assert scheme.effective_default_language == "en"
        assert report.fatal == []

    def test_the_predominant_en_gb_population_is_not_wrongly_set_aside(
        self, db, tmp_path
    ):
        # Every en-gb concept has a preferred label through the matcher's base-language
        # match. The four fr-only concepts have no English label, so their exclusion is
        # correct and not asserted.
        path = self._write(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)
        en_gb_uris = {f"http://example.org/casetally/upper{i}" for i in range(3)} | {
            f"http://example.org/casetally/lower{i}" for i in range(3)
        }
        assert (
            set(
                Concept.objects.filter(static_uri__in=en_gb_uris).values_list(
                    "static_uri", flat=True
                )
            )
            == en_gb_uris
        )
        wrongly_set_aside = {
            entry.subject
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_PREFERRED_LABEL
            and entry.subject in en_gb_uris
        }
        assert wrongly_set_aside == set()


class TestImportConcepts:
    def test_every_concept_in_the_base_vocabulary_is_created_with_its_identifier_and_label(
        self, db
    ):
        report = import_skos(FIXTURES / "rocks.ttl")
        assert Concept.objects.count() == 5
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        assert granite.label == "Granite"
        assert granite.scheme.static_uri == "http://example.org/rocks/"
        assert set(report.created) >= {
            "http://example.org/rocks/",
            "http://example.org/rocks/granite",
            "http://example.org/rocks/igneous",
            "http://example.org/rocks/basalt",
            "http://example.org/rocks/sedimentary",
            "http://example.org/rocks/quartz",
        }

    def test_scheme_membership_via_hasTopConcept_inScheme_and_topConceptOf_all_attach_correctly(
        self, db
    ):
        import_skos(FIXTURES / "mixed_scheme_membership.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/minerals/")
        attached = set(
            Concept.objects.filter(scheme=scheme).values_list("static_uri", flat=True)
        )
        assert attached == {
            "http://example.org/minerals/quartz",
            "http://example.org/minerals/feldspar",
            "http://example.org/minerals/mica",
        }

    def test_a_concept_claiming_a_different_vocabulary_is_set_aside_not_imported(
        self, db
    ):
        report = import_skos(FIXTURES / "mixed_scheme_membership.ttl")
        assert not Concept.objects.filter(
            static_uri="http://example.org/minerals/foreign"
        ).exists()
        mismatches = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VOCABULARY_MISMATCH
        ]
        assert len(mismatches) == 1
        assert mismatches[0].subject == "http://example.org/minerals/foreign"
        assert mismatches[0].params["other"] == "http://example.org/other/"

    def test_a_concept_with_no_preferred_label_in_the_default_language_is_set_aside_and_the_rest_imports(
        self, db
    ):
        report = import_skos(FIXTURES / "no_default_language_label.ttl")
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/quarry/"
            ).count()
            == 2
        )
        assert not Concept.objects.filter(
            static_uri="http://example.org/quarry/c"
        ).exists()
        set_aside = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_PREFERRED_LABEL
        ]
        assert len(set_aside) == 1
        assert set_aside[0].subject == "http://example.org/quarry/c"
        assert set_aside[0].params["language"] == "en"

    def test_reimporting_the_identical_file_updates_rather_than_duplicates_concepts(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        granite_pk = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        ).pk
        report = import_skos(FIXTURES / "rocks.ttl")
        assert Concept.objects.count() == 5
        assert (
            Concept.objects.get(static_uri="http://example.org/rocks/granite").pk
            == granite_pk
        )
        assert "http://example.org/rocks/granite" in report.updated
        assert "http://example.org/rocks/granite" not in report.created


class TestConceptLabelIsSelectedByTheWinnerRule:
    def test_a_concept_whose_only_preferred_label_is_a_variant_of_the_default_language_still_names_it(
        self, db
    ):
        import_skos(FIXTURES / "declares-de-at.ttl")
        rot = Concept.objects.get(static_uri="http://example.org/farben/rot")
        assert rot.label == "Rot"
        assert rot.slug == "rot"

    def test_an_exact_match_is_not_displaced_by_a_more_predominant_variant(
        self, db, tmp_path
    ):
        # "en-gb" is the predominant tag across the file (three occurrences), but the
        # target concept also carries an exact "en" match, which always wins regardless
        # of predominance.
        path = tmp_path / "exact_wins.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/exactwins/> a skos:ConceptScheme ;
                skos:prefLabel "Exact wins"@en .

            <http://example.org/exactwins/other1> a skos:Concept ;
                skos:inScheme <http://example.org/exactwins/> ;
                skos:prefLabel "Other"@en-gb .

            <http://example.org/exactwins/other2> a skos:Concept ;
                skos:inScheme <http://example.org/exactwins/> ;
                skos:prefLabel "Other"@en-gb .

            <http://example.org/exactwins/target> a skos:Concept ;
                skos:inScheme <http://example.org/exactwins/> ;
                skos:prefLabel "Alpha"@en, "Beta"@en-gb .
            """
        )
        import_skos(path)
        target = Concept.objects.get(static_uri="http://example.org/exactwins/target")
        assert target.label == "Alpha"
        # The slug comes from the published identifier's last segment, not the winning
        # label.
        assert target.slug == "target"


class TestLabelsNotesAndNamesResolveThroughTheMatcher:
    def test_an_en_only_vocabulary_imports_into_an_en_gb_configured_site(self, db):
        # General-to-specific: rocks.ttl is unmodified, only the configured languages
        # narrow to en-gb.
        with override_settings(LANGUAGES=[("en-gb", "British English")]):
            report = import_skos(FIXTURES / "rocks.ttl")
            assert report.fatal == []
            igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
            assert igneous.label == "Igneous rock"
            assert (
                igneous.definition("en-gb")
                == "Rock formed by the cooling and solidification of magma or lava."
            )
            granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
            assert granite.alt_labels("en-gb") == ["Magma rock"]
            assert granite.hidden_labels("en-gb") == ["Granit rock"]

    def test_an_en_gb_only_vocabulary_imports_into_an_en_configured_site(self, db):
        report = import_skos(FIXTURES / "en-gb-only.ttl")
        assert report.fatal == []
        colour = Concept.objects.get(static_uri="http://example.org/colours-gb/colour")
        assert colour.label == "Colour"
        assert colour.alt_labels("en") == ["Hue"]
        assert colour.notes("en") == ["The visible spectral quality of light."]

    def test_a_de_at_published_vocabulary_on_a_de_site_imports_its_preferred_labels_without_raising(
        self, db
    ):
        # The alt label and note are also tagged de-at and must resolve through the
        # matcher, not only the preferred label.
        report = import_skos(FIXTURES / "declares-de-at.ttl")
        assert report.fatal == []
        rot = Concept.objects.get(static_uri="http://example.org/farben/rot")
        assert rot.label == "Rot"
        assert rot.alt_labels("de") == ["Karmesinrot"]
        assert rot.notes("de") == ["Eine der Grundfarben."]

    def test_a_tag_differing_only_in_case_is_treated_as_an_exact_match(
        self, db, tmp_path
    ):
        path = tmp_path / "case.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/case/> a skos:ConceptScheme ;
                skos:prefLabel "Case"@en .

            <http://example.org/case/item> a skos:Concept ;
                skos:inScheme <http://example.org/case/> ;
                skos:prefLabel "Item"@en, "Artikel"@DE .
            """
        )
        report = import_skos(path)
        assert report.fatal == []
        item = Concept.objects.get(static_uri="http://example.org/case/item")
        assert item.preferred_label("de") == "Artikel"

    def test_a_tag_sharing_no_base_language_with_any_configured_language_is_still_set_aside(
        self, db, tmp_path
    ):
        path = tmp_path / "nobase.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/nobase/> a skos:ConceptScheme ;
                skos:prefLabel "No base"@en .

            <http://example.org/nobase/item> a skos:Concept ;
                skos:inScheme <http://example.org/nobase/> ;
                skos:prefLabel "Item"@en ;
                skos:altLabel "アイテム"@ja .
            """
        )
        report = import_skos(path)
        item = Concept.objects.get(static_uri="http://example.org/nobase/item")
        assert item.alt_labels("ja") == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        ]
        assert len(entries) == 1
        assert entries[0].subject == item.static_uri
        assert entries[0].params["language"] == "ja"

    def test_the_vocabularys_own_name_and_description_resolve_through_the_matcher_too(
        self, db, tmp_path
    ):
        # Without the matcher, first_literal's exact filter finds no "de" literal and
        # falls back to sorted(...)[0] across every language in the file.
        path = tmp_path / "named.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix dcterms: <http://purl.org/dc/terms/> .

            <http://example.org/named/> a skos:ConceptScheme ;
                skos:prefLabel "Aardvark scheme"@fr, "Named scheme"@de-at ;
                dcterms:description "Aardvark description"@fr, "Named description"@de-at .

            <http://example.org/named/item> a skos:Concept ;
                skos:inScheme <http://example.org/named/> ;
                skos:prefLabel "Item"@de-at .
            """
        )
        import_skos(path)
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/named/")
        assert scheme.effective_default_language == "de"
        assert scheme.name == "Named scheme"
        assert scheme.description == "Named description"

    def test_a_collections_own_name_resolves_through_the_matcher_too(
        self, db, tmp_path
    ):
        path = tmp_path / "named_collection.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/namedcoll/> a skos:ConceptScheme ;
                skos:prefLabel "Named collection scheme"@de .

            <http://example.org/namedcoll/item> a skos:Concept ;
                skos:inScheme <http://example.org/namedcoll/> ;
                skos:prefLabel "Item"@de .

            <http://example.org/namedcoll/coll> a skos:Collection ;
                skos:prefLabel "Aardvark collection"@fr, "Named collection"@de-at ;
                skos:member <http://example.org/namedcoll/item> .
            """
        )
        import_skos(path)
        collection = Collection.objects.get(
            static_uri="http://example.org/namedcoll/coll"
        )
        assert collection.name == "Named collection"


class TestVocabularyAndCollectionNameSubstitutionIsReported:
    def test_the_vocabularys_name_and_description_are_each_reported_as_a_substitution(
        self, db, tmp_path
    ):
        path = tmp_path / "named.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix dcterms: <http://purl.org/dc/terms/> .

            <http://example.org/named/> a skos:ConceptScheme ;
                skos:prefLabel "Aardvark scheme"@fr, "Named scheme"@de-at ;
                dcterms:description "Aardvark description"@fr, "Named description"@de-at .

            <http://example.org/named/item> a skos:Concept ;
                skos:inScheme <http://example.org/named/> ;
                skos:prefLabel "Item"@de-at .
            """
        )
        report = import_skos(path)
        scheme_uri = "http://example.org/named/"
        matching = [
            entry
            for entry in report.normalized
            if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == scheme_uri
        ]
        # One entry each for the name and the description, both de-at -> de.
        assert len(matching) == 2
        assert all(
            entry.params == {"language": "de-at", "kept_as": "de"} for entry in matching
        )

    def test_a_collections_name_is_reported_as_a_substitution(self, db, tmp_path):
        path = tmp_path / "named_collection.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/namedcoll/> a skos:ConceptScheme ;
                skos:prefLabel "Named collection scheme"@de .

            <http://example.org/namedcoll/item> a skos:Concept ;
                skos:inScheme <http://example.org/namedcoll/> ;
                skos:prefLabel "Item"@de .

            <http://example.org/namedcoll/coll> a skos:Collection ;
                skos:prefLabel "Aardvark collection"@fr, "Named collection"@de-at ;
                skos:member <http://example.org/namedcoll/item> .
            """
        )
        report = import_skos(path)
        collection = Collection.objects.get(
            static_uri="http://example.org/namedcoll/coll"
        )
        matching = [
            entry
            for entry in report.normalized
            if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == collection.static_uri
        ]
        assert len(matching) == 1
        assert matching[0].params == {"language": "de-at", "kept_as": "de"}

    def test_an_exact_match_scheme_name_is_not_reported_as_a_substitution(self, db):
        # No substitution when the name is published in exactly the resolved default
        # language.
        report = import_skos(FIXTURES / "rocks.ttl")
        scheme_uri = "http://example.org/rocks/"
        assert not any(
            entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == scheme_uri
            for entry in report.normalized
        )


class TestLanguageSubstitutionIsReported:
    def test_the_concepts_label_alt_label_and_note_are_each_reported_as_a_substitution(
        self, db
    ):
        report = import_skos(FIXTURES / "declares-de-at.ttl")
        rot_uri = "http://example.org/farben/rot"
        substitutions = {
            (entry.params["language"], entry.params["kept_as"])
            for entry in report.normalized
            if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == rot_uri
        }
        assert substitutions == {("de-at", "de")}
        assert (
            len(
                [
                    entry
                    for entry in report.normalized
                    if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
                    and entry.subject == rot_uri
                ]
            )
            == 3
        )  # the label, the alternative label, and the note

    def test_a_substitution_is_distinguishable_from_a_value_that_was_not_stored(
        self, db, tmp_path
    ):
        path = tmp_path / "mixed.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/mixed/> a skos:ConceptScheme ;
                skos:prefLabel "Mixed"@en .

            <http://example.org/mixed/item> a skos:Concept ;
                skos:inScheme <http://example.org/mixed/> ;
                skos:prefLabel "Item"@en ;
                skos:altLabel "Article"@en-gb, "記事"@ja .
            """
        )
        report = import_skos(path)
        item = Concept.objects.get(static_uri="http://example.org/mixed/item")
        assert item.alt_labels("en") == ["Article"]
        substitution_subjects = {
            entry.subject
            for entry in report.normalized
            if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
        }
        not_stored_subjects = {
            entry.subject
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        }
        assert item.static_uri in substitution_subjects
        assert item.static_uri in not_stored_subjects
        substitution_languages = {
            entry.params["language"]
            for entry in report.normalized
            if entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == item.static_uri
        }
        assert substitution_languages == {"en-gb"}
        not_stored_languages = {
            entry.params["language"]
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
            and entry.subject == item.static_uri
        }
        assert not_stored_languages == {"ja"}

    def test_a_substitution_does_not_appear_in_the_language_account(self, db):
        report = import_skos(FIXTURES / "declares-de-at.ttl")
        assert "de-at" not in report.language_account()

    def test_an_exact_case_insensitive_match_is_not_reported_as_a_substitution(
        self, db, tmp_path
    ):
        # A case-only difference is an exact match, not a variant.
        path = tmp_path / "case_no_substitution.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/casesub/> a skos:ConceptScheme ;
                skos:prefLabel "Case"@en .

            <http://example.org/casesub/item> a skos:Concept ;
                skos:inScheme <http://example.org/casesub/> ;
                skos:prefLabel "Item"@en, "Artikel"@DE .
            """
        )
        report = import_skos(path)
        assert report.normalized == []


class TestTheLanguageAccountReflectsARealImport:
    def test_the_account_covers_every_unconfigured_value_and_no_stored_value(
        self, db, tmp_path
    ):
        path = tmp_path / "multilingual.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/multiling/> a skos:ConceptScheme ;
                skos:prefLabel "Multiling"@en .

            <http://example.org/multiling/a> a skos:Concept ;
                skos:inScheme <http://example.org/multiling/> ;
                skos:prefLabel "A"@en ;
                skos:altLabel "A1"@es, "A2"@es .

            <http://example.org/multiling/b> a skos:Concept ;
                skos:inScheme <http://example.org/multiling/> ;
                skos:prefLabel "B"@en ;
                skos:note "B1"@ja .

            <http://example.org/multiling/c> a skos:Concept ;
                skos:inScheme <http://example.org/multiling/> ;
                skos:prefLabel "C"@en ;
                skos:altLabel "C1"@it ;
                skos:note "C2"@it, "C3"@it .
            """
        )
        report = import_skos(path)
        assert report.language_account() == {"es": 2, "ja": 1, "it": 3}

        unconfigured = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        ]
        assert sum(report.language_account().values()) == len(unconfigured)

        assert (
            Concept.objects.get(static_uri="http://example.org/multiling/a").label
            == "A"
        )
        assert "en" not in report.language_account()

    def test_present_and_empty_after_an_import_that_leaves_nothing_behind(self, db):
        # rocks.ttl is the clean-run fixture TestReportPopulatedByARealRun already pins
        # to no set-aside entries.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.set_aside == []
        assert report.language_account() == {}


class TestConceptsImpliedByMembershipButNeverGivenAnRdfType:
    def test_a_node_reachable_only_through_hastopconcept_is_imported_as_a_concept(
        self, db
    ):
        import_skos(FIXTURES / "concept_implied_by_membership_no_rdf_type.ttl")
        alpha = Concept.objects.get(static_uri="http://example.org/implied/alpha")
        assert alpha.label == "Alpha"
        assert alpha.scheme.static_uri == "http://example.org/implied/"

    def test_a_node_reachable_only_through_its_own_inscheme_is_imported_as_a_concept(
        self, db
    ):
        import_skos(FIXTURES / "concept_implied_by_membership_no_rdf_type.ttl")
        beta = Concept.objects.get(static_uri="http://example.org/implied/beta")
        assert beta.label == "Beta"
        assert beta.scheme.static_uri == "http://example.org/implied/"

    def test_a_node_reachable_only_through_its_own_topconceptof_is_imported_as_a_concept(
        self, db
    ):
        import_skos(FIXTURES / "concept_implied_by_membership_no_rdf_type.ttl")
        gamma = Concept.objects.get(static_uri="http://example.org/implied/gamma")
        assert gamma.label == "Gamma"
        assert gamma.scheme.static_uri == "http://example.org/implied/"

    def test_all_three_are_named_created_and_the_run_reports_no_fatal_findings(
        self, db
    ):
        report = import_skos(FIXTURES / "concept_implied_by_membership_no_rdf_type.ttl")
        assert report.fatal == []
        assert set(report.created) == {
            "http://example.org/implied/",
            "http://example.org/implied/alpha",
            "http://example.org/implied/beta",
            "http://example.org/implied/gamma",
        }

    def test_a_node_already_typed_as_something_else_is_never_reclassified(self, db):
        # A node the file does give an rdf:type is never overridden by the widened
        # discovery, so the scheme nodes stay schemes rather than being swept up as
        # concepts.
        import_skos(FIXTURES / "mixed_scheme_membership.ttl")
        assert not Concept.objects.filter(
            static_uri="http://example.org/minerals/"
        ).exists()
        assert ConceptScheme.objects.filter(
            static_uri="http://example.org/minerals/"
        ).exists()


class TestConceptSlugs:
    def test_a_fragment_identifier_slugs_from_the_fragment(self, db, tmp_path):
        path = tmp_path / "fragment_identifier.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <https://example.org/v/colours> a skos:ConceptScheme ; skos:prefLabel "Colours"@en .

            <https://example.org/v/colours#colour> a skos:Concept ;
                skos:inScheme <https://example.org/v/colours> ;
                skos:prefLabel "Colour"@en .
            """
        )
        import_skos(path)
        colour = Concept.objects.get(static_uri="https://example.org/v/colours#colour")
        assert colour.slug == "colour"

    def test_a_path_only_identifier_slugs_from_the_last_path_segment(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        # The label is "Igneous rock" but the slug follows the identifier's last path
        # segment.
        assert igneous.slug == "igneous"

    def test_a_publisher_rename_leaves_the_slug_and_local_url_unchanged(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        granite_before = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        )
        slug_before = granite_before.slug
        local_url_before = granite_before.local_url
        assert granite_before.label == "Granite"

        report = import_skos(FIXTURES / "rocks_updated.ttl")

        granite_after = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        )
        assert "http://example.org/rocks/granite" in report.updated
        assert granite_after.label == "Granite (revised)"
        assert granite_after.slug == slug_before
        assert granite_after.local_url == local_url_before

    def test_two_concepts_sharing_a_label_no_longer_collide_on_slug(self, db):
        # The two concepts share a preferred label ("Quartz") but have distinct
        # identifiers, so the slug, which reads the identifier, has no collision to
        # resolve here.
        import_skos(FIXTURES / "duplicate_slug.ttl")
        first = Concept.objects.get(static_uri="http://example.org/quarry2/quartz-a")
        second = Concept.objects.get(static_uri="http://example.org/quarry2/quartz-b")
        assert first.slug == "quartz-a"
        assert second.slug == "quartz-b"
        assert first.static_uri != second.static_uri

    def test_reimporting_the_identical_file_keeps_each_concept_s_slug(self, db):
        import_skos(FIXTURES / "duplicate_slug.ttl")
        first_slug_before = Concept.objects.get(
            static_uri="http://example.org/quarry2/quartz-a"
        ).slug
        second_slug_before = Concept.objects.get(
            static_uri="http://example.org/quarry2/quartz-b"
        ).slug

        import_skos(FIXTURES / "duplicate_slug.ttl")

        assert (
            Concept.objects.get(static_uri="http://example.org/quarry2/quartz-a").slug
            == first_slug_before
        )
        assert (
            Concept.objects.get(static_uri="http://example.org/quarry2/quartz-b").slug
            == second_slug_before
        )
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/quarry2/"
            ).count()
            == 2
        )


class TestConceptSlugCollisionIsIdentifierDerived:
    def _write(self, tmp_path: Path, name: str, first: str, second: str) -> Path:
        """Write a vocabulary holding two concepts and return its path.

        Args:
            tmp_path: Directory to write the file into.
            name: File name.
            first: Turtle for the first concept.
            second: Turtle for the second concept.

        Returns:
            The path of the written file.
        """
        path = tmp_path / name
        path.write_text(
            f"""
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/collision/> a skos:ConceptScheme ; skos:prefLabel "Collision"@en .

            {first}
            {second}
            """
        )
        return path

    def test_two_identifiers_sharing_a_last_segment_get_distinct_slugs(
        self, db, tmp_path
    ):
        a_clay = (
            "<http://example.org/collision/a/clay> a skos:Concept ; "
            'skos:inScheme <http://example.org/collision/> ; skos:prefLabel "Clay A"@en .'
        )
        b_clay = (
            "<http://example.org/collision/b/clay> a skos:Concept ; "
            'skos:inScheme <http://example.org/collision/> ; skos:prefLabel "Clay B"@en .'
        )
        path = self._write(tmp_path, "collision.ttl", a_clay, b_clay)
        import_skos(path)

        a = Concept.objects.get(static_uri="http://example.org/collision/a/clay")
        b = Concept.objects.get(static_uri="http://example.org/collision/b/clay")
        assert {a.slug, b.slug} == {"clay", "clay-2"}
        assert a.slug != b.slug

    def test_each_keeps_its_slug_when_the_file_is_reimported_with_the_records_declared_in_reverse_order(
        self, db, tmp_path
    ):
        a_clay = (
            "<http://example.org/collision/a/clay> a skos:Concept ; "
            'skos:inScheme <http://example.org/collision/> ; skos:prefLabel "Clay A"@en .'
        )
        b_clay = (
            "<http://example.org/collision/b/clay> a skos:Concept ; "
            'skos:inScheme <http://example.org/collision/> ; skos:prefLabel "Clay B"@en .'
        )
        first_path = self._write(tmp_path, "collision_first.ttl", a_clay, b_clay)
        import_skos(first_path)
        a_slug_before = Concept.objects.get(
            static_uri="http://example.org/collision/a/clay"
        ).slug
        b_slug_before = Concept.objects.get(
            static_uri="http://example.org/collision/b/clay"
        ).slug

        second_path = self._write(tmp_path, "collision_second.ttl", b_clay, a_clay)
        import_skos(second_path)

        assert (
            Concept.objects.get(static_uri="http://example.org/collision/a/clay").slug
            == a_slug_before
        )
        assert (
            Concept.objects.get(static_uri="http://example.org/collision/b/clay").slug
            == b_slug_before
        )


class TestConceptSchemeSlugFollowsThePublishedIdentifier:
    def test_a_scheme_name_arriving_in_a_different_language_does_not_move_the_scheme_or_its_concepts(
        self, db, tmp_path
    ):
        first = tmp_path / "renamed_scheme_first.ttl"
        first.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/renamedscheme/> a skos:ConceptScheme ; skos:prefLabel "Colours"@en-gb .

            <http://example.org/renamedscheme/clay> a skos:Concept ;
                skos:inScheme <http://example.org/renamedscheme/> ;
                skos:prefLabel "Clay"@en-gb .
            """
        )
        second = tmp_path / "renamed_scheme_second.ttl"
        second.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/renamedscheme/> a skos:ConceptScheme ; skos:prefLabel "Color"@en-us .

            <http://example.org/renamedscheme/clay> a skos:Concept ;
                skos:inScheme <http://example.org/renamedscheme/> ;
                skos:prefLabel "Clay"@en-gb .
            """
        )
        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(first)
        scheme_before = ConceptScheme.objects.get(
            static_uri="http://example.org/renamedscheme/"
        )
        slug_before = scheme_before.slug
        clay_before = Concept.objects.get(
            static_uri="http://example.org/renamedscheme/clay"
        )
        local_url_before = clay_before.local_url

        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(second)

        scheme_after = ConceptScheme.objects.get(
            static_uri="http://example.org/renamedscheme/"
        )
        clay_after = Concept.objects.get(
            static_uri="http://example.org/renamedscheme/clay"
        )
        assert scheme_after.name == "Color"
        assert scheme_after.slug == slug_before
        assert clay_after.local_url == local_url_before

    def test_a_scheme_s_slug_is_the_last_segment_of_its_identifier_not_its_name(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/rocks/")
        # The name "Rock types" would slugify to "rock-types"; the slug follows the
        # identifier instead.
        assert scheme.slug == "rocks"


class TestConceptSchemeSlugCollisionIsIdentifierDerived:
    def _write(self, tmp_path: Path, name: str, uri: str, label: str) -> Path:
        """Write a vocabulary with the given identifier and name and return its path.

        Args:
            tmp_path: Directory to write the file into.
            name: File name.
            uri: The vocabulary's published identifier.
            label: The vocabulary's English name.

        Returns:
            The path of the written file.
        """
        path = tmp_path / name
        path.write_text(
            f"""
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <{uri}> a skos:ConceptScheme ; skos:prefLabel "{label}"@en .
            """
        )
        return path

    def test_two_vocabularies_sharing_a_last_segment_both_import_with_distinct_slugs(
        self, db, tmp_path
    ):
        first = self._write(
            tmp_path, "scheme_collision_a.ttl", "http://a.org/colours", "Colours A"
        )
        second = self._write(
            tmp_path, "scheme_collision_b.ttl", "http://b.org/colours", "Colours B"
        )

        import_skos(first)
        import_skos(second)

        a = ConceptScheme.objects.get(static_uri="http://a.org/colours")
        b = ConceptScheme.objects.get(static_uri="http://b.org/colours")
        assert {a.slug, b.slug} == {"colours", "colours-2"}
        assert a.slug != b.slug

    def test_each_vocabulary_keeps_its_slug_when_its_own_file_is_reimported(
        self, db, tmp_path
    ):
        first = self._write(
            tmp_path, "scheme_collision_a.ttl", "http://a.org/colours", "Colours A"
        )
        second = self._write(
            tmp_path, "scheme_collision_b.ttl", "http://b.org/colours", "Colours B"
        )
        import_skos(first)
        import_skos(second)
        a_slug_before = ConceptScheme.objects.get(
            static_uri="http://a.org/colours"
        ).slug
        b_slug_before = ConceptScheme.objects.get(
            static_uri="http://b.org/colours"
        ).slug

        import_skos(first)
        import_skos(second)

        assert (
            ConceptScheme.objects.get(static_uri="http://a.org/colours").slug
            == a_slug_before
        )
        assert (
            ConceptScheme.objects.get(static_uri="http://b.org/colours").slug
            == b_slug_before
        )


class TestASlugAlreadyStoredIsReadBackNeverRecomputed:
    def test_a_vocabulary_keeps_its_suffixed_slug_after_a_colliding_sibling_is_deleted(
        self, db, tmp_path
    ):
        # Deleting the first of two "#terms" vocabularies and re-importing the second's
        # unchanged file must not move it onto the vacated "terms".
        first = tmp_path / "terms_a.ttl"
        first.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://a.example/x#terms> a skos:ConceptScheme ; skos:prefLabel "Terms A"@en .\n'
        )
        second = tmp_path / "terms_b.ttl"
        second.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://b.example/x#terms> a skos:ConceptScheme ; skos:prefLabel "Terms B"@en .\n'
        )
        import_skos(first)
        import_skos(second)
        a = ConceptScheme.objects.get(static_uri="http://a.example/x#terms")
        b = ConceptScheme.objects.get(static_uri="http://b.example/x#terms")
        assert {a.slug, b.slug} == {"terms", "terms-2"}
        b_slug_before = b.slug
        b_local_url_before = b.local_url

        a.delete()
        report = import_skos(second)

        b.refresh_from_db()
        assert b.slug == b_slug_before
        assert b.local_url == b_local_url_before
        assert "http://b.example/x#terms" in report.updated

    def test_a_concept_keeps_its_suffixed_slug_after_a_colliding_local_record_is_deleted(
        self, db, tmp_path
    ):
        # An external concept that collided with a locally authored one
        # (static_uri=None) keeps its suffix once the local record is deleted and the
        # same file is re-imported.
        path = tmp_path / "v4.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://v4.example/v4> a skos:ConceptScheme ; skos:prefLabel "V4"@en .\n'
            "<http://v4.example/v4/one> a skos:Concept ; skos:inScheme <http://v4.example/v4> ; "
            'skos:prefLabel "One"@en .\n'
        )
        import_skos(path)
        scheme = ConceptScheme.objects.get(static_uri="http://v4.example/v4")
        local_apple = ConceptFactory(scheme=scheme, label="Apple")
        assert local_apple.slug == "apple"

        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://v4.example/v4> a skos:ConceptScheme ; skos:prefLabel "V4"@en .\n'
            "<http://v4.example/v4/one> a skos:Concept ; skos:inScheme <http://v4.example/v4> ; "
            'skos:prefLabel "One"@en .\n'
            "<http://v4.example/v4/apple> a skos:Concept ; skos:inScheme <http://v4.example/v4> ; "
            'skos:prefLabel "Apple V4"@en .\n'
        )
        import_skos(path)
        remote_apple = Concept.objects.get(static_uri="http://v4.example/v4/apple")
        assert remote_apple.slug == "apple-2"

        local_apple.delete()
        import_skos(path)

        remote_apple.refresh_from_db()
        assert remote_apple.slug == "apple-2"

    def test_a_collection_keeps_its_suffixed_slug_after_a_colliding_sibling_is_deleted(
        self, db, tmp_path
    ):
        # The same shape for collections: deleting the first of two "#colours"
        # collections and re-importing the second unchanged must not move it onto the
        # vacated "colours".
        path = tmp_path / "collections_collide.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collcollide> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            '<http://pub.example/a#colours> a skos:Collection ; skos:prefLabel "Colours A"@en .\n'
            '<http://pub.example/b#colours> a skos:Collection ; skos:prefLabel "Colours B"@en .\n'
        )
        import_skos(path)
        a = Collection.objects.get(static_uri="http://pub.example/a#colours")
        b = Collection.objects.get(static_uri="http://pub.example/b#colours")
        assert {a.slug, b.slug} == {"colours", "colours-2"}
        b_slug_before = b.slug
        b_local_url_before = b.local_url

        a.delete()
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collcollide> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            '<http://pub.example/b#colours> a skos:Collection ; skos:prefLabel "Colours B"@en .\n'
        )
        report = import_skos(path)

        b.refresh_from_db()
        assert b.slug == b_slug_before
        assert b.local_url == b_local_url_before
        assert "http://pub.example/b#colours" in report.updated

    def test_a_locally_authored_scheme_concept_and_collection_are_matched_not_duplicated_when_first_imported(
        self, db, tmp_path
    ):
        # A locally authored scheme, concept and collection (static_uri NULL) must be
        # matched through get_by_uri's local-parse fallback rather than duplicated, and
        # pinned (slug_is_manual) so a later rename leaves every address where it was.
        scheme = ConceptSchemeFactory(name="Rocks")
        assert scheme.slug == "rocks"
        concept = ConceptFactory(scheme=scheme, label="Granite")
        assert concept.slug == "granite"
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert collection.slug == "igneous"
        base = conf.get_base_uri()

        path = tmp_path / "local_rocks.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<{base}/rocks> a skos:ConceptScheme ; skos:prefLabel "Rocks"@en .\n'
            f"<{base}/rocks/granite> a skos:Concept ; skos:inScheme <{base}/rocks> ; "
            'skos:prefLabel "Granite"@en .\n'
            f'<{base}/rocks/collection/igneous> a skos:Collection ; skos:prefLabel "Igneous"@en .\n'
        )
        report = import_skos(path)

        assert report.fatal == []
        assert ConceptScheme.objects.filter(name="Rocks").count() == 1
        assert (
            Concept.objects.filter(scheme__name="Rocks", label="Granite").count() == 1
        )
        assert (
            Collection.objects.filter(scheme__name="Rocks", name="Igneous").count() == 1
        )
        scheme.refresh_from_db()
        concept.refresh_from_db()
        collection.refresh_from_db()
        assert scheme.slug == "rocks"
        assert concept.slug == "granite"
        assert collection.slug == "igneous"
        assert scheme.slug_is_manual is True
        assert concept.slug_is_manual is True
        assert collection.slug_is_manual is True

        scheme_url_before, concept_url_before, collection_url_before = (
            scheme.local_url,
            concept.local_url,
            collection.local_url,
        )
        scheme.name = "Rock Types"
        scheme.save()
        concept.label = "Granitic Rock"
        concept.save()
        collection.name = "Igneous Rocks"
        collection.save()

        assert scheme.local_url == scheme_url_before
        assert concept.local_url == concept_url_before
        assert collection.local_url == collection_url_before


class TestUniqueSlugForIdentifierTruncationNeverSlicesNegative:
    def test_a_collision_suffix_as_long_as_max_length_does_not_discard_the_base(self):
        # With max_length=2 the retry suffix "-2" is as long as max_length, and an
        # unclamped base[:0] + "-2" would discard the base entirely.
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert result != "-2"
        assert result.startswith("a")

    def test_a_collision_suffix_longer_than_max_length_still_fits_within_max_length(
        self,
    ):
        # Clamping only the base is not enough: base[:1] + "-2" is three characters, so
        # the assembled candidate must be trimmed as well.
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert len(result) <= 2

    def test_a_normal_collision_is_unaffected_by_the_fix(self):
        taken = {"granite": "other"}
        result = unique_slug_for_identifier("http://e.org/#granite", taken, 255)
        assert result == "granite-2"


class TestUniqueSlugForIdentifierGivesUpRatherThanLoopingForever:
    def test_a_collision_that_always_clamps_to_the_same_candidate_gives_up_rather_than_hanging(
        self,
    ):
        # Asserting on the return value alone would hang on a regression instead of
        # failing, so the call runs in a daemon thread with a bounded join (no
        # pytest-timeout dependency).
        result_holder: list[str] = []
        worker = threading.Thread(
            target=lambda: result_holder.append(
                unique_slug_for_identifier(
                    "http://e.org/#ab", {"ab": "other", "a-": "other2"}, 2
                )
            ),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), (
            "unique_slug_for_identifier did not return within 5s (non-termination regression)"
        )
        assert result_holder == [""]

    def test_giving_up_does_not_disturb_a_collision_that_would_have_resolved_anyway(
        self,
    ):
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert result == "a-"

    def test_a_normal_collision_chain_is_unaffected(self):
        taken = {"granite": "other", "granite-2": "other2"}
        result = unique_slug_for_identifier("http://e.org/#granite", taken, 255)
        assert result == "granite-3"


class TestUniqueSlugForIdentifierResolvesACollisionEvenWhenTheBaseIsAlreadyMaxLength:
    def test_a_255_character_base_ending_in_dash_2_still_resolves_its_collision(self):
        base = "a" * 253 + "-2"
        assert len(base) == 255
        result = unique_slug_for_identifier(
            f"http://e.org/#{base}", {base: "other"}, 255
        )
        assert result != ""
        assert result != base

    def test_two_concepts_sharing_a_255_character_slug_base_both_import(
        self, db, tmp_path
    ):
        # Both fragments slugify and truncate to the same 255-character base, so this
        # exercises the give-up through import_skos and not only the helper.
        fragment_a = "a" * 253 + "-2" + "xx"
        fragment_b = "a" * 253 + "-2" + "yy"
        path = tmp_path / "collision.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f"<http://pub.example/scheme#{fragment_a}> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "Concept A"@en .\n'
            f"<http://pub.example/scheme#{fragment_b}> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "Concept B"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        assert report.set_aside == []
        concepts = Concept.objects.filter(
            scheme__static_uri="http://pub.example/scheme"
        )
        assert concepts.count() == 2
        slugs = set(concepts.values_list("slug", flat=True))
        assert len(slugs) == 2


class TestAGiveUpSlugIsReportedNotWrittenOrMislabeled:
    def test_a_concept_s_give_up_slug_is_empty_slug_not_stored_slug_invalid(
        self, db, tmp_path, monkeypatch
    ):
        # The scheme is pre-created so the patched give-up is exercised only through the
        # concept's own call site; a created scheme would hit resolve_scheme's guarded
        # call first.
        ConceptSchemeFactory(name="Vocab", static_uri="http://pub.example/scheme")
        path = tmp_path / "concept.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        monkeypatch.setattr(
            exchange.skos, "unique_slug_for_identifier", lambda *args, **kwargs: ""
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Concept.objects.filter(
            static_uri="http://pub.example/scheme#c1"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/scheme#c1"
        stored_slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert stored_slug_entries == []

    def test_a_collection_s_give_up_slug_is_empty_slug_not_stored_slug_invalid(
        self, db, tmp_path, monkeypatch
    ):
        ConceptSchemeFactory(name="Vocab", static_uri="http://pub.example/collscheme")
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/collscheme#grp> a skos:Collection ; "
            'skos:prefLabel "Group"@en .\n'
        )
        monkeypatch.setattr(
            exchange.skos, "unique_slug_for_identifier", lambda *args, **kwargs: ""
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/collscheme#grp"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert any(
            entry.subject == "http://pub.example/collscheme#grp" for entry in entries
        )
        stored_slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert stored_slug_entries == []


class TestSlugAndNameLengthAreBoundedToTheField:
    def test_a_concept_s_slug_is_truncated_to_the_field_s_max_length(
        self, db, tmp_path
    ):
        long_fragment = "a" * 400
        path = tmp_path / "long_concept_identifier.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/longconcept> a skos:ConceptScheme ; skos:prefLabel "L"@en .\n'
            f"<http://pub.example/longconcept#{long_fragment}> a skos:Concept ; "
            "skos:inScheme <http://pub.example/longconcept> ; "
            'skos:prefLabel "Long"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        concept = Concept.objects.get(
            static_uri=f"http://pub.example/longconcept#{long_fragment}"
        )
        max_length = Concept._meta.get_field("slug").max_length
        assert len(concept.slug) <= max_length
        concept.full_clean()

    def test_a_scheme_s_slug_is_truncated_to_the_field_s_max_length(self, db, tmp_path):
        long_fragment = "b" * 400
        path = tmp_path / "long_scheme_identifier.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/longscheme#{long_fragment}> a skos:ConceptScheme ; skos:prefLabel "S"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(
            static_uri=f"http://pub.example/longscheme#{long_fragment}"
        )
        max_length = ConceptScheme._meta.get_field("slug").max_length
        assert len(scheme.slug) <= max_length
        scheme.full_clean()

    def test_a_collection_s_slug_is_truncated_to_the_field_s_max_length(
        self, db, tmp_path
    ):
        long_fragment = "c" * 400
        path = tmp_path / "long_collection_identifier.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/longcollection> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/longcollection#{long_fragment}> a skos:Collection ; skos:prefLabel "Group"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri=f"http://pub.example/longcollection#{long_fragment}"
        )
        max_length = Collection._meta.get_field("slug").max_length
        assert len(collection.slug) <= max_length
        collection.full_clean()

    def test_a_scheme_name_longer_than_the_field_is_fatal_on_first_import(
        self, db, tmp_path
    ):
        # A created scheme has no earlier name to fall back to, so an unusable one is
        # fatal rather than stored blank.
        long_name = "N" * 300
        path = tmp_path / "long_scheme_name.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/longschemename> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNUSABLE
        assert report.fatal[0].subject == "http://pub.example/longschemename"
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/longschemename"
        ).exists()

    def test_a_matched_scheme_s_over_long_name_is_still_only_set_aside_keeping_the_old_name(
        self, db, tmp_path
    ):
        scheme = ConceptSchemeFactory(
            name="Kept Name", static_uri="http://pub.example/longschemename2"
        )
        long_name = "N" * 300
        path = tmp_path / "long_scheme_name_reimport.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/longschemename2> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme.refresh_from_db()
        assert scheme.name == "Kept Name"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/longschemename2"

    def test_a_collection_name_longer_than_the_field_sets_aside_the_whole_collection_on_first_import(
        self, db, tmp_path
    ):
        # A created collection has no earlier name either, but the rest of the file does
        # not need it, so the whole record is set aside instead of failing the run.
        long_name = "N" * 300
        path = tmp_path / "long_collection_name.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/longcollectionname> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/longcollectionname#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/longcollectionname#grp"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/longcollectionname#grp"

    def test_a_matched_collection_s_over_long_name_is_still_only_set_aside_keeping_the_old_name(
        self, db, tmp_path
    ):
        path = tmp_path / "long_collection_name_first.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/longcollectionname2> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            '<http://pub.example/longcollectionname2#grp> a skos:Collection ; skos:prefLabel "Group"@en .\n'
        )
        import_skos(path)
        collection = Collection.objects.get(
            static_uri="http://pub.example/longcollectionname2#grp"
        )
        assert collection.name == "Group"

        long_name = "N" * 300
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/longcollectionname2> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/longcollectionname2#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection.refresh_from_db()
        assert collection.name == "Group"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1


def _write_shared_label_file(tmp_path: Path, n: int) -> Path:
    """Write a vocabulary of ``n`` concepts that share one preferred label.

    Args:
        tmp_path: Directory to write the file into.
        n: Number of concepts to publish.

    Returns:
        The path of the written file.
    """
    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        '<http://example.org/sharedslug/> a skos:ConceptScheme ; skos:prefLabel "Shared Slug Vocabulary"@en .',
    ]
    for i in range(n):
        uri = f"http://example.org/sharedslug/c{i:04d}"
        lines.append(
            f'<{uri}> a skos:Concept ; skos:inScheme <http://example.org/sharedslug/> ; skos:prefLabel "Shared"@en .'
        )
    path = tmp_path / "shared_label.ttl"
    path.write_text("\n".join(lines))
    return path


class TestOverLongNameSetAsideReportsThePublishedLanguage:
    def test_a_matched_scheme_s_over_long_fallback_name_reports_its_own_language_not_the_default(
        self, db, tmp_path
    ):
        # A matched scheme keeps its frozen default language "en", but its only
        # prefLabel is "fr", so the set-aside must name "fr".
        scheme = ConceptSchemeFactory(
            name="Existing", static_uri="http://pub.example/scheme"
        )
        long_name = "N" * 300
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@fr .\n'
        )
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)

        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].params["language"] == "fr"
        scheme.refresh_from_db()
        assert scheme.name == "Existing"

    def test_a_matched_collection_s_over_long_fallback_name_reports_its_own_language_not_the_default(
        self, db, tmp_path
    ):
        scheme = ConceptSchemeFactory(
            name="Vocab", static_uri="http://pub.example/collscheme"
        )
        collection = CollectionFactory(
            scheme=scheme,
            name="Existing Group",
            static_uri="http://pub.example/collscheme#grp",
        )
        long_name = "N" * 300
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/collscheme#grp> a skos:Collection ; skos:prefLabel "{long_name}"@fr .\n'
        )
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)

        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].params["language"] == "fr"
        collection.refresh_from_db()
        assert collection.name == "Existing Group"


class TestAnyLanguageFallbackPrefersAStorableName:
    def test_a_created_scheme_with_one_over_long_and_one_storable_name_imports_using_the_storable_one(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f"<http://pub.example/scheme> a skos:ConceptScheme ; "
            f'skos:prefLabel "{long_name}"@de, "Zebra Vocabulary"@fr .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/scheme")
        assert scheme.name == "Zebra Vocabulary"
        assert Concept.objects.filter(
            static_uri="http://pub.example/scheme#c1"
        ).exists()

    def test_a_created_collection_with_one_over_long_and_one_storable_name_imports_using_the_storable_one(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@de, "Zebra Group"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/collscheme#grp"
        )
        assert collection.name == "Zebra Group"


class TestADroppedCollectionIsDistinguishableFromAMatchedOneThatKeptItsName:
    def test_a_created_collection_dropped_for_an_unusable_name_also_gets_its_own_record_level_reason(
        self, db, tmp_path
    ):
        long_name = "N" * 300
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/collscheme#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/collscheme#grp"
        ).exists()
        value_too_long = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(value_too_long) == 1
        not_created = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.COLLECTION_NOT_CREATED
        ]
        assert len(not_created) == 1
        assert not_created[0].subject == "http://pub.example/collscheme#grp"

    def test_a_matched_collection_kept_name_reports_only_value_too_long_not_not_created(
        self, db, tmp_path
    ):
        scheme = ConceptSchemeFactory(
            name="Vocab", static_uri="http://pub.example/collscheme2"
        )
        collection = CollectionFactory(
            scheme=scheme,
            name="Existing Group",
            static_uri="http://pub.example/collscheme2#grp",
        )
        long_name = "N" * 300
        path = tmp_path / "collection_matched.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme2> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/collscheme2#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection.refresh_from_db()
        assert collection.name == "Existing Group"
        not_created = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.COLLECTION_NOT_CREATED
        ]
        assert not_created == []


class TestOverLongDefaultLanguageNameFallsBackToAnotherStorableLanguage:
    def test_a_created_scheme_whose_default_language_name_is_over_long_falls_back_to_another_language(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@en, "Roches"@fr .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/scheme")
        assert scheme.name == "Roches"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].params["language"] == "en"

    def test_a_created_collection_whose_default_language_name_is_over_long_falls_back_to_another_language(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@en, "Roches"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/collscheme#grp"
        )
        assert collection.name == "Roches"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].params["language"] == "en"


class TestNoPublishedNameAtAllIsUnusableTheSameAsOverLong:
    def test_a_created_scheme_with_no_preflabel_at_all_is_fatal_not_persisted_blank(
        self, db, tmp_path
    ):
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; dcterms:description "no name"@en .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/scheme"
        ).exists()

    def test_a_created_collection_with_no_preflabel_at_all_is_set_aside_not_persisted_blank(
        self, db, tmp_path
    ):
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/collscheme#grp> a skos:Collection ; "
            "skos:member <http://pub.example/collscheme#c1> .\n"
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/collscheme#grp"
        ).exists()
        # No over-long value exists to name here, so the reason is
        # COLLECTION_NOT_CREATED rather than VALUE_TOO_LONG.
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.COLLECTION_NOT_CREATED
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/collscheme#grp"


class TestAnEmptyPublishedLiteralIsNeverTreatedAsAUsableName:
    def test_a_created_scheme_with_an_empty_and_a_usable_name_in_the_same_language_uses_the_usable_one(
        self, db, tmp_path
    ):
        # The empty and usable literals share the exact-match language, so the per-tag
        # exact match must skip the empty one; the any-language fallback never runs.
        path = tmp_path / "scheme_probe_a.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/schemea> a skos:ConceptScheme ; "
            'skos:prefLabel ""@en, "Geology Vocabulary"@en .\n'
            "<http://pub.example/schemea#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/schemea> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/schemea")
        assert scheme.name == "Geology Vocabulary"

    def test_a_created_scheme_with_only_an_empty_default_language_literal_falls_back_to_another_language(
        self, db, tmp_path
    ):
        # The default language carries only the empty literal, so the any-language
        # fallback must skip it and select the storable "de" value.
        path = tmp_path / "scheme_probe_b.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/schemeb> a skos:ConceptScheme ; "
            'skos:prefLabel ""@en, "Geologie"@de .\n'
            "<http://pub.example/schemeb#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/schemeb> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/schemeb")
        assert scheme.name == "Geologie"

    def test_a_created_collection_with_an_empty_and_a_usable_name_uses_the_usable_one(
        self, db, tmp_path
    ):
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/collscheme#grp> a skos:Collection ; "
            'skos:prefLabel ""@en, "Igneous Rocks"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/collscheme#grp"
        )
        assert collection.name == "Igneous Rocks"

    def test_a_created_scheme_s_second_chance_fallback_never_picks_the_empty_literal(
        self, db, tmp_path
    ):
        # The over-long name can only fall back past the empty "de" literal to the
        # storable "fr" one; the fallback must not treat the empty literal as found.
        long_name = "A" * 300
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f"<http://pub.example/scheme> a skos:ConceptScheme ; "
            f'skos:prefLabel "{long_name}"@en, ""@de, "Geologie Vokabular"@fr .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/scheme")
        assert scheme.name == "Geologie Vokabular"

    def test_a_created_collection_s_second_chance_fallback_never_picks_the_empty_literal(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@en, ""@de, "Geologie Vokabular"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/collscheme#grp"
        )
        assert collection.name == "Geologie Vokabular"

    def test_a_whitespace_only_literal_is_treated_the_same_as_an_empty_one(
        self, db, tmp_path
    ):
        # A whitespace-only literal sorts ahead of a real name like an empty string and
        # shows nothing once stored, so it is unusable too.
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/scheme> a skos:ConceptScheme ; "
            'skos:prefLabel "   "@en, "Geology Vocabulary"@en .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/scheme")
        assert scheme.name == "Geology Vocabulary"

    def test_a_node_publishing_only_an_empty_literal_is_treated_as_no_usable_name_at_all(
        self, db, tmp_path
    ):
        path = tmp_path / "scheme_none_usable.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/schemenone> a skos:ConceptScheme ; skos:prefLabel ""@en .\n'
            "<http://pub.example/schemenone#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/schemenone> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/schemenone"
        ).exists()

    def test_a_whitespace_only_vocabulary_name_is_refused_as_unpublished(
        self, db, tmp_path
    ):
        path = tmp_path / "scheme_whitespace_only.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/schemewsonly> a skos:ConceptScheme ; skos:prefLabel "   "@en .\n'
            "<http://pub.example/schemewsonly#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/schemewsonly> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/schemewsonly"
        ).exists()


class TestAnEmptyPublishedLiteralIsNeverAUsableNameForAnyRecordKind:
    @pytest.mark.parametrize("record_kind", ["scheme", "concept", "collection"])
    def test_an_empty_literal_never_beats_a_real_one_regardless_of_record_kind(
        self, db, tmp_path, record_kind
    ):
        path = tmp_path / f"{record_kind}.ttl"
        if record_kind == "scheme":
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                "<http://pub.example/scheme> a skos:ConceptScheme ; "
                'skos:prefLabel ""@en, "Real Name"@en .\n'
                "<http://pub.example/scheme#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
            )
        elif record_kind == "concept":
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                '<http://pub.example/concept> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
                "<http://pub.example/concept#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/concept> ; skos:prefLabel ""@en, "Real Name"@en .\n'
            )
        else:
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                '<http://pub.example/collection> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
                "<http://pub.example/collection#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/collection> ; skos:prefLabel "One"@en .\n'
                "<http://pub.example/collection#grp> a skos:Collection ; "
                'skos:prefLabel ""@en, "Real Name"@en .\n'
            )

        report = import_skos(path)
        assert report.fatal == []

        if record_kind == "scheme":
            stored_name = ConceptScheme.objects.get(
                static_uri="http://pub.example/scheme"
            ).name
        elif record_kind == "concept":
            stored_name = Concept.objects.get(
                static_uri="http://pub.example/concept#c1"
            ).label
        else:
            stored_name = Collection.objects.get(
                static_uri="http://pub.example/collection#grp"
            ).name

        assert stored_name == "Real Name"
        assert not any(
            entry.reason is SetAsideReason.SURPLUS_PREFERRED_LABEL
            for entry in report.set_aside
        )

    def test_a_whitespace_only_alternative_label_is_not_stored(self, db, tmp_path):
        # ConceptLabel.text rejects "" through blank=False, but Django's blank check
        # lets a whitespace-only string through, so import_labels must read alt and
        # hidden labels through the same is_usable_literal predicate.
        path = tmp_path / "altlabel_whitespace.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/altlabel> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/altlabel#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/altlabel> ; skos:prefLabel "One"@en ; '
            'skos:altLabel "   "@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        concept = Concept.objects.get(static_uri="http://pub.example/altlabel#c1")
        assert list(concept.labels.all()) == []

    def test_an_empty_only_non_default_language_preferred_label_is_silently_absent_not_a_crash(
        self, db, tmp_path
    ):
        # Excluding empty candidates leaves no "fr" winner for a concept whose only fr
        # preferred label is empty, so the import_labels loop must skip it rather than
        # raise KeyError.
        path = tmp_path / "empty_only_variant.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/variantonly> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/variantonly#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/variantonly> ; skos:prefLabel "One"@en, ""@fr .\n'
        )
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)
        assert report.fatal == []
        concept = Concept.objects.get(static_uri="http://pub.example/variantonly#c1")
        assert concept.label == "One"
        assert list(concept.labels.all()) == []


class TestAStoredSlugThatFailsValidationIsSetAsideNotEscaped:
    def test_a_scheme_s_out_of_band_slug_failing_validation_does_not_escape_import_skos(
        self, db, tmp_path
    ):
        scheme = ConceptSchemeFactory(
            name="Out of band slug scheme", static_uri="http://pub.example/scheme"
        )
        ConceptScheme.objects.filter(pk=scheme.pk).update(slug="has spaces/and-slash")
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "Out of band slug scheme"@en .\n'
        )

        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)

        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_RECORD_INVALID
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/scheme"
        scheme.refresh_from_db()
        assert scheme.slug == "has spaces/and-slash"

    def test_a_matched_scheme_s_unconfigured_stored_default_language_is_fatal_not_a_mislabeled_bad_slug(
        self, db, tmp_path
    ):
        # ConceptScheme.save() raises ValidationError for its configured-language check
        # as it does for a bad slug, so a language dropped from LANGUAGES must not be
        # reported as STORED_SLUG_INVALID: the stored slug is untouched here.
        scheme = ConceptSchemeFactory(
            name="Frozen language scheme",
            static_uri="http://pub.example/scheme",
            default_language="de",
        )
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "Frozen language scheme"@en .\n'
            "<http://pub.example/scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/scheme> ; skos:prefLabel "One"@en .\n'
        )

        with (
            override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]),
            pytest.raises(SkosImportFailed) as exc_info,
        ):
            import_skos(path)

        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_RECORD_INVALID
        slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert slug_entries == []
        assert not Concept.objects.filter(
            static_uri="http://pub.example/scheme#c1"
        ).exists()
        scheme.refresh_from_db()
        assert scheme.default_language == "de"

    def test_a_non_dict_validation_error_from_scheme_save_is_a_fatal_not_an_attributeerror(
        self, db, tmp_path, monkeypatch
    ):
        # ValidationError.message_dict raises AttributeError for an exception built from
        # a bare message, the ordinary form a consumer's pre_save receiver or
        # ConceptScheme subclass raises, so the handler must not assume a field dict.
        ConceptSchemeFactory(
            name="Plain refusal scheme",
            static_uri="http://pub.example/scheme",
        )
        path = tmp_path / "scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/scheme> a skos:ConceptScheme ; skos:prefLabel "Plain refusal scheme"@en .\n'
        )

        def failing_save(self, *args, **kwargs):
            raise ValidationError("a plain refusal, no field dict")

        monkeypatch.setattr(ConceptScheme, "save", failing_save)

        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)

        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_RECORD_INVALID
        slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert slug_entries == []

    def test_a_concept_s_out_of_band_slug_failing_validation_does_not_escape_import_skos(
        self, db, tmp_path
    ):
        path = tmp_path / "concept.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/concept> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/concept#one> a skos:Concept ; skos:inScheme <http://pub.example/concept> ; "
            'skos:prefLabel "One"@en .\n'
        )
        import_skos(path)
        concept = Concept.objects.get(static_uri="http://pub.example/concept#one")
        Concept.objects.filter(pk=concept.pk).update(slug="has spaces/and-slash")

        report = import_skos(path)

        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/concept#one"
        concept.refresh_from_db()
        assert concept.slug == "has spaces/and-slash"

    def test_a_collection_s_out_of_band_slug_failing_validation_does_not_escape_import_skos(
        self, db, tmp_path
    ):
        path = tmp_path / "collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/collection> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            '<http://pub.example/collection#grp> a skos:Collection ; skos:prefLabel "Group"@en .\n'
        )
        import_skos(path)
        collection = Collection.objects.get(
            static_uri="http://pub.example/collection#grp"
        )
        Collection.objects.filter(pk=collection.pk).update(slug="has spaces/and-slash")

        report = import_skos(path)

        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/collection#grp"
        collection.refresh_from_db()
        assert collection.slug == "has spaces/and-slash"


class TestSlugAssignmentQueryCountIsLinearInASharedLabelGroup:
    def test_query_cost_per_concept_stays_constant_as_the_shared_label_group_grows(
        self, db, tmp_path
    ):
        # A quadratic slug loop makes the marginal cost of a concept grow with the group, so
        # doubling the group must double the extra queries.
        def query_count(n: int) -> int:
            directory = tmp_path / str(n)
            directory.mkdir()
            path = _write_shared_label_file(directory, n)
            path.write_text(path.read_text().replace("sharedslug", f"sharedslug{n}"))
            with CaptureQueriesContext(connection) as ctx:
                report = import_skos(path)
            assert report.fatal == []
            assert (
                Concept.objects.filter(
                    scheme__static_uri=f"http://example.org/sharedslug{n}/"
                ).count()
                == n
            )
            return len(ctx.captured_queries)

        query_count(4)
        small, medium, large = query_count(20), query_count(40), query_count(80)
        assert large - medium == 2 * (medium - small)

    def test_the_same_file_imported_twice_produces_the_same_slugs(self, db, tmp_path):
        # Re-importing the same file must derive the identical slug for each concept,
        # not merely a unique one.
        path = _write_shared_label_file(tmp_path, 12)
        import_skos(path)
        first_pass = {
            concept.static_uri: concept.slug
            for concept in Concept.objects.filter(
                scheme__static_uri="http://example.org/sharedslug/"
            )
        }
        import_skos(path)
        second_pass = {
            concept.static_uri: concept.slug
            for concept in Concept.objects.filter(
                scheme__static_uri="http://example.org/sharedslug/"
            )
        }
        assert first_pass == second_pass
        assert len(set(first_pass.values())) == 12, (
            "each concept in the shared-label group must get a distinct slug"
        )


def _write_file_with_a_shared_broader_parent(tmp_path: Path, n: int) -> Path:
    """Write a vocabulary with one root concept, ``n`` children and ``n`` collections.

    Every child states ``skos:broader`` back to the root and belongs to its own one-member
    collection, so a re-import looks up ``n`` relations in one scheme and ``n`` collections.

    Args:
        tmp_path: Directory to write the file into.
        n: Number of children, and of collections.

    Returns:
        The path of the written file.
    """
    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        '<http://example.org/inclause/> a skos:ConceptScheme ; skos:prefLabel "In-clause"@en .',
        '<http://example.org/inclause/root> a skos:Concept ; skos:inScheme <http://example.org/inclause/> ; skos:prefLabel "Root"@en .',
    ]
    for i in range(n):
        uri = f"http://example.org/inclause/child{i:04d}"
        lines.append(
            f"<{uri}> a skos:Concept ; skos:inScheme <http://example.org/inclause/> ; "
            f'skos:prefLabel "Child {i}"@en ; skos:broader <http://example.org/inclause/root> .'
        )
        collection_uri = f"http://example.org/inclause/group{i:04d}"
        lines.append(
            f'<{collection_uri}> a skos:Collection ; skos:prefLabel "Group {i}"@en ; skos:member <{uri}> .'
        )
    path = tmp_path / "in_clause.ttl"
    path.write_text("\n".join(lines))
    return path


def _max_in_clause_size(sql: str) -> int:
    """Return the largest number of items in any flat ``IN (...)`` group in ``sql``.

    Django's debug cursor logs SQL with values substituted for placeholders, so this counts
    literal items rather than ``%s`` markers.

    Args:
        sql: A captured SQL statement.

    Returns:
        The size of the largest ``IN`` list, or 0 when the statement has none.
    """
    max_size = 0
    for match in re.finditer(r"\bIN \(([^()]*)\)", sql):
        items = [item for item in match.group(1).split(",") if item.strip()]
        max_size = max(max_size, len(items))
    return max_size


class TestQueryParameterCountDoesNotScaleWithConceptCount:
    def test_no_query_carries_an_in_clause_sized_by_the_concept_count(
        self, db, tmp_path
    ):
        # A query-shape assertion, not a scale reproduction: an IN clause that grows
        # with N at all is already the wrong shape at N=60 as at N=33,000.
        n = 60
        path = _write_file_with_a_shared_broader_parent(tmp_path, n)
        import_skos(path)

        with CaptureQueriesContext(connection) as ctx:
            report = import_skos(path)
        assert report.fatal == []

        worst = max(
            (_max_in_clause_size(entry["sql"]) for entry in ctx.captured_queries),
            default=0,
        )
        assert worst < 20, (
            f"a query carried an IN clause with {worst} items for only {n} concepts — "
            "its parameter count scales with the file's own concept count"
        )


class TestFatalFindingsAndAtomicity:
    def test_a_blank_node_concept_fails_the_run_and_writes_nothing(self, db):
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "blank_node_concept.ttl")
        assert exc_info.value.report.fatal[0].reason is FatalReason.MISSING_IDENTITY
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0

    def test_a_refused_uri_scheme_concept_fails_the_run_and_writes_nothing(self, db):
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "refused_uri_scheme.ttl")
        assert exc_info.value.report.fatal[0].reason is FatalReason.REFUSED_IDENTITY
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0

    def test_every_fatal_problem_in_one_file_is_collected_not_just_the_first(self, db):
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "multiple_fatal_problems.ttl")
        reasons = {finding.reason for finding in exc_info.value.report.fatal}
        assert reasons == {FatalReason.MISSING_IDENTITY, FatalReason.REFUSED_IDENTITY}
        assert len(exc_info.value.report.fatal) == 2

    def test_a_multi_problem_file_rolls_back_even_its_ordinary_concept(self, db):
        with pytest.raises(SkosImportFailed):
            import_skos(FIXTURES / "multiple_fatal_problems.ttl")
        # The scheme and the one perfectly valid concept alongside the two
        # fatal ones must not survive either — the run is all-or-nothing.
        assert ConceptScheme.objects.count() == 0
        assert not Concept.objects.filter(
            static_uri="http://example.org/mixed/ordinary"
        ).exists()

    def test_a_fatal_reimport_rolls_back_a_scheme_field_update_too(self, db):
        # The scheme row is written to (its name set to the file's own) before
        # the fatal concepts are even reached — proving the rollback undoes
        # that write, not just the concept creation, is the point here.
        existing = ConceptSchemeFactory(
            name="Original name", static_uri="http://example.org/mixed/"
        )
        concept_count_before = Concept.objects.count()

        with pytest.raises(SkosImportFailed):
            import_skos(FIXTURES / "multiple_fatal_problems.ttl")

        existing.refresh_from_db()
        assert existing.name == "Original name"
        assert Concept.objects.count() == concept_count_before


class TestVocabularyDefaultLanguageMustItselfBeConfigured:
    def test_an_unconfigured_default_language_fails_the_run_with_one_fatal_finding(
        self, db
    ):
        with (
            override_settings(LANGUAGE_CODE="pt"),
            pytest.raises(SkosImportFailed) as exc_info,
        ):
            import_skos(FIXTURES / "unconfigured_language_vocabulary.ttl")
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.DEFAULT_LANGUAGE_UNCONFIGURED
        assert report.fatal[0].params["language"] == "pt"
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0
        # One problem, not one NO_PREFERRED_LABEL per concept.
        assert report.set_aside == []

    def test_djangos_own_shipped_defaults_are_refused_cleanly_not_silently_emptied(
        self, db, tmp_path
    ):
        # An existing concept-bearing scheme with a frozen blank default_language falls
        # back to LANGUAGE_CODE, and 'en-us' is not in Django's own LANGUAGES default, a
        # configuration most projects hold by never overriding either setting.
        path = tmp_path / "soils.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            <https://example.org/v/soils> a skos:ConceptScheme ; skos:prefLabel "Soils"@en-us .
            <https://example.org/v/soils/clay> a skos:Concept ;
                skos:inScheme <https://example.org/v/soils> ;
                skos:prefLabel "Clay"@en-us .
            """
        )
        with override_settings(
            LANGUAGE_CODE="en-us", LANGUAGES=global_settings.LANGUAGES
        ):
            target = ConceptSchemeFactory(
                static_uri="https://example.org/v/soils", default_language=""
            )
            ConceptFactory(scheme=target)
            with pytest.raises(SkosImportFailed) as exc_info:
                import_skos(path, scheme=target)
        assert (
            exc_info.value.report.fatal[0].reason
            is FatalReason.DEFAULT_LANGUAGE_UNCONFIGURED
        )
        assert exc_info.value.report.fatal[0].params["language"] == "en-us"

    def test_the_sites_own_configured_default_never_trips_this(self, db):
        # 'en' is literally in tests/settings.py's LANGUAGES — must never be
        # mistaken for the unconfigured case.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.fatal == []


class TestVocabularySlugUnusableIsFatalNotAValidationError:
    def test_an_identifier_segment_that_slugifies_to_empty_fails_the_run_with_one_fatal_finding(
        self, db, tmp_path
    ):
        path = tmp_path / "unusable_scheme_slug.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://c.org/vocab/#±> a skos:ConceptScheme ; skos:prefLabel "Symbols"@en .
            """
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_SLUG_UNUSABLE
        assert report.fatal[0].subject == "http://c.org/vocab/#±"
        assert ConceptScheme.objects.count() == 0

    def test_the_name_is_never_used_as_a_fallback_for_the_unusable_slug(
        self, db, tmp_path
    ):
        # A local address never derives from a translated label, so falling back to the
        # name here would reinstate the defect.
        path = tmp_path / "unusable_scheme_slug_fallback.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://c.org/vocab2/#±> a skos:ConceptScheme ; skos:prefLabel "Symbols"@en .
            """
        )
        with pytest.raises(SkosImportFailed):
            import_skos(path)
        assert not ConceptScheme.objects.filter(name="Symbols").exists()


class TestReportPopulatedByARealRun:
    def test_a_first_import_reports_everything_as_created_nothing_as_updated(self, db):
        report = import_skos(FIXTURES / "rocks.ttl")
        expected = {
            "http://example.org/rocks/",
            "http://example.org/rocks/igneous",
            "http://example.org/rocks/granite",
            "http://example.org/rocks/basalt",
            "http://example.org/rocks/sedimentary",
            "http://example.org/rocks/quartz",
            # rocks.ttl's two collections are records with their own identity, so they
            # land in this bucket too.
            "http://example.org/rocks/collection/silica-bearing",
            "http://example.org/rocks/collection/example-sequence",
        }
        assert set(report.created) == expected
        assert report.updated == []
        assert report.set_aside == []
        assert report.fatal == []
        # No duplicates within the bucket either — each URI reported exactly once.
        assert len(report.created) == len(expected)

    def test_a_reimport_reports_everything_as_updated_nothing_as_created(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        report = import_skos(FIXTURES / "rocks.ttl")
        assert set(report.updated) == {
            "http://example.org/rocks/",
            "http://example.org/rocks/igneous",
            "http://example.org/rocks/granite",
            "http://example.org/rocks/basalt",
            "http://example.org/rocks/sedimentary",
            "http://example.org/rocks/quartz",
            "http://example.org/rocks/collection/silica-bearing",
            "http://example.org/rocks/collection/example-sequence",
        }
        assert report.created == []

    def test_set_aside_entries_carry_their_reason_subject_and_params_as_data(self, db):
        report = import_skos(FIXTURES / "no_default_language_label.ttl")
        assert len(report.set_aside) == 1
        entry = report.set_aside[0]
        assert entry.reason is SetAsideReason.NO_PREFERRED_LABEL
        assert entry.subject == "http://example.org/quarry/c"
        assert entry.params == {"language": "en"}
        # A caller groups/counts without parsing report.render() output.
        grouped = report.set_aside_by_reason()
        assert len(grouped[SetAsideReason.NO_PREFERRED_LABEL]) == 1

    def test_created_updated_and_set_aside_all_coexist_in_one_run(self, db):
        # Pre-seed one of mixed_scheme_membership.ttl's concepts so this run
        # exercises created, updated, and set-aside together.
        scheme = ConceptSchemeFactory(
            name="Minerals", static_uri="http://example.org/minerals/"
        )
        ConceptFactory(
            scheme=scheme,
            static_uri="http://example.org/minerals/quartz",
            label="Old quartz",
        )

        report = import_skos(FIXTURES / "mixed_scheme_membership.ttl")

        assert "http://example.org/minerals/quartz" in report.updated
        assert {
            "http://example.org/minerals/feldspar",
            "http://example.org/minerals/mica",
        } <= set(report.created)
        assert any(
            entry.reason is SetAsideReason.VOCABULARY_MISMATCH
            for entry in report.set_aside
        )
        assert report.fatal == []


class TestIdempotentReimport:
    def test_every_primary_key_is_stable_across_two_identical_runs(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        scheme_pk = ConceptScheme.objects.get(static_uri=ROCKS_URI).pk
        concept_pks = {
            c.static_uri: c.pk for c in Concept.objects.filter(scheme_id=scheme_pk)
        }
        assert len(concept_pks) == 5

        import_skos(FIXTURES / "rocks.ttl")

        scheme = ConceptScheme.objects.get(static_uri=ROCKS_URI)
        assert scheme.pk == scheme_pk
        assert ConceptScheme.objects.filter(static_uri=ROCKS_URI).count() == 1
        assert Concept.objects.filter(scheme=scheme).count() == len(concept_pks)
        for uri, pk in concept_pks.items():
            assert Concept.objects.get(static_uri=uri).pk == pk

    def test_a_reference_made_between_two_runs_still_resolves_after_the_second(
        self, db
    ):
        # The reference goes to a concept created locally in granite's scheme, not to
        # basalt: rocks.ttl states the granite-to-basalt hierarchy, so the importer owns
        # that edge and would overwrite it. "outsider" is never mentioned in the file.
        import_skos(FIXTURES / "rocks.ttl")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        outsider = ConceptFactory(scheme=granite.scheme, label="Local outsider")
        relation = ConceptRelationFactory(
            source=granite, target=outsider, kind=ConceptRelation.Kind.BROADER
        )

        import_skos(FIXTURES / "rocks.ttl")

        relation.refresh_from_db()
        assert relation.source_id == granite.pk
        assert relation.target_id == outsider.pk
        assert relation.source.static_uri == "http://example.org/rocks/granite"
        assert relation.target.static_uri == outsider.static_uri


class TestAuthoritativeUpdateForContainedRecords:
    def test_a_corrected_preferred_label_lands_and_keeps_the_concept_s_identity(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        granite_before = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        )
        pk_before = granite_before.pk

        report = import_skos(FIXTURES / "rocks_updated.ttl")

        granite_after = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        )
        assert granite_after.pk == pk_before
        assert granite_after.label == "Granite (revised)"
        assert "http://example.org/rocks/granite" in report.updated
        assert "http://example.org/rocks/granite" not in report.created


class TestRecordsAbsentFromSource:
    def test_a_concept_dropped_from_the_file_is_untouched_and_named_absent(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        quartz_pk, quartz_label = quartz.pk, quartz.label
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        reference = ConceptRelationFactory(
            source=basalt, target=quartz, kind=ConceptRelation.Kind.RELATED
        )

        report = import_skos(FIXTURES / "rocks_updated.ttl")

        quartz_after = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        assert quartz_after.pk == quartz_pk
        assert quartz_after.label == quartz_label
        assert "http://example.org/rocks/quartz" in report.absent_from_source
        assert "http://example.org/rocks/quartz" not in report.updated
        assert "http://example.org/rocks/quartz" not in report.created

        reference.refresh_from_db()
        assert reference.target_id == quartz_pk
        assert reference.target.static_uri == "http://example.org/rocks/quartz"

    def test_a_concept_still_mentioned_in_the_file_is_not_reported_absent(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        report = import_skos(FIXTURES / "rocks_updated.ttl")
        assert "http://example.org/rocks/granite" not in report.absent_from_source
        assert "http://example.org/rocks/basalt" not in report.absent_from_source


class TestVocabularyMetadataUpdate:
    def test_a_description_is_read_from_dcterms_description(self, db):
        import_skos(FIXTURES / "vocabulary_metadata.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/gems/")
        assert scheme.name == "Gemstones"
        assert scheme.description == "A vocabulary of gemstone types."

    def test_a_changed_name_and_description_land_on_reimport_with_identifier_unchanged(
        self, db
    ):
        import_skos(FIXTURES / "vocabulary_metadata.ttl")
        scheme_pk = ConceptScheme.objects.get(static_uri="http://example.org/gems/").pk

        import_skos(FIXTURES / "vocabulary_metadata_updated.ttl")

        scheme = ConceptScheme.objects.get(static_uri="http://example.org/gems/")
        assert scheme.pk == scheme_pk
        assert scheme.static_uri == "http://example.org/gems/"
        assert scheme.name == "Precious stones"
        assert (
            scheme.description
            == "An updated vocabulary of gemstones and precious stones."
        )

    def test_a_description_removed_from_the_file_is_cleared_not_left_stale(self, db):
        import_skos(FIXTURES / "vocabulary_metadata.ttl")

        import_skos(FIXTURES / "vocabulary_metadata_description_removed.ttl")

        scheme = ConceptScheme.objects.get(static_uri="http://example.org/gems/")
        assert scheme.description == ""


class TestFrozenDefaultLanguageConflictIsReported:
    def test_a_conflicting_declared_default_language_is_reported_not_silently_dropped(
        self, db
    ):
        scheme = ConceptSchemeFactory(
            name="Geology",
            static_uri="http://example.org/geology/",
            default_language="",
        )
        ConceptFactory(scheme=scheme, label="Existing concept")

        report = import_skos(FIXTURES / "french_vocabulary.ttl")

        scheme.refresh_from_db()
        assert scheme.default_language == ""
        conflicts = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.DEFAULT_LANGUAGE_FROZEN
        ]
        assert len(conflicts) == 1
        assert conflicts[0].subject == "http://example.org/geology/"
        assert conflicts[0].params == {"declared": "fr", "frozen": "en"}

    def test_an_agreeing_declared_default_language_produces_no_conflict(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        report = import_skos(FIXTURES / "rocks.ttl")
        assert not any(
            entry.reason is SetAsideReason.DEFAULT_LANGUAGE_FROZEN
            for entry in report.set_aside
        )


class TestAtomicityOnAPopulatedDatabase:
    def test_a_failed_reimport_leaves_a_populated_database_exactly_as_it_was(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        granite_before = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        )
        pk_before, label_before = granite_before.pk, granite_before.label
        concept_count_before = Concept.objects.count()
        scheme = ConceptScheme.objects.get(static_uri=ROCKS_URI)
        name_before = scheme.name

        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(FIXTURES / "reimport_rolls_back_an_update.ttl")
        assert exc_info.value.report.fatal[0].reason is FatalReason.MISSING_IDENTITY

        granite_after = Concept.objects.get(pk=pk_before)
        assert granite_after.label == label_before
        assert Concept.objects.count() == concept_count_before
        assert not Concept.objects.filter(label="Ghost concept").exists()
        scheme.refresh_from_db()
        assert scheme.name == name_before


class TestConceptLabels:
    def test_preferred_labels_in_other_configured_languages_are_stored(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        others = {
            (row.language, row.text)
            for row in igneous.labels.filter(kind=ConceptLabel.Kind.PREFERRED)
        }
        assert others == {("de", "Magmatisches Gestein"), ("fr", "Roche ignée")}

    def test_default_language_preferred_label_is_not_duplicated_as_a_concept_label(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        assert igneous.label == "Igneous rock"
        assert not igneous.labels.filter(
            language="en", kind=ConceptLabel.Kind.PREFERRED
        ).exists()

    def test_alternative_and_hidden_labels_are_stored_with_their_own_kind_and_language(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        assert granite.alt_labels("en") == ["Magma rock"]
        assert granite.hidden_labels("en") == ["Granit rock"]
        assert quartz.alt_labels("de") == ["Quartz"]

    def test_reimport_removes_an_alternative_label_the_publisher_dropped_leaving_the_concept_intact(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        granite_pk = Concept.objects.get(
            static_uri="http://example.org/rocks/granite"
        ).pk
        assert Concept.objects.get(pk=granite_pk).alt_labels("en") == ["Magma rock"]

        import_skos(FIXTURES / "rocks_updated.ttl")

        granite = Concept.objects.get(pk=granite_pk)
        assert granite.alt_labels("en") == []
        assert granite.hidden_labels("en") == ["Granit rock"]
        assert granite.pk == granite_pk


class TestSurplusPreferredLabelInAnotherConfiguredLanguage:
    def test_one_value_is_kept_deterministically_and_the_run_does_not_crash(self, db):
        report = import_skos(FIXTURES / "surplus_preferred_label.ttl")
        assert report.fatal == []
        gadget = Concept.objects.get(static_uri="http://example.org/surplus/gadget")
        assert gadget.preferred_label("de") == "Apparat"
        assert (
            ConceptLabel.objects.filter(
                concept=gadget, language="de", kind=ConceptLabel.Kind.PREFERRED
            ).count()
            == 1
        )

    def test_the_surplus_value_is_set_aside_and_reported(self, db):
        report = import_skos(FIXTURES / "surplus_preferred_label.ttl")
        gadget_uri = "http://example.org/surplus/gadget"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.SURPLUS_PREFERRED_LABEL
        ]
        assert len(entries) == 1
        assert entries[0].subject == gadget_uri
        assert entries[0].params["language"] == "de"


class TestSurplusPreferredLabelInTheDefaultLanguage:
    def test_one_value_is_kept_as_the_concepts_label(self, db):
        import_skos(FIXTURES / "surplus_preferred_label_default_language.ttl")
        widget = Concept.objects.get(static_uri="http://example.org/surplus2/widget")
        assert widget.label == "Doohickey"
        assert not widget.labels.filter(
            language="en", kind=ConceptLabel.Kind.PREFERRED
        ).exists()

    def test_the_surplus_default_language_value_is_set_aside_and_reported(self, db):
        report = import_skos(FIXTURES / "surplus_preferred_label_default_language.ttl")
        widget_uri = "http://example.org/surplus2/widget"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.SURPLUS_PREFERRED_LABEL
            and entry.subject == widget_uri
        ]
        assert len(entries) == 1
        assert entries[0].params["language"] == "en"


class TestPreferredLabelWinnerIsReKeyedOnTheResolvedLanguage:
    def _predominant_variant_contest(self, tmp_path):
        """Write a vocabulary where one German variant outnumbers another.

        Args:
            tmp_path: Directory to write the file into.

        Returns:
            The path of the written file.
        """
        # de-at is predominant (3 occurrences across the file) over de-ch (1); neither is an exact
        # "de" match, so the winner can only come from real predominance, not tag alphabetising.
        path = tmp_path / "predominant_de.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/predominant/> a skos:ConceptScheme ;
                skos:prefLabel "Predominant"@en .

            <http://example.org/predominant/filler1> a skos:Concept ;
                skos:inScheme <http://example.org/predominant/> ;
                skos:prefLabel "Filler one"@en, "Eins"@de-at .

            <http://example.org/predominant/filler2> a skos:Concept ;
                skos:inScheme <http://example.org/predominant/> ;
                skos:prefLabel "Filler two"@en, "Zwei"@de-at .

            <http://example.org/predominant/target> a skos:Concept ;
                skos:inScheme <http://example.org/predominant/> ;
                skos:prefLabel "Target"@en, "Ziel-AT"@de-at, "Ziel-CH"@de-ch .
            """
        )
        return path

    def test_two_different_tags_resolving_to_one_non_default_language_no_longer_crash_the_run(
        self, db, tmp_path
    ):
        path = self._predominant_variant_contest(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        assert report.fatal == []

    def test_the_predominant_variant_is_stored_not_the_alphabetically_first_tag_or_value(
        self, db, tmp_path
    ):
        path = self._predominant_variant_contest(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            import_skos(path)
        target = Concept.objects.get(static_uri="http://example.org/predominant/target")
        assert target.preferred_label("de") == "Ziel-AT"
        assert (
            ConceptLabel.objects.filter(
                concept=target, language="de", kind=ConceptLabel.Kind.PREFERRED
            ).count()
            == 1
        )

    def test_importing_the_same_file_twice_stores_the_same_value_both_times(
        self, db, tmp_path
    ):
        path = self._predominant_variant_contest(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            import_skos(path)
            import_skos(path)
        target = Concept.objects.get(static_uri="http://example.org/predominant/target")
        assert target.preferred_label("de") == "Ziel-AT"

    def test_an_exact_match_in_a_non_default_language_wins_over_a_more_predominant_variant(
        self, db, tmp_path
    ):
        path = tmp_path / "exact_over_predominant_de.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/exactnondefault/> a skos:ConceptScheme ;
                skos:prefLabel "Exact non-default"@en .

            <http://example.org/exactnondefault/filler1> a skos:Concept ;
                skos:inScheme <http://example.org/exactnondefault/> ;
                skos:prefLabel "Filler one"@en, "Eins"@de-at .

            <http://example.org/exactnondefault/filler2> a skos:Concept ;
                skos:inScheme <http://example.org/exactnondefault/> ;
                skos:prefLabel "Filler two"@en, "Zwei"@de-at .

            <http://example.org/exactnondefault/target> a skos:Concept ;
                skos:inScheme <http://example.org/exactnondefault/> ;
                skos:prefLabel "Target"@en, "Ziel-AT"@de-at, "Ziel"@de .
            """
        )
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        assert report.fatal == []
        target = Concept.objects.get(
            static_uri="http://example.org/exactnondefault/target"
        )
        assert target.preferred_label("de") == "Ziel"

    def test_the_winner_reported_by_import_labels_agrees_with_concept_label_for_the_default_language(
        self, db, tmp_path
    ):
        # A predominance-driven winner that differs from both an alphabetical-value pick
        # and an alphabetical-tag pick. If import_labels's winner disagreed with
        # Concept.label, the "loser" it names would be the very value stored.
        path = tmp_path / "predominant_default.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/predominantdefault/> a skos:ConceptScheme ;
                skos:prefLabel "Predominant default"@en-us .

            <http://example.org/predominantdefault/filler1> a skos:Concept ;
                skos:inScheme <http://example.org/predominantdefault/> ;
                skos:prefLabel "Filler one"@en-us .

            <http://example.org/predominantdefault/filler2> a skos:Concept ;
                skos:inScheme <http://example.org/predominantdefault/> ;
                skos:prefLabel "Filler two"@en-us .

            <http://example.org/predominantdefault/target> a skos:Concept ;
                skos:inScheme <http://example.org/predominantdefault/> ;
                skos:prefLabel "Alpha"@en-gb, "Zed"@en-us .
            """
        )
        with override_settings(LANGUAGES=[("en", "English")]):
            report = import_skos(path)
        target = Concept.objects.get(
            static_uri="http://example.org/predominantdefault/target"
        )
        assert target.label == "Zed"
        losers = [
            entry
            for entry in report.set_aside
            if entry.subject == target.static_uri
            and entry.reason
            in (SetAsideReason.SURPLUS_PREFERRED_LABEL, SetAsideReason.VARIANT_NOT_KEPT)
        ]
        assert len(losers) == 1
        assert losers[0].params["language"] != "en-us"


class TestExactMatchPreferredLabelFailingOnItsOwnMeritsIsNotBackfilledByAVariant:
    def test_the_concept_is_set_aside_under_value_too_long_and_the_variants_value_is_not_promoted(
        self, db, tmp_path
    ):
        path = tmp_path / "exact_fails_variant_available.ttl"
        path.write_text(
            f"""
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/emptyexact/> a skos:ConceptScheme ;
                skos:prefLabel "Empty exact"@en .

            <http://example.org/emptyexact/target> a skos:Concept ;
                skos:inScheme <http://example.org/emptyexact/> ;
                skos:prefLabel "{"x" * 300}"@en, "Usable"@en-gb .
            """
        )
        report = import_skos(path)
        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
            and entry.subject == "http://example.org/emptyexact/target"
        ]
        assert len(entries) == 1
        assert not Concept.objects.filter(
            static_uri="http://example.org/emptyexact/target"
        ).exists()


class TestVariantContestLosersAreDiscriminatedInEveryConfiguredLanguage:
    def _three_preferred_labels_two_under_one_tag_one_under_a_variant(self, tmp_path):
        """Write a vocabulary whose target concept has two de-at labels and one de-ch label.

        Args:
            tmp_path: Directory to write the file into.

        Returns:
            The path of the written file.
        """
        # de-at wins on predominance (4 occurrences: 2 fillers + 2 on target) over de-ch (1); the
        # two de-at values on target are a same-language duplicate, the de-ch value a contest loser.
        path = tmp_path / "mixed_losers_de.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/mixedlosers/> a skos:ConceptScheme ;
                skos:prefLabel "Mixed losers"@en .

            <http://example.org/mixedlosers/filler1> a skos:Concept ;
                skos:inScheme <http://example.org/mixedlosers/> ;
                skos:prefLabel "Filler one"@en, "Eins"@de-at .

            <http://example.org/mixedlosers/filler2> a skos:Concept ;
                skos:inScheme <http://example.org/mixedlosers/> ;
                skos:prefLabel "Filler two"@en, "Zwei"@de-at .

            <http://example.org/mixedlosers/target> a skos:Concept ;
                skos:inScheme <http://example.org/mixedlosers/> ;
                skos:prefLabel "Target"@en, "Ziel-AT-1"@de-at, "Ziel-AT-2"@de-at, "Ziel-CH"@de-ch .
            """
        )
        return path

    def test_the_run_succeeds_and_stores_exactly_one_de_label(self, db, tmp_path):
        path = self._three_preferred_labels_two_under_one_tag_one_under_a_variant(
            tmp_path
        )
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        assert report.fatal == []
        target = Concept.objects.get(static_uri="http://example.org/mixedlosers/target")
        assert target.preferred_label("de") == "Ziel-AT-1"
        assert (
            ConceptLabel.objects.filter(
                concept=target, language="de", kind=ConceptLabel.Kind.PREFERRED
            ).count()
            == 1
        )

    def test_one_entry_of_each_reason_and_only_the_variant_reaches_the_language_account(
        self, db, tmp_path
    ):
        path = self._three_preferred_labels_two_under_one_tag_one_under_a_variant(
            tmp_path
        )
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        target_uri = "http://example.org/mixedlosers/target"
        surplus = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.SURPLUS_PREFERRED_LABEL
            and entry.subject == target_uri
        ]
        variant = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VARIANT_NOT_KEPT
            and entry.subject == target_uri
        ]
        assert len(surplus) == 1
        assert surplus[0].params["language"] == "de"
        assert len(variant) == 1
        assert variant[0].params["language"] == "de-ch"
        assert variant[0].params["kept_as"] == "de"
        assert report.language_account().get("de-ch") == 1
        assert "de" not in report.language_account()


class TestAnEmptyLiteralDoesNotVoteOnPredominance:
    def test_two_unusable_literals_in_one_variant_cannot_flip_predominance_for_another_concept(
        self, db, tmp_path
    ):
        # Without unusable1 and unusable2, de-de appears twice and de-at once, so de-de
        # wins. Counting their empty and whitespace de-at literals would push de-at to
        # three and flip c1's value to "Alpha AT".
        path = tmp_path / "predominance.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/tally/> a skos:ConceptScheme ;
                skos:prefLabel "Tally"@en .

            <http://example.org/tally/filler> a skos:Concept ;
                skos:inScheme <http://example.org/tally/> ;
                skos:prefLabel "Filler"@en, "Filler DE"@de-de .

            <http://example.org/tally/c1> a skos:Concept ;
                skos:inScheme <http://example.org/tally/> ;
                skos:prefLabel "One"@en, "Alpha DE"@de-de, "Alpha AT"@de-at .

            <http://example.org/tally/unusable1> a skos:Concept ;
                skos:inScheme <http://example.org/tally/> ;
                skos:prefLabel "Two"@en, ""@de-at .

            <http://example.org/tally/unusable2> a skos:Concept ;
                skos:inScheme <http://example.org/tally/> ;
                skos:prefLabel "Three"@en, "   "@de-at .
            """
        )
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        assert report.fatal == []
        c1 = Concept.objects.get(static_uri="http://example.org/tally/c1")
        assert c1.preferred_label("de") == "Alpha DE"


class TestConceptNotes:
    def test_definition_and_each_note_kind_are_stored_against_the_right_concept(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        sedimentary = Concept.objects.get(
            static_uri="http://example.org/rocks/sedimentary"
        )
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")

        assert (
            igneous.definition("en")
            == "Rock formed by the cooling and solidification of magma or lava."
        )
        assert granite.notes("en", ConceptNote.Kind.SCOPE) == [
            "Used here for coarse-grained intrusive igneous rock."
        ]
        assert basalt.notes("en", ConceptNote.Kind.EXAMPLE) == [
            "Columnar basalt at the Giant's Causeway."
        ]
        assert sedimentary.notes("en", ConceptNote.Kind.EDITORIAL) == [
            "Confirm classification against the regional survey before publishing."
        ]
        assert quartz.notes("en", ConceptNote.Kind.HISTORY) == [
            "Reclassified from 'Silica minerals' in the 2020 revision."
        ]
        assert quartz.notes("en", ConceptNote.Kind.CHANGE) == [
            "Definition tightened in 2022."
        ]
        assert quartz.notes("en", ConceptNote.Kind.NOTE) == [
            "See also feldspar for a related silicate."
        ]

    def test_reimport_removes_a_note_the_publisher_dropped_leaving_the_concept_intact(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        basalt_pk = Concept.objects.get(static_uri="http://example.org/rocks/basalt").pk
        assert Concept.objects.get(pk=basalt_pk).notes(
            "en", ConceptNote.Kind.EXAMPLE
        ) == ["Columnar basalt at the Giant's Causeway."]

        import_skos(FIXTURES / "rocks_updated.ttl")

        basalt = Concept.objects.get(pk=basalt_pk)
        assert basalt.notes("en", ConceptNote.Kind.EXAMPLE) == []
        assert basalt.label == "Basalt"
        assert basalt.pk == basalt_pk


class TestAlternativeLabelsHiddenLabelsAndNotesHaveNoPerLanguageContest:
    def test_alternative_labels_in_two_variants_of_one_configured_language_are_both_kept(
        self, db
    ):
        report = import_skos(FIXTURES / "variants.ttl")
        assert report.fatal == []
        colour = Concept.objects.get(static_uri="http://example.org/colours/colour")
        assert set(colour.alt_labels("en")) == {"Colour", "Color"}

    def test_neither_alternative_label_is_set_aside_as_a_duplicate_or_a_contest_loser(
        self, db
    ):
        # The preferred label has its own contest (en-gb vs en-us for the default "en"
        # slot) and contributes exactly one loser; running the alternative label through
        # it would add a second.
        report = import_skos(FIXTURES / "variants.ttl")
        colour_uri = "http://example.org/colours/colour"
        losses = [
            entry
            for entry in report.set_aside
            if entry.subject == colour_uri
            and entry.reason
            in (SetAsideReason.SURPLUS_PREFERRED_LABEL, SetAsideReason.VARIANT_NOT_KEPT)
        ]
        assert len(losses) == 1

    def test_notes_in_two_variants_of_one_configured_language_are_both_kept(self, db):
        import_skos(FIXTURES / "variants.ttl")
        colour = Concept.objects.get(static_uri="http://example.org/colours/colour")
        assert colour.notes("en") == [
            "Spelling follows regional convention.",
            "Spelling follows regional convention.",
        ]


class TestReimportAfterAddingALanguageStoresItsValues:
    def test_the_added_language_s_preferred_labels_are_stored_for_existing_concepts(
        self, db
    ):
        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        assert igneous.preferred_label("fr") is None

        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            import_skos(FIXTURES / "rocks.ttl")

        igneous.refresh_from_db()
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        sedimentary = Concept.objects.get(
            static_uri="http://example.org/rocks/sedimentary"
        )
        assert igneous.preferred_label("fr") == "Roche ignée"
        assert granite.preferred_label("fr") == "Granite"
        assert sedimentary.preferred_label("fr") == "Roche sédimentaire"

    def test_the_second_run_s_report_no_longer_counts_the_newly_stored_language_as_left_behind(
        self, db
    ):
        with override_settings(LANGUAGES=[("en", "English")]):
            first_report = import_skos(FIXTURES / "rocks.ttl")
        assert first_report.language_account().get("fr") == 3

        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            second_report = import_skos(FIXTURES / "rocks.ttl")
        assert "fr" not in second_report.language_account()


class TestReimportAfterAddingALanguageKeepsEveryOtherRecordUnchanged:
    @staticmethod
    def _identity(obj) -> tuple[int, str, str | None, str, str]:
        """Return the fields that make up a record's identity and address.

        Args:
            obj: A concept, vocabulary or collection.

        Returns:
            Its primary key, URI, static URI, slug and local URL.
        """
        return (obj.pk, obj.uri, obj.static_uri, obj.slug, obj.local_url)

    def test_every_concept_scheme_and_collection_keeps_its_identity_across_the_reimport(
        self, db
    ):
        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(FIXTURES / "rocks.ttl")

        scheme_before = self._identity(ConceptScheme.objects.get(static_uri=ROCKS_URI))
        concept_uris = [
            "http://example.org/rocks/igneous",
            "http://example.org/rocks/granite",
            "http://example.org/rocks/basalt",
            "http://example.org/rocks/sedimentary",
            "http://example.org/rocks/quartz",
        ]
        collection_uris = [
            "http://example.org/rocks/collection/silica-bearing",
            "http://example.org/rocks/collection/example-sequence",
        ]
        concepts_before = {
            uri: self._identity(Concept.objects.get(static_uri=uri))
            for uri in concept_uris
        }
        collections_before = {
            uri: self._identity(Collection.objects.get(static_uri=uri))
            for uri in collection_uris
        }

        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            import_skos(FIXTURES / "rocks.ttl")

        assert (
            self._identity(ConceptScheme.objects.get(static_uri=ROCKS_URI))
            == scheme_before
        )
        for uri in concept_uris:
            assert (
                self._identity(Concept.objects.get(static_uri=uri))
                == concepts_before[uri]
            )
        for uri in collection_uris:
            assert (
                self._identity(Collection.objects.get(static_uri=uri))
                == collections_before[uri]
            )

    def test_content_already_held_in_english_is_unchanged_by_the_reimport(self, db):
        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(FIXTURES / "rocks.ttl")

        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            import_skos(FIXTURES / "rocks.ttl")

        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        assert igneous.label == "Igneous rock"
        assert (
            igneous.definition("en")
            == "Rock formed by the cooling and solidification of magma or lava."
        )
        assert granite.label == "Granite"
        assert granite.alt_labels("en") == ["Magma rock"]
        assert granite.hidden_labels("en") == ["Granit rock"]
        assert granite.notes("en", ConceptNote.Kind.SCOPE) == [
            "Used here for coarse-grained intrusive igneous rock."
        ]


class TestUnconfiguredLanguageValuesAreSetAside:
    def test_labels_and_notes_in_an_unconfigured_language_are_set_aside_and_named(
        self, db
    ):
        report = import_skos(FIXTURES / "unconfigured_language_values.ttl")
        schist = Concept.objects.get(static_uri="http://example.org/quarry3/schist")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
            and entry.subject == schist.static_uri
        ]
        # Two alternative labels and one scope note, each named individually
        # rather than merged into a single "some values were dropped" entry.
        assert len(entries) == 3
        assert all(entry.params["language"] == "es" for entry in entries)

    def test_the_concept_still_imports_on_its_configured_language_content(self, db):
        import_skos(FIXTURES / "unconfigured_language_values.ttl")
        schist = Concept.objects.get(static_uri="http://example.org/quarry3/schist")
        assert schist.label == "Schist"
        assert schist.alt_labels("es") == []
        assert schist.notes("es") == []


class TestUntaggedOrNonLiteralValuesAreSetAside:
    def test_an_untagged_alternative_label_is_set_aside_and_named(self, db):
        report = import_skos(FIXTURES / "untagged_literal_values.ttl")
        alpha_uri = "http://example.org/untagged/alpha"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_LANGUAGE_TAG
            and entry.subject == alpha_uri
        ]
        assert len(entries) == 2, (
            "expected one entry for the untagged altLabel and one for the untagged definition"
        )
        assert {entry.params.get("predicate") for entry in entries} == {
            "skos:altLabel",
            "skos:definition",
        }

    def test_the_untagged_alternative_label_is_not_stored_under_any_language(self, db):
        import_skos(FIXTURES / "untagged_literal_values.ttl")
        alpha = Concept.objects.get(static_uri="http://example.org/untagged/alpha")
        assert list(alpha.labels.all()) == []
        assert alpha.notes("en") == []

    def test_a_non_literal_definition_object_is_set_aside_the_same_way(self, db):
        # skos:definition <some-uri> — not language-tagged text at all, the
        # same branch an untagged Literal falls through, and the same
        # unusable-value treatment applies.
        report = import_skos(FIXTURES / "untagged_literal_values.ttl")
        beta_uri = "http://example.org/untagged/beta"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_LANGUAGE_TAG
            and entry.subject == beta_uri
        ]
        assert len(entries) == 1
        assert entries[0].params["predicate"] == "skos:definition"
        beta = Concept.objects.get(static_uri=beta_uri)
        assert beta.notes("en") == []

    def test_an_untagged_foreign_description_is_also_set_aside(self, db):
        # The dcterms:description alias _import_notes reads separately from
        # the native NOTE_PREDICATES loop has the identical defect — an
        # untagged value there was dropped with no report entry either.
        report = import_skos(FIXTURES / "untagged_literal_values.ttl")
        gamma_uri = "http://example.org/untagged/gamma"
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_LANGUAGE_TAG
            and entry.subject == gamma_uri
        ]
        assert len(entries) == 1
        assert entries[0].params["predicate"] == "dcterms:description"
        gamma = Concept.objects.get(static_uri=gamma_uri)
        assert gamma.notes("en") == []
        assert report.normalized == [] or all(
            entry.subject != gamma_uri for entry in report.normalized
        )

    def test_the_concepts_still_import_successfully_on_their_usable_content(self, db):
        report = import_skos(FIXTURES / "untagged_literal_values.ttl")
        assert report.fatal == []
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/untagged/"
            ).count()
            == 3
        )
        alpha = Concept.objects.get(static_uri="http://example.org/untagged/alpha")
        assert alpha.label == "Alpha"


class TestUnheldValuesAndNormalisation:
    def test_the_concepts_still_import_successfully(self, db):
        report = import_skos(FIXTURES / "unmodelled_and_normalised_values.ttl")
        assert report.fatal == []
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/hardware/"
            ).count()
            == 2
        )

    def test_a_notation_is_set_aside(self, db):
        report = import_skos(FIXTURES / "unmodelled_and_normalised_values.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NOTATION
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/hardware/widget"

    def test_a_mapping_predicate_is_set_aside_naming_the_predicate(self, db):
        report = import_skos(FIXTURES / "unmodelled_and_normalised_values.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.MAPPING
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/hardware/widget"
        assert entries[0].params["predicate"] == "skos:exactMatch"

    def test_a_predicate_from_outside_skos_is_set_aside_naming_the_predicate(self, db):
        report = import_skos(FIXTURES / "unmodelled_and_normalised_values.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNMODELLED_PREDICATE
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/hardware/widget"
        assert entries[0].params["predicate"] == "http://example.org/ns#customAttribute"

    def test_a_foreign_description_is_read_as_the_definition_and_reported_as_normalised(
        self, db
    ):
        report = import_skos(FIXTURES / "unmodelled_and_normalised_values.ttl")
        gadget = Concept.objects.get(static_uri="http://example.org/hardware/gadget")
        assert gadget.definition("en") == "A small mechanical device."
        assert len(report.normalized) == 1
        entry = report.normalized[0]
        assert entry.reason is NormalizedReason.FOREIGN_DEFINITION
        assert entry.subject == "http://example.org/hardware/gadget"
        assert entry.params["predicate"] == "dcterms:description"
        assert entry.params["language"] == "en"

    def test_a_concept_with_its_own_definition_is_not_normalised(self, db):
        # rocks.ttl's igneous carries a native skos:definition; nothing about
        # a run that never needs the dcterms alias should land in
        # report.normalized.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.normalized == []

    def test_broader_related_and_collection_membership_are_not_reported_as_unmodelled(
        self, db
    ):
        # The models have a place for skos:broader, related, member and memberList, so
        # they must never be reported as UNMODELLED_PREDICATE.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert not any(
            entry.reason is SetAsideReason.UNMODELLED_PREDICATE
            for entry in report.set_aside
        )


class TestUnmodelledPredicatesAreReportedForSchemeAndCollectionNodesToo:
    def test_an_unmodelled_predicate_on_the_scheme_node_is_reported(self, db):
        report = import_skos(
            FIXTURES / "unmodelled_predicate_on_scheme_and_collection.ttl"
        )
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNMODELLED_PREDICATE
        ]
        matches = [
            entry
            for entry in entries
            if entry.subject == "http://example.org/scheme-collection-unmodelled/"
        ]
        assert len(matches) == 1
        assert matches[0].params["predicate"] == "http://example.org/custom#owner"

    def test_an_unmodelled_predicate_on_a_collection_node_is_reported(self, db):
        report = import_skos(
            FIXTURES / "unmodelled_predicate_on_scheme_and_collection.ttl"
        )
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNMODELLED_PREDICATE
        ]
        matches = [
            entry
            for entry in entries
            if entry.subject
            == "http://example.org/scheme-collection-unmodelled/collection/group"
        ]
        assert len(matches) == 1
        assert matches[0].params["predicate"] == "http://example.org/custom#curatedBy"

    def test_the_scheme_and_collection_still_import_successfully(self, db):
        report = import_skos(
            FIXTURES / "unmodelled_predicate_on_scheme_and_collection.ttl"
        )
        assert report.fatal == []
        assert ConceptScheme.objects.filter(
            static_uri="http://example.org/scheme-collection-unmodelled/"
        ).exists()
        assert Collection.objects.filter(
            static_uri="http://example.org/scheme-collection-unmodelled/collection/group"
        ).exists()


class TestNoPreferredLabelConceptIsSetAsideAndTheRestImports:
    def test_the_concept_with_no_default_language_label_is_set_aside_and_named(
        self, db
    ):
        report = import_skos(FIXTURES / "no_default_language_label.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_PREFERRED_LABEL
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/quarry/c"
        assert entries[0].params["language"] == "en"
        assert not Concept.objects.filter(
            static_uri="http://example.org/quarry/c"
        ).exists()

    def test_the_rest_of_the_vocabulary_imports_with_its_own_content_intact(self, db):
        import_skos(FIXTURES / "no_default_language_label.ttl")
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/quarry/"
            ).count()
            == 2
        )
        b = Concept.objects.get(static_uri="http://example.org/quarry/b")
        assert b.label == "B"
        assert b.alt_labels("en") == ["B-alt"]


class TestNoPreferredLabelConceptStillAccountsItsOwnLanguages:
    def test_the_skipped_concepts_own_published_language_is_visible_in_the_account(
        self, db
    ):
        with override_settings(LANGUAGES=[("en", "English")]):
            report = import_skos(FIXTURES / "no_default_language_label.ttl")
        assert "fr" in report.language_account()
        assert not Concept.objects.filter(
            static_uri="http://example.org/quarry/c"
        ).exists()

    def test_the_configured_default_language_itself_never_appears_in_the_account(
        self, db
    ):
        # NO_PREFERRED_LABEL's params["language"] is the configured default the concept
        # lacks, never a published tag, so it must not be folded into the account as
        # though it were one.
        with override_settings(LANGUAGES=[("en", "English")]):
            report = import_skos(FIXTURES / "no_default_language_label.ttl")
        assert "en" not in report.language_account()

    def test_the_no_preferred_label_entry_itself_is_still_reported_unchanged(self, db):
        with override_settings(LANGUAGES=[("en", "English")]):
            report = import_skos(FIXTURES / "no_default_language_label.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.NO_PREFERRED_LABEL
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/quarry/c"
        assert entries[0].params["language"] == "en"


class TestEmptySlugLabelIsSetAsideNotCrashed:
    def test_an_identifier_segment_that_slugifies_to_empty_is_set_aside_and_named(
        self, db
    ):
        report = import_skos(FIXTURES / "empty_slug_label.ttl")
        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/emptyslug/symbol#±"
        assert not Concept.objects.filter(
            static_uri="http://example.org/emptyslug/symbol#±"
        ).exists()

    def test_the_rest_of_the_vocabulary_imports_with_its_own_content_intact(self, db):
        import_skos(FIXTURES / "empty_slug_label.ttl")
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/emptyslug/"
            ).count()
            == 1
        )
        normal = Concept.objects.get(static_uri="http://example.org/emptyslug/normal")
        assert normal.label == "Normal"
        assert normal.alt_labels("en") == ["Normal-alt"]

    def test_a_collision_the_importer_gives_up_on_is_reported_without_blaming_the_identifier(
        self, db, tmp_path, monkeypatch
    ):
        # The identifier segment and label are both usable; the slug is empty only
        # because the collision loop gave up.
        monkeypatch.setattr(
            ConceptImporter,
            "assign_unique_slug",
            staticmethod(lambda *args, **kwargs: None),
        )
        source = tmp_path / "give_up.ttl"
        source.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://giveup.example/scheme>\n"
            "    a skos:ConceptScheme ;\n"
            '    skos:prefLabel "Give up"@en .\n'
            "<http://giveup.example/scheme/c1>\n"
            "    a skos:Concept ;\n"
            "    skos:inScheme <http://giveup.example/scheme> ;\n"
            '    skos:prefLabel "Perfectly Fine Label"@en .\n',
            encoding="utf-8",
        )
        report = import_skos(source)
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert [entry.subject for entry in entries] == [
            "http://giveup.example/scheme/c1"
        ]


class TestOverlongValueIsSetAsideNotCrashed:
    def test_an_overlong_alt_label_is_set_aside_and_named_not_raised(self, db):
        report = import_skos(FIXTURES / "value_too_long_label.ttl")
        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.VALUE_TOO_LONG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/longvalue/toolong"
        assert entries[0].params["language"] == "en-GB"

    def test_the_concept_carrying_the_overlong_value_still_imports_on_its_other_content(
        self, db
    ):
        import_skos(FIXTURES / "value_too_long_label.ttl")
        toolong = Concept.objects.get(static_uri="http://example.org/longvalue/toolong")
        assert toolong.label == "TooLong"
        assert toolong.alt_labels("en") == []

    def test_the_rest_of_the_file_still_imports(self, db):
        import_skos(FIXTURES / "value_too_long_label.ttl")
        ok = Concept.objects.get(static_uri="http://example.org/longvalue/ok")
        assert ok.label == "OK"
        assert ok.alt_labels("en") == ["OK-alt"]


class TestBroaderAndNarrowerRelations:
    def test_a_narrower_triple_lands_with_the_ends_the_right_way_round(self, db):
        # rocks.ttl's igneous states "skos:narrower basalt" — igneous is the
        # broader end, basalt the narrower one, so the canonical row must read
        # source=basalt, target=igneous, even though the file names igneous first.
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        assert list(basalt.broader()) == [igneous]
        assert basalt in igneous.narrower()
        assert ConceptRelation.objects.get(
            source=basalt, target=igneous, kind=ConceptRelation.Kind.BROADER
        )

    def test_a_broader_triple_lands_with_the_ends_the_right_way_round(self, db):
        # rocks.ttl's granite states "skos:broader igneous" directly — granite
        # is already the narrower end, so no swap is needed.
        import_skos(FIXTURES / "rocks.ttl")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        assert list(granite.broader()) == [igneous]
        assert ConceptRelation.objects.get(
            source=granite, target=igneous, kind=ConceptRelation.Kind.BROADER
        )

    def test_both_directions_of_one_pair_produce_exactly_one_row(self, db):
        # relation_both_directions.ttl states the parent/child pair from both
        # ends: parent's own "narrower child" and child's own "broader parent".
        import_skos(FIXTURES / "relation_both_directions.ttl")
        parent = Concept.objects.get(static_uri="http://example.org/hierarchy/parent")
        child = Concept.objects.get(static_uri="http://example.org/hierarchy/child")
        assert (
            ConceptRelation.objects.filter(
                source=child, target=parent, kind=ConceptRelation.Kind.BROADER
            ).count()
            == 1
        )
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.BROADER).count()
            == 1
        )

    def test_reimporting_the_identical_file_does_not_duplicate_the_relation(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        import_skos(FIXTURES / "rocks.ttl")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        igneous = Concept.objects.get(static_uri="http://example.org/rocks/igneous")
        assert (
            ConceptRelation.objects.filter(
                source=granite, target=igneous, kind=ConceptRelation.Kind.BROADER
            ).count()
            == 1
        )


class TestSelfReferentialBroaderIsSkippedLikeSelfReferentialRelated:
    def test_a_self_referential_broader_triple_is_skipped_not_crashed(self, db):
        report = import_skos(FIXTURES / "self_referential_broader.ttl")
        assert report.fatal == []
        loop = Concept.objects.get(static_uri="http://example.org/selfref/loop")
        assert list(loop.broader()) == []
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.BROADER).count()
            == 0
        )


class TestRelatedRelations:
    def test_a_related_pair_stated_once_is_stored_as_one_symmetric_relation(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        assert quartz in granite.related()
        assert granite in quartz.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 1
        )

    def test_both_directions_of_one_related_pair_produce_exactly_one_row(self, db):
        # relation_both_directions.ttl states east-related-west AND
        # west-related-east — both name the same unordered pair.
        import_skos(FIXTURES / "relation_both_directions.ttl")
        east = Concept.objects.get(static_uri="http://example.org/hierarchy/east")
        west = Concept.objects.get(static_uri="http://example.org/hierarchy/west")
        assert west in east.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 1
        )

    def test_reimporting_the_identical_file_does_not_duplicate_the_related_row(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        import_skos(FIXTURES / "rocks.ttl")
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 1
        )


class TestRelationEndpointsMissingOrKnown:
    def test_an_end_already_in_the_database_from_an_earlier_import_is_stored(self, db):
        import_skos(FIXTURES / "relation_endpoints.ttl")
        alpha_pk = Concept.objects.get(
            static_uri="http://example.org/relendpoints/alpha"
        ).pk
        beta_pk = Concept.objects.get(
            static_uri="http://example.org/relendpoints/beta"
        ).pk

        import_skos(FIXTURES / "relation_endpoints_updated.ttl")

        assert ConceptRelation.objects.filter(
            source_id=alpha_pk, target_id=beta_pk, kind=ConceptRelation.Kind.BROADER
        ).exists()
        # beta is untouched — the file no longer mentions it as a concept at all.
        assert Concept.objects.filter(pk=beta_pk).exists()

    def test_an_end_neither_in_the_file_nor_the_database_is_set_aside_naming_both_ends(
        self, db
    ):
        import_skos(FIXTURES / "relation_endpoints.ttl")

        report = import_skos(FIXTURES / "relation_endpoints_updated.ttl")

        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.MISSING_RELATION_END
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/relendpoints/alpha"
        assert entries[0].params["other"] == "http://example.org/relendpoints/ghost"
        assert not Concept.objects.filter(
            static_uri="http://example.org/relendpoints/ghost"
        ).exists()

    def test_the_run_succeeds_and_every_other_relationship_still_lands(self, db):
        import_skos(FIXTURES / "relation_endpoints.ttl")

        report = import_skos(FIXTURES / "relation_endpoints_updated.ttl")

        assert report.fatal == []
        alpha = Concept.objects.get(static_uri="http://example.org/relendpoints/alpha")
        beta = Concept.objects.get(static_uri="http://example.org/relendpoints/beta")
        assert beta in alpha.broader()

    def test_an_end_that_exists_but_in_a_different_vocabulary_is_set_aside_not_a_crash(
        self, db
    ):
        # ConceptRelation only ever joins concepts of the same scheme
        # (_reject_cross_scheme), so asserting one across vocabularies must not raise an
        # uncaught ValidationError.
        import_skos(FIXTURES / "rocks.ttl")

        report = import_skos(FIXTURES / "relation_cross_scheme_target.ttl")

        assert report.fatal == []
        outsider = Concept.objects.get(
            static_uri="http://example.org/outsiders/outsider"
        )
        assert list(outsider.broader()) == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.MISSING_RELATION_END
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/outsiders/outsider"
        assert entries[0].params["other"] == "http://example.org/rocks/granite"


class TestRelationRemovalOnReimport:
    def test_a_removed_related_edge_is_gone_and_both_concepts_remain(self, db):
        import_skos(FIXTURES / "relation_lifecycle.ttl")
        quarry = Concept.objects.get(static_uri="http://example.org/lifecycle/quarry")
        vein = Concept.objects.get(static_uri="http://example.org/lifecycle/vein")
        assert vein in quarry.related()

        import_skos(FIXTURES / "relation_lifecycle_updated.ttl")

        assert not ConceptRelation.objects.filter(
            kind=ConceptRelation.Kind.RELATED,
            source_id__in=(quarry.pk, vein.pk),
            target_id__in=(quarry.pk, vein.pk),
        ).exists()
        assert Concept.objects.filter(pk=quarry.pk).exists()
        assert Concept.objects.filter(pk=vein.pk).exists()

    def test_an_edge_whose_other_end_left_the_file_entirely_survives(self, db):
        # quarry-outlier is not restated by relation_lifecycle_updated.ttl, but outlier
        # itself is not written by that run either: the file's silence about outlier is
        # not a retraction of quarry's edge to it.
        import_skos(FIXTURES / "relation_lifecycle.ttl")
        quarry = Concept.objects.get(static_uri="http://example.org/lifecycle/quarry")
        outlier = Concept.objects.get(static_uri="http://example.org/lifecycle/outlier")
        assert outlier in quarry.related()

        report = import_skos(FIXTURES / "relation_lifecycle_updated.ttl")

        assert outlier in quarry.related()
        assert Concept.objects.filter(pk=outlier.pk).exists()
        assert "http://example.org/lifecycle/outlier" in report.absent_from_source

    def test_a_relationship_the_file_still_states_survives_the_same_reimport(self, db):
        # quarry's related edge to companion is unchanged between the two fixtures, so
        # the removal above must be selective, not a wholesale wipe of quarry's
        # relations.
        import_skos(FIXTURES / "relation_lifecycle.ttl")
        quarry = Concept.objects.get(static_uri="http://example.org/lifecycle/quarry")
        companion = Concept.objects.get(
            static_uri="http://example.org/lifecycle/companion"
        )

        import_skos(FIXTURES / "relation_lifecycle_updated.ttl")

        assert companion in quarry.related()


class TestRelationDisjointness:
    def test_broader_and_related_stated_together_keeps_broader_and_sets_aside_related(
        self, db
    ):
        report = import_skos(FIXTURES / "relation_disjointness_conflict.ttl")
        assert report.fatal == []
        child = Concept.objects.get(static_uri="http://example.org/disjoint/child")
        parent = Concept.objects.get(static_uri="http://example.org/disjoint/parent")
        assert parent in child.broader()
        assert parent not in child.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 0
        )
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.RELATION_DISJOINTNESS
        ]
        assert len(entries) == 1
        assert {entries[0].subject, entries[0].params["other"]} == {
            "http://example.org/disjoint/child",
            "http://example.org/disjoint/parent",
        }

    def test_a_related_row_from_an_earlier_run_does_not_crash_a_later_run_stating_broader(
        self, db
    ):
        import_skos(FIXTURES / "relation_disjointness_prior_related.ttl")
        a = Concept.objects.get(static_uri="http://example.org/disjoint2/a")
        b = Concept.objects.get(static_uri="http://example.org/disjoint2/b")
        assert b in a.related()

        report = import_skos(
            FIXTURES / "relation_disjointness_prior_related_updated.ttl"
        )

        assert report.fatal == []
        a.refresh_from_db()
        assert b in a.broader()
        assert b not in a.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 0
        )
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.RELATION_DISJOINTNESS
        ]
        assert len(entries) == 1
        assert {entries[0].subject, entries[0].params["other"]} == {
            "http://example.org/disjoint2/a",
            "http://example.org/disjoint2/b",
        }

    def test_a_broader_row_from_an_earlier_run_does_not_crash_a_later_run_stating_related(
        self, db
    ):
        # The symmetric route: the earlier-run survivor is a BROADER row this
        # time, and the later run states RELATED for the same pair instead.
        import_skos(FIXTURES / "relation_disjointness_prior_broader.ttl")
        a = Concept.objects.get(static_uri="http://example.org/disjoint3/a")
        b = Concept.objects.get(static_uri="http://example.org/disjoint3/b")
        assert b in a.broader()

        report = import_skos(
            FIXTURES / "relation_disjointness_prior_broader_updated.ttl"
        )

        assert report.fatal == []
        assert b in a.broader()
        assert b not in a.related()
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 0
        )
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.RELATION_DISJOINTNESS
        ]
        assert len(entries) == 1
        assert {entries[0].subject, entries[0].params["other"]} == {
            "http://example.org/disjoint3/a",
            "http://example.org/disjoint3/b",
        }


class TestCollectionSlugFollowsThePublishedIdentifier:
    def test_a_publisher_rename_leaves_the_collection_s_slug_and_local_url_unchanged(
        self, db, tmp_path
    ):
        first = tmp_path / "renamed_collection_first.ttl"
        first.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://pub.example/x> a skos:ConceptScheme ; skos:prefLabel "Scheme"@en .

            <http://pub.example/x#c1> a skos:Concept ;
                skos:inScheme <http://pub.example/x> ;
                skos:prefLabel "Concept One"@en .

            <http://pub.example/x#grp> a skos:Collection ;
                skos:prefLabel "Colours"@en ;
                skos:member <http://pub.example/x#c1> .
            """
        )
        import_skos(first)
        collection_before = Collection.objects.get(
            static_uri="http://pub.example/x#grp"
        )
        slug_before = collection_before.slug
        local_url_before = collection_before.local_url
        assert collection_before.name == "Colours"

        second = tmp_path / "renamed_collection_second.ttl"
        second.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://pub.example/x> a skos:ConceptScheme ; skos:prefLabel "Scheme"@en .

            <http://pub.example/x#c1> a skos:Concept ;
                skos:inScheme <http://pub.example/x> ;
                skos:prefLabel "Concept One"@en .

            <http://pub.example/x#grp> a skos:Collection ;
                skos:prefLabel "Colors"@en ;
                skos:member <http://pub.example/x#c1> .
            """
        )
        report = import_skos(second)

        collection_after = Collection.objects.get(static_uri="http://pub.example/x#grp")
        assert "http://pub.example/x#grp" in report.updated
        assert collection_after.name == "Colors"
        assert collection_after.slug == slug_before
        assert collection_after.local_url == local_url_before

    def test_a_collection_s_slug_is_the_last_segment_of_its_identifier_not_its_name(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        collection = Collection.objects.get(
            static_uri="http://example.org/rocks/collection/silica-bearing"
        )
        # The name "Silica-bearing rocks" would slugify to "silica-bearing-rocks"; the
        # slug follows the identifier's last segment.
        assert collection.slug == "silica-bearing"

    def test_a_collection_created_on_this_site_still_derives_its_slug_from_its_name(
        self, db, scheme
    ):
        collection = Collection.objects.create(
            scheme=scheme, name="Silica bearing rocks"
        )
        assert collection.static_uri is None
        assert collection.slug_is_manual is False
        assert collection.slug == "silica-bearing-rocks"


class TestUnusableCollectionSlugIsSetAsideNotCrashed:
    def test_an_identifier_segment_that_slugifies_to_empty_is_set_aside_and_named(
        self, db, tmp_path
    ):
        path = tmp_path / "unusable_collection_slug.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://c.org/vocab3/> a skos:ConceptScheme ; skos:prefLabel "Symbols"@en .

            <http://c.org/vocab3/ok> a skos:Concept ;
                skos:inScheme <http://c.org/vocab3/> ;
                skos:prefLabel "OK"@en .

            <http://c.org/vocab3/#±> a skos:Collection ;
                skos:prefLabel "Assorted symbols"@en ;
                skos:member <http://c.org/vocab3/ok> .
            """
        )
        report = import_skos(path)
        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://c.org/vocab3/#±"
        assert not Collection.objects.filter(
            static_uri="http://c.org/vocab3/#±"
        ).exists()

    def test_the_rest_of_the_file_still_imports(self, db, tmp_path):
        path = tmp_path / "unusable_collection_slug2.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://c.org/vocab4/> a skos:ConceptScheme ; skos:prefLabel "Symbols"@en .

            <http://c.org/vocab4/ok> a skos:Concept ;
                skos:inScheme <http://c.org/vocab4/> ;
                skos:prefLabel "OK"@en .

            <http://c.org/vocab4/#±> a skos:Collection ;
                skos:prefLabel "Assorted symbols"@en ;
                skos:member <http://c.org/vocab4/ok> .
            """
        )
        import_skos(path)
        assert ConceptScheme.objects.filter(static_uri="http://c.org/vocab4/").exists()
        assert Concept.objects.filter(static_uri="http://c.org/vocab4/ok").exists()


class TestCollectionsCollidingOnlyByNameNoLongerCrash:
    def test_two_collections_sharing_a_name_but_not_an_identifier_both_import(
        self, db, tmp_path
    ):
        path = tmp_path / "collection_name_collision.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://c.org/vocab5/> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .

            <http://c.org/vocab5/collection/a> a skos:Collection ; skos:prefLabel "Rock Types"@en .
            <http://c.org/vocab5/collection/b> a skos:Collection ; skos:prefLabel "rock types"@en .
            """
        )
        report = import_skos(path)
        assert report.fatal == []
        assert report.set_aside == []
        a = Collection.objects.get(static_uri="http://c.org/vocab5/collection/a")
        b = Collection.objects.get(static_uri="http://c.org/vocab5/collection/b")
        assert a.slug != b.slug
        assert {a.slug, b.slug} == {"a", "b"}


class TestCollectionsAndMembership:
    def test_a_collection_is_created_holding_its_published_identifier(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/silica-bearing"
        )
        assert collection.scheme == ConceptScheme.objects.get(
            static_uri="http://example.org/rocks/"
        )
        assert collection.ordered is False

    def test_the_collection_holds_exactly_its_published_members(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/silica-bearing"
        )
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        assert set(collection.members()) == {granite, quartz}

    def test_reimporting_the_identical_file_does_not_duplicate_the_collection_or_its_members(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        import_skos(FIXTURES / "rocks.ttl")
        assert (
            Collection.objects.filter(
                static_uri="http://example.org/rocks/collection/silica-bearing"
            ).count()
            == 1
        )
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/silica-bearing"
        )
        assert collection.memberships.count() == 2

    def test_a_first_import_reports_the_collection_as_created(self, db):
        report = import_skos(FIXTURES / "rocks.ttl")
        assert "http://example.org/rocks/collection/silica-bearing" in report.created


class TestOrderedCollectionMemberOrder:
    def test_an_ordered_collection_is_marked_ordered(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )
        assert collection.ordered is True

    def test_members_come_back_in_the_files_own_order(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        sedimentary = Concept.objects.get(
            static_uri="http://example.org/rocks/sedimentary"
        )
        assert collection.members() == [basalt, granite, sedimentary]

    def test_a_reimport_that_changes_the_order_updates_the_positions_to_match(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        collection_pk = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        ).pk

        import_skos(FIXTURES / "rocks_updated.ttl")

        collection = Collection.objects.get(pk=collection_pk)
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        sedimentary = Concept.objects.get(
            static_uri="http://example.org/rocks/sedimentary"
        )
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        assert collection.members() == [granite, sedimentary, basalt]

    def test_the_ordered_collections_own_identifier_is_unchanged_by_reordering(
        self, db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        before = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )

        import_skos(FIXTURES / "rocks_updated.ttl")

        after = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )
        assert after.pk == before.pk
        assert after.static_uri == before.static_uri


class TestOrderedCollectionFallsBackToMember:
    def test_an_ordered_collection_with_only_member_is_not_empty(self, db):
        report = import_skos(FIXTURES / "ordered_collection_member_only.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/ordered-member-only/collection/group"
        )
        alpha = Concept.objects.get(
            static_uri="http://example.org/ordered-member-only/alpha"
        )
        beta = Concept.objects.get(
            static_uri="http://example.org/ordered-member-only/beta"
        )
        assert collection.ordered is True
        assert collection.members() == [alpha, beta]
        assert report.fatal == []

    def test_a_reimport_with_only_member_does_not_empty_existing_membership(self, db):
        # An empty member_uris from a genuinely empty file is a full retraction; a
        # collection that states members must not be read as if it had none.
        import_skos(FIXTURES / "ordered_collection_member_only.ttl")
        import_skos(FIXTURES / "ordered_collection_member_only.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/ordered-member-only/collection/group"
        )
        assert collection.memberships.count() == 2

    def test_memberlist_governs_order_and_member_only_entries_are_appended(self, db):
        import_skos(FIXTURES / "ordered_collection_member_and_memberlist.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/ordered-mixed/collection/group"
        )
        alpha = Concept.objects.get(static_uri="http://example.org/ordered-mixed/alpha")
        beta = Concept.objects.get(static_uri="http://example.org/ordered-mixed/beta")
        gamma = Concept.objects.get(static_uri="http://example.org/ordered-mixed/gamma")
        assert collection.members() == [gamma, alpha, beta]


class TestCollectionMembershipMissingOrAbsentEnds:
    def test_a_member_neither_in_the_file_nor_the_database_is_set_aside_naming_both(
        self, db
    ):
        report = import_skos(FIXTURES / "collection_lifecycle.ttl")
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.MISSING_MEMBER
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/lifecycle-collections/missing"
        assert (
            entries[0].params["collection"]
            == "http://example.org/lifecycle-collections/collection/group"
        )

    def test_the_collection_is_still_created_and_the_run_succeeds(self, db):
        report = import_skos(FIXTURES / "collection_lifecycle.ttl")
        assert report.fatal == []
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )
        alpha = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/alpha"
        )
        beta = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/beta"
        )
        gamma = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/gamma"
        )
        assert set(collection.members()) == {alpha, beta, gamma}
        assert not Concept.objects.filter(
            static_uri="http://example.org/lifecycle-collections/missing"
        ).exists()

    def test_a_member_the_file_still_states_survives_the_reimport(self, db):
        import_skos(FIXTURES / "collection_lifecycle.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )
        alpha = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/alpha"
        )

        import_skos(FIXTURES / "collection_lifecycle_updated.ttl")

        assert alpha in collection.members()

    def test_a_member_the_file_still_contains_but_excludes_is_removed(self, db):
        # beta stays a concept in collection_lifecycle_updated.ttl, but
        # "group"'s own member list no longer names it — a genuine
        # retraction, since beta was mentioned (and rewritten) this run.
        import_skos(FIXTURES / "collection_lifecycle.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )
        beta = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/beta"
        )

        import_skos(FIXTURES / "collection_lifecycle_updated.ttl")

        assert beta not in collection.members()
        assert Concept.objects.filter(pk=beta.pk).exists()

    def test_a_member_whose_concept_the_file_no_longer_mentions_at_all_survives(
        self, db
    ):
        # The same rule as for a relation: gamma leaves the updated file entirely, so
        # this run never rewrites it, and the file's silence is not "group" retracting
        # the membership. It stays, as gamma's own row does.
        import_skos(FIXTURES / "collection_lifecycle.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )
        gamma = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/gamma"
        )

        report = import_skos(FIXTURES / "collection_lifecycle_updated.ttl")

        assert gamma in collection.members()
        assert Concept.objects.filter(pk=gamma.pk).exists()
        assert (
            "http://example.org/lifecycle-collections/gamma"
            in report.absent_from_source
        )

    def test_a_new_member_is_added_on_reimport(self, db):
        import_skos(FIXTURES / "collection_lifecycle.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )

        import_skos(FIXTURES / "collection_lifecycle_updated.ttl")

        delta = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/delta"
        )
        assert delta in collection.members()

    def test_the_final_membership_matches_the_updated_file_plus_the_survivor(self, db):
        import_skos(FIXTURES / "collection_lifecycle.ttl")
        collection = Collection.objects.get_by_uri(
            "http://example.org/lifecycle-collections/collection/group"
        )

        import_skos(FIXTURES / "collection_lifecycle_updated.ttl")

        alpha = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/alpha"
        )
        gamma = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/gamma"
        )
        delta = Concept.objects.get(
            static_uri="http://example.org/lifecycle-collections/delta"
        )
        assert set(collection.members()) == {alpha, gamma, delta}


class TestCollectionAbsentFromSource:
    def test_a_collection_dropped_from_the_file_is_untouched_and_named_absent(self, db):
        import_skos(FIXTURES / "collection_absent_from_source.ttl")
        dropped = Collection.objects.get_by_uri(
            "http://example.org/vanishing-collections/collection/dropped"
        )
        dropped_pk, dropped_name = dropped.pk, dropped.name

        report = import_skos(FIXTURES / "collection_absent_from_source_updated.ttl")

        dropped_after = Collection.objects.get_by_uri(
            "http://example.org/vanishing-collections/collection/dropped"
        )
        assert dropped_after.pk == dropped_pk
        assert dropped_after.name == dropped_name
        assert (
            "http://example.org/vanishing-collections/collection/dropped"
            in report.absent_from_source
        )
        assert (
            "http://example.org/vanishing-collections/collection/dropped"
            not in report.updated
        )
        assert (
            "http://example.org/vanishing-collections/collection/dropped"
            not in report.created
        )

    def test_a_collection_still_mentioned_in_the_file_is_not_reported_absent(self, db):
        import_skos(FIXTURES / "collection_absent_from_source.ttl")
        report = import_skos(FIXTURES / "collection_absent_from_source_updated.ttl")
        assert (
            "http://example.org/vanishing-collections/collection/kept"
            not in report.absent_from_source
        )

    def test_a_dropped_collections_membership_survives_untouched(self, db):
        # Left untouched, not only not deleted: the concept stays a member of the absent
        # collection, as an absent concept's own foreign-key references survive
        # (TestRecordsAbsentFromSource).
        import_skos(FIXTURES / "collection_absent_from_source.ttl")
        dropped = Collection.objects.get_by_uri(
            "http://example.org/vanishing-collections/collection/dropped"
        )
        alpha = Concept.objects.get(
            static_uri="http://example.org/vanishing-collections/alpha"
        )

        import_skos(FIXTURES / "collection_absent_from_source_updated.ttl")

        assert alpha in dropped.members()


class TestAbsentFromSourceNeverContainsNone:
    def test_a_locally_authored_concept_reports_its_dynamic_uri_not_none(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/rocks/")
        local = ConceptFactory(scheme=scheme, label="Local only")
        assert local.static_uri is None

        report = import_skos(FIXTURES / "rocks.ttl")

        assert None not in report.absent_from_source
        assert local.uri in report.absent_from_source

    def test_a_locally_authored_collection_reports_its_dynamic_uri_not_none(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/rocks/")
        local = CollectionFactory(scheme=scheme, name="Local collection only")
        assert local.static_uri is None

        report = import_skos(FIXTURES / "rocks.ttl")

        assert None not in report.absent_from_source
        assert local.uri in report.absent_from_source


class TestExistingConceptIsNotSilentlyMovedBetweenVocabularies:
    def test_a_concept_already_in_another_vocabulary_is_not_moved(self, db):
        first = ConceptSchemeFactory(name="First")
        second = ConceptSchemeFactory(name="Second")
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)

        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=second)

        a = Concept.objects.get(static_uri="http://example.org/reassignment/a")
        b = Concept.objects.get(static_uri="http://example.org/reassignment/b")
        assert a.scheme_id == first.pk
        assert b.scheme_id == first.pk
        assert first.concepts.count() == 2
        assert second.concepts.count() == 0

    def test_the_conflict_is_reported_naming_both_vocabularies(self, db):
        first = ConceptSchemeFactory(name="First")
        second = ConceptSchemeFactory(name="Second")
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)

        report = import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=second)

        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY
        ]
        assert {entry.subject for entry in entries} == {
            "http://example.org/reassignment/a",
            "http://example.org/reassignment/b",
        }
        for entry in entries:
            assert entry.params["current"] == first.uri
            assert entry.params["target"] == second.uri

    def test_report_updated_does_not_claim_the_move_happened(self, db):
        first = ConceptSchemeFactory(name="First")
        second = ConceptSchemeFactory(name="Second")
        import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=first)

        report = import_skos(FIXTURES / "vocabulary_reassignment.ttl", scheme=second)

        assert "http://example.org/reassignment/a" not in report.updated
        assert "http://example.org/reassignment/b" not in report.updated
        assert "http://example.org/reassignment/a" not in report.created
        assert "http://example.org/reassignment/b" not in report.created


class TestExistingCollectionIsNotSilentlyReassignedBetweenVocabularies:
    def test_a_collection_already_in_another_vocabulary_is_not_reassigned(self, db):
        import_skos(FIXTURES / "shared_collection_vocab_a.ttl")
        import_skos(FIXTURES / "shared_collection_vocab_b.ttl")

        vocab_a = ConceptScheme.objects.get(
            static_uri="http://example.org/shared-collection/vocab-a/"
        )
        collection = Collection.objects.get_by_uri("http://example.org/shared/coll")
        concept_a = Concept.objects.get(
            static_uri="http://example.org/shared-collection/vocab-a/concept-a"
        )
        concept_b = Concept.objects.get(
            static_uri="http://example.org/shared-collection/vocab-b/concept-b"
        )

        assert collection.scheme_id == vocab_a.pk
        assert collection.members() == [concept_a]
        assert concept_b not in collection.members()

    def test_the_conflict_is_reported_naming_both_vocabularies(self, db):
        import_skos(FIXTURES / "shared_collection_vocab_a.ttl")
        vocab_a = ConceptScheme.objects.get(
            static_uri="http://example.org/shared-collection/vocab-a/"
        )
        vocab_b_uri = "http://example.org/shared-collection/vocab-b/"

        report = import_skos(FIXTURES / "shared_collection_vocab_b.ttl")

        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/shared/coll"
        assert entries[0].params["current"] == vocab_a.uri
        assert entries[0].params["target"] == vocab_b_uri


class TestUriHeldByARecordOfADifferentKind:
    def test_a_concept_uri_already_held_by_a_collection_is_refused(self, db):
        import_skos(FIXTURES / "uri_kind_collection_first.ttl")

        report = import_skos(FIXTURES / "uri_kind_concept_second.ttl")

        assert not Concept.objects.filter(
            static_uri="http://example.org/kind-clash/thing"
        ).exists()
        assert Collection.objects.filter(
            static_uri="http://example.org/kind-clash/thing"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.URI_HELD_BY_DIFFERENT_KIND
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/kind-clash/thing"

    def test_a_collection_uri_already_held_by_a_concept_is_refused(self, db):
        import_skos(FIXTURES / "uri_kind_concept_second.ttl")

        report = import_skos(FIXTURES / "uri_kind_collection_first.ttl")

        assert not Collection.objects.filter(
            static_uri="http://example.org/kind-clash/thing"
        ).exists()
        assert Concept.objects.filter(
            static_uri="http://example.org/kind-clash/thing"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.URI_HELD_BY_DIFFERENT_KIND
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://example.org/kind-clash/thing"


class TestBlankNodeCollectionFails:
    def test_a_blank_node_collection_fails_the_run(self, db):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "blank_node_collection.ttl")
        entries = [
            entry
            for entry in excinfo.value.report.fatal
            if entry.reason is FatalReason.MISSING_IDENTITY
        ]
        assert len(entries) == 1
        assert entries[0].subject == "Nameless collection"

    def test_a_blank_node_collection_writes_nothing(self, db):
        with pytest.raises(SkosImportFailed):
            import_skos(FIXTURES / "blank_node_collection.ttl")
        assert not Concept.objects.filter(
            static_uri="http://example.org/rocks/igneous"
        ).exists()
        assert not Collection.objects.exists()

    def test_an_ordered_collections_list_cells_are_not_identities(self, db):
        # rocks.ttl's example-sequence is an ordinary ordered collection whose
        # skos:memberList is an RDF list, blank nodes by construction. None of those
        # cells may be treated as a record needing its own identity.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.fatal == []
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )
        assert collection.ordered is True


class TestFixtureCorpus:
    def test_the_fixture_directory_is_not_empty(self):
        # Guards the discovery above: an empty or moved directory would otherwise
        # parametrize to nothing and report as a clean pass.
        assert len(ALL_FIXTURES) >= len(BASE_SERIALIZATIONS)

    @pytest.mark.parametrize("filename,fmt", ALL_FIXTURES)
    def test_every_fixture_is_discoverable_and_parses(self, filename, fmt):
        path = FIXTURES / filename
        assert path.is_file(), (
            f"{filename} is not discoverable under tests/fixtures/skos/"
        )
        graph = rdflib.Graph()
        graph.parse(path, format=fmt)
        assert len(graph) > 0, f"{filename} parsed to an empty graph"

    @pytest.mark.parametrize("filename,fmt", BASE_SERIALIZATIONS)
    def test_base_vocabulary_declares_the_scheme_and_its_top_concepts(
        self, filename, fmt
    ):
        graph = rdflib.Graph()
        graph.parse(FIXTURES / filename, format=fmt)
        assert (ROCKS_SCHEME_URI, rdflib.RDF.type, SKOS.ConceptScheme) in graph
        top_concepts = set(graph.objects(ROCKS_SCHEME_URI, SKOS.hasTopConcept))
        assert top_concepts == {
            rdflib.URIRef("http://example.org/rocks/igneous"),
            rdflib.URIRef("http://example.org/rocks/sedimentary"),
        }

    @pytest.mark.parametrize("filename,fmt", BASE_SERIALIZATIONS)
    def test_base_vocabulary_carries_multilingual_labels_notes_hierarchy_related_and_collections(
        self, filename, fmt
    ):
        graph = rdflib.Graph()
        graph.parse(FIXTURES / filename, format=fmt)
        granite = rdflib.URIRef("http://example.org/rocks/granite")
        quartz = rdflib.URIRef("http://example.org/rocks/quartz")
        igneous = rdflib.URIRef("http://example.org/rocks/igneous")

        # Multilingual preferred labels (en/de/fr — the test settings' configured languages).
        granite_labels = {
            (o.language, str(o)) for o in graph.objects(granite, SKOS.prefLabel)
        }
        assert granite_labels == {
            ("en", "Granite"),
            ("de", "Granit"),
            ("fr", "Granite"),
        }

        assert (igneous, SKOS.definition, None) in graph
        assert (granite, SKOS.scopeNote, None) in graph
        assert (quartz, SKOS.historyNote, None) in graph
        assert (quartz, SKOS.changeNote, None) in graph
        assert (quartz, SKOS.note, None) in graph

        assert (granite, SKOS.broader, igneous) in graph
        assert (granite, SKOS.related, quartz) in graph

        unordered = rdflib.URIRef("http://example.org/rocks/collection/silica-bearing")
        ordered = rdflib.URIRef("http://example.org/rocks/collection/example-sequence")
        assert (unordered, rdflib.RDF.type, SKOS.Collection) in graph
        assert set(graph.objects(unordered, SKOS.member)) == {granite, quartz}
        assert (ordered, rdflib.RDF.type, SKOS.OrderedCollection) in graph
        member_list = graph.value(ordered, SKOS.memberList)
        assert list(graph.items(member_list)) == [
            rdflib.URIRef("http://example.org/rocks/basalt"),
            granite,
            rdflib.URIRef("http://example.org/rocks/sedimentary"),
        ]

    def test_the_three_base_serializations_are_isomorphic(self):
        from rdflib.compare import isomorphic

        graphs = []
        for filename, fmt in BASE_SERIALIZATIONS:
            graph = rdflib.Graph()
            graph.parse(FIXTURES / filename, format=fmt)
            graphs.append(graph)
        assert isomorphic(graphs[0], graphs[1]), (
            "rocks.ttl and rocks.rdf are not isomorphic"
        )
        assert isomorphic(graphs[0], graphs[2]), (
            "rocks.ttl and rocks.jsonld are not isomorphic"
        )

    def test_updated_fixture_carries_the_four_re_import_edits(self):
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "rocks_updated.ttl", format="turtle")
        granite = rdflib.URIRef("http://example.org/rocks/granite")
        quartz = rdflib.URIRef("http://example.org/rocks/quartz")

        assert (
            granite,
            SKOS.prefLabel,
            rdflib.Literal("Granite (revised)", lang="en"),
        ) in graph
        assert (
            granite,
            SKOS.prefLabel,
            rdflib.Literal("Granite", lang="en"),
        ) not in graph

        assert (granite, SKOS.altLabel, None) not in graph

        # A concept dropped from the file entirely, taking its related edge and
        # collection membership with it. It stays in an already-imported database, so a
        # re-import names it as absent.
        assert (quartz, rdflib.RDF.type, SKOS.Concept) not in graph
        assert (granite, SKOS.related, quartz) not in graph
        unordered = rdflib.URIRef("http://example.org/rocks/collection/silica-bearing")
        assert quartz not in set(graph.objects(unordered, SKOS.member))

        ordered = rdflib.URIRef("http://example.org/rocks/collection/example-sequence")
        member_list = graph.value(ordered, SKOS.memberList)
        assert list(graph.items(member_list)) == [
            granite,
            rdflib.URIRef("http://example.org/rocks/sedimentary"),
            rdflib.URIRef("http://example.org/rocks/basalt"),
        ]

    def test_variants_fixture_carries_several_variants_of_one_base_language_across_labels_and_notes(
        self,
    ):
        # Several variants of one base language (en) spread across preferred labels,
        # alternative labels and notes: the population the variant contest needs.
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "variants.ttl", format="turtle")
        colour = rdflib.URIRef("http://example.org/colours/colour")

        pref_labels = {
            (o.language, str(o)) for o in graph.objects(colour, SKOS.prefLabel)
        }
        assert pref_labels == {("en-gb", "Colour"), ("en-us", "Color")}

        alt_labels = {
            (o.language, str(o)) for o in graph.objects(colour, SKOS.altLabel)
        }
        assert alt_labels == {("en-gb", "Colour"), ("en-us", "Color")}

        note_languages = {o.language for o in graph.objects(colour, SKOS.note)}
        assert note_languages == {"en-gb", "en-us"}

    def test_en_gb_only_fixture_publishes_only_the_specific_to_general_direction(self):
        # A vocabulary published only as en-gb, for a site configured only for en (no
        # bare "en" tag anywhere in the file).
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "en-gb-only.ttl", format="turtle")
        languages = {
            literal.language for literal in graph.objects(None, SKOS.prefLabel)
        }
        assert languages == {"en-gb"}

    def test_declares_de_at_fixture_declares_itself_in_a_variant_of_a_configured_language(
        self,
    ):
        # The vocabulary's own skos:prefLabel is a single de-at tag, for the
        # default-language resolution path.
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "declares-de-at.ttl", format="turtle")
        scheme = rdflib.URIRef("http://example.org/farben/")
        assert (scheme, rdflib.RDF.type, SKOS.ConceptScheme) in graph
        scheme_labels = {
            (o.language, str(o)) for o in graph.objects(scheme, SKOS.prefLabel)
        }
        assert scheme_labels == {("de-at", "Farben")}

    def test_blank_node_concept_fixture_has_no_uri_identity(self):
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "blank_node_concept.ttl", format="turtle")
        concepts = list(graph.subjects(rdflib.RDF.type, SKOS.Concept))
        assert len(concepts) == 1
        assert isinstance(concepts[0], rdflib.BNode), (
            "the fixture's concept must be a blank node, not a URI"
        )

    def test_blank_node_collection_fixture_has_no_uri_identity(self):
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "blank_node_collection.ttl", format="turtle")
        collections = list(graph.subjects(rdflib.RDF.type, SKOS.Collection))
        assert len(collections) == 1
        assert isinstance(collections[0], rdflib.BNode), (
            "the fixture's collection must be a blank node, not a URI"
        )

    def test_refused_uri_scheme_fixture_uses_a_disallowed_scheme(self):
        from controlled_vocabularies.conf import DEFAULT_ALLOWED_URI_SCHEMES

        graph = rdflib.Graph()
        graph.parse(FIXTURES / "refused_uri_scheme.ttl", format="turtle")
        concepts = list(graph.subjects(rdflib.RDF.type, SKOS.Concept))
        assert len(concepts) == 1
        scheme = str(concepts[0]).split(":", 1)[0]
        assert scheme not in DEFAULT_ALLOWED_URI_SCHEMES, (
            f"fixture's concept scheme '{scheme}' must be outside the default allowlist"
        )


# Restated from the SKOS specification rather than imported from exchange.mapping: a
# check built from the constants production uses to decide what it has handled could
# never notice production ceasing to read what it still claims to.
_COVERAGE_LABEL_KIND = {
    SKOS.prefLabel: ConceptLabel.Kind.PREFERRED,
    SKOS.altLabel: ConceptLabel.Kind.ALTERNATIVE,
    SKOS.hiddenLabel: ConceptLabel.Kind.HIDDEN,
}
_COVERAGE_NOTE_KIND = {
    SKOS.definition: ConceptNote.Kind.DEFINITION,
    SKOS.scopeNote: ConceptNote.Kind.SCOPE,
    SKOS.example: ConceptNote.Kind.EXAMPLE,
    SKOS.editorialNote: ConceptNote.Kind.EDITORIAL,
    SKOS.historyNote: ConceptNote.Kind.HISTORY,
    SKOS.changeNote: ConceptNote.Kind.CHANGE,
    SKOS.note: ConceptNote.Kind.NOTE,
}
# CURIEs for the label and note predicates, restated rather than borrowed from skos.py
# for the same reason.
_COVERAGE_LABEL_NOTE_CURIE = {
    SKOS.prefLabel: "skos:prefLabel",
    SKOS.altLabel: "skos:altLabel",
    SKOS.hiddenLabel: "skos:hiddenLabel",
    SKOS.definition: "skos:definition",
    SKOS.scopeNote: "skos:scopeNote",
    SKOS.example: "skos:example",
    SKOS.editorialNote: "skos:editorialNote",
    SKOS.historyNote: "skos:historyNote",
    SKOS.changeNote: "skos:changeNote",
    SKOS.note: "skos:note",
}
_COVERAGE_MAPPING_CURIE = {
    SKOS.exactMatch: "skos:exactMatch",
    SKOS.closeMatch: "skos:closeMatch",
    SKOS.broadMatch: "skos:broadMatch",
    SKOS.narrowMatch: "skos:narrowMatch",
    SKOS.relatedMatch: "skos:relatedMatch",
    SKOS.mappingRelation: "skos:mappingRelation",
}

# Reasons under which the whole record was never created or updated, so none of its
# predicates needs further evidence.
_COVERAGE_WHOLE_RECORD_EXCLUDED_REASONS = frozenset(
    {
        SetAsideReason.NO_PREFERRED_LABEL,
        SetAsideReason.VOCABULARY_MISMATCH,
        SetAsideReason.EMPTY_SLUG,
        SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY,
        SetAsideReason.URI_HELD_BY_DIFFERENT_KIND,
    }
)

# Fatal-path fixtures, and two that need a caller-named scheme, write no record and no
# non-fatal report entry; each has its own test class.
_PREDICATE_COVERAGE_EXCLUDED_FIXTURES = frozenset(
    {
        "blank_node_concept.ttl",  # TestFatalFindingsAndAtomicity
        "blank_node_collection.ttl",  # TestBlankNodeCollectionFails
        "refused_uri_scheme.ttl",  # TestFatalFindingsAndAtomicity
        "multiple_fatal_problems.ttl",  # TestFatalFindingsAndAtomicity
        "reimport_rolls_back_an_update.ttl",  # TestAtomicityOnAPopulatedDatabase
        "two_vocabularies.ttl",  # TestChoosingBetweenDeclaredVocabularies
        "no_scheme_declared.ttl",  # TestImportSkosVocabulary
        "vocabulary_reassignment.ttl",  # TestExistingConceptIsNotSilentlyMovedBetweenVocabularies
        "cyclic_member_list.ttl",  # TestCraftedFilesStayInsideTheExceptionContract: raises, no report
    }
)

_PREDICATE_COVERAGE_FIXTURES = sorted(
    (filename, fmt)
    for filename, fmt in ALL_FIXTURES
    if filename not in _PREDICATE_COVERAGE_EXCLUDED_FIXTURES
)


def _coverage_membership_covered(collection_uri: str, concept_uri: str, report) -> bool:
    """Report whether a collection member landed or was reported as missing.

    Args:
        collection_uri: The collection's published identifier.
        concept_uri: The member concept's published identifier.
        report: The import report to search for a missing-member entry.

    Returns:
        True when the concept is a stored member of the collection, or the report names it as
        a member that could not be found.
    """
    if CollectionMember.objects.filter(
        collection__static_uri=collection_uri, concept__static_uri=concept_uri
    ).exists():
        return True
    return any(
        entry.reason is SetAsideReason.MISSING_MEMBER
        and entry.subject == concept_uri
        and entry.params.get("collection") == collection_uri
        for entry in report.set_aside
    )


def _coverage_relation_covered(
    kind: str, source_uri: str, target_uri: str, report
) -> bool:
    """Report whether a relation landed or was reported as missing or disjoint.

    Args:
        kind: The relation kind.
        source_uri: The published identifier of the relation's source concept.
        target_uri: The published identifier of the relation's target concept.
        report: The import report to search for a set-aside entry.

    Returns:
        True when a ``kind`` relation from source to target is stored, or the report names the
        pair as missing an end or disjoint.
    """
    if ConceptRelation.objects.filter(
        kind=kind, source__static_uri=source_uri, target__static_uri=target_uri
    ).exists():
        return True
    return any(
        entry.reason
        in (SetAsideReason.MISSING_RELATION_END, SetAsideReason.RELATION_DISJOINTNESS)
        and {entry.subject, entry.params.get("other")} == {source_uri, target_uri}
        for entry in report.set_aside
    )


def _coverage_scheme_membership_covered(
    concept_uri: str, scheme_uri: str, excluded_subjects: set[str]
) -> bool:
    """Report whether a concept landed inside the vocabulary its file names.

    Args:
        concept_uri: The concept's published identifier.
        scheme_uri: The published identifier of the vocabulary the file places it in.
        excluded_subjects: Subjects set aside whole, which were never created.

    Returns:
        True when the concept is stored in that vocabulary, or was never created this run.
    """
    if concept_uri in excluded_subjects:
        return True
    return Concept.objects.filter(
        static_uri=concept_uri, scheme__static_uri=scheme_uri
    ).exists()


def _coverage_label_covered(
    subject_uri: str,
    language: str,
    text: str,
    kind: str,
    excluded_subjects: set[str],
    report,
) -> bool:
    """Report whether a label value landed or was reported as set aside.

    Args:
        subject_uri: The published identifier of the record carrying the label.
        language: The language tag the value was published under.
        text: The label text.
        kind: The label kind.
        excluded_subjects: Subjects set aside whole, which were never created.
        report: The import report to search for a set-aside entry.

    Returns:
        True when the value is the scheme's name, a concept's label or a stored label row, or
        the report names it as set aside.
    """
    # A value may land under a resolved language other than its published tag, so the
    # landed-row checks are not scoped to ``language``.
    if subject_uri in excluded_subjects:
        return True
    if kind == ConceptLabel.Kind.PREFERRED:
        if ConceptScheme.objects.filter(static_uri=subject_uri, name=text).exists():
            return True
        if Concept.objects.filter(static_uri=subject_uri, label=text).exists():
            return True
        if Collection.objects.filter(static_uri=subject_uri, name=text).exists():
            return True
    if ConceptLabel.objects.filter(
        concept__static_uri=subject_uri, kind=kind, text=text
    ).exists():
        return True
    return any(
        entry.subject == subject_uri
        and entry.params.get("language") == language
        and entry.reason
        in (
            SetAsideReason.UNCONFIGURED_LANGUAGE,
            SetAsideReason.SURPLUS_PREFERRED_LABEL,
            SetAsideReason.VARIANT_NOT_KEPT,
            # A value the model's own field refuses on length.
            SetAsideReason.VALUE_TOO_LONG,
        )
        for entry in report.set_aside
    )


def _coverage_note_covered(
    subject_uri: str,
    language: str,
    text: str,
    kind: str,
    excluded_subjects: set[str],
    report,
) -> bool:
    """Report whether a note value landed or was reported as set aside.

    Args:
        subject_uri: The published identifier of the concept carrying the note.
        language: The language tag the value was published under.
        text: The note text.
        kind: The note kind.
        excluded_subjects: Subjects set aside whole, which were never created.
        report: The import report to search for a set-aside entry.

    Returns:
        True when the value is a stored note row, or the report names it as set aside.
    """
    # Not scoped to ``language`` on the landed-row check, for the reason given in
    # _coverage_label_covered.
    if subject_uri in excluded_subjects:
        return True
    if ConceptNote.objects.filter(
        concept__static_uri=subject_uri, kind=kind, value=text
    ).exists():
        return True
    return any(
        entry.subject == subject_uri
        and entry.params.get("language") == language
        and entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        for entry in report.set_aside
    )


def _coverage_untagged_covered(
    subject_uri: str, predicate_curie: str, excluded_subjects: set[str], report
) -> bool:
    """Report whether a value with no language tag was reported as set aside.

    Args:
        subject_uri: The published identifier of the record carrying the value.
        predicate_curie: The label or note predicate, as a CURIE.
        excluded_subjects: Subjects set aside whole, which were never created.
        report: The import report to search for a ``NO_LANGUAGE_TAG`` entry.

    Returns:
        True when the report names the value under that predicate.
    """
    if subject_uri in excluded_subjects:
        return True
    return any(
        entry.subject == subject_uri
        and entry.params.get("predicate") == predicate_curie
        and entry.reason is SetAsideReason.NO_LANGUAGE_TAG
        for entry in report.set_aside
    )


def _coverage_predicate_covered(
    predicate: rdflib.URIRef,
    graph: rdflib.Graph,
    in_scope: set[str],
    excluded_subjects: set[str],
    report,
) -> tuple[bool, str | None]:
    """Check that every in-scope triple of a predicate landed in a record or was reported.

    Args:
        predicate: The SKOS predicate to verify.
        graph: The parsed fixture.
        in_scope: Identifiers of the records the importer is accountable for.
        excluded_subjects: Subjects set aside whole, whose predicates need no further evidence.
        report: The import report to search for set-aside entries.

    Returns:
        ``(True, None)`` when covered, otherwise ``(False, subject)`` naming the subject of the
        first triple with no evidence.
    """
    if predicate in _COVERAGE_LABEL_KIND:
        kind = _COVERAGE_LABEL_KIND[predicate]
        for subject_node, literal in graph.subject_objects(predicate):
            subject_uri = str(subject_node)
            if subject_uri not in in_scope:
                continue
            if not isinstance(literal, rdflib.Literal) or not literal.language:
                if not _coverage_untagged_covered(
                    subject_uri,
                    _COVERAGE_LABEL_NOTE_CURIE[predicate],
                    excluded_subjects,
                    report,
                ):
                    return False, subject_uri
                continue
            if not _coverage_label_covered(
                subject_uri,
                literal.language,
                str(literal),
                kind,
                excluded_subjects,
                report,
            ):
                return False, subject_uri
        return True, None

    if predicate in _COVERAGE_NOTE_KIND:
        kind = _COVERAGE_NOTE_KIND[predicate]
        for subject_node, literal in graph.subject_objects(predicate):
            subject_uri = str(subject_node)
            if subject_uri not in in_scope:
                continue
            if not isinstance(literal, rdflib.Literal) or not literal.language:
                if not _coverage_untagged_covered(
                    subject_uri,
                    _COVERAGE_LABEL_NOTE_CURIE[predicate],
                    excluded_subjects,
                    report,
                ):
                    return False, subject_uri
                continue
            if not _coverage_note_covered(
                subject_uri,
                literal.language,
                str(literal),
                kind,
                excluded_subjects,
                report,
            ):
                return False, subject_uri
        return True, None

    if predicate in _COVERAGE_MAPPING_CURIE:
        curie = _COVERAGE_MAPPING_CURIE[predicate]
        for subject_node, _obj in graph.subject_objects(predicate):
            subject_uri = str(subject_node)
            if subject_uri not in in_scope or subject_uri in excluded_subjects:
                continue
            reported = any(
                entry.reason is SetAsideReason.MAPPING
                and entry.subject == subject_uri
                and entry.params.get("predicate") == curie
                for entry in report.set_aside
            )
            if not reported:
                return False, subject_uri
        return True, None

    if predicate == SKOS.notation:
        for subject_node, _obj in graph.subject_objects(predicate):
            subject_uri = str(subject_node)
            if subject_uri not in in_scope or subject_uri in excluded_subjects:
                continue
            reported = any(
                entry.reason is SetAsideReason.NOTATION and entry.subject == subject_uri
                for entry in report.set_aside
            )
            if not reported:
                return False, subject_uri
        return True, None

    if predicate in (SKOS.broader, SKOS.narrower):
        for subject_node, object_node in graph.subject_objects(predicate):
            subject_uri, object_uri = str(subject_node), str(object_node)
            if subject_uri not in in_scope or subject_uri == object_uri:
                continue
            if subject_uri in excluded_subjects or object_uri in excluded_subjects:
                continue
            narrower_uri, broader_uri = (
                (subject_uri, object_uri)
                if predicate == SKOS.broader
                else (object_uri, subject_uri)
            )
            if not _coverage_relation_covered(
                ConceptRelation.Kind.BROADER, narrower_uri, broader_uri, report
            ):
                return False, subject_uri
        return True, None

    if predicate == SKOS.related:
        for subject_node, object_node in graph.subject_objects(predicate):
            subject_uri, object_uri = str(subject_node), str(object_node)
            if subject_uri not in in_scope or subject_uri == object_uri:
                continue
            if subject_uri in excluded_subjects or object_uri in excluded_subjects:
                continue
            covered = _coverage_relation_covered(
                ConceptRelation.Kind.RELATED, subject_uri, object_uri, report
            ) or _coverage_relation_covered(
                ConceptRelation.Kind.RELATED, object_uri, subject_uri, report
            )
            if not covered:
                return False, subject_uri
        return True, None

    if predicate in (SKOS.inScheme, SKOS.topConceptOf):
        for subject_node, object_node in graph.subject_objects(predicate):
            concept_uri, scheme_uri = str(subject_node), str(object_node)
            if concept_uri not in in_scope:
                continue
            if not _coverage_scheme_membership_covered(
                concept_uri, scheme_uri, excluded_subjects
            ):
                return False, concept_uri
        return True, None

    if predicate == SKOS.hasTopConcept:
        for subject_node, object_node in graph.subject_objects(predicate):
            scheme_uri, concept_uri = str(subject_node), str(object_node)
            if scheme_uri not in in_scope:
                continue
            if not _coverage_scheme_membership_covered(
                concept_uri, scheme_uri, excluded_subjects
            ):
                return False, scheme_uri
        return True, None

    if predicate == SKOS.member:
        for subject_node, object_node in graph.subject_objects(predicate):
            collection_uri, concept_uri = str(subject_node), str(object_node)
            if collection_uri not in in_scope or collection_uri in excluded_subjects:
                continue
            if not _coverage_membership_covered(collection_uri, concept_uri, report):
                return False, collection_uri
        return True, None

    if predicate == SKOS.memberList:
        for subject_node, list_head in graph.subject_objects(predicate):
            collection_uri = str(subject_node)
            if collection_uri not in in_scope or collection_uri in excluded_subjects:
                continue
            for item in graph.items(list_head):
                if not _coverage_membership_covered(collection_uri, str(item), report):
                    return False, collection_uri
        return True, None

    # A SKOS predicate with no independent verification logic is uncovered, not skipped,
    # so a predicate the corpus grows to carry cannot pass merely because production
    # classifies it as handled.
    return False, str(predicate)


class TestEverySkosPredicateIsReadOrReported:
    @pytest.mark.parametrize("filename,fmt", _PREDICATE_COVERAGE_FIXTURES)
    def test_every_skos_predicate_in_this_fixture_is_read_or_reported(
        self, db, filename, fmt
    ):
        path = FIXTURES / filename
        graph = rdflib.Graph()
        graph.parse(path, format=fmt)

        report = import_skos(path)
        assert report.fatal == [], (
            f"{filename} unexpectedly failed to import: {[f.render() for f in report.fatal]}"
        )

        concept_nodes = set(graph.subjects(rdflib.RDF.type, SKOS.Concept))
        collection_nodes = set(graph.subjects(rdflib.RDF.type, SKOS.Collection)) | set(
            graph.subjects(rdflib.RDF.type, SKOS.OrderedCollection)
        )
        scheme_nodes = set(graph.subjects(rdflib.RDF.type, SKOS.ConceptScheme))
        # Only the resolved scheme is in scope: a merely-referenced second scheme
        # (mixed_scheme_membership.ttl's "other") is never a record this importer
        # creates.
        resolved_scheme_uris = set(
            ConceptScheme.objects.filter(
                static_uri__in=[str(node) for node in scheme_nodes]
            ).values_list("static_uri", flat=True)
        )
        in_scope = (
            {str(node) for node in concept_nodes}
            | {str(node) for node in collection_nodes}
            | resolved_scheme_uris
        )

        excluded_subjects = {
            entry.subject
            for entry in report.set_aside
            if entry.reason in _COVERAGE_WHOLE_RECORD_EXCLUDED_REASONS
        }
        predicates = {
            predicate
            for predicate in graph.predicates()
            if str(predicate).startswith(str(SKOS))
        }

        failures = []
        for predicate in predicates:
            covered, failing_subject = _coverage_predicate_covered(
                predicate, graph, in_scope, excluded_subjects, report
            )
            if not covered:
                failures.append((str(predicate), failing_subject))
        assert not failures, (
            f"{filename}: SKOS predicate(s) neither reflected in a record nor named in the report: {failures}"
        )


class TestExchangePackage:
    def test_package_is_importable(self):
        assert exchange is not None

    def test_package_has_a_module_docstring(self):
        assert exchange.__doc__, (
            "controlled_vocabularies.exchange has no module docstring"
        )


class TestSafetyExceptionsAreExportedAndPartOfTheDocumentedHierarchy:
    def test_unsaferdfxmlerror_is_a_skosimporterror(self):
        assert issubclass(UnsafeRdfXmlError, SkosImportError)

    def test_unsafejsonlderror_is_a_skosimporterror(self):
        assert issubclass(UnsafeJsonLdError, SkosImportError)

    def test_both_are_exported_from_the_exchange_package(self):
        assert exchange.UnsafeRdfXmlError is UnsafeRdfXmlError
        assert exchange.UnsafeJsonLdError is UnsafeJsonLdError
        assert "UnsafeRdfXmlError" in exchange.__all__
        assert "UnsafeJsonLdError" in exchange.__all__

    def test_a_consumer_catching_only_the_documented_pair_still_catches_a_hostile_rdf_xml_file(
        self, db
    ):
        # Code written against only the two documented exception types must not let a
        # hostile file through as an unhandled exception.
        try:
            import_skos(SECURITY_FIXTURES / "entity_bomb.rdf", serialization="xml")
        except (SkosImportError, SkosImportFailed):
            caught = True
        else:
            caught = False
        assert caught, (
            "a hostile RDF/XML file escaped the documented (SkosImportError, SkosImportFailed) pair"
        )

    def test_a_consumer_catching_only_the_documented_pair_still_catches_a_hostile_json_ld_file(
        self, db
    ):
        try:
            import_skos(SECURITY_FIXTURES / "exfil_via_import.jsonld")
        except (SkosImportError, SkosImportFailed):
            caught = True
        else:
            caught = False
        assert caught, (
            "a hostile JSON-LD file escaped the documented (SkosImportError, SkosImportFailed) pair"
        )


def _write_deeply_nested_jsonld(tmp_path: Path, depth: int) -> Path:
    """Write a JSON-LD document nesting one object inside another ``depth`` times.

    Built as raw text because ``json.dump`` hits Python's recursion limit before the file is
    written, at a depth well below what reproduces the parser's own recursion failure.

    Args:
        tmp_path: Directory to write the file into.
        depth: How many objects to nest.

    Returns:
        The path of the written file.
    """
    open_frag = '{"@id":"http://example.org/deep/","nested":'
    close_frag = "}"
    parts = [open_frag] * depth
    parts.append('{"val":0}')
    parts.extend([close_frag] * depth)
    path = tmp_path / "deep.jsonld"
    path.write_text("".join(parts))
    return path


class TestCraftedFilesStayInsideTheExceptionContract:
    def test_a_turtle_file_renamed_to_rdf_raises_skosimporterror_not_a_bare_sax_exception(
        self, tmp_path
    ):
        # Not well-formed XML at all, so this is scan_rdf_xml's own parser rejecting
        # malformed input, not the entity or external-reference guards.
        bad = tmp_path / "not_actually_xml.rdf"
        bad.write_text("@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n")
        with pytest.raises(SkosImportError) as excinfo:
            SkosGraph.from_file(bad)
        err = excinfo.value
        assert err.code == "skos_parse_failed"
        assert err.__cause__ is not None, (
            "the underlying SAX exception must be chained for developer diagnostics"
        )

    def test_a_deeply_nested_json_ld_document_raises_skosimporterror_not_a_bare_recursionerror(
        self, tmp_path
    ):
        path = _write_deeply_nested_jsonld(tmp_path, 3000)
        with pytest.raises(SkosImportError) as excinfo:
            SkosGraph.from_file(path, serialization="json-ld")
        err = excinfo.value
        assert err.code == "skos_parse_failed"
        assert err.__cause__ is not None, (
            "the underlying RecursionError must be chained for developer diagnostics"
        )

    def test_an_unsafe_rdf_xml_document_still_raises_unsaferdfxmlerror_not_wrapped(
        self,
    ):
        # The wrapping for malformed XML must not swallow the deliberate safety refusal
        # into a generic SkosImportError: a caller distinguishing "unsafe" from
        # "unreadable" needs the specific type.
        with pytest.raises(UnsafeRdfXmlError):
            SkosGraph.from_file(
                SECURITY_FIXTURES / "entity_bomb.rdf", serialization="xml"
            )

    def test_an_unsafe_json_ld_document_still_raises_unsafejsonlderror_not_wrapped(
        self,
    ):
        with pytest.raises(UnsafeJsonLdError):
            SkosGraph.from_file(
                SECURITY_FIXTURES / "remote_context_string.jsonld",
                serialization="json-ld",
            )

    @pytest.mark.django_db
    def test_a_cyclic_memberlist_raises_skosimporterror_not_a_bare_valueerror(self):
        with pytest.raises(SkosImportError) as excinfo:
            import_skos(FIXTURES / "cyclic_member_list.ttl")
        err = excinfo.value
        assert err.code == "skos_cyclic_member_list"
        assert err.__cause__ is not None, (
            "the underlying ValueError must be chained for developer diagnostics"
        )

    @pytest.mark.django_db
    def test_a_cyclic_memberlist_rolls_back_the_whole_run(self):
        # The run is all-or-nothing: the scheme and concept that import cleanly before
        # the cyclic collection is reached must not survive if the run as a whole is
        # refused.
        with pytest.raises(SkosImportError):
            import_skos(FIXTURES / "cyclic_member_list.ttl")
        assert not ConceptScheme.objects.filter(
            static_uri="http://example.org/cyclic/"
        ).exists()
        assert not Concept.objects.filter(
            static_uri="http://example.org/cyclic/a"
        ).exists()


class TestFailureMessagesUseOnlyNamedPlaceholders:
    def test_missing_file_message(self, tmp_path, uses_only_named_placeholders):
        with pytest.raises(SkosImportError) as excinfo:
            SkosGraph.from_file(tmp_path / "does-not-exist.ttl")
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "skos_file_not_found"

    def test_unsupported_serialization_message(self, uses_only_named_placeholders):
        with pytest.raises(SkosImportError) as excinfo:
            SkosGraph.from_file(FIXTURES / "rocks.ttl", serialization="n3")
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "skos_format_unsupported"

    def test_unparseable_file_message_and_its_developer_diagnostic_exemption(
        self, tmp_path, uses_only_named_placeholders
    ):
        bad = tmp_path / "bad.ttl"
        bad.write_text("this is not turtle @@@ not even close {{{ ]][[ ")
        with pytest.raises(SkosImportError) as excinfo:
            SkosGraph.from_file(bad)
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "skos_parse_failed"
        # Developer-diagnostic exemption: the raw rdflib parser exception is
        # chained onto __cause__, not translated — only the curator-facing
        # wrapper message just checked above is held to Article XII.
        assert err.__cause__ is not None, (
            "the underlying rdflib exception must be chained for developer diagnostics"
        )

    @pytest.mark.django_db
    def test_import_failed_message(self, uses_only_named_placeholders):
        with pytest.raises(SkosImportFailed) as excinfo:
            import_skos(FIXTURES / "blank_node_concept.ttl")
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "skos_import_failed"


class TestNoContentIsStoredInAnUnconfiguredLanguage:
    @staticmethod
    def _assert_only_configured_languages_are_stored():
        """Assert that no stored label, note or vocabulary default language is unconfigured."""
        configured = {code for code, _label in django_settings.LANGUAGES}
        stray_labels = ConceptLabel.objects.exclude(language__in=configured)
        stray_notes = ConceptNote.objects.exclude(language__in=configured)
        assert list(stray_labels) == []
        assert list(stray_notes) == []
        for scheme in ConceptScheme.objects.all():
            assert scheme.effective_default_language in configured

    @pytest.mark.parametrize(
        "filename",
        ["rocks.ttl", "variants.ttl", "en-gb-only.ttl", "declares-de-at.ttl"],
    )
    def test_no_stray_language_lands_across_every_matching_path_this_feature_touches(
        self, db, filename
    ):
        report = import_skos(FIXTURES / filename)
        assert report.fatal == []
        self._assert_only_configured_languages_are_stored()

    def test_the_invariant_holds_under_djangos_own_99_language_default(
        self, db, tmp_path
    ):
        # tests/settings.py declares its own three-language LANGUAGES, so not overriding
        # it would silently test that list rather than Django's 99-language default,
        # which the ordinary consuming project (declaring no LANGUAGES) runs on.
        path = tmp_path / "many_languages.ttl"
        path.write_text(
            """
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/manylang/> a skos:ConceptScheme ;
                skos:prefLabel "Many languages"@en .

            <http://example.org/manylang/item> a skos:Concept ;
                skos:inScheme <http://example.org/manylang/> ;
                skos:prefLabel "Item"@en-us ;
                skos:altLabel "Artikel"@de-at, "Nothing shares this base"@zzz .
            """
        )
        with override_settings(LANGUAGES=global_settings.LANGUAGES):
            report = import_skos(path)
            assert report.fatal == []
            self._assert_only_configured_languages_are_stored()
            # A tag sharing no base with any of Django's 99 shipped languages is still refused,
            # even under the largest configured set the package will ever see.
            entries = [
                entry
                for entry in report.set_aside
                if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
            ]
            assert any(entry.params["language"] == "zzz" for entry in entries)


class TestAddingABaseSharingLanguageLeavesEveryAddressWhereItWas:
    SCHEME_URI = "http://example.org/colours/"
    CONCEPT_URI = "http://example.org/colours/colour"

    @staticmethod
    def _address(obj) -> tuple[int, str | None, str, str]:
        """Return the fields that make up a record's address.

        Args:
            obj: A concept or vocabulary.

        Returns:
            Its primary key, static URI, slug and local URL.
        """
        return (obj.pk, obj.static_uri, obj.slug, obj.local_url)

    def test_adding_en_gb_to_an_en_site_moves_no_slug_and_no_local_url(self, db):
        with override_settings(LANGUAGES=[("en", "English")]):
            assert import_skos(FIXTURES / "variants.ttl").fatal == []

        # Only the address is asserted, not the name: a displayed label may follow the language
        # configuration, an address must not.
        scheme_before = self._address(
            ConceptScheme.objects.get(static_uri=self.SCHEME_URI)
        )
        concept_before = self._address(Concept.objects.get(static_uri=self.CONCEPT_URI))

        with override_settings(
            LANGUAGES=[("en", "English"), ("en-gb", "British English")]
        ):
            assert import_skos(FIXTURES / "variants.ttl").fatal == []

        assert (
            self._address(ConceptScheme.objects.get(static_uri=self.SCHEME_URI))
            == scheme_before
        )
        assert (
            self._address(Concept.objects.get(static_uri=self.CONCEPT_URI))
            == concept_before
        )

    def test_the_added_language_does_reach_the_stored_content(self, db):
        # The guard above is only meaningful if the second run genuinely changed what is stored;
        # otherwise it would pass against an import that did nothing at all.
        with override_settings(LANGUAGES=[("en", "English")]):
            import_skos(FIXTURES / "variants.ttl")
        assert (
            Concept.objects.get(static_uri=self.CONCEPT_URI)
            .labels.filter(language="en-gb")
            .count()
            == 0
        )

        with override_settings(
            LANGUAGES=[("en", "English"), ("en-gb", "British English")]
        ):
            import_skos(FIXTURES / "variants.ttl")
        assert (
            Concept.objects.get(static_uri=self.CONCEPT_URI)
            .labels.filter(language="en-gb")
            .count()
            > 0
        )
