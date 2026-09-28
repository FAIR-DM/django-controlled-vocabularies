"""Tests for controlled_vocabularies.management.sources."""

from __future__ import annotations

import inspect
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from controlled_vocabularies.management import sources
from controlled_vocabularies.management.sources import SourceResolver
from tests.i18n_sweep import visit_management_source


class TestHTTPStubFixture:
    def test_the_stub_serves_a_configured_status_body_and_content_type(self, http_stub):
        http_stub.set_response(
            "/vocab.ttl",
            status=200,
            body=b"@prefix skos: <http://example.org/> .",
            content_type="text/turtle",
        )
        with urllib.request.urlopen(http_stub.url + "/vocab.ttl") as response:  # noqa: S310 -- stub is localhost-only
            assert response.status == 200
            assert response.read() == b"@prefix skos: <http://example.org/> ."
            assert response.headers.get_content_type() == "text/turtle"

    def test_the_stub_serves_a_non_2xx_status(self, http_stub):
        http_stub.set_response("/missing.ttl", status=404, body=b"not found")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(http_stub.url + "/missing.ttl")  # noqa: S310 -- stub is localhost-only
        assert exc_info.value.code == 404

    def test_an_unconfigured_path_answers_404(self, http_stub):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(http_stub.url + "/never-configured.ttl")  # noqa: S310 -- stub is localhost-only
        assert exc_info.value.code == 404


class TestSourceResolverClassification:
    def test_a_value_beginning_http_is_a_url(self):
        assert SourceResolver("http://example.org/vocab.ttl").classify() == "url"

    def test_a_value_beginning_https_case_insensitively_is_a_url(self):
        assert SourceResolver("HTTPS://host/v.ttl").classify() == "url"

    def test_a_bare_relative_filename_is_a_path(self):
        assert SourceResolver("vocab.ttl").classify() == "path"

    def test_a_windows_drive_letter_is_a_path_not_a_one_letter_scheme(self):
        assert SourceResolver("C:/vocab/skos.ttl").classify() == "path"

    def test_an_absolute_unix_path_is_a_path(self):
        assert SourceResolver("/srv/vocab/skos.ttl").classify() == "path"

    def test_an_unsupported_scheme_is_refused_naming_the_scheme(self):
        with pytest.raises(CommandError) as exc_info:
            SourceResolver("ftp://host/v.ttl").classify()
        assert "ftp" in str(exc_info.value)


class TestSourceResolverFetch:
    def test_a_served_document_is_fetched_to_a_temporary_file_with_the_url_as_base_uri(
        self, http_stub
    ):
        http_stub.set_response(
            "/vocab.ttl", status=200, body=b"stub body", content_type="text/turtle"
        )
        url = http_stub.url + "/vocab.ttl"
        resolver = SourceResolver(url, serialization="turtle")
        resolved = resolver.resolve()
        try:
            assert Path(resolved.path).read_bytes() == b"stub body"
            assert resolved.base_uri == url
            assert resolved.serialization == "turtle"
        finally:
            resolver.cleanup()

    def test_a_non_2xx_status_is_refused_naming_the_url(self, http_stub):
        http_stub.set_response("/vocab.ttl", status=500, body=b"boom")
        url = http_stub.url + "/vocab.ttl"
        resolver = SourceResolver(url, serialization="turtle")
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        assert url in str(exc_info.value)

    def test_the_temporary_file_does_not_survive_cleanup(self, http_stub):
        http_stub.set_response("/vocab.ttl", status=200, body=b"stub body")
        resolver = SourceResolver(http_stub.url + "/vocab.ttl", serialization="turtle")
        resolved = resolver.resolve()
        resolver.cleanup()
        assert not Path(resolved.path).exists()

    def test_a_redirect_to_another_http_url_is_followed(self, http_stub):
        http_stub.set_response(
            "/redirect.ttl",
            status=302,
            headers={"Location": http_stub.url + "/target.ttl"},
        )
        http_stub.set_response(
            "/target.ttl",
            status=200,
            body=b"redirected body",
            content_type="text/turtle",
        )
        resolver = SourceResolver(
            http_stub.url + "/redirect.ttl", serialization="turtle"
        )
        resolved = resolver.resolve()
        try:
            assert Path(resolved.path).read_bytes() == b"redirected body"
            # The base URI is the address the document was served from, not the one
            # typed.
            assert resolved.base_uri == http_stub.url + "/target.ttl"
        finally:
            resolver.cleanup()

    def test_a_fetch_with_no_redirect_reports_the_address_it_was_given(self, http_stub):
        http_stub.set_response(
            "/vocab.ttl", status=200, body=b"body", content_type="text/turtle"
        )
        resolver = SourceResolver(http_stub.url + "/vocab.ttl", serialization="turtle")
        resolved = resolver.resolve()
        try:
            assert resolved.base_uri == http_stub.url + "/vocab.ttl"
        finally:
            resolver.cleanup()

    def test_a_redirect_target_names_the_serialization_the_typed_address_does_not(
        self, http_stub
    ):
        # An extensionless redirecting address (a PURL, a w3id) landing on a ".ttl" is
        # the ordinary publishing shape. No --format and no Content-Type, so only the
        # served address's extension can answer.
        http_stub.set_response(
            "/latest", status=302, headers={"Location": http_stub.url + "/v2/rocks.ttl"}
        )
        http_stub.set_response("/v2/rocks.ttl", status=200, body=b"body")
        resolver = SourceResolver(http_stub.url + "/latest")
        resolved = resolver.resolve()
        try:
            assert resolved.serialization == "turtle"
        finally:
            resolver.cleanup()

    def test_a_redirect_to_a_non_http_scheme_is_refused_without_opening_a_connection(
        self, http_stub
    ):
        http_stub.set_response(
            "/redirect.ttl",
            status=302,
            headers={"Location": "ftp://10.255.255.1/vocab.ttl"},
        )
        url = http_stub.url + "/redirect.ttl"
        resolver = SourceResolver(url, serialization="turtle")
        started = time.monotonic()
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        elapsed = time.monotonic() - started
        # A real connection to a non-routable host would not fail this fast: the opener
        # has no ftp handler, so none is attempted
        # (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).
        assert elapsed < 1.0
        assert url in str(exc_info.value)

    def test_a_response_exceeding_the_byte_ceiling_is_abandoned_and_writes_nothing(
        self, http_stub, monkeypatch
    ):
        monkeypatch.setattr(sources, "_MAX_RESPONSE_BYTES", 16)
        url = http_stub.url + "/big.ttl"
        http_stub.set_response(
            "/big.ttl", status=200, body=b"x" * 1000, content_type="text/turtle"
        )
        resolver = SourceResolver(url, serialization="turtle")
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        assert url in str(exc_info.value)
        temp_path = resolver._temp_path
        assert temp_path is not None
        resolver.cleanup()
        assert not temp_path.exists()

    def test_a_transfer_exceeding_the_total_deadline_is_abandoned(
        self, http_stub, monkeypatch
    ):
        # The read timeout is per read and the byte ceiling counts bytes, so a slow
        # trickle escapes both and only the total deadline stops it. The deadline is
        # shortened here rather than the trickle slowed.
        monkeypatch.setattr(sources, "_MAX_TOTAL_SECONDS", 0)
        url = http_stub.url + "/slow.ttl"
        http_stub.set_response(
            "/slow.ttl", status=200, body=b"x" * 1000, content_type="text/turtle"
        )
        resolver = SourceResolver(url, serialization="turtle")
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        assert url in str(exc_info.value)
        temp_path = resolver._temp_path
        assert temp_path is not None
        resolver.cleanup()
        assert not temp_path.exists()

    def test_an_ordinary_fetch_is_well_inside_the_total_deadline(self, http_stub):
        http_stub.set_response(
            "/vocab.ttl", status=200, body=b"x" * 1000, content_type="text/turtle"
        )
        resolver = SourceResolver(http_stub.url + "/vocab.ttl", serialization="turtle")
        started = time.monotonic()
        resolver.resolve()
        resolver.cleanup()
        assert time.monotonic() - started < sources._MAX_TOTAL_SECONDS


class TestSourceResolverSerializationLadder:
    def test_explicit_format_wins_over_the_url_extension(self, http_stub):
        # ".rdf" would guess "xml" (rdflib.util.guess_format) — the explicit value must
        # win.
        http_stub.set_response(
            "/vocab.rdf",
            status=200,
            body=b"stub body",
            content_type="application/rdf+xml",
        )
        resolver = SourceResolver(http_stub.url + "/vocab.rdf", serialization="turtle")
        resolved = resolver.resolve()
        try:
            assert resolved.serialization == "turtle"
        finally:
            resolver.cleanup()

    def test_the_url_extension_is_used_when_no_format_is_given(self, http_stub):
        # No Content-Type, so only the URL's ".ttl" extension can decide this.
        http_stub.set_response("/vocab.ttl", status=200, body=b"stub body")
        resolver = SourceResolver(http_stub.url + "/vocab.ttl")
        resolved = resolver.resolve()
        try:
            assert resolved.serialization == "turtle"
        finally:
            resolver.cleanup()

    def test_the_content_type_is_used_when_the_url_has_no_recognisable_extension(
        self, http_stub
    ):
        http_stub.set_response(
            "/download",
            status=200,
            body=b"stub body",
            content_type="application/rdf+xml",
        )
        resolver = SourceResolver(http_stub.url + "/download")
        resolved = resolver.resolve()
        try:
            assert resolved.serialization == "xml"
        finally:
            resolver.cleanup()

    def test_json_ld_content_type_is_recognised(self, http_stub):
        http_stub.set_response(
            "/download", status=200, body=b"{}", content_type="application/ld+json"
        )
        resolver = SourceResolver(http_stub.url + "/download")
        resolved = resolver.resolve()
        try:
            assert resolved.serialization == "json-ld"
        finally:
            resolver.cleanup()

    def test_neither_extension_nor_content_type_is_refused_naming_format(
        self, http_stub
    ):
        http_stub.set_response(
            "/download",
            status=200,
            body=b"stub body",
            content_type="application/octet-stream",
        )
        resolver = SourceResolver(http_stub.url + "/download")
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        assert "--format" in str(exc_info.value)
        resolver.cleanup()


class TestSourcesI18nSweep:
    def test_every_output_string_is_translatable_with_named_placeholders(self):
        source = Path(inspect.getfile(sources)).read_text()
        visitor = visit_management_source(source)
        assert visitor.positional_placeholders == [], (
            f"{sources.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
        assert visitor.bare_literals == [], (
            f"{sources.__name__} passes a bare, untranslated literal to an output sink: {visitor.bare_literals}"
        )
