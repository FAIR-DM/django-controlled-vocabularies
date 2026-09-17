"""Classifying and, for a URL, fetching a management-command source (T007-T009, plan.md
"Source resolution", research.md R3/R4, decisions.md D3).

:class:`SourceResolver` takes the raw ``source`` argument and answers what it is, before
:class:`~controlled_vocabularies.management.commands.import_skos.Command` acts on it. A
one-character parsed scheme is a Windows drive letter (``urlsplit("C:/vocab.ttl").scheme``
is ``"c"``), not a network protocol, so it is not mistaken for one (research.md R3).
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import (
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    UnknownHandler,
)

import rdflib.util
from django.core.management.base import CommandError
from django.utils.translation import gettext_lazy as _

_URL_PREFIXES = ("http://", "https://")

# The three serializations this application reads (matches exchange/skos.py's own
# _SUPPORTED_FORMATS), mapped from a response's Content-Type for the third rung of the
# serialization ladder (T009, research.md R4). rdflib.util.guess_format knows nothing about
# media types, so this mapping is the resolver's own.
_CONTENT_TYPE_SERIALIZATIONS = {
    "text/turtle": "turtle",
    "application/rdf+xml": "xml",
    "application/ld+json": "json-ld",
}

# One socket-read timeout and one byte ceiling, neither configurable (plan.md "Source
# resolution"). The operator cannot see how long a publisher takes to answer or how much
# it intends to send, so both bound what the remote server chooses rather than an operator
# mistake (craft-security "always/ask/never" — DoS via an unbounded transfer). Both are set
# against real published vocabularies rather than the test fixtures: a large vocabulary is
# often generated per request, so first-byte latency of several seconds is ordinary, and the
# widely-vendored thesauri run to tens of megabytes in RDF/XML. The values catch a server that
# has stopped answering or does not intend to stop sending, not a slow or large publisher.
_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 64 * 1024
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MiB

# The third bound, and the one the other two do not cover (SEC-703, decisions.md D21).
# _TIMEOUT_SECONDS is a per-socket-read timeout and _MAX_RESPONSE_BYTES counts bytes, so a
# server that answers continuously but slowly — one byte every few seconds — resets the read
# timeout forever and never approaches the ceiling. Measured on the branch before this: a
# stub trickling one byte per 20s was still being read after 65 seconds having transferred
# 3 bytes, and would never have stopped. Generous against the same real vocabularies the
# other two are sized against: 50 MiB inside ten minutes is 85 KiB/s, slower than any
# publisher this command is pointed at, and it is a stop rather than a rate limit.
_MAX_TOTAL_SECONDS = 600  # 10 minutes

# An opener carrying only the http/https handlers (T008, research.md R3): a handler
# removed, not a check added. Python's default opener's HTTPRedirectHandler permits a
# redirect onto ftp as well as http/https, and checking the final URL on the response
# object happens only after urllib has already connected and pulled the body — this
# opener has no handler for any other scheme, so it fails before a connection is attempted.
#
# Built via OpenerDirector().add_handler(...) rather than build_opener(...): build_opener
# always merges its own default handlers (FTPHandler, FileHandler, DataHandler, ...) for
# every protocol not explicitly overridden by an instance of the *same* default class, so
# build_opener(HTTPHandler, HTTPSHandler, HTTPRedirectHandler, HTTPErrorProcessor) still
# carries a live FTPHandler — confirmed by inspecting opener.handlers and by a redirect to
# ftp://10.255.255.1/... actually reaching ftplib's connect and timing out on it, which is
# the real network call this design exists to prevent (decisions.md D15). UnknownHandler is
# added so a scheme with no registered handler raises URLError immediately rather than
# OpenerDirector.open() silently returning None. HTTPDefaultErrorHandler is added for the
# same reason: without it, HTTPErrorProcessor's own non-2xx handling has nothing registered
# to call and OpenerDirector.open() returns None for a 404/500 instead of raising HTTPError
# (found by this task's own failing test, T010).
_opener = OpenerDirector()
for _handler_class in (
    HTTPHandler,
    HTTPSHandler,
    HTTPRedirectHandler,
    HTTPErrorProcessor,
    UnknownHandler,
    HTTPDefaultErrorHandler,
):
    _opener.add_handler(_handler_class())


@dataclass
class ResolvedSource:
    """What :class:`SourceResolver` hands the importer: a local path, plus the base URI
    and serialization a fetched document carries (``None`` for a local path, which keeps
    ``from_file``'s own defaults, T007-T009)."""

    path: str
    base_uri: str | None
    serialization: str | None


@dataclass
class Fetched:
    path: Path
    content_type: str | None
    #: The address the document was actually served from, which differs from the one the
    #: operator typed whenever a redirect was followed (CORR-001, decisions.md D20).
    final_url: str


class SourceResolver:
    """Classify ``source`` and, for a URL, fetch it into a local file (T007-T009)."""

    def __init__(self, source: str, *, serialization: str | None = None) -> None:
        self.source = source
        self.serialization = serialization
        self._temp_path: Path | None = None

    def classify(self) -> str:
        """Return ``"url"`` or ``"path"`` for :attr:`source` (T007, research.md R3).

        A value beginning ``http://``/``https://``, case-insensitively, is a URL. Anything
        else is a path unless its parsed scheme is longer than one character, which is
        refused as an unsupported source.
        """
        if self.source.lower().startswith(_URL_PREFIXES):
            return "url"
        scheme = urlsplit(self.source).scheme
        if len(scheme) <= 1:
            return "path"
        raise CommandError(
            str(
                _(
                    "'%(source)s' names a source this command does not support ('%(scheme)s' is not http or https)."
                )
            )
            % {"source": self.source, "scheme": scheme}
        )

    def resolve(self) -> ResolvedSource:
        """Classify :attr:`source` and, for a URL, fetch it (T007-T009).

        The caller is responsible for calling :meth:`cleanup` once it is done with the
        result, whether or not the import that follows succeeds (plan.md "Source
        resolution").
        """
        if self.classify() == "path":
            return ResolvedSource(
                path=self.source, base_uri=None, serialization=self.serialization
            )
        fetched = self._fetch()
        serialization = self._resolve_serialization(fetched)
        return ResolvedSource(
            path=str(fetched.path),
            base_uri=fetched.final_url,
            serialization=serialization,
        )

    def _retrieval_error(self, exc: OSError) -> CommandError:
        """The one message for a retrieval that could not complete (T008, T010, FR-014).

        Opening the connection and reading the body fail the same way from the operator's
        side — an unreachable host, a non-2xx status, a timed-out read — so both raise
        through here rather than each building the message itself.
        """
        return CommandError(
            str(_("'%(source)s' could not be retrieved: %(error)s"))
            % {"source": self.source, "error": exc}
        )

    def _fetch(self) -> Fetched:
        """Fetch :attr:`source` to a temporary file under a timeout and a byte ceiling
        (T008, research.md R3)."""
        try:
            response = _opener.open(self.source, timeout=_TIMEOUT_SECONDS)
        except OSError as exc:
            raise self._retrieval_error(exc) from exc
        with response:
            content_type = response.headers.get_content_type()
            # The address the response actually came from, not the one asked for
            # (CORR-001, decisions.md D20). A vocabulary is very often published behind a
            # redirecting address — a PURL, a w3id, a "/latest" alias — and RFC 3986 §5.1.3
            # makes the *final* URL the base a relative identifier resolves against. Taking
            # the typed address instead stored every relative identifier under a URI its
            # publisher never assigned, so a later import from the canonical address created
            # a second copy of the whole vocabulary — the outcome D10 exists to prevent.
            final_url = response.url
            fd, name = tempfile.mkstemp()
            self._temp_path = Path(name)
            written = 0
            started = time.monotonic()
            with os.fdopen(fd, "wb") as tmp:
                while True:
                    try:
                        chunk = response.read(_CHUNK_SIZE)
                    except OSError as exc:
                        raise self._retrieval_error(exc) from exc
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _MAX_RESPONSE_BYTES:
                        raise CommandError(
                            str(
                                _(
                                    "'%(source)s' exceeded the maximum response size and was abandoned."
                                )
                            )
                            % {"source": self.source}
                        )
                    if time.monotonic() - started > _MAX_TOTAL_SECONDS:
                        raise CommandError(
                            str(
                                _(
                                    "'%(source)s' took too long to transfer and was abandoned."
                                )
                            )
                            % {"source": self.source}
                        )
                    tmp.write(chunk)
        return Fetched(
            path=self._temp_path, content_type=content_type, final_url=final_url
        )

    def _resolve_serialization(self, fetched: Fetched) -> str:
        """Resolve a fetched document's serialization (T009, research.md R4): explicit
        ``--format``, then the URL path's extension, then the response ``Content-Type``,
        then a refusal naming what could not be determined. ``from_file``'s own extension
        guess is never consulted for a fetched document — the value here is always passed
        through explicitly, or the run is refused before it gets there.
        """
        if self.serialization:
            return self.serialization
        # Guessed from the address the document was served from, for the same reason the
        # base URI is (CORR-001, decisions.md D20): an extensionless PURL redirecting to a
        # ".ttl" is the ordinary shape, and guessing from the typed address would fall
        # through to Content-Type or a refusal for a source that names its format plainly.
        guessed = rdflib.util.guess_format(urlsplit(fetched.final_url).path)
        if guessed:
            return guessed
        mapped = _CONTENT_TYPE_SERIALIZATIONS.get(fetched.content_type or "")
        if mapped:
            return mapped
        raise CommandError(
            str(
                _(
                    "'%(source)s' does not name a serialization this application recognises "
                    "(Turtle, RDF/XML, or JSON-LD). Pass --format to state it."
                )
            )
            % {"source": self.source}
        )

    def cleanup(self) -> None:
        """Remove the temporary file a fetch wrote, if any (T008). A no-op for a local
        path source, and safe to call more than once."""
        if self._temp_path is not None:
            self._temp_path.unlink(missing_ok=True)
