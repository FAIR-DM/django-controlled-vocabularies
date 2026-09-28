"""Classifying a command source and fetching it when it is a URL (FS-008)."""

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

# rdflib.util.guess_format knows nothing about media types.
_CONTENT_TYPE_SERIALIZATIONS = {
    "text/turtle": "turtle",
    "application/rdf+xml": "xml",
    "application/ld+json": "json-ld",
}

# Neither is configurable: they bound what the remote server chooses, sized for real
# published vocabularies (tens of megabytes, seconds to first byte), not for test fixtures
# (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).
_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 64 * 1024
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MiB

# A server trickling one byte every few seconds resets the read timeout forever and never
# nears the byte ceiling, so the transfer also has a total deadline (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).
_MAX_TOTAL_SECONDS = 600  # 10 minutes

# Built by hand, not with build_opener, which merges FTPHandler and other default handlers
# back in. UnknownHandler and HTTPDefaultErrorHandler make an unhandled scheme or a non-2xx
# status raise instead of open() returning None (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).
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
    """What :class:`SourceResolver` hands the importer.

    Attributes:
        path: The local path to read.
        base_uri: The address a fetched document was served from, or ``None`` for a local
            path, which keeps ``from_file``'s own defaults.
        serialization: The serialization to read it as, or ``None`` for a local path with
            none named.
    """

    path: str
    base_uri: str | None
    serialization: str | None


@dataclass
class Fetched:
    """A document fetched to a temporary file.

    Attributes:
        path: The temporary file holding the body.
        content_type: The response's media type, if it named one.
        final_url: The address the document was served from, which differs from the one
            typed whenever a redirect was followed.
    """

    path: Path
    content_type: str | None
    final_url: str


class SourceResolver:
    """Classify a command's ``source`` and, for a URL, fetch it into a local file.

    Args:
        source: The raw ``source`` argument: a local path or an http(s) URL.
        serialization: The serialization named with ``--format``, if any.
    """

    def __init__(self, source: str, *, serialization: str | None = None) -> None:
        self.source = source
        self.serialization = serialization
        self._temp_path: Path | None = None

    def classify(self) -> str:
        """Classify :attr:`source` as a URL or a path.

        A value starting ``http://`` or ``https://``, in any case, is a URL. Anything else is
        a path, unless its parsed scheme is longer than one character. A one-character scheme
        is a Windows drive letter such as ``C:``, not a protocol.

        Returns:
            ``"url"`` or ``"path"``.

        Raises:
            CommandError: The source names a scheme other than http or https.
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
        """Classify :attr:`source` and, for a URL, fetch it and settle its serialization.

        The caller must call :meth:`cleanup` once done with the result, whether or not the
        import that follows succeeds.

        Returns:
            The local path to import, with the base URI and serialization
            a fetched document carries.
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
        """Build the one error for a retrieval that could not complete.

        Opening the connection and reading the body fail the same way from the operator's
        side, so both raise through here.

        Args:
            exc: The underlying failure.

        Returns:
            The error to raise.
        """
        return CommandError(
            str(_("'%(source)s' could not be retrieved: %(error)s"))
            % {"source": self.source, "error": exc}
        )

    def _fetch(self) -> Fetched:
        """Fetch :attr:`source` to a temporary file under a timeout and a byte ceiling.

        Returns:
            The temporary file with the response's media type and final URL.

        Raises:
            CommandError: The response was too large or took too long.
            self._retrieval_error: Opening the connection or reading the body failed, as a
                ``CommandError`` built by :meth:`_retrieval_error`.
        """
        try:
            response = _opener.open(self.source, timeout=_TIMEOUT_SECONDS)
        except OSError as exc:
            raise self._retrieval_error(exc) from exc
        with response:
            content_type = response.headers.get_content_type()
            # The final URL is the base a relative identifier resolves against
            # (RFC 3986 section 5.1.3, docs/adr/0006-a-document-identity-comes-from-where-it-was-published.md).
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
        """Settle a fetched document's serialization.

        Order: explicit ``--format``, the URL path's extension, the response ``Content-Type``,
        then a refusal. ``from_file``'s own extension guess is never consulted.

        Args:
            fetched: The fetched document.

        Returns:
            The serialization name to pass to rdflib.

        Raises:
            CommandError: None of the sources names a serialization.
        """
        if self.serialization:
            return self.serialization
        # Guessed from the served address, not the typed one: an extensionless PURL often
        # redirects to a ".ttl" (docs/adr/0006-a-document-identity-comes-from-where-it-was-published.md).
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
        """Remove the temporary file a fetch wrote, if any.

        A no-op for a local path, and safe to call more than once.
        """
        if self._temp_path is not None:
            self._temp_path.unlink(missing_ok=True)
