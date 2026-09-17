"""``controlled_vocabularies.management.sources`` — classifying and, for a URL, fetching a
management-command source (T007-T009, plan.md "Source resolution", research.md R3/R4).

The ``http_stub`` and ``hanging_socket`` fixtures (``tests/conftest.py``, T006, research.md R8)
are proven here first, before :class:`SourceResolver` exists to exercise them — no real network
call is made anywhere in this file.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from controlled_vocabularies.management import sources
from controlled_vocabularies.management.sources import SourceResolver


class TestHTTPStubFixture:
    """T006 — the stub itself, exercised directly rather than tested in isolation."""

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

    # CORR-003 (review, correctness): test_each_test_gets_a_fresh_server_on_its_own_port
    # was deleted here. It was a byte-for-byte duplicate of the success case above minus
    # the status and content-type assertions, and it recorded no port and referenced no
    # prior server, so it could not distinguish a torn-down stub from a leaked one —
    # deleting conftest's try/finally left it green. The honest replacement, probing the
    # previous test's port, is flaky by construction: an ephemeral port the OS has since
    # handed to another process reads as a leak. A test that cannot fail for its own
    # reason and can fail for someone else's is worth less than the two lines it costs.


class TestSourceResolverClassification:
    """T007, research.md R3, decisions.md D3 — classifying a raw source argument, with no
    fetch and no filesystem access, so every case here is exercised with no real network call."""

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
    """T008, research.md R3 — the fetch: an opener carrying only the http/https handlers,
    a byte ceiling, a temporary file, and cleanup on both the success and the failure path.
    No real network call: every case is served by ``http_stub``."""

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
            # CORR-001 (review, correctness): the base URI is the address the document was
            # served from, not the one typed. This test asserted only on the bytes, so
            # nothing pinned which of the two a redirected fetch reported.
            assert resolved.base_uri == http_stub.url + "/target.ttl"
        finally:
            resolver.cleanup()

    def test_a_fetch_with_no_redirect_reports_the_address_it_was_given(self, http_stub):
        # The control for the line above: taking the base URI off the response must not
        # change what an ordinary, unredirected fetch reports.
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
        # The second half of CORR-001: an extensionless redirecting address (a PURL, a
        # w3id) landing on a ".ttl" is the ordinary publishing shape. Guessing from the
        # typed address finds no extension and falls through; guessing from the served
        # address reads it straight off. No --format and no Content-Type here, so the
        # extension is the only thing that can answer.
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
        # A real connection attempt to a non-routable host would not fail this fast — the
        # opener has no handler for ftp at all, so no connection is ever attempted (research.md R3).
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
        # SEC-703 (review, security): neither of the other two bounds catches a server
        # that answers continuously but slowly. The read timeout is per read, so a
        # trickle resets it forever, and the byte ceiling counts bytes a trickle never
        # sends. Measured before this bound existed: 65 seconds elapsed, 3 bytes
        # transferred, still running. The deadline is shortened here rather than the
        # trickle slowed, so the test costs a fraction of a second.
        monkeypatch.setattr(sources, "_MAX_TOTAL_SECONDS", 0)
        url = http_stub.url + "/slow.ttl"
        http_stub.set_response(
            "/slow.ttl", status=200, body=b"x" * 1000, content_type="text/turtle"
        )
        resolver = SourceResolver(url, serialization="turtle")
        with pytest.raises(CommandError) as exc_info:
            resolver.resolve()
        assert url in str(exc_info.value)
        assert "too long" in str(exc_info.value)
        temp_path = resolver._temp_path
        assert temp_path is not None
        resolver.cleanup()
        assert not temp_path.exists()

    def test_an_ordinary_fetch_is_well_inside_the_total_deadline(self, http_stub):
        # The control: the deadline must be a stop for a pathological server, not a
        # bound an ordinary local fetch can approach.
        http_stub.set_response(
            "/vocab.ttl", status=200, body=b"x" * 1000, content_type="text/turtle"
        )
        resolver = SourceResolver(http_stub.url + "/vocab.ttl", serialization="turtle")
        started = time.monotonic()
        resolver.resolve()
        resolver.cleanup()
        assert time.monotonic() - started < sources._MAX_TOTAL_SECONDS


class TestSourceResolverSerializationLadder:
    """T009, research.md R4 — resolving a fetched document's serialization: explicit
    ``--format``, then the URL's own extension, then the response ``Content-Type``, then a
    refusal naming ``--format`` as the way out."""

    def test_explicit_format_wins_over_the_url_extension(self, http_stub):
        # ".rdf" would guess "xml" (rdflib.util.guess_format) — the explicit value must win.
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
        # No Content-Type at all — only the URL's ".ttl" extension can decide this.
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
