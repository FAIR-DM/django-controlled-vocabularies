"""Pre-flight safety scan of untrusted RDF/XML and JSON-LD (research.md R3, decisions.md D9/D36).

Article V names imported RDF as untrusted input. Measured against `rdflib` 7.6's
RDF/XML parser: external entity references do not resolve (a canary file
referenced this way parses to an empty string, nothing leaked), but internal
entity expansion is wide open — eight nested entity declarations in a ~500-byte
document expand to a single 781,250-character literal, unbounded in the
document's own size (research.md R3). That is a denial-of-service route into any
deployment that lets a curator supply a file.

`rdflib.plugins.parsers.rdfxml.create_parser` calls `xml.sax.make_parser()`
itself and accepts no parser argument, so a defused parser cannot be substituted
directly. The fix is a pre-flight scan: the raw bytes are run through
`defusedxml.sax` with a do-nothing content handler first, and only reach
`rdflib` if that returns cleanly (decisions.md D9).

`rdflib`'s JSON-LD parser carries the same shape of hole by a different route
(decisions.md D36): a document whose ``@context`` is a plain string, or an
array containing one, is resolved through `urlopen` with no allowlist —
against a remote host, or against ``file://`` and any local path the process
can read. Spec Assumptions is explicit that this feature reads "a file, not a
URL"; :func:`scan_json_ld` is the same pre-flight-refusal shape applied to
that hole, refusing any document that carries a string (rather than a
locally-embedded object) ``@context`` reference before `rdflib` ever sees it.

An inline *object* ``@context`` is not automatically safe, though (decisions.md
D47): `rdflib.plugins.shared.jsonld.context.Context._read_source` reads an
``@import`` key from any dict it treats as a context — the document's own
top-level context, an array entry, a term's own nested ``@context``, or a
node's own ``@context`` inside ``@graph`` — and resolves a string value
through the identical `urlopen`-backed fetch a string ``@context`` uses.
:func:`scan_json_ld` refuses that too, wherever in the document it appears.
"""

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

# SkosImportError is re-exported rather than used here: it was defined in this
# module until the hierarchy moved to exceptions.py, so callers importing it
# from `exchange.safety` keep working.
__all__ = [
    "SkosImportError",
    "UnsafeJsonLdError",
    "UnsafeRdfXmlError",
    "scan_json_ld",
    "scan_rdf_xml",
]


class DoNothingContentHandler(ContentHandler):
    """A content handler with no behaviour.

    The scan exists only to let `defusedxml`'s guards fire during parsing; it
    never needs to extract or hold anything from the document.
    """


def scan_rdf_xml(data: bytes) -> None:
    """Refuse ``data`` before it reaches rdflib if it is unsafe RDF/XML (research.md R3).

    Runs ``data`` through `defusedxml.sax` with a do-nothing handler, which
    forbids entity declarations and external references by default (an ordinary
    RDF/XML document — one with no DTD at all — is unaffected). Raises
    :class:`UnsafeRdfXmlError`, naming the cause with a named placeholder
    (Article XII), for a document that declares any entity (the internal
    expansion route, and — since declaring one is enough — the external-entity
    route the same construct carries) or that references an external DTD
    subset. Returns ``None`` for a document that triggers neither.

    This does not check that ``data`` is well-formed or valid RDF/XML — only
    that it is safe to hand to `rdflib`, which reports its own parse errors for
    a document that fails on those grounds instead.
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
    raise UnsafeJsonLdError(
        _(
            "This JSON-LD document was refused before parsing: its '@context' references a "
            "remote location ('%(context)s') that this application does not fetch."
        ),
        params={"context": value},
        code="jsonld_remote_context_forbidden",
    )


def _refused_context_import(value: str) -> None:
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
    """Refuse ``context`` if it is, contains, or carries a fetch-triggering reference
    (decisions.md D36/D47).

    A plain string ``@context`` names a location for rdflib to fetch and parse
    itself — the first vector this scan closes. An array ``@context`` may
    freely mix inline objects with string references, dict entries, and further
    arrays, so every entry is passed back through this function whatever its
    type; only the first offending entry is named in the refusal, consistent
    with :func:`scan_rdf_xml` naming only the first problem it meets.

    That recursion is the point, not tidiness (SEC-701, decisions.md D19). The
    array branch used to check only ``str`` and ``dict`` entries, and
    ``Context._prep_sources`` recurses into a nested array and hands each
    string inside it to ``_fetch_context``. So ``{"@context": [["http://…"]]}``
    passed the scan and was fetched, as did the same shape wrapping an
    ``@import`` object, while the flat forms either side of it were correctly
    refused.

    A ``dict`` — an inline, locally-embedded context, the ordinary shape of a
    published file — was previously left alone entirely on the reasoning that
    it "carries nothing to resolve". That was false (decisions.md D47):
    `rdflib.plugins.shared.jsonld.context.Context._read_source` reads
    ``source.get('@import')`` from *any* dict it treats as a context — the
    document's own top-level one, an array entry, a term's own nested
    ``@context``, or a node's own ``@context`` inside ``@graph`` (every one of
    those shapes reaches ``_read_source`` the same way, and
    :func:`_iter_context_values` already finds every ``@context``-keyed value
    anywhere in the document, nested or not) — and resolves a string
    ``@import`` value through the identical `urlopen`-backed
    ``_fetch_context``/``source_to_json`` path a string ``@context`` uses. So
    a dict is checked for that key too. Every *other* dict-shaped context
    construct rdflib's own ``_read_source`` reads (``@vocab``, ``@version``,
    ``@base``, ``@propagate``, ``@protected``, term definitions and their
    ``@id``/``@type``/``@container``/etc.) only ever assigns local state or
    calls :func:`_rec_expand`/:func:`_prep_expand`, neither of which reaches
    `source_to_json` or `urlopen` — ``@import`` is the only key in a context
    object that triggers a fetch, so it is the only one guarded here.
    ``None`` (no ``@context`` at all) carries nothing to resolve either and is
    left alone.
    """
    if isinstance(context, str):
        _refused_remote_context(context)
    elif isinstance(context, list):
        for entry in context:
            _check_context_value(entry)
    elif isinstance(context, dict):
        imports = context.get("@import")
        if isinstance(imports, str):
            _refused_context_import(imports)


def _iter_context_values(node: Any) -> list[Any]:
    """Every value keyed ``@context`` anywhere in ``node`` (JSON-LD allows one
    per embedded node object, not only at the document's top level).
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


def scan_json_ld(data: bytes) -> None:
    """Refuse ``data`` before it reaches rdflib if it is unsafe JSON-LD (decisions.md D36).

    rdflib's JSON-LD parser resolves a string ``@context`` — at the document's
    top level, or nested inside any embedded node object — through `urlopen`,
    with no allowlist: a remote host, or a ``file://``/local-path reference,
    is fetched or read exactly as if the caller had asked for it, when all
    the caller actually supplied was the document doing the asking. Raises
    :class:`UnsafeJsonLdError`, naming the refused reference with a named
    placeholder (Article XII), for any string ``@context`` value, including
    one inside an array ``@context``. An inline, locally-embedded object
    ``@context`` — the ordinary shape of a published file — is unaffected,
    and so is a document with no ``@context`` at all.

    This does not check that ``data`` is well-formed or valid JSON-LD — only
    that it is safe to hand to `rdflib`. Malformed JSON is left for rdflib's
    own parser to report, the same division :func:`scan_rdf_xml` draws
    against a malformed RDF/XML document.
    """
    try:
        document = json.loads(data)
    except ValueError:
        return
    for context in _iter_context_values(document):
        _check_context_value(context)
