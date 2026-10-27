"""Shared pytest fixtures and a local HTTP stub."""

import http.server
import socket
import threading

import pytest
import rdflib
import rdflib.parser
import rdflib.plugin
from rdflib.compare import isomorphic
from rdflib.namespace import XSD

from tests.factories import ConceptSchemeFactory, RecordFactory


@pytest.fixture
def scheme(db):
    return ConceptSchemeFactory()


@pytest.fixture
def concept(db):
    return RecordFactory()


@pytest.fixture
def multilingual_scheme(db):
    """A vocabulary holding one concept named and defined in English and German."""
    scheme = ConceptSchemeFactory()
    RecordFactory(
        scheme=scheme,
        data={
            "skos:prefLabel": [
                {"@value": "Granite", "@language": "en"},
                {"@value": "Granit", "@language": "de"},
            ],
            "skos:definition": [
                {"@value": "A coarse-grained igneous rock.", "@language": "en"},
                {"@value": "Ein grobkörniges Tiefengestein.", "@language": "de"},
            ],
        },
    )
    RecordFactory(scheme=scheme)
    return scheme


@pytest.fixture
def with_sessions(settings):
    """Install the session, authentication and message middleware the test project omits."""
    settings.MIDDLEWARE = [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]


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
        """Record the request's headers, then send the response configured for the path, or 404."""
        self.server.request_headers.append(dict(self.headers))  # type: ignore[attr-defined]
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

    @property
    def request_headers(self) -> list[dict[str, str]]:
        """The headers of every request the server has answered, in order."""
        return self._server.request_headers  # type: ignore[attr-defined]

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
    server.request_headers = []  # type: ignore[attr-defined]
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


class RdfReadBack:
    """Read serialized RDF back into statements so two renderings can be compared."""

    @staticmethod
    def parse(serialization, data):
        """Parse serialized bytes into one graph holding the statements of all its graphs.

        The parser is the one rdflib registers under the serialization's name, else the
        one registered under its media type.

        Args:
            serialization: The ``Serialization`` the bytes were written in.
            data: The serialized bytes.

        Returns:
            A graph of every statement, whichever graph of the document held it.
        """
        for name in (serialization.name, serialization.media_type):
            try:
                rdflib.plugin.get(name, rdflib.parser.Parser)
            except rdflib.plugin.PluginException:
                continue
            break
        dataset = rdflib.Dataset()
        dataset.parse(data=data, format=name)
        statements = rdflib.Graph()
        for subject, predicate, obj, _graph in dataset.quads():
            statements.add((subject, predicate, obj))
        return statements

    @staticmethod
    def plain(graph):
        """Return a copy of ``graph`` with every ``xsd:string`` literal made plain.

        Args:
            graph: The graph to normalise.

        Returns:
            The copy.
        """
        normalised = rdflib.Graph()
        for subject, predicate, obj in graph:
            if isinstance(obj, rdflib.Literal) and obj.datatype == XSD.string:
                obj = rdflib.Literal(str(obj))
            normalised.add((subject, predicate, obj))
        return normalised

    @classmethod
    def same_statements(cls, left, right):
        """Return whether two graphs state the same thing, treating blank nodes as unnamed.

        Args:
            left: One graph.
            right: The other.

        Returns:
            True when they are isomorphic once ``xsd:string`` literals are made plain.
        """
        return isomorphic(cls.plain(left), cls.plain(right))

    @classmethod
    def survives(cls, serialization, graph):
        """Return whether a graph written in a serialization reads back unchanged.

        Args:
            serialization: The ``Serialization`` to write in.
            graph: The graph to write.

        Returns:
            True when the output parses back to the same statements.
        """
        return cls.same_statements(
            cls.parse(serialization, serialization.serialize(graph)), graph
        )


@pytest.fixture
def rdf_read_back():
    return RdfReadBack
