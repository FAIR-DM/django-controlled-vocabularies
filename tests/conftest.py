"""Shared pytest fixtures and a local HTTP stub."""

import http.server
import socket
import threading

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from tests.factories import ConceptFactory, ConceptSchemeFactory


@pytest.fixture
def scheme(db):
    return ConceptSchemeFactory()


@pytest.fixture
def concept(db):
    return ConceptFactory()


@pytest.fixture
def multilingual_scheme(db):
    scheme = ConceptSchemeFactory()
    ConceptFactory(scheme=scheme, multilingual=True)
    ConceptFactory(scheme=scheme)
    return scheme


@pytest.fixture
def single_language_scheme(db):
    scheme = ConceptSchemeFactory()
    ConceptFactory(scheme=scheme)
    ConceptFactory(scheme=scheme)
    return scheme


@pytest.fixture
def with_sessions(settings):
    """Install the session, authentication and message middleware the test project omits."""
    settings.MIDDLEWARE = [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]


@pytest.fixture
def make_user(db):
    """Return a factory for a user holding the named vocabulary permissions.

    Returns:
        A callable taking permission verbs (``"add"``, ``"change"``, ``"delete"``).
    """
    count = iter(range(1_000_000))

    def make(*verbs):
        user = get_user_model().objects.create_user(f"user-{next(count)}")
        user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="controlled_vocabularies",
                codename__in=[f"{verb}_conceptscheme" for verb in verbs],
            )
        )
        return user

    return make


@pytest.fixture
def curator(make_user):
    """A user who may add, change and delete vocabularies."""
    return make_user("add", "change", "delete")


@pytest.fixture
def reader(make_user):
    """A signed-in user holding no vocabulary permission."""
    return make_user()


class StubResponse:
    """One configured answer for a path on :class:`HTTPStub`.

    Args:
        status: The HTTP status code to send.
        body: The response body.
        content_type: The ``Content-Type`` header, or ``None`` to send none.
        headers: Extra headers to send.
    """

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
    """Answer GET requests from the responses configured on the server."""

    def do_GET(self) -> None:
        """Send the response configured for the path, or 404."""
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
        """Silence request logging."""


class HTTPStub:
    """A local HTTP server for exercising a fetch without a real network call.

    Responses are configured per path, so one running server can answer a success, a 404,
    a redirect and an HTML body within a single test.

    Args:
        server: The running server whose responses this stub configures.
    """

    def __init__(self, server: http.server.ThreadingHTTPServer) -> None:
        self._server = server

    @property
    def url(self) -> str:
        """The base URL the server listens on."""
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
        """Configure the response the server gives for a path.

        Args:
            path: The request path to answer.
            status: The HTTP status code to send.
            body: The response body.
            content_type: The ``Content-Type`` header, or ``None`` to send none.
            headers: Extra headers to send.
        """
        self._server.responses[path] = StubResponse(
            status, body, content_type, headers or {}
        )  # type: ignore[attr-defined]


@pytest.fixture
def http_stub():
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        sock.close()
