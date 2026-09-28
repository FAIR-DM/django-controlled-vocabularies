"""Tests for controlled_vocabularies.exchange.safety."""

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
    """Return the bytes of a security fixture file.

    Args:
        name: The file name under ``tests/fixtures/security``.

    Returns:
        The file's contents.
    """
    return (FIXTURES / name).read_bytes()


class TestScanRdfXml:
    def test_the_measured_entity_bomb_is_refused_with_a_translatable_message(self):
        # The measured defect: eight nested entity declarations, each repeating the
        # previous one five times, expand ~500 bytes into a single 781,250-character
        # literal.
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
        assert scan_rdf_xml(_read("ordinary.rdf")) is None

    def test_a_document_declaring_an_external_entity_is_refused_not_silently_emptied(
        self,
    ):
        # Before the scan this parsed cleanly, the reference resolving to an empty
        # string. Declaring the entity at all is now enough to refuse the document.
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
        # No entity is declared, but the doctype itself points at an external resource.
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
        # The scan refuses only unsafe content; rdflib's own parse reports invalid JSON.
        assert scan_json_ld(b"not json at all {{{") is None


class TestScanJsonLdRefusesContextImport:
    def test_context_import_at_the_top_level_is_refused(self):
        # A dict @context once bypassed the scan entirely and rdflib resolved its
        # @import.
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
        # An array @context may mix inline objects with string references, so a dict
        # entry carrying its own @import is the same hole one level deeper.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_array.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_context_import_nested_inside_a_terms_own_context_is_refused(self):
        # A term definition may carry an @context scoped to that term, which rdflib
        # loads like any other context.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_nested_term.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_context_import_on_a_node_inside_graph_is_refused(self):
        # Any node object in @graph may carry its own @context, read the same way.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(_read("context_import_graph_node.jsonld"))
        assert excinfo.value.params == {"context": "exfil_secret.jsonld"}
        assert excinfo.value.code == "jsonld_context_import_forbidden"

    def test_an_ordinary_inline_object_context_with_no_import_still_passes(self):
        assert scan_json_ld(_read("inline_context.jsonld")) is None


class TestScanJsonLdWalksNestedArrayContexts:
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
        # The walk is a recursion, not one more hard-coded level, so an arbitrary depth
        # proves it.
        with pytest.raises(UnsafeJsonLdError) as excinfo:
            scan_json_ld(b'{"@context": [[[["http://127.0.0.1:1/x.json"]]]]}')
        assert excinfo.value.code == "jsonld_remote_context_forbidden"

    def test_an_inline_term_map_inside_a_nested_array_still_passes(self):
        assert (
            scan_json_ld(
                b'{"@context": [[{"skos": "http://www.w3.org/2004/02/skos/core#"}]]}'
            )
            is None
        )


class TestRefusalMessagesUseOnlyNamedPlaceholders:
    def test_entity_bomb_message_and_its_developer_diagnostic_exemption(
        self, uses_only_named_placeholders
    ):
        with pytest.raises(UnsafeRdfXmlError) as excinfo:
            scan_rdf_xml(_read("entity_bomb.rdf"))
        err = excinfo.value
        assert isinstance(err.message, Promise)
        assert uses_only_named_placeholders(str(err.message))
        assert err.code == "rdf_xml_entities_forbidden"
        # Developer diagnostics are exempt from translation (Article XII), so the raw
        # defusedxml exception is chained rather than translated.
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
