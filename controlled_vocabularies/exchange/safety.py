"""Pre-flight scans that refuse unsafe RDF/XML and JSON-LD before rdflib reads them."""

from __future__ import annotations

import json
from typing import Any
from xml.sax import ContentHandler

import defusedxml.sax
from defusedxml.common import EntitiesForbidden, ExternalReferenceForbidden
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    UnsafeJsonLdError,
    UnsafeRdfXmlError,
)

# SkosImportError is only re-exported, so callers importing it from here keep working.
__all__ = [
    "SkosImportError",
    "UnsafeJsonLdError",
    "UnsafeRdfXmlError",
    "scan_json_ld",
    "scan_rdf_xml",
]


class DoNothingContentHandler(ContentHandler):
    """A SAX content handler that ignores every event."""


# rdflib's RDF/XML parser builds its own SAX parser and accepts none, so a defused one cannot
# be substituted. Internal entity expansion is otherwise unbounded (Article V).
def scan_rdf_xml(data: bytes) -> None:
    """Refuse ``data`` if it is unsafe RDF/XML.

    Runs the bytes through ``defusedxml.sax``, which forbids entity declarations and
    external DTD references. Ordinary RDF/XML without a DTD is unaffected. Well-formedness
    is not checked: rdflib reports its own parse errors.

    Args:
        data: The raw RDF/XML document.

    Raises:
        UnsafeRdfXmlError: The document declares an entity or references an external
            resource.
    """
    try:
        defusedxml.sax.parseString(data, DoNothingContentHandler())
    except EntitiesForbidden as exc:
        raise UnsafeRdfXmlError(
            _(
                "This RDF/XML document was refused before parsing: it declares an entity "
                "('%(name)s') that could expand into a memory-exhaustion attack or resolve "
                "an external reference."
            ),
            params={"name": exc.name or ""},
            code="rdf_xml_entities_forbidden",
        ) from exc
    except ExternalReferenceForbidden as exc:
        raise UnsafeRdfXmlError(
            _(
                "This RDF/XML document was refused before parsing: it references an "
                "external resource ('%(system_id)s') that this application does not fetch."
            ),
            params={"system_id": exc.sysid or ""},
            code="rdf_xml_external_reference_forbidden",
        ) from exc


def _refused_remote_context(value: str) -> None:
    """Raise :class:`UnsafeJsonLdError` for a remote ``@context`` reference.

    Args:
        value: The refused ``@context`` string.

    Raises:
        UnsafeJsonLdError: Always.
    """
    raise UnsafeJsonLdError(
        _(
            "This JSON-LD document was refused before parsing: its '@context' references a "
            "remote location ('%(context)s') that this application does not fetch."
        ),
        params={"context": value},
        code="jsonld_remote_context_forbidden",
    )


def _refused_context_import(value: str) -> None:
    """Raise :class:`UnsafeJsonLdError` for an ``@import`` inside a context.

    Args:
        value: The refused ``@import`` string.

    Raises:
        UnsafeJsonLdError: Always.
    """
    raise UnsafeJsonLdError(
        _(
            "This JSON-LD document was refused before parsing: an '@context' carries an "
            "'@import' reference to a location ('%(context)s') that this application does "
            "not fetch."
        ),
        params={"context": value},
        code="jsonld_context_import_forbidden",
    )


def _check_context_value(context: Any) -> None:
    """Refuse ``context`` if it is or carries a reference rdflib would fetch.

    Raises :class:`UnsafeJsonLdError` for a string, or for an object with a string
    ``@import``. Only the first offending entry is named, as :func:`scan_rdf_xml` names
    only the first problem it meets.

    Args:
        context: One value found under an ``@context`` key.
    """
    if isinstance(context, str):
        _refused_remote_context(context)
    elif isinstance(context, list):
        # rdflib recurses into nested arrays and fetches every string inside, so each entry
        # goes back through this check whatever its type (Article V).
        for entry in context:
            _check_context_value(entry)
    elif isinstance(context, dict):
        # @import is the only key in a context object that makes rdflib fetch; every other
        # key only sets local state.
        imports = context.get("@import")
        if isinstance(imports, str):
            _refused_context_import(imports)


def _iter_context_values(node: Any) -> list[Any]:
    """Collect every value keyed ``@context`` anywhere in ``node``.

    Args:
        node: A parsed JSON value.

    Returns:
        The ``@context`` values at any depth, since JSON-LD allows one per
        embedded node.
    """
    found: list[Any] = []
    if isinstance(node, dict):
        if "@context" in node:
            found.append(node["@context"])
        for value in node.values():
            found.extend(_iter_context_values(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_context_values(item))
    return found


# rdflib fetches a string @context, or an @import in any context object, through urlopen
# with no allowlist, and this package reads a file rather than a URL (Article V).
def scan_json_ld(data: bytes) -> None:
    """Refuse ``data`` if it is unsafe JSON-LD.

    Refuses any string ``@context`` (also inside an array) and any string ``@import`` inside
    a context object, wherever it appears. An inline object ``@context`` or no ``@context``
    at all is unaffected. Malformed JSON is left for rdflib to report. Raises
    :class:`UnsafeJsonLdError` for a document carrying a reference rdflib would fetch.

    Args:
        data: The raw JSON-LD document.
    """
    try:
        document = json.loads(data)
    except ValueError:
        return
    for context in _iter_context_values(document):
        _check_context_value(context)
