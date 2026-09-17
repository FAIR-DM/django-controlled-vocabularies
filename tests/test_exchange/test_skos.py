"""``controlled_vocabularies.exchange.skos`` — reading a published SKOS file
into records (tasks.md Phase US-1).

Grows one task at a time, mirroring the module. T006 covers only
``_read_graph``: a file becomes an ``rdflib.Graph``, the serialization is
stated or determined, and RDF/XML is routed through the T004 safety scan
before rdflib ever sees it.
"""

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
from tests.factories import CollectionFactory, ConceptFactory, ConceptSchemeFactory

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"
SECURITY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "security"

SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
ROCKS_URI = "http://example.org/rocks/"
ROCKS_SCHEME_URI = rdflib.URIRef(ROCKS_URI)

# (filename, rdflib format) for the base vocabulary in its three serializations.
BASE_SERIALIZATIONS = [
    ("rocks.ttl", "turtle"),
    ("rocks.rdf", "xml"),
    ("rocks.jsonld", "json-ld"),
]

# Every fixture in the directory, whatever its purpose, must at least parse as
# RDF (fatal-path fixtures are semantically invalid for import, never
# syntactically invalid RDF — that distinction is exactly what makes them
# useful fatal-path material rather than parser-crash material). Discovered by
# walking the directory rather than listed by hand, so a fixture added by a
# later story is covered without anyone remembering to register it.
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
        # A real vocabulary under an extension guess_format does not recognise,
        # and no explicit format given: FR-002's "cannot be determined" half.
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with pytest.raises(SkosImportError):
            SkosGraph.from_file(mystery)

    def test_serialization_not_among_the_three_supported_fails_even_if_named_explicitly(
        self,
    ):
        # "n3" is a real rdflib format, but not one of FR-002's three — stating
        # it explicitly must not smuggle it past the supported-formats gate.
        with pytest.raises(SkosImportError):
            SkosGraph.from_file(FIXTURES / "rocks.ttl", serialization="n3")

    def test_rdf_xml_is_routed_through_the_safety_scan_before_rdflib_sees_it(self):
        # Reinstates the measured entity bomb (research.md R3) as input to the
        # public reading path, not just to scan_rdf_xml() directly — proving
        # the two are actually wired together, not merely both present. The
        # scan's own UnsafeRdfXmlError propagates as-is (both it and
        # SkosImportError are ValidationError subclasses; wrapping one inside
        # the other would only blur which stage actually refused the file).
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
        # FIX 1 (review, decisions.md D36) — a string @context is a location
        # rdflib's own JSON-LD parser would fetch via urlopen with no
        # allowlist. Reinstates that exact document against the public
        # reading path, the same proof-of-wiring shape used above for
        # RDF/XML: if this were not actually wired in, the failure would be
        # a connection error from the real fetch attempt, not this refusal.
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
        # FIX 14 (review, security, decisions.md D47) — the actual measured
        # defect: an inline *object* @context was waved through the old scan
        # entirely, but rdflib still resolves that object's own "@import" key
        # through urlopen. Before this fix, import_skos() on this exact file
        # succeeds and creates a scheme whose URI is
        # 'http://example.org/SECRET-FROM-LOCAL-FILE/scheme' — content merged
        # in from exfil_secret.jsonld, a file the caller never named, chosen
        # entirely by the uploaded document itself. Exercised through
        # import_skos(), the public entry point the review's own reproduction
        # used, not only _read_graph(), so the whole pipeline is proven, not
        # only the scan in isolation.
        with pytest.raises(UnsafeJsonLdError):
            import_skos(SECURITY_FIXTURES / "exfil_via_import.jsonld")
        assert not ConceptScheme.objects.filter(
            static_uri__startswith="http://example.org/SECRET-FROM-LOCAL-FILE/"
        ).exists()


#: T001, FR-003, decisions.md D10 — the same small document (an empty-relative
#: scheme, two relative concepts, one skos:broader between them) in each
#: supported serialization, so relative resolution is exercised on a subject,
#: an object, and the scheme, in every format rdflib takes a base through by a
#: different route. Written per-test under ``tmp_path`` rather than committed
#: under ``tests/fixtures/skos/`` (decisions.md D10 implementation note):
#: that directory is walked wholesale by ``TestFixtureCorpus`` and
#: ``TestEverySkosPredicateIsReadOrReported``, and a document whose every
#: identifier is relative can only ever fail the latter's plain
#: ``import_skos()`` (no ``base_uri``) with ``REFUSED_IDENTITY`` — a ``file://``
#: scheme is never in :data:`~controlled_vocabularies.conf.DEFAULT_ALLOWED_URI_SCHEMES`.
#: That is not a defect this class exists to prove or fix, so the document is
#: built in an unswept location instead of extending that pre-existing test's
#: own fixture-exclusion table.
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
    """T001, FR-003, FR-014, decisions.md D10 — an optional ``base_uri`` on
    :meth:`SkosGraph.from_file`, purely additive over #50/#51's own behaviour.

    Every existing call in this module omits ``base_uri`` and must go on
    behaving exactly as it does today — that is proven by this file's whole
    pre-existing suite passing unmodified, not by anything in this class.
    """

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
    """T002 — the predominance count a variant contest is decided over
    (research.md R2, decisions.md D4/D5): how often each published tag appears
    across the concept nodes' own ``skos:prefLabel`` values, that population
    and no other."""

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
        # CORR-003/SEC-003: rdflib preserves published case per literal, but a
        # re-cased tag is not a different language (RFC 5646/RDF 1.1) — two
        # concepts publishing "en-GB" and "en-gb" respectively must be one
        # population, not two.
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
        # Counted graph-wide, this would additionally sweep the scheme's and the
        # collection's own de-tagged skos:prefLabel — silently changing the
        # already-shipped determine_default_language rule (T002, D4/D5).
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
    """T002 — ``SkosImporter.run`` builds one ``LanguageMatcher`` per run from
    the concept nodes' predominance counts and passes it to ``SchemeResolver``
    and ``ConceptImporter`` as a constructor argument, rather than either
    building its own (research.md R2, plan.md "One winner, one computation")."""

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
    """T007 — the vocabulary itself: created, updated, matched against a named
    target, or refused when neither the file nor the caller can settle which
    one is being imported. These assert on the scheme's own bucket entry
    only — the concept walk (T009) also populates ``created``/``updated``
    for each concept, covered separately in ``TestImportConcepts``."""

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
        # T001, decisions.md D10: a fetched document's every refusal names
        # where it came from, not the temporary file it happened to be
        # written to for the parse.
        path = FIXTURES / "no_scheme_declared.ttl"
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path, base_uri="https://example.org/loose.ttl")
        finding = exc_info.value.report.fatal[0]
        assert finding.reason is FatalReason.VOCABULARY_UNDETERMINED
        assert "https://example.org/loose.ttl" in finding.render()
        assert str(path) not in finding.render()


class TestChoosingBetweenDeclaredVocabularies:
    """T007 — which vocabulary a file with more than one declared is about.

    Typing a second ``skos:ConceptScheme`` is ordinary: it is how a concept
    names a vocabulary it belongs to elsewhere, which spec Edge Cases §1
    requires be set aside rather than refused. So the file's own concepts
    decide, and only a genuine tie with no named target is refused.
    """

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
    """T008 — FR-005/decisions.md D4: the imported vocabulary's default
    language comes from the file where the file says, and only ever a
    language the site is configured for."""

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
        # ConceptScheme.save() itself refuses to change default_language once
        # concepts exist (R1's own guard — it anchors their identity). A
        # scheme matched by URI that already has concepts from an earlier
        # run must not trip that guard just because this run recomputed a
        # (possibly identical, possibly not) value from the file.
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
    """T006 — FR-007/decisions.md D9: the vocabulary's default language is
    resolved by the same base-language matching rule as everything else, so a
    vocabulary declaring itself in a variant of a configured language
    resolves to that configured language rather than falling back to the
    site's own default (the failure D9 describes)."""

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
        # The scheme itself declares no single language (two tags on its own
        # prefLabel), so determine_default_language falls back to the
        # commonest language among the concepts' own preferred labels — that
        # fallback must resolve through the matcher too, not just the
        # declared-language branch.
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
        # Regression: unchanged from #50 — a declared language with no
        # configured base at all still falls back to the site default.
        import_skos(FIXTURES / "unconfigured_language_vocabulary.ttl")
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/geology2/")
        assert scheme.effective_default_language == "en"


class TestDefaultLanguageCommonestFallbackFoldsCaseLikeThePreferredLabelTally:
    """T040 — FR-001/FR-007, decisions.md D34: ``SkosGraph.preferred_label_tag_counts`` folds
    its keys case-insensitively (``key = language.lower()``), but
    ``SchemeResolver.determine_default_language`` held a character-for-character copy of the
    same walk over the same concept nodes and the same predicate *without* the fold — so
    ``EN-GB`` and ``en-gb`` split one population's vote across two tally keys instead of
    counting as the one published tag FR-001 says they are. A vocabulary published 60%
    ``en-gb`` (mixed-case) and 40% ``fr`` therefore resolved its default language to ``fr``,
    setting aside six of its ten concepts as ``NO_PREFERRED_LABEL``. The fix is a deletion, not
    an edit (Article XV): ``determine_default_language`` calls ``preferred_label_tag_counts``
    instead of keeping its own copy.
    """

    def _write(self, tmp_path: Path) -> Path:
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
        # The vocabulary's default language resolves to "en" (the fix): every en-gb-labelled
        # concept has a preferred label in it (via the matcher's base-language match) and
        # imports. Under the bug, default_language resolved to "fr" instead, and these six
        # concepts — having no French label at all — were wrongly set aside as
        # NO_PREFERRED_LABEL. The four fr-only concepts have no English label either way, so
        # their own exclusion is correct and not asserted against here.
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
    """T009 — concepts land inside the vocabulary being imported, each
    holding its published identifier and its default-language preferred
    label; scheme membership is read via any of the three SKOS predicates;
    a concept claiming a different vocabulary is set aside, not imported."""

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
    """T007 — FR-002/FR-003: ``Concept.label`` is chosen by ``LanguageMatcher.resolve_winner``
    (T021), the same rule ``import_labels``'s own surplus report reads, rather than exact tag
    equality — so a concept whose only preferred label is a variant of the default language still
    names the concept, and an exact match is never displaced by a more predominant variant."""

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
        # "en-gb" is the predominant tag across the file (three occurrences),
        # but the target concept also carries an exact "en" match, which
        # FR-002 says always wins regardless of predominance.
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
        # T029/decisions.md D35: the slug is derived from the published
        # identifier's own last segment, not from the winning label.
        assert target.slug == "target"


class TestLabelsNotesAndNamesResolveThroughTheMatcher:
    """T008 — FR-001, call sites 3/4/5/6/7/8: ``import_labels`` and ``_import_notes`` store a
    matched value under its resolved configured language rather than comparing raw published tags,
    and ``SkosGraph.first_literal``'s ``language=`` filter — read for a vocabulary's own name and
    description and for a collection's name — resolves through the matcher too."""

    def test_an_en_only_vocabulary_imports_into_an_en_gb_configured_site(self, db):
        # SC-001: general-to-specific. rocks.ttl's own content is unmodified;
        # only the site's configured languages narrow to en-gb alone.
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
        # SC-002: specific-to-general, the direction that stored nothing before this feature.
        report = import_skos(FIXTURES / "en-gb-only.ttl")
        assert report.fatal == []
        colour = Concept.objects.get(static_uri="http://example.org/colours-gb/colour")
        assert colour.label == "Colour"
        assert colour.alt_labels("en") == ["Hue"]
        assert colour.notes("en") == ["The visible spectral quality of light."]

    def test_a_de_at_published_vocabulary_on_a_de_site_imports_its_preferred_labels_without_raising(
        self, db
    ):
        # SC-010's write half: T006 and T007 alone still stop short of this — the concept's own
        # alt label and note are also tagged de-at and must resolve through the matcher too.
        report = import_skos(FIXTURES / "declares-de-at.ttl")
        assert report.fatal == []
        rot = Concept.objects.get(static_uri="http://example.org/farben/rot")
        assert rot.label == "Rot"
        assert rot.alt_labels("de") == ["Karmesinrot"]
        assert rot.notes("de") == ["Eine der Grundfarben."]

    def test_a_tag_differing_only_in_case_is_treated_as_an_exact_match(
        self, db, tmp_path
    ):
        # SC-004.
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
        # SC-003.
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
        # Call sites 6/7: without this, first_literal's exact filter finds no "de" literal and
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
        # Call site 8.
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
    """T027 — CORR-002, FR-006/Article XI, decisions.md D34: a vocabulary's name,
    a vocabulary's description, and a collection's name are all filled by variant
    matching through ``_localized_literal`` exactly as ``Concept.label`` is — but
    unlike ``Concept.label``, none of the three reported a ``LANGUAGE_SUBSTITUTION``.
    The same one-line guard ``Concept.label``'s own write already applies."""

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
        # SC-004: no substitution when the scheme's own name is published in
        # exactly the resolved default language — declares-de-at.ttl's own
        # de-at is a variant of de, so it must not appear here.
        report = import_skos(FIXTURES / "rocks.ttl")
        scheme_uri = "http://example.org/rocks/"
        assert not any(
            entry.reason is NormalizedReason.LANGUAGE_SUBSTITUTION
            and entry.subject == scheme_uri
            for entry in report.normalized
        )


class TestLanguageSubstitutionIsReported:
    """T009 — FR-006/SC-009: every value stored under a configured language other than the tag
    it was published under is reported as a substitution, distinguishable from a value that was
    not stored at all, and never counted in ``language_account()`` — that account is for what a
    curator could recover by configuring something, and a substitution already made it in."""

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
        # SC-004: a case-only difference is an exact match, not a variant.
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
    """T011/T012 — FR-008/SC-011/SC-012/SC-013: :meth:`ImportReport.language_account`
    driven from a real import through ``import_skos``, the way a curator
    actually reaches it — not a hand-built report, which ``TestLanguageAccount``
    in ``test_report.py`` already covers at the unit level (T004). The account
    must cover every value not stored for a language reason and no value that
    was stored, and must be present and empty rather than absent after a run
    that left nothing behind, so #52 can render from it without asking which
    kind of run produced it."""

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

        # Covers every value not stored for a language reason...
        unconfigured = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.UNCONFIGURED_LANGUAGE
        ]
        assert sum(report.language_account().values()) == len(unconfigured)

        # ...and no value that was stored: the en preferred labels landed,
        # and the account carries nothing under a configured language.
        assert (
            Concept.objects.get(static_uri="http://example.org/multiling/a").label
            == "A"
        )
        assert "en" not in report.language_account()

    def test_present_and_empty_after_an_import_that_leaves_nothing_behind(self, db):
        # SC-013: rocks.ttl is #50's own established clean-run fixture
        # (TestReportPopulatedByARealRun pins report.set_aside == [] against
        # it) — reused rather than duplicated, per decisions.md D21.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.set_aside == []
        assert report.language_account() == {}


class TestConceptsImpliedByMembershipButNeverGivenAnRdfType:
    """FIX 17 (review, decisions.md D50) — ``concept_nodes`` used to come only
    from ``graph.subjects(rdf.RDF.type, SKOS.Concept)``. A node the file
    identifies as a concept through ``skos:inScheme``, ``skos:topConceptOf``,
    or the scheme's own ``skos:hasTopConcept`` — the identical three
    predicates ``scheme_refs`` already reads — but which never states
    ``rdf:type`` at all, was invisible to the whole import: not created, not
    set aside, not named anywhere in the report. A curator importing such a
    file got a green result reporting only the scheme, with no explanation
    for the missing concepts at all."""

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
        # A node the file does give an rdf:type is never overridden by this
        # widened discovery — mixed_scheme_membership.ttl's own concepts are
        # all explicitly typed, and the scheme nodes there must stay schemes,
        # not be swept up as concepts merely for appearing as an inScheme
        # object (they never do — inScheme's *subject* is the candidate, not
        # its object — but this asserts the outcome, not only the mechanism).
        import_skos(FIXTURES / "mixed_scheme_membership.ttl")
        assert not Concept.objects.filter(
            static_uri="http://example.org/minerals/"
        ).exists()
        assert ConceptScheme.objects.filter(
            static_uri="http://example.org/minerals/"
        ).exists()


class TestConceptSlugs:
    """T029 — FR-017/decisions.md D35: an imported concept's slug is the
    fragment of its published identifier where it has one, otherwise the
    last segment of its path — assigned once and never recomputed from a
    later import, even when the publisher renames the record (SC-026,
    SC-027). Supersedes D6, which derived the slug from the label: two
    concepts that happen to share a label no longer collide at all, because
    the slug no longer reads the label, and a publisher rename that used to
    move the slug (D6's own deliberate choice) now leaves it alone.
    """

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
        # The URI's own last path segment is "igneous"; the label is "Igneous
        # rock". Under D6 the slug tracked the label ("igneous-rock"); under
        # D35 it tracks the identifier instead.
        assert igneous.slug == "igneous"

    def test_a_publisher_rename_leaves_the_slug_and_local_url_unchanged(self, db):
        # SC-027 — the case D6 deliberately let move, and D35 stops moving.
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
        # duplicate_slug.ttl's two concepts share one preferred label
        # ("Quartz") but have distinct identifiers; D35 slugs from the
        # identifier, so there is no collision left for this fixture to
        # exercise (T032 covers identifiers that actually collide).
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
    """T032 — FR-020/SC-029: two concepts whose identifiers end in the same segment (e.g.
    ``.../a/clay`` and ``.../b/clay``) both import with distinct slugs, and each keeps the slug it
    had regardless of the order the file declares them in. ``import_concepts`` already processes
    ``concept_nodes`` in a stable order sorted on the full identifier string (never the order a file
    happens to declare them in), and ``assign_unique_slug``'s ``taken_slugs`` (FIX 16, D49) reads
    each concept's own previously-stored slug back before minting a suffix — so once T029 changed the
    base derivation to the identifier, the existing collision machinery already resolves this the
    way FR-020 requires, with no separate order-tracking rule needed.
    """

    def _write(self, tmp_path: Path, name: str, first: str, second: str) -> Path:
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
    """T030 — FR-018/decisions.md D35: a vocabulary's own slug is the fragment of its published
    identifier where it has one, otherwise the last segment of its path — assigned once and never
    recomputed, exactly like a concept's (T029). Before this task ``ConceptScheme.save()`` re-derived
    the slug from ``name`` on every save with no manual mechanism at all, so a vocabulary's name
    arriving in a different language moved the address of every record it holds (SC-028) — the exact
    case D35 measured: ``scheme.slug`` going from ``colours`` to ``colors`` with ``static_uri``
    unchanged throughout.
    """

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
        # The URI's own last path segment is "rocks"; the name is "Rock types",
        # which would slugify to "rock-types" under the superseded rule (D6).
        assert scheme.slug == "rocks"


class TestConceptSchemeSlugCollisionIsIdentifierDerived:
    """T035 — FR-018/FR-020/SC-028/SC-029, decisions.md D35: two vocabularies whose published
    identifiers end in the same segment (``.../a/colours``, ``.../b/colours``) are ordinary in
    SKOS, and T030's identifier-derived scheme slug (:meth:`SchemeResolver.resolve_scheme`) made
    that an uncaught ``ValidationError`` out of ``ConceptScheme.save()`` — a regression against
    cd4f1c6, where the slug came from each scheme's own distinct name. Resolved exactly the way
    ``ConceptImporter.assign_unique_slug`` already resolves a concept collision: the same
    identifier-derived base, a numeric suffix minted only when the candidate already belongs to a
    *different* scheme (matched on ``static_uri``, so a scheme reads its own prior slug back to
    itself and a re-import is stable). ``ConceptScheme.save()`` itself keeps refusing rather than
    auto-suffixing (research R4) — the importer resolves its own collisions, as it already does
    for concepts.
    """

    def _write(self, tmp_path: Path, name: str, uri: str, label: str) -> Path:
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
    """T041 — FR-020, decisions.md D35 (fix cycle 3): a record's slug is minted through
    ``unique_slug_for_identifier`` only when the record does not already have one; a record
    that does gets its stored slug read back and left alone. Before this, ``assign_unique_slug``
    and ``resolve_scheme`` recomputed *every* record's slug on *every* import from whatever else
    currently occupies the scheme/table — so a record's public address could move for a reason
    that had nothing to do with its own identifier, whenever something else vacated (or newly
    claimed) the base slug it was minted against. FR-020 requires the opposite: the same file
    yields the same slugs on every import, "however it is traversed" — reworded here to "however
    many times it is imported."
    """

    def test_a_vocabulary_keeps_its_suffixed_slug_after_a_colliding_sibling_is_deleted(
        self, db, tmp_path
    ):
        # (a) — two vocabularies whose identifiers both end in "#terms" import as "terms" and
        # "terms-2"; deleting the first and re-importing the second's UNCHANGED file must not
        # move the second's address onto the now-vacant "terms".
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
        # The same defect at concept granularity: an external concept collides on its base slug
        # with a *locally authored* concept already occupying it (static_uri=None), gets
        # suffixed on its first import, and must keep that suffix once the local record is
        # deleted and the same file is re-imported unchanged.
        path = tmp_path / "v4.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://v4.example/v4> a skos:ConceptScheme ; skos:prefLabel "V4"@en .\n'
            "<http://v4.example/v4/one> a skos:Concept ; skos:inScheme <http://v4.example/v4> ; "
            'skos:prefLabel "One"@en .\n'
        )
        import_skos(path)
        scheme = ConceptScheme.objects.get(static_uri="http://v4.example/v4")
        local_apple = Concept.objects.create(scheme=scheme, label="Apple")
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
        # CORR-301 — the same (a) shape at collection granularity, the third record kind: two
        # collections in one vocabulary whose identifiers both end in "#colours" import as
        # "colours" and "colours-2"; deleting the first and re-importing a file describing only
        # the second, UNCHANGED, must not move the second's address onto the now-vacant
        # "colours". Would fail (moving b to "colours") if CollectionImporter's own `if
        # created:` guard around minting were removed or never existed.
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
        # (c) — a locally authored scheme "Rocks" (slug "rocks", static_uri NULL) holding a
        # locally authored concept "Granite" (slug "granite") and a locally authored collection
        # "Igneous" (slug "igneous"), all static_uri NULL. Importing a file naming those exact
        # composed local URIs must match all three existing rows via get_by_uri's local-parse
        # fallback, not recompute a colliding slug for any of them and not create a second row
        # for any of them. CORR-302: extended with the collection (T048) to also assert that a
        # record the importer *matched* rather than created gets pinned (`slug_is_manual`) on
        # all three kinds — D46 names this as the reason `set_slug`/direct attribute assignment
        # became the write path even for a matched row — and that a subsequent local rename
        # then leaves every address exactly where it was. Would fail (an address moving after
        # its own unrelated rename) if any of the three `slug_is_manual = True` assignments on
        # the matched-row path were ever skipped.
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
    """T046 — SEC-303: ``base[: max_length - len(suffix_text)]`` goes negative once a collision
    suffix is as long as (or longer than) ``max_length``, and Python silently slices from the
    *end* of the string instead of raising — at ``max_length == len(suffix_text)`` the slice
    bound is exactly ``0``, and the returned candidate is the bare suffix, with no relationship
    to the base at all. Unreachable from the three current call sites (all pass 255), fixed by
    construction anyway with ``max(max_length - len(suffix_text), 1)``, which always keeps at
    least one character of the base.
    """

    def test_a_collision_suffix_as_long_as_max_length_does_not_discard_the_base(self):
        """Reproduces SEC-303's own evidence: with max_length=2, the base 'ab' collides, and the
        retry appends suffix '-2' (also length 2). The unfixed slice, base[:2 - 2] + '-2', is
        base[:0] + '-2' == '-2' — the base is gone entirely, and the result is indistinguishable
        from another record's own base 'b-2'. Would fail (return '-2') without the fix.
        """
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert result != "-2"
        assert result.startswith("a")

    def test_a_collision_suffix_longer_than_max_length_still_fits_within_max_length(
        self,
    ):
        """SEC-405, decisions.md D63 (fix cycle 5): the docstring's own contract is "the returned
        candidate never exceeds max_length however many collisions it resolves" — true only once
        the fix below clamps the whole candidate, not only the base. Before it, ``max_length=2``
        with a two-character suffix returned ``'a-2'`` (length 3): ``base[: max(2 - 2, 1)]`` keeps
        one base character, but nothing then trims the assembled ``base + suffix`` back down.
        """
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert len(result) <= 2

    def test_a_normal_collision_is_unaffected_by_the_fix(self):
        """max_length comfortably larger than any suffix (the shape every real field is in,
        SlugField(max_length=255)) must keep resolving collisions exactly as before.
        """
        taken = {"granite": "other"}
        result = unique_slug_for_identifier("http://e.org/#granite", taken, 255)
        assert result == "granite-2"


class TestUniqueSlugForIdentifierGivesUpRatherThanLoopingForever:
    """T056 — CORR-503, decisions.md D66 (fix cycle 6): SEC-405's assembled-candidate clamp (D63)
    can make two *different* suffixes render as the identical truncated candidate once
    ``max_length`` is small relative to the suffix text. Reproduced exactly as the round-5 review
    reported it: with ``max_length=2``, the first retry's candidate ``'a-2'`` clamps to ``'a-'``,
    and every retry after it clamps to the same ``'a-'`` regardless of how large the suffix grows
    — a candidate that already belongs to another record (``'a-'`` taken by ``'other2'``) then
    loops without ever producing a different one. Confirmed hanging (60s+ with no return) before
    this fix, on a call this module-level helper's own docstring exposes to any direct caller —
    not reachable through ``import_skos`` today, since all three call sites pass
    ``SlugField(max_length=255)``.
    """

    def test_a_collision_that_always_clamps_to_the_same_candidate_gives_up_rather_than_hanging(
        self,
    ):
        """T061 — CORR-604 (round 6, low): asserting on the return value alone means a
        regression of the give-up itself hangs this call forever rather than failing — pytest
        never reaches the assertion below, and CI cannot tell the difference between that and a
        stuck runner. No ``pytest-timeout`` dependency is added for one test; the call runs in a
        daemon worker thread with a bounded ``join()`` instead, which is the same "fail within
        seconds, not never" property using only the standard library. Five seconds is generous
        for a call that, when it does not hang, returns in microseconds.
        """
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
        """The existing SEC-303/SEC-405 fixtures resolve on their very first retry (``'a-'`` is
        not taken in either), so the give-up path must never fire for them.
        """
        result = unique_slug_for_identifier(
            "http://e.org/#ab", {"ab": "other", "b-2": "other2"}, 2
        )
        assert result == "a-"

    def test_a_normal_collision_chain_is_unaffected(self):
        taken = {"granite": "other", "granite-2": "other2"}
        result = unique_slug_for_identifier("http://e.org/#granite", taken, 255)
        assert result == "granite-3"


class TestUniqueSlugForIdentifierResolvesACollisionEvenWhenTheBaseIsAlreadyMaxLength:
    """T060 — CORR-601/SEC-604 (round 6, high): D66's give-up (T056, fix cycle 6) seeds ``tried``
    with ``base`` itself before the loop has generated any candidate. Whenever ``len(base) ==
    max_length`` and ``base`` ends in ``-2``, the clamp (D63) makes the *first* retry's candidate
    reproduce ``base`` exactly — ``base[:253] + "-2" == base`` at ``max_length=255`` — so the
    give-up fires on the very first retry and abandons a collision the next suffix (``-3``)
    resolves trivially. Reproduced exactly as the round-6 review reported it: two concepts whose
    identifier fragments both slugify (then truncate to 255 characters) to the identical string
    ``"a" * 253 + "-2"``.
    """

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
        """The two fragments the round-6 review reproduced this with — both slugify (and
        truncate) to the identical 255-character base, so this exercises the give-up through the
        public ``import_skos``, not only the module-level helper directly.
        """
        fragment_a = "a" * 253 + "-2" + "xx"
        fragment_b = "a" * 253 + "-2" + "yy"
        path = tmp_path / "t060_collision.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/t060scheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f"<http://pub.example/t060scheme#{fragment_a}> a skos:Concept ; "
            'skos:inScheme <http://pub.example/t060scheme> ; skos:prefLabel "Concept A"@en .\n'
            f"<http://pub.example/t060scheme#{fragment_b}> a skos:Concept ; "
            'skos:inScheme <http://pub.example/t060scheme> ; skos:prefLabel "Concept B"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        assert report.set_aside == []
        concepts = Concept.objects.filter(
            scheme__static_uri="http://pub.example/t060scheme"
        )
        assert concepts.count() == 2
        slugs = set(concepts.values_list("slug", flat=True))
        assert len(slugs) == 2


class TestAGiveUpSlugIsReportedNotWrittenOrMislabeled:
    """T060 — SEC-604 (round 6, low): D66's give-up return (``""``) is checked at
    ``SchemeResolver.resolve_scheme``'s own call site (``VOCABULARY_SLUG_UNUSABLE``), but not at
    ``ConceptImporter.assign_unique_slug`` or ``CollectionImporter.import_collections`` — an
    empty slug from either reached ``save()`` unchecked and was caught only by the model's own
    manual-slug validation, reported as ``STORED_SLUG_INVALID`` — a reason whose own message says
    a *stored* slug fails validation, which is false for a record whose slug was never written at
    all. ``unique_slug_for_identifier`` is monkeypatched to always give up, the shape a
    to-date-unreachable collision (D51/D63: ~10^250 prior collisions at ``max_length=255``) would
    produce, without needing to actually construct one.
    """

    def test_a_concept_s_give_up_slug_is_empty_slug_not_stored_slug_invalid(
        self, db, tmp_path, monkeypatch
    ):
        """The scheme itself is pre-created (matched, not created) so the patched give-up is
        exercised only through the concept's own call site — a *created* scheme would hit
        ``resolve_scheme``'s own already-guarded call first and refuse the whole run instead.
        """
        ConceptSchemeFactory(name="Vocab", static_uri="http://pub.example/sec604scheme")
        path = tmp_path / "sec604_concept.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec604scheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec604scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec604scheme> ; skos:prefLabel "One"@en .\n'
        )
        monkeypatch.setattr(
            exchange.skos, "unique_slug_for_identifier", lambda *args, **kwargs: ""
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Concept.objects.filter(
            static_uri="http://pub.example/sec604scheme#c1"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/sec604scheme#c1"
        stored_slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert stored_slug_entries == []

    def test_a_collection_s_give_up_slug_is_empty_slug_not_stored_slug_invalid(
        self, db, tmp_path, monkeypatch
    ):
        """Same pre-creation reasoning as the concept test above."""
        ConceptSchemeFactory(
            name="Vocab", static_uri="http://pub.example/sec604collscheme"
        )
        path = tmp_path / "sec604_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec604collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec604collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec604collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/sec604collscheme#grp> a skos:Collection ; "
            'skos:prefLabel "Group"@en .\n'
        )
        monkeypatch.setattr(
            exchange.skos, "unique_slug_for_identifier", lambda *args, **kwargs: ""
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/sec604collscheme#grp"
        ).exists()
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        ]
        assert any(
            entry.subject == "http://pub.example/sec604collscheme#grp"
            for entry in entries
        )
        stored_slug_entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert stored_slug_entries == []


class TestSlugAndNameLengthAreBoundedToTheField:
    """T042 — SEC-002-shaped, decisions.md D35 (fix cycle 3): a published identifier segment or
    name can be far longer than the field meant to hold it. Nothing on this write path calls
    ``full_clean()``, so an over-long value lands unchecked on SQLite and raises a bare
    ``DataError`` on PostgreSQL, aborting the whole run — the same failure shape SEC-002 already
    guards for a label. ``unique_slug_for_identifier`` now truncates its derived base to the
    field's own ``max_length`` (never a literal ``255`` written a second time) rather than
    minting a slug the model would refuse; ``ConceptScheme.name`` and ``Collection.name`` get the
    same pre-write ``VALUE_TOO_LONG`` set-aside guard ``Concept.label`` already has.
    """

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
        """T044, decisions.md D49 (fix cycle 4, ARCH-301/CORR-303/SEC-302): a *created* scheme
        has no earlier name to fall back to, so an unusable one is fatal rather than stored
        blank. Overturns the previous version of this test, which asserted
        ``report.fatal == []`` and only checked ``len(scheme.name) <= max_length`` — a blank
        name (the actual defect this cycle fixes) satisfies that length check too, so the old
        assertion could not have caught it.
        """
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
        """The matched-row half of T044: a scheme that already has a name keeps it when a
        re-import's name is unusable, set aside rather than fatal. Would fail if the new
        created-only fatal branch fired for a matched row too.
        """
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
        """T044, decisions.md D49 (fix cycle 4, ARCH-301/CORR-303/SEC-302): a *created*
        collection has no earlier name to fall back to either — but unlike a scheme, the rest of
        the file does not need this collection in order to import, so the whole record is set
        aside (never created) rather than failing the run. Overturns the previous version of
        this test, which only checked ``len(collection.name) <= max_length`` — a blank name (the
        actual defect) satisfies that too.
        """
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
        """The matched-row half of T044 for a collection: an already-imported collection keeps
        its stored name, and the collection itself is not removed, when a re-import's name is
        unusable. Would fail if the created-only ``continue`` fired for a matched row too.
        """
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
    """A Turtle file with ``n`` concepts sharing one ``skos:prefLabel`` — D6's
    "two source concepts commonly sharing a preferred label" case, scaled up
    to make a quadratic query cost in ``_assign_unique_slug`` measurable
    (FIX 16, decisions.md D49). Written to a real file, not built as an
    in-memory graph, because ``import_skos`` reads from a path."""
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
    """T047 — CORR-305, decisions.md D52 (fix cycle 4): when a scheme's or collection's own
    default-language ``skos:prefLabel`` is absent, the over-long name comes from the
    any-language fallback (``SkosGraph.first_literal``) — the ``VALUE_TOO_LONG`` set-aside must
    name the language that value was actually published in, not the target language the
    fallback exists because nothing resolved to it.
    """

    def test_a_matched_scheme_s_over_long_fallback_name_reports_its_own_language_not_the_default(
        self, db, tmp_path
    ):
        """The scheme's effective default language is frozen at 'en' (a matched row, D46/D50 —
        resolve_scheme never assigns default_language to a matched row). Its own prefLabel is
        published only in 'fr', so the VALUE_TOO_LONG set-aside must say 'fr'. Would fail
        (reporting 'en') if winning_tag stayed at its pre-fallback default.
        """
        scheme = ConceptSchemeFactory(
            name="Existing", static_uri="http://pub.example/corr305scheme"
        )
        long_name = "N" * 300
        path = tmp_path / "corr305_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/corr305scheme> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@fr .\n'
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
        """The same shape one record kind over: an existing collection's own scheme has effective
        default language 'en', the collection's re-published name is 'fr'-only and over-long.
        Would fail (reporting 'en') without the fix.
        """
        scheme = ConceptSchemeFactory(
            name="Vocab", static_uri="http://pub.example/corr305collscheme"
        )
        collection = CollectionFactory(
            scheme=scheme,
            name="Existing Group",
            static_uri="http://pub.example/corr305collscheme#grp",
        )
        long_name = "N" * 300
        path = tmp_path / "corr305_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr305collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/corr305collscheme#grp> a skos:Collection ; skos:prefLabel "{long_name}"@fr .\n'
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
    """T051 — SEC-401, decisions.md D56: T047's any-language fallback
    (``SkosGraph.first_literal_with_language``) selected the lexicographically first literal
    regardless of length, so a single over-long ``skos:prefLabel`` in one language could refuse
    an entire first import even though the same file also published a perfectly storable name in
    another language. The fallback now selects the first *storable* literal; only when nothing
    published fits the field does the vocabulary become fatal (a scheme) or the whole collection
    get set aside (a collection).
    """

    def test_a_created_scheme_with_one_over_long_and_one_storable_name_imports_using_the_storable_one(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "sec401_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f"<http://pub.example/sec401scheme> a skos:ConceptScheme ; "
            f'skos:prefLabel "{long_name}"@de, "Zebra Vocabulary"@fr .\n'
            "<http://pub.example/sec401scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec401scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/sec401scheme")
        assert scheme.name == "Zebra Vocabulary"
        assert Concept.objects.filter(
            static_uri="http://pub.example/sec401scheme#c1"
        ).exists()

    def test_a_created_collection_with_one_over_long_and_one_storable_name_imports_using_the_storable_one(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "sec401_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec401collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec401collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec401collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/sec401collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@de, "Zebra Group"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/sec401collscheme#grp"
        )
        assert collection.name == "Zebra Group"


class TestADroppedCollectionIsDistinguishableFromAMatchedOneThatKeptItsName:
    """T054 — CORR-404, decisions.md D60 (fix cycle 5): a created collection whose name is
    unusable is dropped whole (``continue``, no row ever written); a matched collection whose
    re-published name is unusable keeps its stored one and stays exactly as it was. Both reported
    only ``VALUE_TOO_LONG``, whose message ("it was not stored") describes a field-level omission
    on a record that exists — the two outcomes were distinguishable only by querying the database
    the report exists to describe. A created collection now also gets ``COLLECTION_NOT_CREATED``,
    naming the record-level outcome.
    """

    def test_a_created_collection_dropped_for_an_unusable_name_also_gets_its_own_record_level_reason(
        self, db, tmp_path
    ):
        long_name = "N" * 300
        path = tmp_path / "corr404_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr404collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/corr404collscheme#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/corr404collscheme#grp"
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
        assert not_created[0].subject == "http://pub.example/corr404collscheme#grp"

    def test_a_matched_collection_kept_name_reports_only_value_too_long_not_not_created(
        self, db, tmp_path
    ):
        scheme = ConceptSchemeFactory(
            name="Vocab", static_uri="http://pub.example/corr404collscheme2"
        )
        collection = CollectionFactory(
            scheme=scheme,
            name="Existing Group",
            static_uri="http://pub.example/corr404collscheme2#grp",
        )
        long_name = "N" * 300
        path = tmp_path / "corr404_collection_matched.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr404collscheme2> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            f'<http://pub.example/corr404collscheme2#grp> a skos:Collection ; skos:prefLabel "{long_name}"@en .\n'
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
    """T054 — CORR-402, decisions.md D56 (fix cycle 5): T051 only fixed the any-language
    fallback branch (nothing published in the effective default language at all). When the
    default-language ``skos:prefLabel`` exists but is itself over-long, ``resolve_scheme`` and
    ``import_collections`` never ran that fallback — ``name_match`` was not ``None`` — so a
    created record was fatal (a scheme) or dropped whole (a collection) even when another
    configured language published a storable name in the same file.
    """

    def test_a_created_scheme_whose_default_language_name_is_over_long_falls_back_to_another_language(
        self, db, tmp_path
    ):
        long_name = "A" * 300
        path = tmp_path / "corr402_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f'<http://pub.example/corr402scheme> a skos:ConceptScheme ; skos:prefLabel "{long_name}"@en, "Roches"@fr .\n'
            "<http://pub.example/corr402scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/corr402scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(
            static_uri="http://pub.example/corr402scheme"
        )
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
        path = tmp_path / "corr402_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr402collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/corr402collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/corr402collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/corr402collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@en, "Roches"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/corr402collscheme#grp"
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
    """T054 — SEC-404, decisions.md D56 (fix cycle 5): D49/T044 closed the blank-name shape only
    for the over-long trigger. A created scheme or collection with no ``skos:prefLabel`` at all
    never enters that guard — ``name`` stays ``None`` all the way through, the ``elif name:``
    assignment is skipped for falsiness, and the row would otherwise persist with the field
    default ``''``, which fails its own ``full_clean()`` forever after — the exact state D49
    already declares impossible for a created record, reached by a different route.
    """

    def test_a_created_scheme_with_no_preflabel_at_all_is_fatal_not_persisted_blank(
        self, db, tmp_path
    ):
        """T058, CORR-504, decisions.md D68 (fix cycle 6): overturns the reason this test
        asserted since fix cycle 5 (D59) — ``VOCABULARY_NAME_UNUSABLE``, whose template says the
        published name is "longer than this application can store." Nothing is published here at
        all, so that message is false on this trigger; a dedicated
        ``VOCABULARY_NAME_UNPUBLISHED`` names what actually happened. The type-only assertion
        this test previously made could not have caught the message being wrong, so ``render()``
        is now asserted too.

        T061, SEC-603/CORR-603, decisions.md D71 (fix cycle 7): overturns this test's own
        substring assertion in turn. T055's ``str(literal).strip()`` filter (this same cycle 6,
        after this test was written) routes a *whitespace-only* published vocabulary name into
        this identical fatal, and the message's claim that "no skos:prefLabel was published for
        it at all" is false on that path — a triple was published, it was merely unusable. The
        template is reworded to name the actual condition ("no skos:prefLabel with a usable
        value was published ... in any language") rather than a fact about the file that does
        not always hold; the substring this test checks for is updated to match.
        """
        path = tmp_path / "sec404_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
            '<http://pub.example/sec404scheme> a skos:ConceptScheme ; dcterms:description "no name"@en .\n'
            "<http://pub.example/sec404scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec404scheme> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        message = report.fatal[0].render()
        assert "longer than" not in message
        assert "no skos:prefLabel with a usable value was published" in message
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/sec404scheme"
        ).exists()

    def test_a_created_collection_with_no_preflabel_at_all_is_set_aside_not_persisted_blank(
        self, db, tmp_path
    ):
        path = tmp_path / "sec404_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec404collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec404collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec404collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/sec404collscheme#grp> a skos:Collection ; "
            "skos:member <http://pub.example/sec404collscheme#c1> .\n"
        )
        report = import_skos(path)
        assert report.fatal == []
        assert not Collection.objects.filter(
            static_uri="http://pub.example/sec404collscheme#grp"
        ).exists()
        # CORR-404, decisions.md D60 (fix cycle 5): COLLECTION_NOT_CREATED, not a reused
        # VALUE_TOO_LONG — there is no over-long value to name for this trigger.
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.COLLECTION_NOT_CREATED
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/sec404collscheme#grp"


class TestAnEmptyPublishedLiteralIsNeverTreatedAsAUsableName:
    """T055 — SEC-501/SEC-502/CORR-501/CORR-502/SEC-504, decisions.md D65 (fix cycle 6): every
    name-selection path sorted an empty (or whitespace-only) literal ahead of a real one, because
    the only filters applied so far (``max_length`` on the fallback, nothing at all on
    ``first_literal``) admit ``""`` — it has length zero and it sorts first. Two opposite
    symptoms, one root cause:

    - A file that plainly publishes a usable name was refused outright, when the empty literal
      happened to occupy the exact slot ``_localized_literal`` or the any-language fallback would
      otherwise fill.
    - A record was created and persisted with ``name == ''`` when T054's own second-chance
      fallback treated the empty literal as "found a storable value" — the exact state D49 exists
      to prevent, reopened through the fallback it added.

    Fixed at the one place each is selected: ``SkosGraph.first_literal``,
    ``SkosGraph.first_literal_with_language`` and (by construction, since it composes
    ``first_literal``) ``_localized_literal`` now all treat a literal whose value is empty or
    whitespace-only as unusable, never a candidate.
    """

    def test_a_created_scheme_with_an_empty_and_a_usable_name_in_the_same_language_uses_the_usable_one(
        self, db, tmp_path
    ):
        """SEC-501 probe A: the empty literal and the usable one share the exact-match language
        (the site default, ``en``), so ``_localized_literal``'s own per-tag exact match is what
        must skip the empty one — the any-language fallback never runs at all for this probe.
        """
        path = tmp_path / "sec501_scheme_probe_a.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/sec501schemea> a skos:ConceptScheme ; "
            'skos:prefLabel ""@en, "Geology Vocabulary"@en .\n'
            "<http://pub.example/sec501schemea#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec501schemea> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(
            static_uri="http://pub.example/sec501schemea"
        )
        assert scheme.name == "Geology Vocabulary"

    def test_a_created_scheme_with_only_an_empty_default_language_literal_falls_back_to_another_language(
        self, db, tmp_path
    ):
        """SEC-501 probe B: the default language (``en``) carries only the empty literal, so
        ``_localized_literal`` finds no candidate at all and the any-language fallback
        (``first_literal_with_language``) is what must skip the empty one and select the
        storable ``de`` value instead.
        """
        path = tmp_path / "sec501_scheme_probe_b.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/sec501schemeb> a skos:ConceptScheme ; "
            'skos:prefLabel ""@en, "Geologie"@de .\n'
            "<http://pub.example/sec501schemeb#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec501schemeb> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(
            static_uri="http://pub.example/sec501schemeb"
        )
        assert scheme.name == "Geologie"

    def test_a_created_collection_with_an_empty_and_a_usable_name_uses_the_usable_one(
        self, db, tmp_path
    ):
        """SEC-501 probe C, collection counterpart."""
        path = tmp_path / "sec501_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec501collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec501collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec501collscheme> ; skos:prefLabel "One"@en .\n'
            "<http://pub.example/sec501collscheme#grp> a skos:Collection ; "
            'skos:prefLabel ""@en, "Igneous Rocks"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/sec501collscheme#grp"
        )
        assert collection.name == "Igneous Rocks"

    def test_a_created_scheme_s_second_chance_fallback_never_picks_the_empty_literal(
        self, db, tmp_path
    ):
        """SEC-502/CORR-501: the over-long default-language name has nowhere storable to fall
        back to except the empty ``de`` literal and the storable ``fr`` one — before the fix, the
        second-chance fallback (T054, D58) treated the empty literal as found and persisted
        ``name == ''``, exactly the state D49 declares impossible for a created record.
        """
        long_name = "A" * 300
        path = tmp_path / "sec502_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            f"<http://pub.example/sec502scheme> a skos:ConceptScheme ; "
            f'skos:prefLabel "{long_name}"@en, ""@de, "Geologie Vokabular"@fr .\n'
            "<http://pub.example/sec502scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec502scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/sec502scheme")
        assert scheme.name == "Geologie Vokabular"

    def test_a_created_collection_s_second_chance_fallback_never_picks_the_empty_literal(
        self, db, tmp_path
    ):
        """SEC-502/CORR-501, collection counterpart."""
        long_name = "A" * 300
        path = tmp_path / "sec502_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec502collscheme> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec502collscheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec502collscheme> ; skos:prefLabel "One"@en .\n'
            f"<http://pub.example/sec502collscheme#grp> a skos:Collection ; "
            f'skos:prefLabel "{long_name}"@en, ""@de, "Geologie Vokabular"@fr .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        collection = Collection.objects.get(
            static_uri="http://pub.example/sec502collscheme#grp"
        )
        assert collection.name == "Geologie Vokabular"

    def test_a_whitespace_only_literal_is_treated_the_same_as_an_empty_one(
        self, db, tmp_path
    ):
        """SEC-504: a whitespace-only literal sorts ahead of a real name exactly as an empty
        string does, and has no visible content once stored — the same emptiness test must treat
        it the same way.
        """
        path = tmp_path / "sec504_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "<http://pub.example/sec504scheme> a skos:ConceptScheme ; "
            'skos:prefLabel "   "@en, "Geology Vocabulary"@en .\n'
            "<http://pub.example/sec504scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec504scheme> ; skos:prefLabel "One"@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        scheme = ConceptScheme.objects.get(static_uri="http://pub.example/sec504scheme")
        assert scheme.name == "Geology Vocabulary"

    def test_a_node_publishing_only_an_empty_literal_is_treated_as_no_usable_name_at_all(
        self, db, tmp_path
    ):
        """The record-level outcome when *every* published literal is unusable must be unchanged:
        this is not a new way to have a name, it is the same "nothing storable" case D59 already
        makes fatal for a created scheme — reported as ``VOCABULARY_NAME_UNPUBLISHED`` (T058,
        decisions.md D68), since an empty literal is, per this same task's own fix, the same as
        nothing having been published at all.
        """
        path = tmp_path / "sec501_scheme_none_usable.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec501schemenone> a skos:ConceptScheme ; skos:prefLabel ""@en .\n'
            "<http://pub.example/sec501schemenone#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec501schemenone> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/sec501schemenone"
        ).exists()

    def test_a_whitespace_only_vocabulary_name_is_refused_with_a_message_that_stays_true(
        self, db, tmp_path
    ):
        """T061 — SEC-603 (round 6, medium): a scheme publishing only a whitespace-only
        ``skos:prefLabel`` reaches this identical fatal (T055's filter makes ``name`` arrive
        ``None``, exactly as if nothing had been published), but a triple *was* published — the
        message must not tell a curator to add one that is already in their file.
        """
        path = tmp_path / "sec603_scheme_whitespace_only.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec603schemewsonly> a skos:ConceptScheme ; skos:prefLabel "   "@en .\n'
            "<http://pub.example/sec603schemewsonly#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/sec603schemewsonly> ; skos:prefLabel "One"@en .\n'
        )
        with pytest.raises(SkosImportFailed) as exc_info:
            import_skos(path)
        report = exc_info.value.report
        assert len(report.fatal) == 1
        assert report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNPUBLISHED
        message = report.fatal[0].render()
        assert "at all" not in message
        assert "no skos:prefLabel with a usable value was published" in message
        assert not ConceptScheme.objects.filter(
            static_uri="http://pub.example/sec603schemewsonly"
        ).exists()


class TestAnEmptyPublishedLiteralIsNeverAUsableNameForAnyRecordKind:
    """T059 — SEC-601/CORR-602, decisions.md D69 (fix cycle 7): D65 (T055, fix cycle 6) filtered
    an empty-or-whitespace-only literal out of ``SkosGraph.first_literal`` and
    ``first_literal_with_language`` — the two accessors a vocabulary's and a collection's own
    name are selected through. A concept's label is selected through a third accessor,
    ``SkosGraph.preferred_label_in``, which D65 never touched, so a concept published as
    ``skos:prefLabel ""@en, "Real Name"@en`` stored ``Concept.label == ''`` and reported "Real
    Name" as a surplus preferred label discarded, not merely passed over.

    Fixed structurally rather than by copying the same inline check to a third place:
    ``SkosGraph.is_usable_literal`` is now the one predicate every literal-to-name-candidate read
    shares (``first_literal``, ``first_literal_with_language``, ``preferred_label_in`` and
    ``label_languages`` all call it), so a fourth record kind or a fifth call site inherits the
    rule by construction rather than needing its own copy minted for it.
    """

    @pytest.mark.parametrize("record_kind", ["scheme", "concept", "collection"])
    def test_an_empty_literal_never_beats_a_real_one_regardless_of_record_kind(
        self, db, tmp_path, record_kind
    ):
        """One parametrized test drives all three record kinds through the identical fixture
        shape — an empty literal published alongside a real one, in the record's own name
        predicate — so a regression in any single kind's selection path fails this one test,
        not a kind-specific test nobody thought to write.
        """
        path = tmp_path / f"t059_{record_kind}.ttl"
        if record_kind == "scheme":
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                "<http://pub.example/t059scheme> a skos:ConceptScheme ; "
                'skos:prefLabel ""@en, "Real Name"@en .\n'
                "<http://pub.example/t059scheme#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/t059scheme> ; skos:prefLabel "One"@en .\n'
            )
        elif record_kind == "concept":
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                '<http://pub.example/t059concept> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
                "<http://pub.example/t059concept#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/t059concept> ; skos:prefLabel ""@en, "Real Name"@en .\n'
            )
        else:
            path.write_text(
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                '<http://pub.example/t059collection> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
                "<http://pub.example/t059collection#c1> a skos:Concept ; "
                'skos:inScheme <http://pub.example/t059collection> ; skos:prefLabel "One"@en .\n'
                "<http://pub.example/t059collection#grp> a skos:Collection ; "
                'skos:prefLabel ""@en, "Real Name"@en .\n'
            )

        report = import_skos(path)
        assert report.fatal == []

        if record_kind == "scheme":
            stored_name = ConceptScheme.objects.get(
                static_uri="http://pub.example/t059scheme"
            ).name
        elif record_kind == "concept":
            stored_name = Concept.objects.get(
                static_uri="http://pub.example/t059concept#c1"
            ).label
        else:
            stored_name = Collection.objects.get(
                static_uri="http://pub.example/t059collection#grp"
            ).name

        assert stored_name == "Real Name"
        assert not any(
            entry.reason is SetAsideReason.SURPLUS_PREFERRED_LABEL
            for entry in report.set_aside
        )

    def test_a_whitespace_only_alternative_label_is_not_stored(self, db, tmp_path):
        """Audit finding, T059 brief: ``ConceptImporter.import_labels`` reads ``skos:altLabel``/
        ``skos:hiddenLabel`` (and a non-default-language ``skos:prefLabel``) straight off the
        graph rather than through any of the four filtered accessors — the "fifth call site" the
        structural fix exists to catch. A true empty string is already refused by
        ``ConceptLabel.text``'s own ``blank=False`` (``full_clean()`` raises before the row is
        written), but Django's blank check does not treat a whitespace-only string as blank, so
        ``"   "`` used to pass straight through and get stored as a visible-nothing alternative
        label. Routing this loop through the same ``is_usable_literal`` predicate closes it.
        """
        path = tmp_path / "t059_altlabel_whitespace.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/t059altlabel> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/t059altlabel#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/t059altlabel> ; skos:prefLabel "One"@en ; '
            'skos:altLabel "   "@en .\n'
        )
        report = import_skos(path)
        assert report.fatal == []
        concept = Concept.objects.get(static_uri="http://pub.example/t059altlabel#c1")
        assert list(concept.labels.all()) == []

    def test_an_empty_only_non_default_language_preferred_label_is_silently_absent_not_a_crash(
        self, db, tmp_path
    ):
        """Audit finding, T059 brief: before the raw ``import_labels`` loop was routed through
        ``is_usable_literal``, closing ``preferred_label_in``'s own gap alone would have made
        this scenario raise ``KeyError`` instead of importing cleanly — a concept whose *only*
        ``fr`` (a configured, non-default) preferred label is empty has no ``fr`` winner in
        ``preferred_winner_by_language`` once empty candidates are excluded from it, but the raw
        loop would still try to look one up for this literal without the same exclusion.
        """
        path = tmp_path / "t059_empty_only_variant.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/t059variantonly> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/t059variantonly#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/t059variantonly> ; skos:prefLabel "One"@en, ""@fr .\n'
        )
        with override_settings(LANGUAGES=[("en", "English"), ("fr", "French")]):
            report = import_skos(path)
        assert report.fatal == []
        concept = Concept.objects.get(
            static_uri="http://pub.example/t059variantonly#c1"
        )
        assert concept.label == "One"
        assert list(concept.labels.all()) == []


class TestAStoredSlugThatFailsValidationIsSetAsideNotEscaped:
    """T045 — SEC-301, decisions.md D50 (fix cycle 4): T041's read-back means a matched record's
    already-stored slug reaches the model's manual-slug validation unchanged. A slug written out
    of band (``.update()``, ``loaddata``, ``bulk_create``, a data migration) never runs through
    ``save()``'s own validation when it is written, so it can be malformed by the time an import
    later matches that row and calls ``set_slug()``/``save()`` again — which, before this fix,
    let ``django.core.exceptions.ValidationError`` escape ``import_skos`` entirely, outside its
    own (``SkosImportError``/``SkosImportFailed``) exception hierarchy.
    """

    def test_a_scheme_s_out_of_band_slug_failing_validation_does_not_escape_import_skos(
        self, db, tmp_path
    ):
        """T052, CORR-401/SEC-402, decisions.md D57 (fix cycle 5): overturns the version of this
        test fix cycle 4 shipped, which asserted ``report.fatal == []`` — the scheme could not be
        resolved, so nothing else in the file has a target to import into, and a run that imports
        nothing must not report ``fatal == []`` (every other ``return None, None`` in
        ``resolve_scheme`` is preceded by ``add_fatal``; this one was not). The set-aside naming
        the bad slug is unchanged; a fatal is now added alongside it.
        """
        scheme = ConceptSchemeFactory(
            name="Sec Three O One Scheme", static_uri="http://pub.example/sec301scheme"
        )
        ConceptScheme.objects.filter(pk=scheme.pk).update(slug="has spaces/and-slash")
        path = tmp_path / "sec301_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec301scheme> a skos:ConceptScheme ; skos:prefLabel "Sec Three O One Scheme"@en .\n'
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
        assert entries[0].subject == "http://pub.example/sec301scheme"
        scheme.refresh_from_db()
        assert scheme.slug == "has spaces/and-slash"

    def test_a_matched_scheme_s_unconfigured_stored_default_language_is_fatal_not_a_mislabeled_bad_slug(
        self, db, tmp_path
    ):
        """T052, CORR-401/SEC-403, decisions.md D57 (fix cycle 5): ``ConceptScheme.save()`` raises
        ``ValidationError`` for its configured-language check exactly as it does for a bad manual
        slug, and a matched row's stored ``default_language`` is never reassigned by
        ``resolve_scheme`` (D46) — so a language later dropped from ``settings.LANGUAGES`` reaches
        this path with the slug untouched and perfectly valid. The bare ``except ValidationError``
        T045 added could not tell the two apart and reported this as ``STORED_SLUG_INVALID``,
        which is false: the stored slug never changes in this scenario.
        """
        scheme = ConceptSchemeFactory(
            name="Corr Four O One Scheme",
            static_uri="http://pub.example/corr401scheme",
            default_language="de",
        )
        path = tmp_path / "corr401_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr401scheme> a skos:ConceptScheme ; skos:prefLabel "Corr Four O One Scheme"@en .\n'
            "<http://pub.example/corr401scheme#c1> a skos:Concept ; "
            'skos:inScheme <http://pub.example/corr401scheme> ; skos:prefLabel "One"@en .\n'
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
            static_uri="http://pub.example/corr401scheme#c1"
        ).exists()
        scheme.refresh_from_db()
        assert scheme.default_language == "de"

    def test_a_non_dict_validation_error_from_scheme_save_is_a_fatal_not_an_attributeerror(
        self, db, tmp_path, monkeypatch
    ):
        """T057, CORR-505/SEC-503, decisions.md D67 (fix cycle 6): ``ValidationError.message_dict``
        is a property that raises ``AttributeError`` (``getattr(self, "error_dict")``) whenever the
        exception was built from a bare message or a list rather than a field dict —
        ``ValidationError("message")`` is the ordinary form a consumer's own ``pre_save`` receiver
        or a ``ConceptScheme`` subclass override would raise, not the dict form every raise inside
        this package's own ``ConceptScheme.save()`` chain uses. The handler's own ``"slug" in
        exc.message_dict`` line therefore converted a non-dict ``ValidationError`` into an
        ``AttributeError`` escaping ``import_skos`` — precisely the guarantee this except clause
        exists to give. Reproduced by monkeypatching ``ConceptScheme.save`` directly, the same
        shape a downstream receiver produces.
        """
        ConceptSchemeFactory(
            name="Corr Five O Five Scheme",
            static_uri="http://pub.example/corr505scheme",
        )
        path = tmp_path / "corr505_scheme.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/corr505scheme> a skos:ConceptScheme ; skos:prefLabel "Corr Five O Five Scheme"@en .\n'
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
        path = tmp_path / "sec301_concept.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec301concept> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            "<http://pub.example/sec301concept#one> a skos:Concept ; skos:inScheme <http://pub.example/sec301concept> ; "
            'skos:prefLabel "One"@en .\n'
        )
        import_skos(path)
        concept = Concept.objects.get(static_uri="http://pub.example/sec301concept#one")
        Concept.objects.filter(pk=concept.pk).update(slug="has spaces/and-slash")

        report = import_skos(path)

        assert report.fatal == []
        entries = [
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.STORED_SLUG_INVALID
        ]
        assert len(entries) == 1
        assert entries[0].subject == "http://pub.example/sec301concept#one"
        concept.refresh_from_db()
        assert concept.slug == "has spaces/and-slash"

    def test_a_collection_s_out_of_band_slug_failing_validation_does_not_escape_import_skos(
        self, db, tmp_path
    ):
        path = tmp_path / "sec301_collection.ttl"
        path.write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            '<http://pub.example/sec301collection> a skos:ConceptScheme ; skos:prefLabel "Vocab"@en .\n'
            '<http://pub.example/sec301collection#grp> a skos:Collection ; skos:prefLabel "Group"@en .\n'
        )
        import_skos(path)
        collection = Collection.objects.get(
            static_uri="http://pub.example/sec301collection#grp"
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
        assert entries[0].subject == "http://pub.example/sec301collection#grp"
        collection.refresh_from_db()
        assert collection.slug == "has spaces/and-slash"


class TestSlugAssignmentQueryCountIsLinearInASharedLabelGroup:
    """FIX 16 (review, decisions.md D49) — ``_assign_unique_slug``'s
    ``while Concept.objects.filter(...).exclude(pk=...).exists()`` loop issued
    one query per suffix attempt, and the suffix counter restarted at 1 for
    every concept, so N concepts deriving the same base slug cost N(N+1)/2
    round-trips inside the one ``transaction.atomic()`` the whole run sits in
    — quadratic in the size of a shared-label group, which plan.md's own
    reading strategy rules out. D6 already establishes that two source
    concepts sharing a preferred label is the *expected* case, not a rare
    edge condition, so this is not a hypothetical: a controlled-vocabulary
    file (e.g. many concepts named "Unspecified" or "Other" across
    sub-branches) can plausibly carry a group this size.
    """

    def test_query_count_stays_bounded_as_the_shared_label_group_grows(
        self, db, tmp_path
    ):
        # A small N, chosen to keep the test itself fast, but large enough to
        # separate the two shapes clearly. Measured directly against this
        # exact fixture and settings: the *pre-fix* quadratic version (one
        # query per suffix attempt, restarting at 1 for every concept) cost
        # 1,069 queries at N=40; the *post-fix* linear version cost 250 at
        # the same N (and scaled linearly at larger N: 130/250/490/970 for
        # N=20/40/80/160 — each doubling of N roughly doubles the count,
        # never roughly quadruples it). The bound below sits well above the
        # fix's own linear cost and well below the quadratic one, so it is
        # generous headroom against an unrelated small query-count change
        # elsewhere, not a tight ceiling — while still making it impossible
        # for the quadratic shape to pass.
        n = 40
        path = _write_shared_label_file(tmp_path, n)
        with CaptureQueriesContext(connection) as ctx:
            report = import_skos(path)
        assert report.fatal == []
        assert (
            Concept.objects.filter(
                scheme__static_uri="http://example.org/sharedslug/"
            ).count()
            == n
        )
        assert len(ctx.captured_queries) < 12 * n

    def test_the_same_file_imported_twice_produces_the_same_slugs(self, db, tmp_path):
        # D6: determinism survives whatever mechanism replaces the quadratic
        # loop — the same file re-imported must derive the identical slug for
        # each concept both times, not merely *a* unique one.
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
    """A Turtle file with one root concept and ``n`` children, each stating
    ``skos:broader`` back to the root, plus ``n`` one-member collections
    (FIX 20, review, decisions.md D53) — ``n`` ``ConceptRelation`` rows all
    sharing one scheme (the shape ``_import_relations``'s own existing-row
    lookup has to scan on a re-import) and ``n`` collection URIs (the shape
    ``_import_collections``'s own absent-from-source lookup has to scan)."""
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
    """The largest number of comma-separated items inside any flat ``IN (...)``
    group in ``sql`` (FIX 20, review, decisions.md D53) — a direct,
    query-shape-level check that a query never carries a parameter list
    sized by the file's own concept count, the same "measure the actual
    mechanism" discipline :func:`_write_shared_label_file`'s own query-count
    test already applies to FIX 16. Django's debug cursor logs SQL with
    values already substituted in, not placeholders, so this counts literal
    items rather than ``%s``/``?`` markers."""
    max_size = 0
    for match in re.finditer(r"\bIN \(([^()]*)\)", sql):
        items = [item for item in match.group(1).split(",") if item.strip()]
        max_size = max(max_size, len(items))
    return max_size


class TestQueryParameterCountDoesNotScaleWithConceptCount:
    """FIX 20 (review, decisions.md D53) — ``_import_relations`` passed
    ``source_id__in=successful_ids, target_id__in=successful_ids`` (2N bind
    parameters) and ``_import_concepts``/``_import_collections`` passed
    ``static_uri__in=mentioned_uris`` (N). Django does not chunk an ``__in``
    clause itself except for Oracle's own ``max_in_list_size`` — confirmed by
    reading ``django.db.models.lookups.In`` and every backend's
    ``operations.py`` in the installed Django version, not assumed —, so
    PostgreSQL's 65,535-bind-parameter-per-statement limit is reached at
    roughly 33k concepts, inside the "tens of thousands" the spec names as
    the target. SQLite CI cannot catch the failure itself (its own parameter
    ceiling is different, and no fixture in this suite is remotely close to
    either backend's limit), so this asserts the *query shape* directly
    instead — the size of any single ``IN (...)`` clause captured by a real
    query — rather than trying to reproduce the failure at production scale.
    """

    def test_no_query_carries_an_in_clause_sized_by_the_concept_count(
        self, db, tmp_path
    ):
        # A modest N, deliberately far below any real parameter ceiling —
        # this is a query-shape assertion, not a scale reproduction. If any
        # query's IN clause grows with N at all, it is already the wrong
        # shape at N=60 just as much as at N=33,000.
        n = 60
        path = _write_file_with_a_shared_broader_parent(tmp_path, n)
        import_skos(path)  # first pass: creates the concepts and relations

        with CaptureQueriesContext(connection) as ctx:
            report = import_skos(path)  # second pass: exercises the existing-row lookup
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
    """T011 — FR-003/FR-004, decisions.md D3/D8, research.md R7: a missing or
    refused identity fails the whole run; a file with more than one such
    problem reports all of them in one run; the transaction rolls back so
    the database is exactly as it was before the run started."""

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
    """T024 — SC-023, S6 SEC-001, decisions.md D34: a vocabulary whose
    ``effective_default_language`` is not itself one of the site's configured
    languages fails the whole run with one fatal finding naming it, rather than
    silently storing nothing while emitting one ``NO_PREFERRED_LABEL`` per
    concept. ``effective_default_language`` falls back to ``settings.LANGUAGE_CODE``
    unvalidated against ``settings.LANGUAGES`` — Django's own shipped defaults are
    exactly this shape (``LANGUAGE_CODE='en-us'``, absent from the 99-code default
    ``LANGUAGES``), a configuration most consuming projects hold simply by never
    overriding either setting."""

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
        # SC-023: one problem, not one NO_PREFERRED_LABEL per concept.
        assert report.set_aside == []

    def test_djangos_own_shipped_defaults_are_refused_cleanly_not_silently_emptied(
        self, db, tmp_path
    ):
        # SEC-001's exact repro: an existing, concept-bearing scheme whose
        # default_language is frozen blank (D18) falls back to LANGUAGE_CODE,
        # and LANGUAGE_CODE='en-us' is not itself in Django's own 99-code global
        # LANGUAGES default — a configuration most consuming projects hold
        # simply by never overriding either setting.
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
    """T036 — FR-018, decisions.md D35: T030 made a vocabulary's own slug derive from its
    published identifier's own segment, exactly like a concept's (T029), but only the concept path
    (``import_concepts``' ``EMPTY_SLUG`` check) got a guard for a segment that ``slugify()``
    strips down to nothing — the scheme path did not, so ``SchemeResolver.resolve_scheme`` let
    ``ConceptScheme.save()`` raise an uncaught ``ValidationError`` instead. A regression against
    cd4f1c6, where the slug came from the vocabulary's own name and 'Symbols' slugified fine.

    Fatal rather than set-aside, deliberately: without a resolvable vocabulary there is nothing for
    the rest of the file to import into.
    """

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
        # FR-018's whole point: a local address never derives from a translated label. Falling
        # back to the name here would reinstate the exact defect FR-018 exists to remove.
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
    """T012 — FR-015: a real run's report distinguishes what was created,
    what was updated, and what was set aside with its reason, all as data a
    caller reads directly rather than parses from prose."""

    def test_a_first_import_reports_everything_as_created_nothing_as_updated(self, db):
        report = import_skos(FIXTURES / "rocks.ttl")
        expected = {
            "http://example.org/rocks/",
            "http://example.org/rocks/igneous",
            "http://example.org/rocks/granite",
            "http://example.org/rocks/basalt",
            "http://example.org/rocks/sedimentary",
            "http://example.org/rocks/quartz",
            # T027 (decisions.md D32): rocks.ttl's own two collections are
            # records with their own identity, same as a concept or the
            # vocabulary itself, so they land in this bucket too.
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
            # T027 (decisions.md D32): see the sibling test above.
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
        Concept.objects.create(
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
    """T013 — FR-004/FR-013: importing an identical file twice creates
    nothing new and recreates nothing. Every record's primary key is stable
    across both runs, and a foreign-key reference made *between* the two
    runs still resolves to the same row afterward — the acceptance scenario
    specifically distinguishes this from merely re-reading the same URI.

    (decisions.md D30) The second test's illustrative reference was
    originally made between granite and basalt, an edge rocks.ttl itself
    states and is therefore authoritative over; it has since been repointed
    at a locally created concept the file never mentions, so the test still
    proves a foreign key surviving a re-import untouched rather than a
    relationship the importer now correctly overwrites."""

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
        # The illustrative reference is deliberately made to a concept
        # created locally in granite's own scheme rather than to basalt:
        # rocks.ttl states granite's own hierarchy down to basalt, so the
        # importer has since taken ownership of that edge (decisions.md D30)
        # and would correctly overwrite, not merely leave, it. "outsider"
        # here is never mentioned by rocks.ttl at all, so it stands in for a
        # foreign key genuinely made between two runs, outside anything the
        # file speaks about.
        import_skos(FIXTURES / "rocks.ttl")
        granite = Concept.objects.get(static_uri="http://example.org/rocks/granite")
        outsider = ConceptFactory(scheme=granite.scheme, label="Local outsider")
        relation = ConceptRelation.objects.create(
            source=granite, target=outsider, kind=ConceptRelation.Kind.BROADER
        )

        import_skos(FIXTURES / "rocks.ttl")

        relation.refresh_from_db()
        assert relation.source_id == granite.pk
        assert relation.target_id == outsider.pk
        assert relation.source.static_uri == "http://example.org/rocks/granite"
        assert relation.target.static_uri == outsider.static_uri


class TestAuthoritativeUpdateForContainedRecords:
    """T014 — FR-013/decisions.md D5: for a record the file still contains, the
    file is authoritative for that record's own content. `rocks_updated.ttl`
    corrects granite's preferred label; the corrected value must land, and the
    concept must keep its identifier and database identity while it does.

    `rocks_updated.ttl` (T005) also drops granite's alternative label and its
    `related` edge to quartz, matching the spec's full Independent Test framing
    — but `import_skos()` does not read `skos:altLabel` or `skos:related` at
    all yet (that's US-3/US-4, T018-T026, explicitly out of this story's scope
    per the brief's prohibitions). Asserting their removal here is therefore not
    yet meaningful; decisions.md D20 records the scoping and why it is safe to
    defer to the stories that actually build those read paths, reusing this
    same fixture pair.
    """

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
    """T015 — FR-013: a record the file no longer mentions is left exactly as
    it is and named in the report's absent-from-source bucket. `rocks_updated.ttl`
    drops quartz entirely; a concept elsewhere already referencing it (standing in
    for "something downstream may already reference it", D5's own reasoning) must
    still resolve to it afterward."""

    def test_a_concept_dropped_from_the_file_is_untouched_and_named_absent(self, db):
        import_skos(FIXTURES / "rocks.ttl")
        quartz = Concept.objects.get(static_uri="http://example.org/rocks/quartz")
        quartz_pk, quartz_label = quartz.pk, quartz.label
        basalt = Concept.objects.get(static_uri="http://example.org/rocks/basalt")
        reference = ConceptRelation.objects.create(
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
    """T016 — FR-013: the vocabulary's own name and description update from
    the file on re-import, identifier unchanged. SKOS defines no description
    predicate for a ``skos:ConceptScheme``; decisions.md D21 records
    ``dcterms:description`` as the source, the same alias CONTEXT.md already
    establishes for a concept's own ``definition``."""

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
    """Carried from the US-1 review (decisions.md D18/D22): D18 froze an
    existing, concept-bearing scheme's ``default_language`` by silently
    skipping recomputation on every non-creating run. That protects the
    database but says nothing to the curator — a re-imported file that
    genuinely declares a different default language now gets reported."""

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
    """T017 — FR-003: a run that fails partway leaves the database exactly as
    it was, asserted against an already-populated database rather than an
    empty one, so the test fails if the transaction boundary only protected
    creation. T011 already proved this for a scheme field write and for a
    plain creation; this proves it for an *update to an already-existing
    concept*, which a creation-only rollback would let through."""

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
    """T018 — FR-008/research.md R5: preferred labels in configured languages
    other than the default, and alternative and hidden labels, are stored
    against their concept through ``Concept.add_label``, each with its own
    kind and language. The preferred label in the vocabulary's default
    language is ``Concept.label`` itself (T009) and is never also written as
    a ``ConceptLabel`` row — ``ConceptLabel.clean()`` refuses that (models.py
    ``_reject_default_language_preferred``), and this importer must not even
    attempt it."""

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
    """FIX 3 (review, decisions.md D38/D25) — ``ConceptLabel.clean()`` allows
    at most one ``PREFERRED`` row per (concept, language); D25 filters an
    unconfigured language ahead of the write for exactly this "don't rely on
    the model's own refusal as control flow" reason, but never implemented
    this — the cardinality — half of the same rule. Two ``skos:prefLabel``
    values in one non-default *configured* language reached ``add_label``
    twice, and the second raised the model's own uncaught ``ValidationError``.
    One is kept deterministically — the lexicographically first, the same
    rule ``preferred_label_in`` already uses for the default language — and
    the rest are set aside and reported."""

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
    """FIX 4 (review, decisions.md D38) — ``preferred_label_in`` already
    picks one default-language ``skos:prefLabel`` deterministically as
    ``Concept.label`` (T009); ``_import_labels`` then skips *every* PREFERRED
    literal in that language, including the ones that were not chosen —
    dropped with no report at all, the silent-normalisation Article XI
    forbids and the README's own "nothing a file contains is ever dropped in
    silence" contradicts. The surplus is now reported under the same
    ``SetAsideReason.SURPLUS_PREFERRED_LABEL`` FIX 3 uses — the same defect,
    just in the language ``Concept.label`` itself anchors rather than any
    other."""

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
    """T013 — FR-002/FR-003, call site 3: ``import_labels``'s own preferred-label contest keys on
    the *resolved* configured language rather than the raw published tag, and the winner comes from
    :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner` (T021) — the
    identical computation ``import_concepts`` already runs for ``Concept.label`` over the identical
    ``preferred_label_in`` candidates, so the two agree by construction rather than the coincidence
    ``decisions.md`` D13 named. Grouping by raw tag let two *different* tags resolving to one
    non-default configured language both reach ``add_label()`` — a raw-tag group can never see that
    contest, because each tag was its own singleton group — crashing the run on the model's own
    one-``PREFERRED``-row-per-(concept, language) constraint."""

    def _predominant_variant_contest(self, tmp_path):
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
        # SC-006's second clause.
        path = self._predominant_variant_contest(tmp_path)
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            import_skos(path)
            import_skos(path)
        target = Concept.objects.get(static_uri="http://example.org/predominant/target")
        assert target.preferred_label("de") == "Ziel-AT"

    def test_an_exact_match_in_a_non_default_language_wins_over_a_more_predominant_variant(
        self, db, tmp_path
    ):
        # SC-005, applied to call site 3's own contest rather than Concept.label's.
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
        # A predominance-driven winner that differs from both an alphabetical-value pick and an
        # alphabetical-tag pick — the case decisions.md D13 says the two computations agreed on
        # only by coincidence before both read T021's rule from one place. If import_labels's own
        # winner disagreed with Concept.label, the "loser" it names would be the very value stored.
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
    """T013 — spec Edge Cases: "A file carrying both an exact match and a variant for the same
    value, where the exact match is empty or unusable. The exact match wins the contest and then
    fails on its own merits, and the variant does not silently take its place." FR-002's exact-match
    priority (``resolve_winner``, T021) and ``import_concepts``'s own pre-write length check
    (SEC-002, decisions.md D34) already combine to produce this: ``resolve_winner`` is called once
    and its winner is never displaced by a fallback to the next candidate. Pinned here as an explicit
    regression, because backfilling from the variant is what an implementer chasing "don't lose
    content" would naturally reach for, and is exactly what the spec forbids.

    Demonstrated through ``VALUE_TOO_LONG`` rather than ``EMPTY_SLUG``: T029/decisions.md D35 moved
    slug derivation from the label to the identifier, so a label's own content (here, its length) no
    longer decides whether the *slug* is usable — but it still decides whether the *label* is, which
    is the failure this test needs.
    """

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
    """T014 — FR-005, T022, decisions.md D14: once T013 re-keyed ``preferred_by_language`` on the
    resolved language, one group can hold both a same-language duplicate and a genuine contest
    loser. A loser whose published tag equals the winner's (case-insensitively) is a same-language
    duplicate and keeps ``SURPLUS_PREFERRED_LABEL``; one published under a different tag is a
    contest loser and takes ``VARIANT_NOT_KEPT`` — the same discriminator US-1's T008 already
    applies to the default-language branch (decisions.md D24), extended here to every other
    configured language (skos.py's own general branch)."""

    def _three_preferred_labels_two_under_one_tag_one_under_a_variant(self, tmp_path):
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
    """T061 — SEC-602 (round 6, medium): closed as a consequence of T059's structural fix
    (decisions.md D69) rather than needing a fix of its own — ``SkosGraph.label_languages`` is
    one of ``is_usable_literal``'s four call sites, so ``preferred_label_tag_counts`` (built
    entirely from it) no longer tallies a literal that could never itself win a name slot.
    Pinned here as its own regression test, in the shape the round-6 review reported it: before
    T059, an empty or whitespace-only literal was excluded from ever winning a contest but still
    counted toward its published tag's predominance, letting a publisher tip which of two *real*
    variants fills a configured language's slot — for an entirely unrelated concept — using
    literals that could not themselves be stored anywhere.
    """

    def test_two_unusable_literals_in_one_variant_cannot_flip_predominance_for_another_concept(
        self, db, tmp_path
    ):
        """Baseline predominance (without ``unusable1``/``unusable2``): ``de-de`` appears twice
        (``filler`` and ``c1``), ``de-at`` once (``c1`` only) — ``de-de`` wins and
        ``c1.preferred_label("de")`` is ``"Alpha DE"``. Before the fix, ``unusable1`` and
        ``unusable2``'s own empty/whitespace ``de-at`` literals each still counted a vote,
        pushing ``de-at`` to three against ``de-de``'s two and flipping ``c1``'s own stored value
        to ``"Alpha AT"`` — neither publishing anything storable themselves.
        """
        path = tmp_path / "sec602_predominance.ttl"
        path.write_text(
            """
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

            <http://example.org/sec602/> a skos:ConceptScheme ;
                skos:prefLabel "Sec Six O Two"@en .

            <http://example.org/sec602/filler> a skos:Concept ;
                skos:inScheme <http://example.org/sec602/> ;
                skos:prefLabel "Filler"@en, "Filler DE"@de-de .

            <http://example.org/sec602/c1> a skos:Concept ;
                skos:inScheme <http://example.org/sec602/> ;
                skos:prefLabel "One"@en, "Alpha DE"@de-de, "Alpha AT"@de-at .

            <http://example.org/sec602/unusable1> a skos:Concept ;
                skos:inScheme <http://example.org/sec602/> ;
                skos:prefLabel "Two"@en, ""@de-at .

            <http://example.org/sec602/unusable2> a skos:Concept ;
                skos:inScheme <http://example.org/sec602/> ;
                skos:prefLabel "Three"@en, "   "@de-at .
            """
        )
        with override_settings(LANGUAGES=[("en", "English"), ("de", "German")]):
            report = import_skos(path)
        assert report.fatal == []
        c1 = Concept.objects.get(static_uri="http://example.org/sec602/c1")
        assert c1.preferred_label("de") == "Alpha DE"


class TestConceptNotes:
    """T019 — FR-009/research.md R5: the definition and each of the six SKOS
    documentary note kinds are stored against their concept, each in its own
    language, through ``Concept.add_note``."""

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
    """T015 — FR-004, SC-007: unlike the preferred-label slot, the models hold as many alternative
    labels, hidden labels and notes per language as the file offers (``ConceptLabel``'s uniqueness
    constraint is conditional on the preferred kind alone, and ``ConceptNote`` carries none at all,
    decisions.md D4), so several variants resolving to one configured language are all stored and
    none is set aside. T013/T014's contest applies only where storing more than one would collide —
    the preferred slot — so ``variants.ttl`` (T005), carrying ``en-gb``/``en-us`` variants of an
    alternative label and a note alongside its preferred label, should reach this branch's plain
    resolve-and-store path unchanged, with no production code of its own."""

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
        # The concept's *preferred* label does have a contest (en-gb vs en-us for the default "en"
        # slot, T008) and legitimately contributes exactly one loser entry; if the alternative label
        # were wrongly run through the same contest, a second entry would appear alongside it.
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
    """T016 — FR-009/SC-014/SC-016: a file imported into a site configured for one language, then
    re-imported after the site is reconfigured for a second language the file also carries, stores
    that language's values for the concepts already present, and the report no longer counts them
    as left behind. ``rocks.ttl`` already carries ``en``/``de``/``fr`` preferred labels for exactly
    this population (decisions.md D16's own reference fixture)."""

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
    """T017 — FR-009/SC-015: the same re-import leaves every ``Concept``'s, ``ConceptScheme``'s and
    ``Collection``'s URI, ``static_uri``, slug, local URL and pk unchanged, and the content already
    stored in a language the site held before the re-import is unchanged. Scoped per decisions.md
    D16: ``ConceptLabel``/``ConceptNote`` rows are deleted and recreated on every run by design
    (#50, ``skos.py``'s ``labels.all().delete()``), so their pks legitimately change and are not
    asserted here — what is asserted about them is their values."""

    @staticmethod
    def _identity(obj) -> tuple[int, str, str | None, str, str]:
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
    """T020 — FR-014: a label or note in a language the site is not configured
    for is stored nowhere and is named in the report with its language, and
    the concept still imports on whatever configured-language content it
    carries. Filtered ahead of the write rather than caught from the models'
    own refusal (decisions.md D25) — ``ConceptLabel.clean()``/``ConceptNote.clean()``
    would refuse these too, but the importer must not rely on that exception
    as its control flow."""

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
    """FIX 15 (review, decisions.md D48) — ``_import_labels`` and
    ``_import_notes`` both ``continue`` on an object that is not an
    ``rdflib.Literal``, or that carries no ``.language``, with no report entry
    at all: a plain literal with no language tag, or a triple whose object is
    a URI where the predicate is a label or note predicate, vanished from a
    successful run with nothing in ``report.set_aside`` and nothing in
    ``report.normalized`` to show for it. Plain (untagged) literals are
    widespread in published SKOS, and FR-008/FR-009 both require a label or
    note to be stored "with its language" — a value with none cannot meet
    that requirement, so (argued in decisions.md D48) it is set aside and
    reported under the new ``SetAsideReason.NO_LANGUAGE_TAG``, the same
    "unusable value, never dropped in silence" treatment every other kind of
    unusable value in this feature already gets, rather than guessed into the
    vocabulary's default language — a guess the file never asserted, and one
    that risks colliding with ``ConceptLabel``'s own per-language cardinality
    rules for a ``PREFERRED`` value in particular.
    """

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
    """T021 — FR-014: a notation, a mapping to another vocabulary, and a
    predicate from outside SKOS entirely are each set aside and reported
    rather than passed over in silence, and the concepts still import
    successfully. FR-009: a foreign ``dcterms:description`` read as a
    concept's definition, because the concept carries no ``skos:definition``
    of its own, is reported as a normalisation rather than applied silently
    (decisions.md D24 in mapping.py, D21's precedent extended from the scheme
    level to the concept level)."""

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
        # skos:broader/related/member/memberList are SKOS predicates this
        # importer does not read yet (US-4/US-5), but the models do have a
        # place for them — they must never be reported as UNMODELLED_PREDICATE
        # merely because this story doesn't build that read path yet.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert not any(
            entry.reason is SetAsideReason.UNMODELLED_PREDICATE
            for entry in report.set_aside
        )


class TestUnmodelledPredicatesAreReportedForSchemeAndCollectionNodesToo:
    """FIX 12 (review, decisions.md D45) — ``_import_unheld_values`` is
    called once per concept, from ``_import_concept_content``; neither
    ``_resolve_scheme`` nor ``_import_collections`` ran an equivalent walk,
    so a non-SKOS predicate on the vocabulary's own scheme node, or on a
    collection node, was dropped with no report entry at all. FR-014's own
    wording is unqualified by node kind, and D27's justification for
    silently skipping a SKOS predicate this module has not built a read
    path for yet turns on "a story that will claim it" — no story claims a
    predicate genuinely outside SKOS."""

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


class TestNoPreferredLabelFinishedByUS3:
    """T022 — FR-006: a concept with no preferred label in the vocabulary's
    default language is set aside under ``NO_PREFERRED_LABEL`` and named in
    the report, and the rest of the vocabulary imports. Built at T009
    (decisions.md D17) because FR-006 states it in the same sentence as
    concept creation itself; D17 left it deliberately minimal and named this
    task as where it is finished. Nothing about the shape D17 chose disagrees
    with what US-3 built on top of it, so "finished" here means acceptance
    coverage proving the rest of the vocabulary imports *with* its own US-3
    content (labels, in this fixture) alongside the set-aside concept, not a
    production change."""

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
    """T026 — SC-025, S6 CORR-001, decisions.md D34: a concept skipped for
    having no usable preferred label never reached ``import_labels``, so none
    of its own published tags ever entered ``language_account()`` — the
    failure landing precisely on the concept a curator most needs to be told
    about (FR-008's sufficiency clause, SC-012). Accounted here under the
    concept's own published tag(s), never under the configured default it
    lacks — folding ``NO_PREFERRED_LABEL``'s own ``params["language"]`` (a
    configured code) into the account the way a published tag is would be
    D14's failure mode all over again."""

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
        # D14's failure mode: NO_PREFERRED_LABEL's own params["language"] is the
        # *configured* default the concept lacks, never a published tag — must
        # never be folded into the account as though it were one.
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
    """FIX 5 (review, decisions.md D39), updated by T029/decisions.md D35 —
    ``assign_unique_slug`` derives a concept's slug from its published
    identifier's own segment with ``slugify()``, then sets
    ``slug_is_manual = True`` and lets ``Concept.save()`` write it.
    ``save()`` refuses an *explicit* (manual) slug that is empty — an
    identifier segment made up only of characters ``slugify()`` strips
    (e.g. a ``"±"`` fragment) produces exactly that. The identifier and the
    label are both perfectly fine; it is the *derived slug* that is
    unusable, so the concept must be set aside and reported — under a
    reason that names the real problem, not the model's own slug-shaped
    message — rather than crashing the run on an uncaught
    ``ValidationError``."""

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

    def test_the_message_does_not_blame_a_preferred_label_that_is_perfectly_usable(
        self, db
    ):
        """CORR-701 (review round 7, decisions.md D72) — the set-aside concept's label is
        ``"Symbol"``, which slugifies perfectly well; it is the identifier's own ``#±``
        fragment that does not. Since T029/decisions.md D35 moved the slug off the label
        entirely, a message blaming the preferred label sends a curator to correct a value
        that is not at fault, on every one of this reason's call sites."""
        report = import_skos(FIXTURES / "empty_slug_label.ttl")
        entry = next(
            entry
            for entry in report.set_aside
            if entry.reason is SetAsideReason.EMPTY_SLUG
        )
        message = entry.render()
        assert entry.subject in message
        assert "preferred label" not in message

    def test_a_collision_the_importer_gives_up_on_is_reported_without_blaming_the_identifier(
        self, db, tmp_path, monkeypatch
    ):
        """CORR-701 — the second call site T060 added. Here the identifier segment *and* the
        label are both perfectly usable and the slug is empty only because the collision
        loop ran out of candidates, so a message naming characters ``slugify()`` strips is
        false about a value the file never got wrong."""
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
        assert "preferred label" not in entries[0].render()


class TestOverlongValueIsSetAsideNotCrashed:
    """T025 — SC-024, S6 SEC-002, decisions.md D34: variant matching now routes
    label values that were previously set aside (an exact-tag-only site never
    reached them) into ``Concept.add_label``, whose ``full_clean()`` refuses text
    beyond 255 characters. Guarded the way ``EMPTY_SLUG`` already guards the slug
    (FIX 5): caught ahead of a rolled-back transaction, set aside with its own
    reason, and the rest of the file — including the rest of the same concept —
    still imports."""

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
    """T023 — FR-010/research.md R4: ``skos:broader`` and ``skos:narrower`` both
    land as the single ``ConceptRelation`` row the models define, ``source`` the
    narrower end and ``target`` the broader end, whichever direction the file
    states it from. Both directions stated for the same pair still produce
    exactly one row, never two."""

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
    """FIX 6 (review, decisions.md D40) — a concept stating ``skos:related``
    about itself is already a deliberate no-op (decisions.md D29's
    ``if len(pair) < 2: continue``): not a real association, and the
    model's own ``_reject_self`` would refuse it if attempted. The same
    shape on ``skos:broader`` had no such guard: ``desired_broader`` never
    collapses a ``(uri, uri)`` pair the way ``desired_related``'s
    ``frozenset`` naturally does, so it reached ``add_broader`` and raised
    the model's own uncaught ``ValidationError`` instead of being skipped
    the same way."""

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
    """T024 — FR-010: ``skos:related`` is stored once as a symmetric
    association, including when the file states it from both concepts."""

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
    """T025 — FR-011: a relationship end that is neither in the file nor
    already in the database is set aside and reported, naming both ends, and
    the run still succeeds; a relationship end already in the database from
    an earlier import is stored even when this file does not separately
    redeclare it. Builds no new production behaviour of its own — T023's
    ``_resolve_relation_concept``/``_import_relations`` (research.md R4,
    decisions.md D29) already has to make exactly this distinction to avoid
    crashing on an ordinary, partial published file, so this task's own job
    is acceptance coverage proving it, the same shape decisions.md D17/T022
    already established for this story's predecessor."""

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
        # (models.py _reject_cross_scheme); asserting one across vocabularies
        # must not raise an uncaught ValidationError (decisions.md D29).
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
    """T026 — FR-013: a re-import of a file from which a relationship has
    been removed removes it, leaving both concepts. This is the third case
    decisions.md D20 deferred out of T014.

    (decisions.md D30) `rocks_updated.ttl`'s dropped granite-quartz edge no
    longer proves this: quartz leaves the file entirely, and correcting
    `_import_relations` to require *both* ends of a row to have been written
    by this run before deleting it means that edge now survives instead —
    exactly the "leaves both concepts" wording this class's own docstring
    already promised, just not for the case this class used to test. This
    class now uses its own dedicated `relation_lifecycle.ttl`/
    `relation_lifecycle_updated.ttl` fixture pair rather than a third edit to
    the shared rocks corpus (decisions.md D28), covering the genuine
    retraction this class is named for, the D30 survival case, and the
    selectivity check the original third test made, side by side."""

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
        # decisions.md D30: quarry-outlier is not restated by
        # relation_lifecycle_updated.ttl, but outlier itself is not written
        # by that run either — the file's silence about outlier is not the
        # same as the file retracting quarry's edge to it, so the edge is
        # left exactly as it was rather than deleted.
        import_skos(FIXTURES / "relation_lifecycle.ttl")
        quarry = Concept.objects.get(static_uri="http://example.org/lifecycle/quarry")
        outlier = Concept.objects.get(static_uri="http://example.org/lifecycle/outlier")
        assert outlier in quarry.related()

        report = import_skos(FIXTURES / "relation_lifecycle_updated.ttl")

        assert outlier in quarry.related()
        assert Concept.objects.filter(pk=outlier.pk).exists()
        assert "http://example.org/lifecycle/outlier" in report.absent_from_source

    def test_a_relationship_the_file_still_states_survives_the_same_reimport(self, db):
        # quarry's related edge to companion is unchanged between
        # relation_lifecycle.ttl and relation_lifecycle_updated.ttl — the
        # removal above must be selective, not a wholesale wipe of every
        # relation touching quarry.
        import_skos(FIXTURES / "relation_lifecycle.ttl")
        quarry = Concept.objects.get(static_uri="http://example.org/lifecycle/quarry")
        companion = Concept.objects.get(
            static_uri="http://example.org/lifecycle/companion"
        )

        import_skos(FIXTURES / "relation_lifecycle_updated.ttl")

        assert companion in quarry.related()


class TestRelationDisjointness:
    """FIX 2 (review, decisions.md D37) — SKOS makes ``broader``/``narrower``
    disjoint from ``related`` (models.py ``ConceptRelation._reject_disjointness_violation``):
    a pair joined one way refuses a relation of the other kind. ``_import_relations``
    built ``resolved_broader`` and ``resolved_related`` independently, so a pair the
    file (or an earlier and a later run together) states both ways raised an
    uncaught ``ValidationError`` from ``add_related``/``add_broader``, defeating
    the "set aside and reported, never a crash" rule every other unusable value in
    this feature already follows. The hierarchical relation wins (it is the
    stronger statement, and SKOS itself declares the two disjoint); the related
    statement is set aside and reported instead, in every route that can produce
    the conflict — stated together in one file, and split across two runs, in
    either direction.
    """

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
    """T038 — FR-017/FR-019/decisions.md D35: a collection is a third imported record
    with a published identifier and a real local address (``Collection.local_url``),
    and it was missed when ``Concept`` (T029) and ``ConceptScheme`` (T030) moved to
    identifier-derived slugs — three review lenses independently found the gap. A
    publisher renaming a collection's ``skos:prefLabel`` must not move its slug or
    ``local_url``, the same guarantee SC-026/SC-027 already give a concept and a
    vocabulary. A collection authored on this site (never imported) keeps deriving its
    slug from its name (FR-019).
    """

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
        # The URI's own last path segment is "silica-bearing"; the name is
        # "Silica-bearing rocks", which would slugify to "silica-bearing-rocks"
        # under the superseded name-derived rule (D6).
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
    """T039 — FR-011/FR-014, decisions.md D35 (fix cycle 3): T038 made a collection's slug
    derive from its published identifier's own segment, exactly like a concept's, but the
    concept-side ``EMPTY_SLUG`` guard (``import_concepts``'s pre-write
    ``slugify(identifier_slug_segment(uri))`` check) was not mirrored for a collection — so an
    identifier segment made up only of characters ``slugify()`` strips let
    ``CollectionImporter.import_collections`` write an empty slug straight onto the row, and
    ``Collection.save()``'s own manual-slug refusal (``An explicit slug must not be empty.``)
    escaped uncaught, rolling back the whole run (SC-024). Guarded the same way, ahead of the
    write: the collection is set aside under ``EMPTY_SLUG`` and the rest of the file — including
    a concept in the very same file — still imports. Unlike a vocabulary, a collection is not
    something the rest of the file needs in order to import, so this is a set-aside, not fatal.
    """

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
    """T039(a) — decisions.md D35 (fix cycle 3): before T038, two collections whose *names*
    slugified to the same value (e.g. ``'Rock Types'@en`` and ``'rock types'@en``) raised an
    uncaught ``ValidationError`` from ``Collection.save()``'s own colliding-slug refusal and
    stored nothing at all — zero schemes, zero concepts. Since T038 a collection's slug is
    identifier-derived, so two distinct identifiers never produce one slug and there is no
    second collision mechanism to add (D35 — "assert that rather than adding a second
    mechanism"); this asserts the already-resolved behaviour directly rather than re-deriving a
    fix :class:`TestCollectionSlugFollowsThePublishedIdentifier` already proves.
    """

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
    """T027 — FR-012: a ``skos:Collection`` lands as a ``Collection`` holding
    the identifier the file gave it, inside the vocabulary being imported,
    with each ``skos:member`` concept attached through the model's own
    membership API (``Collection.add``) — never a row constructed to bypass
    its cross-scheme check."""

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
    """T028 — FR-012: an ordered collection's ``skos:memberList`` is walked in
    order (research.md R2), ``ordered`` is set, and each member's position
    matches the file. A re-import whose list states a different order updates
    the positions to match (FR-013)."""

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
    """FIX 11 (review, decisions.md D44) — the ``if ordered:`` branch of
    ``_import_collections`` read membership exclusively from
    ``skos:memberList``; a ``skos:OrderedCollection`` asserted only with
    ``skos:member`` therefore imported with no members at all, and a
    re-import additionally *removed* membership an earlier, correctly-read
    import had written, because the reconciliation pass treats an empty
    ``member_uris`` as "the file states no members now". The SKOS reference
    treats ``memberList`` as narrowing ``member`` rather than replacing it,
    so both are read: ``memberList``, when present, governs the order of
    the members it names; any ``skos:member`` it omits is appended
    afterward, in the same deterministic sorted order the unordered branch
    already uses for a member that carries no order of its own."""

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
        # The reconciliation pass's own failure mode: an empty member_uris
        # read from a genuinely empty file is correctly a full retraction,
        # but the bug here was reading the collection as if it had none when
        # it plainly does.
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
    """T029 — FR-011: a collection member neither in the file nor already in
    the database is set aside and reported, and the collection is still
    created; the run succeeds. FR-013: a re-import that adds and removes
    members leaves membership matching the file, except that decisions.md
    D30's own rule — settled for relationship reconciliation and carried
    here unchanged, not re-derived — means a member whose concept the file no
    longer mentions *at all* survives, exactly as that concept itself
    survives (``report.absent_from_source``)."""

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
        # decisions.md D30's rule, applied to membership rather than a
        # relation: gamma leaves collection_lifecycle_updated.ttl entirely,
        # so this run never rewrites gamma at all — the file's silence about
        # gamma is not the same as "group" retracting its membership, and the
        # membership is left exactly as it was, same as gamma's own concept
        # row (report.absent_from_source).
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
    """T034 — closes the gap decisions.md D33 named rather than invented: a
    collection an earlier import created that the current file no longer
    mentions at all is left untouched and named in
    ``report.absent_from_source``, the same way a concept in that position
    already is (T015). A collection is a record with its own identity for
    the same reasons a concept and a vocabulary are (decisions.md D32)."""

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
        # FR-013's "left untouched", not only "not deleted": the concept
        # stays a member of the absent collection across the re-import,
        # exactly as an absent concept's own foreign-key references survive
        # (TestRecordsAbsentFromSource, T015).
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
    """FIX 7 (review, decisions.md D41) — ``Concept.objects.filter(scheme=...)
    .exclude(static_uri__in=mentioned_uris)`` (and ``_import_collections``'s
    identical query for ``Collection``) also selects a row whose
    ``static_uri`` is ``NULL``: Django's ``exclude(field__in=...)`` compiles
    to ``NOT (field IN (...) AND field IS NOT NULL)``, which is true for a
    NULL row regardless of what ``mentioned_uris`` holds. A locally authored
    record — one the file could never "mention" at all, since it carries no
    external identifier for the file to name in the first place — was
    therefore always "absent from source", and its ``None`` static URI was
    appended straight into ``report.absent_from_source: list[str]``.
    CONTEXT.md is explicit that a record's ``uri`` is "always present,
    never None"; the value to report is that property (the dynamic local
    URL), not the raw column."""

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
    """FIX 8 (review, decisions.md D42) — ``_import_concepts`` assigned
    ``concept.scheme = target_scheme`` unconditionally on a ``get_by_uri``
    match, with no check that the matched record already belonged to a
    *different* vocabulary. FR-005 lets a file that declares no vocabulary
    of its own be imported into any caller-named target, so importing the
    same file into a second target silently emptied the first — the report
    called it ``updated``, indistinguishable from an ordinary content
    refresh. Moving a record between vocabularies is a curatorial act, not
    something reading a file should do as a side effect: a concept whose
    URI already belongs to a different vocabulary is left exactly where it
    is, set aside and reported naming both vocabularies."""

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
    """FIX 9 (review, decisions.md D42) — the identical defect FIX 8 closes
    for a concept, one level up: ``_import_collections`` wrote
    ``row.scheme = target_scheme`` unconditionally on a matched collection,
    with no equivalent of ``conflicting_scheme_ref``. Two files that both
    declare the same collection identifier from different vocabularies
    would silently reassign the collection to whichever imported last,
    leaving it holding a foreign member from the vocabulary it was pulled
    out of — exactly the state ``CollectionMember._reject_cross_scheme``
    exists to prevent, produced through the package's own public API. Same
    rule as FIX 8: the existing collection is left exactly where it is,
    membership included, set aside and reported naming both vocabularies."""

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
    """FIX 10 (review, decisions.md D43) — spec Edge Cases: "later a
    concept's identifier is found to be held by a record of a different
    kind — a collection in one file, a concept in another. This is a
    contradictory source and is reported while reading, rather than
    surfacing as a database constraint violation." ``_import_concepts``
    consults only ``Concept.objects.get_by_uri`` and ``_import_collections``
    only ``Collection.objects.get_by_uri``, so the per-model unique
    constraints never collide and nothing catches the clash: two records
    silently end up asserting the same static URI, which Article IX makes
    the sole identity."""

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
    """T030 — decisions.md D3: a collection identified only by a blank node
    fails the run, on the same rule that governs a concept. An ordered
    collection's ``skos:memberList`` uses blank nodes structurally for the
    list's own cells; those are not identities and are read normally."""

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
        # rocks.ttl's example-sequence is an ordinary ordered collection: its
        # skos:memberList is an RDF list, which is blank nodes by
        # construction (research.md R2). The run must not treat any of those
        # cells as a record needing its own identity.
        report = import_skos(FIXTURES / "rocks.ttl")
        assert report.fatal == []
        collection = Collection.objects.get_by_uri(
            "http://example.org/rocks/collection/example-sequence"
        )
        assert collection.ordered is True


class TestFixtureCorpus:
    """T005 — the published-vocabulary fixtures are discoverable and parse (FR-018, SC-016).

    The suite's own fixture set, not built inline: one small vocabulary ("Rock
    types") in each of the three supported serializations, an edited copy for the
    re-import scenarios, and the malformed documents the fatal paths (D3, FR-004)
    need. `rdflib` is a test-only tool here (T005 is Phase 0 — the reader that
    makes it a genuine runtime dependency lands at T006, decisions.md D12); every
    fixture is exercised the same way a real import would read it.
    """

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

        # Notes of several kinds, spread across concepts.
        assert (igneous, SKOS.definition, None) in graph
        assert (granite, SKOS.scopeNote, None) in graph
        assert (quartz, SKOS.historyNote, None) in graph
        assert (quartz, SKOS.changeNote, None) in graph
        assert (quartz, SKOS.note, None) in graph

        # A broader/narrower hierarchy and a related pair.
        assert (granite, SKOS.broader, igneous) in graph
        assert (granite, SKOS.related, quartz) in graph

        # An unordered and an ordered collection.
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

        # 1. A corrected preferred label.
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

        # 2. A removed alternative label.
        assert (granite, SKOS.altLabel, None) not in graph

        # 3. A concept dropped from the file entirely (taking its related edge and
        # its collection membership with it) — still present in an already-imported
        # database, so the re-import scenario names it as absent from this source.
        assert (quartz, rdflib.RDF.type, SKOS.Concept) not in graph
        assert (granite, SKOS.related, quartz) not in graph
        unordered = rdflib.URIRef("http://example.org/rocks/collection/silica-bearing")
        assert quartz not in set(graph.objects(unordered, SKOS.member))

        # 4. A changed collection order.
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
        # T005/FR-015/SC-020: several variants of one base language (en), spread
        # across preferred labels, alternative labels, and notes — the contest
        # population US-3 needs, reused rather than rebuilt by #52 (spec US-5).
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
        # T005/SC-002: a vocabulary published only as en-gb, for a site configured
        # only for en (no bare "en" tag anywhere in this file).
        graph = rdflib.Graph()
        graph.parse(FIXTURES / "en-gb-only.ttl", format="turtle")
        languages = {
            literal.language for literal in graph.objects(None, SKOS.prefLabel)
        }
        assert languages == {"en-gb"}

    def test_declares_de_at_fixture_declares_itself_in_a_variant_of_a_configured_language(
        self,
    ):
        # T005/SC-010: the vocabulary's own skos:prefLabel is a single de-at tag,
        # for the default-language resolution path.
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


# FIX 13 (review, decisions.md D46) — independent, domain-level predicate
# knowledge for TestEverySkosPredicateIsReadOrReported's own behavioural
# rewrite below. Deliberately *not* imported from
# controlled_vocabularies.exchange.mapping: reusing production's own tables
# would repeat exactly the defect this fix closes — a check built from the
# same constant production uses to decide what it has handled can never
# notice production quietly stopping to read what it still claims to. This
# restates the SKOS specification's own vocabulary (which predicate is a
# preferred/alternative/hidden label, which is which note kind, which is a
# cross-vocabulary mapping and its CURIE) from the spec, not the module under
# test.
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
# FIX 15 (review, decisions.md D48) — independent CURIE naming for the same
# label/note predicates above, restated rather than borrowed from skos.py's
# own skos_curie helper (the same "no shared classification" discipline FIX
# 13 already applies to _COVERAGE_MAPPING_CURIE below).
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

# A set-aside reason under which the *whole* record was never created or
# updated this run — as opposed to one where the record exists but a
# specific value on it was left out. Only these blanket-excuse every one of
# that node's own predicates from needing further evidence: there is no
# concept or collection row left to check anything against.
_COVERAGE_WHOLE_RECORD_EXCLUDED_REASONS = frozenset(
    {
        SetAsideReason.NO_PREFERRED_LABEL,
        SetAsideReason.VOCABULARY_MISMATCH,
        SetAsideReason.EMPTY_SLUG,
        SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY,
        SetAsideReason.URI_HELD_BY_DIFFERENT_KIND,
    }
)

# Fatal-path fixtures, and the two that need a caller-named scheme this sweep
# does not attempt to supply, write nothing on their own — there is no
# resulting record and no non-fatal report entry for a predicate's coverage
# to appear in. Excluded explicitly, not silently skipped: each is already
# exercised directly by its own dedicated test class.
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
        "cyclic_member_list.ttl",  # TestCraftedFilesStayInsideTheExceptionContract (FIX 18) — raises, no report
    }
)

_PREDICATE_COVERAGE_FIXTURES = sorted(
    (filename, fmt)
    for filename, fmt in ALL_FIXTURES
    if filename not in _PREDICATE_COVERAGE_EXCLUDED_FIXTURES
)


def _coverage_membership_covered(collection_uri: str, concept_uri: str, report) -> bool:
    """Direct evidence that ``concept_uri`` landed as a member of ``collection_uri``,
    or was reported as a member that could not be found (FIX 13)."""
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
    """Direct evidence that a ``kind`` relation between ``source_uri`` and ``target_uri``
    (in that direction) landed, or was reported missing/disjoint (FIX 13)."""
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
    """Direct evidence that ``concept_uri`` landed inside the vocabulary ``scheme_uri``
    names, or that the concept was never created at all this run (FIX 13)."""
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
    """Direct evidence that this ``skos:prefLabel``/``altLabel``/``hiddenLabel`` value
    landed — as the scheme's own name, a concept's identity anchor, or a
    ``ConceptLabel`` row — or was reported set aside (FIX 13).

    T008 (FS-007 US-1): a value may now land under a *resolved* configured language
    other than its own published tag (FR-001/FR-006), so the landed-row check is no
    longer scoped to ``language`` — decisions.md D21 named this sweep as something to
    re-check once these fixtures' values start landing instead of being set aside.
    ``VARIANT_NOT_KEPT`` (T022) joins the recognised set-aside reasons for the same
    reason: a losing variant is reported under it, keyed by its own published tag,
    exactly as ``UNCONFIGURED_LANGUAGE`` already is.
    """
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
            # T025, S6 SEC-002: a value the model's own field refuses on length.
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
    """Direct evidence that this note value landed as a ``ConceptNote`` row, or was
    reported set aside (FIX 13).

    T008: not scoped to ``language`` on the landed-row check, for the same reason as
    :func:`_coverage_label_covered` — a note may land under a resolved configured
    language other than its own published tag.
    """
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
    """Direct evidence that a label/note object with no language tag — or one that is not
    even a Literal — was reported set aside under ``NO_LANGUAGE_TAG`` (FIX 15, decisions.md
    D48), rather than silently skipped the way this gate used to skip it too."""
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
    """Whether every in-scope triple of ``predicate`` in ``graph`` has direct evidence
    of landing in a record or being named in the report (FIX 13). Returns
    ``(True, None)`` when covered, or ``(False, subject)`` naming the first
    triple's subject that has no such evidence."""
    if predicate in _COVERAGE_LABEL_KIND:
        kind = _COVERAGE_LABEL_KIND[predicate]
        for subject_node, literal in graph.subject_objects(predicate):
            subject_uri = str(subject_node)
            if subject_uri not in in_scope:
                continue
            if not isinstance(literal, rdflib.Literal) or not literal.language:
                # FIX 15 (review, decisions.md D48): previously skipped outright
                # — the exact blind spot that let an untagged/non-literal value
                # go unreported and unnoticed by this gate.
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
                # FIX 15 (review, decisions.md D48): same blind spot, the note side.
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

    # A SKOS predicate this dispatcher has no independent verification logic
    # for yet. Treated as uncovered, not silently skipped — the whole point
    # of this rewrite is that a predicate the fixture corpus grows to carry
    # cannot pass this test merely by production classifying it as handled.
    return False, str(predicate)


class TestEverySkosPredicateIsReadOrReported:
    """T033/FIX 13 (review, decisions.md D46) — a behavioural rewrite of the
    original T033 gate. That version computed its own "recognised" set from
    ``_HANDLED_CONCEPT_PREDICATES | _READ_BUT_NOT_AT_CONCEPT_LEVEL`` —
    production's own exclusion set, imported directly. Membership there means
    "not double-reported by ``_import_unheld_values``", which is *not* the
    claim FR-014 actually makes: "read by the importer, or named in the
    report." Adding a predicate to ``_HANDLED_CONCEPT_PREDICATES`` while
    never building a read path for it made the old test pass and the
    behaviour regress in the same edit, because the test's own "recognised"
    set and the constant a review-introduced mutation would touch were one
    and the same object — precisely the failure D34 wrote this gate to
    prevent, and precisely what it could not actually prevent.

    This version imports every fixture that can succeed standing alone
    (``scheme=None``, no pre-seeded database — the excluded fixtures above
    cannot, and are each exercised directly by their own dedicated test
    class instead) and, for every SKOS predicate the fixture's own graph
    carries on a node this importer treats as a record (a concept, the
    vocabulary's own scheme node, or a collection — a *foreign* scheme node
    merely referenced, as in ``mixed_scheme_membership.ttl``, is not itself
    such a record), requires direct, independently-derived evidence —
    a matching database row, or a matching report entry — that the
    predicate's value was either read into a record or named in the report.
    None of that evidence-gathering reuses ``skos.py``'s own handled-predicate
    tables; :data:`_COVERAGE_LABEL_KIND`/`_COVERAGE_NOTE_KIND`/`_COVERAGE_MAPPING_CURIE`
    above restate the SKOS specification's own vocabulary independently.
    """

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
        # Only the *resolved* scheme is in scope — a second, merely-referenced
        # declared scheme (mixed_scheme_membership.ttl's "other") is never a
        # record this importer creates, so its own predicates are not this
        # importer's to account for.
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
    """T002 — the ``controlled_vocabularies.exchange`` package exists and is
    importable. The package is the module tree the import feature lands in
    (plan.md Project Structure); this only asserts the scaffold itself is in
    place. Homed here rather than in a file of its own because the package's
    own surface — ``import_skos`` and its exceptions — is exercised by this
    module more than any other in ``exchange``.
    """

    def test_package_is_importable(self):
        assert exchange is not None

    def test_package_has_a_module_docstring(self):
        # A public package gets documented (Article VI); this catches an
        # accidentally-empty __init__.py before anything is re-exported from it.
        assert exchange.__doc__, (
            "controlled_vocabularies.exchange has no module docstring"
        )


class TestSafetyExceptionsAreExportedAndPartOfTheDocumentedHierarchy:
    """FIX 19 (review, decisions.md D52) — ``UnsafeRdfXmlError``/``UnsafeJsonLdError``
    propagate out of ``import_skos()`` but were in neither
    ``controlled_vocabularies.exchange.__all__`` nor a subclass of
    ``SkosImportError``. A consumer writing the package's own documented
    ``except (SkosImportError, SkosImportFailed)`` — the shape every other
    test in this module already exercises — did not catch a hostile file,
    precisely the case the safety scan exists to guard against."""

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
        # The actual consumer-facing failure this fix closes: code written
        # against only the two documented exception types must not let a
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
    """A JSON-LD document nesting one object inside another ``depth`` times
    (FIX 18, review, decisions.md D51). Built as raw text, not via
    ``json.dump`` — the encoder's own recursive descent hits Python's
    recursion limit before the file is even written, at a depth well below
    what is needed to reproduce the *parser's* own recursion failure."""
    open_frag = '{"@id":"http://example.org/deep/","nested":'
    close_frag = "}"
    parts = [open_frag] * depth
    parts.append('{"val":0}')
    parts.extend([close_frag] * depth)
    path = tmp_path / "deep.jsonld"
    path.write_text("".join(parts))
    return path


class TestCraftedFilesStayInsideTheExceptionContract:
    """FIX 18 (review, decisions.md D51) — three verified paths raised an
    exception that is neither ``SkosImportError`` nor ``SkosImportFailed``,
    so a caller catching only the documented pair (a downstream upload form,
    say) got an unhandled exception instead: a non-well-formed RDF/XML
    document (including a Turtle file merely renamed to ``.rdf``) raised a
    bare ``xml.sax.SAXParseException`` from ``scan_rdf_xml`` at
    ``_read_graph`` time, before the surrounding try/except that already
    wraps ``graph.parse()``'s own failures; a deeply nested JSON-LD document
    raised a bare ``RecursionError`` from ``scan_json_ld``'s own recursive
    walk, the same "outside the try/except" shape; and a cyclic
    ``skos:memberList`` (an ``rdf:rest`` chain that loops back on itself
    instead of terminating in ``rdf:nil``) raised a bare
    ``ValueError("List contains a recursive rdf:rest reference")`` from
    ``graph.items()`` deep inside ``_import_collections``, well after the
    scan stage entirely.
    """

    def test_a_turtle_file_renamed_to_rdf_raises_skosimporterror_not_a_bare_sax_exception(
        self, tmp_path
    ):
        # Not well-formed XML at all — no angle brackets, no doctype, nothing
        # defusedxml.sax's own EntitiesForbidden/ExternalReferenceForbidden
        # guards were built to catch. This is scan_rdf_xml's own parser
        # rejecting malformed input, a different failure than either guard.
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
        # The wrapping added for the malformed-XML case above must not
        # swallow the *deliberate* safety refusal into a generic
        # SkosImportError — a caller distinguishing "unsafe" from "merely
        # unreadable" needs the specific type to keep working.
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
        # research.md R7/FR-003: the run is all-or-nothing. The scheme and
        # concept that import cleanly before the cyclic collection is reached
        # must not survive if the run as a whole is refused.
        with pytest.raises(SkosImportError):
            import_skos(FIXTURES / "cyclic_member_list.ttl")
        assert not ConceptScheme.objects.filter(
            static_uri="http://example.org/cyclic/"
        ).exists()
        assert not Concept.objects.filter(
            static_uri="http://example.org/cyclic/a"
        ).exists()


class TestFailureMessagesUseOnlyNamedPlaceholders:
    """T031 (FR-016, spec User Story 6 Acceptance Scenarios 1 and 4) — the
    "named, not positional" check applied to the messages this module raises
    directly rather than adding to ``ImportReport``. Every ``raise …Error(_("…"))``
    call site in ``skos.py`` is exercised once here.

    Acceptance Scenario 4's developer-diagnostics exemption is the raw rdflib
    parse error the unparseable-file refusal chains onto ``__cause__``: named and
    asserted present, rather than left as an unstated gap in the sweep.
    """

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
    """T010 — FR-010/SC-017: across every matching path this feature introduces — the default
    language, ``Concept.label``, labels, notes, and the vocabulary/collection name and
    description — no value is ever stored in a language absent from the site's configuration.
    This is the test that would fail if a later change made the matcher permissive."""

    @staticmethod
    def _assert_only_configured_languages_are_stored():
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
        # tests/settings.py declares its own three-language LANGUAGES list, so simply not
        # overriding it here would silently mean that list rather than Django's own default —
        # the obvious-looking test that pins nothing (decisions.md D12/D17). The ordinary
        # consuming project declares no LANGUAGES at all, so this is the behaviour that needs
        # holding still.
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
    """SC-022 — adding a configured language that *shares a base* with one the site already
    holds, then re-importing the unchanged file, leaves every record's slug and local address
    exactly as they were.

    SC-015's test could never have failed this, because it only ever adds a language sharing no
    base with an existing one (``en`` → ``en``+``fr``), so no incumbent's candidate set can
    shrink. ``variants.ttl`` publishes one concept as ``"Colour"@en-gb`` and ``"Color"@en-us``
    with no bare ``en`` anywhere, so adding ``en-gb`` genuinely moves which value wins the ``en``
    slot — which is the case that must leave the address alone.

    The concept's *name* is deliberately not asserted: SC-022's ``name`` clause is struck
    (decisions.md D48). A displayed label following the site's language configuration is what
    configuring a language asks for; an address following it is the harm FR-017 removes.
    """

    SCHEME_URI = "http://example.org/colours/"
    CONCEPT_URI = "http://example.org/colours/colour"

    @staticmethod
    def _address(obj) -> tuple[int, str | None, str, str]:
        return (obj.pk, obj.static_uri, obj.slug, obj.local_url)

    def test_adding_en_gb_to_an_en_site_moves_no_slug_and_no_local_url(self, db):
        with override_settings(LANGUAGES=[("en", "English")]):
            assert import_skos(FIXTURES / "variants.ttl").fatal == []

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
