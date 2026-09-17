"""T004 — the pre-flight safety scan of untrusted RDF/XML (research.md R3, decisions.md D9).

`rdflib`'s RDF/XML parser calls `xml.sax.make_parser()` itself, so a defused
parser cannot be substituted directly; `scan_rdf_xml` is the pre-flight check
that stands in front of it. This reinstates the actual measured defect — the
eight-level nested-entity bomb from research.md R3 — as the test input, rather
than a mock, so the control is proven against the real one.
"""

from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.utils.functional import Promise

from controlled_vocabularies.exchange.safety import (
    UnsafeJsonLdError,
    UnsafeRdfXmlError,
    scan_json_ld,
    scan_rdf_xml,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "security"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestScanRdfXml:
    """The scan refuses the untrusted constructs research.md R3 measured and
    lets an ordinary document through untouched."""

    def test_the_measured_entity_bomb_is_refused_with_a_translatable_message(self):
        # research.md R3: eight nested entity declarations, each repeating the previous
        # one five times, expand to a single 781,250-character literal from ~500 bytes.
        # This is that exact document, not a stand-in.
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("entity_bomb.rdf"))
        err = excinfo.value
        assert isinstance(err, ValidationError)
        assert isinstance(err.message, Promise), (
            "entity-bomb refusal message is not lazily translatable"
        )
        assert "%(name)s" in str(err.message), (
            "entity-bomb refusal message lacks a named %(name)s placeholder"
        )
        assert err.params == {"name": "e0"}
        assert "e0" in err.messages[0]
        assert err.code == "rdf_xml_entities_forbidden"
        assert isinstance(err.__cause__, Exception), (
            "the underlying defusedxml exception must be chained"
        )

    def test_an_ordinary_rdf_xml_document_passes_untouched(self):
        # No DTD, no entities: scan_rdf_xml is a no-op and raises nothing.
        assert scan_rdf_xml(_read("ordinary.rdf")) is None

    def test_a_document_declaring_an_external_entity_is_refused_not_silently_emptied(
        self,
    ):
        # research.md R3's own canary probe: a document referencing a file on disk via
        # a declared external entity. Before this scan it parsed cleanly with the
        # reference resolving to an empty string; now declaring the entity at all is
        # enough to refuse the document outright.
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("external_entity.rdf"))
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "external-entity refusal message is not lazily translatable"
        )
        assert "%(name)s" in str(err.message)
        assert err.params == {"name": "xxe"}
        assert err.code == "rdf_xml_entities_forbidden"

    def test_a_document_referencing_an_external_dtd_subset_is_refused(self):
        # A distinct route to the same untrusted-fetch problem: no entity is declared,
        # but the doctype itself points at an external resource.
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("external_dtd.rdf"))
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "external-DTD refusal message is not lazily translatable"
        )
        assert "%(system_id)s" in str(err.message)
        assert err.params == {"system_id": "http://example.org/nonexistent.dtd"}
        assert "http://example.org/nonexistent.dtd" in err.messages[0]
        assert err.code == "rdf_xml_external_reference_forbidden"


class TestScanJsonLd:
    """FIX 1 (review) — JSON-LD's ``@context`` can name a remote location that
    rdflib's parser resolves through ``urlopen`` with no allowlist (a string
    ``@context``, or a string entry inside an array ``@context``, is a URL
    rdflib will fetch during parsing). Spec Assumptions says "a file, not a
    URL": this application never fetches network resources or reads
    caller-uncontrolled local files as a side effect of reading one it was
    handed. The same pre-flight-refusal shape D9 used for RDF/XML — refuse
    before rdflib ever sees the bytes, rather than patch the parser.

    An inline, locally-embedded ``@context`` object — the overwhelmingly
    common shape in a published file — carries no reference to resolve and
    must be unaffected.
    """

    def test_a_string_context_naming_a_remote_location_is_refused(self):
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("remote_context_string.jsonld"))
        err = excinfo.value
        assert isinstance(err, ValidationError)
        assert isinstance(err.message, Promise), (
            "remote-context refusal message is not lazily translatable"
        )
        assert "%(context)s" in str(err.message)
        assert err.params == {"context": "http://127.0.0.1:1/x.json"}
        assert "http://127.0.0.1:1/x.json" in err.messages[0]
        assert err.code == "jsonld_remote_context_forbidden"

    def test_a_remote_string_inside_an_array_context_is_refused(self):
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("remote_context_array.jsonld"))
        err = excinfo.value
        assert err.params == {"context": "http://127.0.0.1:1/x.json"}
        assert err.code == "jsonld_remote_context_forbidden"

    def test_an_inline_object_context_is_unaffected(self):
        assert scan_json_ld(_read("inline_context.jsonld")) is None

    def test_a_document_with_no_context_at_all_is_unaffected(self):
        assert scan_json_ld(b'{"@id": "http://example.org/rocks/"}') is None

    def test_malformed_json_is_left_for_rdflibs_own_parser_to_report(self):
        # scan_json_ld only refuses unsafe *content*; a document that is not even
        # valid JSON is not this scan's problem to diagnose — rdflib's own parse
        # raises its own error for that, exactly as an unparseable Turtle file does.
        assert scan_json_ld(b"not json at all {{{") is None


class TestScanJsonLdRefusesContextImport:
    """FIX 14 (review, security, decisions.md D47) — an inline *object*
    ``@context`` was previously waved through on the reasoning that it "carries
    nothing to resolve" (the old module docstring's own words). False:
    rdflib's ``Context._read_source`` (``rdflib/plugins/shared/jsonld/context.py``)
    reads ``source.get('@import')`` from *any* dict it treats as a context —
    the document's own top-level context, an entry inside an array context, a
    term's own nested ``@context``, or a node's own ``@context`` inside
    ``@graph`` — and resolves a string value through ``_fetch_context`` /
    ``source_to_json`` / ``urlopen`` exactly as a string ``@context`` does.
    ``exfil_via_import.jsonld`` is the actual measured defect: before this fix,
    reading it through rdflib directly merges in ``exfil_secret.jsonld`` (a
    stand-in for a server-side file the uploaded document must never be able to
    read) and the merged ``leaked:`` prefix resolves the scheme node's own URI
    to ``http://example.org/SECRET-FROM-LOCAL-FILE/scheme`` — the contents of a
    file the caller never named, chosen entirely by the uploaded document.
    """

    def test_context_import_at_the_top_level_is_refused(self):
        # The reproduction as measured: a dict @context bypassed the scan
        # entirely and its @import was resolved by rdflib.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("exfil_via_import.jsonld"))
        err = excinfo.value
        assert isinstance(err, ValidationError)
        assert isinstance(err.message, Promise), (
            "@import refusal message is not lazily translatable"
        )
        assert "%(context)s" in str(err.message)
        assert err.params == {"context": "exfil_secret.jsonld"}
        assert err.code == "jsonld_context_import_forbidden"

    def test_context_import_inside_an_array_context_entry_is_refused(self):
        # An array @context may freely mix inline objects with string
        # references (refused already); a dict entry carrying its own
        # @import is the same hole, one level deeper.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_array.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_context_import_nested_inside_a_terms_own_context_is_refused(self):
        # A context inside a context: a term definition may itself carry a
        # "@context" scoped to that term, which rdflib loads exactly as any
        # other context — including running _read_source's @import check on it.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_nested_term.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_context_import_on_a_node_inside_graph_is_refused(self):
        # Every embedded node object in @graph may carry its own "@context",
        # not only the document's top-level one; that node-scoped context is
        # read through the identical _read_source path.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_graph_node.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_an_ordinary_inline_object_context_with_no_import_still_passes(self):
        # The regression control: an inline, locally-embedded @context — the
        # overwhelmingly common shape of a published file — carries no @import
        # and must be completely unaffected by this guard.
        assert scan_json_ld(_read("inline_context.jsonld")) is None


class TestScanJsonLdWalksNestedArrayContexts:
    """SEC-701 (review, security lens, decisions.md D19) — the array branch used
    to check only ``str`` and ``dict`` entries, so an array nested inside an array
    was walked into by rdflib and not by the scan.

    ``Context._prep_sources`` (``rdflib/plugins/shared/jsonld/context.py``) ends
    with ``if isinstance(source, list): self._prep_sources(...)`` — it recurses to
    any depth and hands every string it reaches to ``_fetch_context``, which is
    the same ``urlopen``-backed path the flat forms use. Measured on the branch
    before the fix: ``{"@context": [["http://…"]]}`` passed the scan and was
    fetched, as did ``[[{"@import": …}]]``, while the flat forms either side of
    them were correctly refused. This is the first release in which a *remote
    server* chooses that document, which is why the lens caught it here.
    """

    def test_a_remote_string_inside_a_nested_array_context_is_refused(self):
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("remote_context_nested_array.jsonld"))
        assert excinfo.value.params == {"context": "http://127.0.0.1:1/x.json"}
        assert excinfo.value.code == "jsonld_remote_context_forbidden"

    def test_a_context_import_inside_a_nested_array_context_is_refused(self):
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_nested_array.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_the_walk_is_total_rather_than_one_level_deeper(self):
        # The fix is a recursion, not a second hard-coded level: the array branch
        # now passes every entry back through the same check whatever its type.
        # Pinning an arbitrary depth is what proves that, and it is why the fix
        # is not "handle [[x]] too".
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(b'{"@context": [[[["http://127.0.0.1:1/x.json"]]]]}')
        assert excinfo.value.code == "jsonld_remote_context_forbidden"

    def test_an_inline_term_map_inside_a_nested_array_still_passes(self):
        # The negative control for the recursion: making the walk total must not
        # start refusing a legitimate context, at any nesting depth.
        assert (
            scan_json_ld(
                b'{"@context": [[{"skos": "http://www.w3.org/2004/02/skos/core#"}]]}'
            )
            is None
        )


class TestRefusalMessagesUseOnlyNamedPlaceholders:
    """T031 (FR-016, spec User Story 6 Acceptance Scenarios 1 and 4) — the
    "named, not positional" check applied to the messages this module raises
    directly rather than adding to ``ImportReport``.

    Acceptance Scenario 4's developer-diagnostics exemption is the raw
    ``defusedxml`` guard exception each refusal chains onto ``__cause__``: named
    and asserted present here, so the exemption is stated rather than an unstated
    gap in the sweep. It is the only thing this module puts in front of a person
    that Article XII does not hold to a translatable, named-placeholder standard.
    """

    def test_entity_bomb_message_and_its_developer_diagnostic_exemption(
        self, uses_only_named_placeholders
    ):
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("entity_bomb.rdf"))
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "rdf_xml_entities_forbidden"
        # Developer-diagnostic exemption: the raw defusedxml guard exception
        # is chained, not translated (this module's own docstring says so).
        assert err.__cause__ is not None, (
            "the underlying defusedxml exception must be chained for developer diagnostics"
        )

    def test_external_dtd_message_and_its_developer_diagnostic_exemption(
        self, uses_only_named_placeholders
    ):
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("external_dtd.rdf"))
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "rdf_xml_external_reference_forbidden"
        assert err.__cause__ is not None, (
            "the underlying defusedxml exception must be chained for developer diagnostics"
        )

    def test_remote_context_message_uses_only_named_placeholders(
        self, uses_only_named_placeholders
    ):
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("remote_context_string.jsonld"))
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "jsonld_remote_context_forbidden"
