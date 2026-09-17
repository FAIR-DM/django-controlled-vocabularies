"""Shared pytest fixtures.

Django settings are wired via ``DJANGO_SETTINGS_MODULE`` in ``pyproject.toml``;
pytest-django handles setup/teardown from there.

The object fixtures below are thin wrappers over the model factories. A test uses
one when it needs a scheme or a concept only as a precondition. A test that asserts
on a specific derived slug or URI builds its object inline instead, since the exact
name is then the thing under test.
"""

import http.server
import socket
import threading

import pytest

from tests.factories import ConceptFactory, ConceptSchemeFactory


@pytest.fixture
def scheme(db):
    """A saved :class:`ConceptScheme` with an app-wide-unique generated name."""
    return ConceptSchemeFactory()


@pytest.fixture
def concept(db):
    """A saved :class:`Concept`, with its owning scheme auto-created."""
    return ConceptFactory()


@pytest.fixture
def multilingual_scheme(db):
    """A saved :class:`ConceptScheme` with two concepts, one of them carrying
    preferred labels in more than one language (T002; reused by #87, #88, #89
    so each does not have to build this shape itself).
    """
    scheme = ConceptSchemeFactory()
    ConceptFactory(scheme=scheme, multilingual=True)
    ConceptFactory(scheme=scheme)
    return scheme


@pytest.fixture
def single_language_scheme(db):
    """A second saved :class:`ConceptScheme`, distinct from
    :func:`multilingual_scheme`, with two concepts in the default language
    only (T002; reused by #87, #88, #89).
    """
    scheme = ConceptSchemeFactory()
    ConceptFactory(scheme=scheme)
    ConceptFactory(scheme=scheme)
    return scheme


class StubResponse:
    """One configured answer for a path on :class:`HTTPStub` (T006, research.md R8)."""

    def __init__(
        self,
        status: int,
        body: bytes,
        content_type: str | None,
        headers: dict[str, str],
    ) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers


class StubRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        response = self.server.responses.get(self.path)  # type: ignore[attr-defined]
        if response is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(response.status)
        if response.content_type is not None:
            self.send_header("Content-Type", response.content_type)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format_: str, *args: object) -> None:
        pass  # keep test output quiet — nothing here is a test failure signal


class HTTPStub:
    """A local HTTP server for exercising a fetch without a real network call (T006).

    Parameterised per path rather than per fixture instance, so one running server
    answers a success case, a 404, a redirect and an HTML body across a single test
    (research.md R8).
    """

    def __init__(self, server: http.server.ThreadingHTTPServer) -> None:
        self._server = server

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def set_response(
        self,
        path: str,
        *,
        status: int = 200,
        body: bytes = b"",
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._server.responses[path] = StubResponse(
            status, body, content_type, headers or {}
        )  # type: ignore[attr-defined]


@pytest.fixture
def http_stub():
    """A :class:`ThreadingHTTPServer` bound to port 0, serving in a background thread
    (T006, research.md R8). Torn down on teardown — no real network call anywhere in
    this story."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubRequestHandler)
    server.responses = {}  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield HTTPStub(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def hanging_socket():
    """A listening socket that accepts a connection and never answers, for the fetch
    timeout case (T006, research.md R8) — no HTTP response is ever written, so a
    client is left waiting on the response and must time out rather than hang."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        sock.close()
