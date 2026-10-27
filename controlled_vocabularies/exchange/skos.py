"""Import a published SKOS file into records and report what the run did (FS-006)."""

from __future__ import annotations

import json
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import TypeGuard

import rdflib
import rdflib.util
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rdflib.collection import Collection as RdfList
from rdflib.namespace import RDF, SKOS, XSD

from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
    UnsafeJsonLdError,
    UnsafeRdfXmlError,
)
from controlled_vocabularies.exchange.report import FatalReason, ImportReport
from controlled_vocabularies.exchange.safety import scan_json_ld, scan_rdf_xml
from controlled_vocabularies.models import ConceptScheme, Record
from controlled_vocabularies.predicates import Namespaces

# The serializations this importer reads. Anything else fails the run instead of reaching rdflib.
SUPPORTED_FORMATS = frozenset({"turtle", "xml", "json-ld"})

#: Schemes refused as an identifier, because a stored URI is rendered as a link.
UNSAFE_SCHEMES = frozenset({"javascript", "data", "vbscript"})

#: The classes that make a subject a record, lowest priority first: a subject typed with
#: several becomes the last one it matches.
RECORD_CLASSES = (
    (SKOS.Concept, Record.Type.CONCEPT),
    (SKOS.Collection, Record.Type.COLLECTION),
    (SKOS.OrderedCollection, Record.Type.ORDERED_COLLECTION),
)


class SkosImporter:
    """Run one import: read the graph, then upsert the vocabulary and its records.

    Every predicate on a subject is kept in its record's document, in every language, so
    nothing a file says is set aside. Re-running upserts: a record the file contains is
    matched by its URI, and a record it does not mention is left untouched and named in
    ``report.absent_from_source``.

    Args:
        file: Path of the SKOS file to import.
        serialization: The file's serialization (``turtle``, ``xml`` or ``json-ld``),
            guessed from its extension when omitted.
        scheme: The vocabulary to import into, for a file that declares none of its own.
        base_uri: The address a fetched document was published at, used as the parse
            base.
    """

    def __init__(
        self,
        file: str | Path,
        *,
        serialization: str | None = None,
        scheme: ConceptScheme | None = None,
        base_uri: str | None = None,
    ) -> None:
        self.file = file
        self.serialization = serialization
        self.target = scheme
        self.base_uri = base_uri
        self.report = ImportReport()

    def run(self) -> ImportReport:
        """Import the file and return the run's report.

        The whole run is one transaction. Fatal findings are collected before anything
        is written, so a file with several problems reports all of them.

        Returns:
            The report of what the run created and updated.

        Raises:
            SkosImportFailed: The run recorded a fatal finding; nothing is written.
        """
        graph = self.read_graph()
        source_label = str(self.base_uri or self.file)

        with transaction.atomic():
            declared = self.declared_scheme(graph, source_label)
            scheme_node = declared or rdflib.URIRef(
                self.target.uri if self.target else ""
            )
            nodes = self.record_nodes(graph, scheme_node)
            if self.report.fatal:
                raise SkosImportFailed(self.report)

            documents = {node: self.document(graph, node) for node in nodes}
            scheme = self.upsert_scheme(graph, declared, documents)
            held = Record.objects.in_bulk(
                [str(node) for node in nodes], field_name="uri"
            )
            claimed = self.claimed_nodes(graph, scheme_node)
            seen = set()
            for node, record_type in nodes.items():
                record = held.get(str(node))
                if record is not None and record.scheme_id != scheme.pk:
                    if node not in claimed:
                        # Described here, held by another vocabulary: its own import
                        # owns it.
                        self.report.held_elsewhere.append(str(node))
                        continue
                    # The file says the record belongs here, so its publisher moved it.
                    record.slug = ""
                self.upsert_record(scheme, node, record_type, documents[node], record)
                seen.add(str(node))
            for uri in scheme.records.values_list("uri", flat=True):
                if uri not in seen:
                    self.report.absent_from_source.append(uri)
        return self.report

    def read_graph(self) -> rdflib.Graph:
        """Read the file into a graph, scanning RDF/XML and JSON-LD first.

        The scan runs before rdflib sees the bytes
        (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).

        Returns:
            The parsed graph.

        Raises:
            SkosImportError: The file is missing, in an unsupported serialization, or cannot
                be parsed.
            UnsafeRdfXmlError: The RDF/XML document fails the safety scan.
            UnsafeJsonLdError: The JSON-LD document fails the safety scan.
        """
        path = Path(self.file)
        # A fetched document's temporary file is gone by the time an operator reads a
        # message.
        source_name = str(self.base_uri or path)
        if not path.is_file():
            raise SkosImportError(
                _("'%(file)s' could not be found."),
                params={"file": source_name},
                code="skos_file_not_found",
            )
        resolved_format = self.serialization or rdflib.util.guess_format(str(path))
        if resolved_format not in SUPPORTED_FORMATS:
            raise SkosImportError(
                _(
                    "'%(file)s' is not in a serialization this application reads (Turtle, RDF/XML, or JSON-LD)."
                ),
                params={"file": source_name},
                code="skos_format_unsupported",
            )
        graph = rdflib.Graph()
        try:
            if resolved_format == "xml":
                # Parsed from the path, not these bytes: pre-read `data=` would change the base URI.
                scan_rdf_xml(path.read_bytes())
            elif resolved_format == "json-ld":
                scan_json_ld(path.read_bytes())
            if self.base_uri is not None:
                graph.parse(str(path), format=resolved_format, publicID=self.base_uri)
            else:
                graph.parse(str(path), format=resolved_format)
        except (UnsafeRdfXmlError, UnsafeJsonLdError):
            raise
        except Exception as exc:
            raise SkosImportError(
                _("'%(file)s' could not be parsed as %(format)s: %(error)s"),
                params={
                    "file": source_name,
                    "format": resolved_format,
                    "error": str(exc),
                },
                code="skos_parse_failed",
            ) from exc
        return graph

    def declared_scheme(
        self, graph: rdflib.Graph, source_label: str
    ) -> rdflib.URIRef | None:
        """Find the scheme node the file declares, or record a fatal finding.

        Args:
            graph: The parsed graph.
            source_label: How to name the file in a finding.

        Returns:
            The declared scheme, or None when the file declares none the run can use.
        """
        nodes = sorted(set(graph.subjects(RDF.type, SKOS.ConceptScheme)), key=str)
        declared = [node for node in nodes if self.identifiable(node)]

        if self.target is not None:
            for node in declared:
                if str(node) != self.target.uri:
                    self.report.add_fatal(
                        FatalReason.VOCABULARY_TARGET_MISMATCH,
                        str(node),
                        target=self.target.uri,
                    )
            return declared[0] if declared and not self.report.fatal else None
        if not declared:
            self.report.add_fatal(FatalReason.VOCABULARY_UNDETERMINED, source_label)
        elif len(declared) > 1:
            self.report.add_fatal(
                FatalReason.VOCABULARY_AMBIGUOUS,
                source_label,
                declared=", ".join(map(str, declared)),
            )
        else:
            return declared[0]
        return None

    def record_nodes(
        self, graph: rdflib.Graph, scheme_node: rdflib.URIRef
    ) -> dict[rdflib.URIRef, str]:
        """Find the subjects that become records, and the type each becomes.

        Typed subjects are records, and so are untyped subjects that say they belong to
        the scheme. A blank node cannot be identified again on a re-import, so it is
        fatal.

        Args:
            graph: The parsed graph.
            scheme_node: The vocabulary the records belong to.

        Returns:
            The record type of each subject, in URI order.
        """
        found: dict[rdflib.term.Node, str] = {}
        for rdf_class, record_type in RECORD_CLASSES:
            found.update(
                dict.fromkeys(graph.subjects(RDF.type, rdf_class), record_type)
            )
        for predicate in (SKOS.inScheme, SKOS.topConceptOf):
            for node in graph.subjects(predicate, scheme_node):
                found.setdefault(node, Record.Type.CONCEPT)
        for node in graph.objects(scheme_node, SKOS.hasTopConcept):
            if not isinstance(node, rdflib.Literal):
                found.setdefault(node, Record.Type.CONCEPT)

        claimed = self.claimed_nodes(graph, scheme_node)
        records = {}
        for node in sorted(found, key=str):
            if not self.identifiable(node):
                continue
            if node not in claimed and self.claimed_elsewhere(graph, node, scheme_node):
                # A concept of another vocabulary, described here only to be linked to.
                self.report.held_elsewhere.append(str(node))
                continue
            records[node] = found[node]
        return records

    @staticmethod
    def claimed_nodes(
        graph: rdflib.Graph, scheme_node: rdflib.URIRef
    ) -> set[rdflib.term.Node]:
        """Return the subjects the file states belong to the vocabulary being imported.

        Args:
            graph: The parsed graph.
            scheme_node: The vocabulary being imported.

        Returns:
            Every subject naming it with ``skos:inScheme`` or ``skos:topConceptOf``, and
            every object of its ``skos:hasTopConcept``.
        """
        claimed = set(graph.subjects(SKOS.inScheme, scheme_node))
        claimed |= set(graph.subjects(SKOS.topConceptOf, scheme_node))
        claimed |= set(graph.objects(scheme_node, SKOS.hasTopConcept))
        return claimed

    @staticmethod
    def claimed_elsewhere(
        graph: rdflib.Graph, node: rdflib.term.Node, scheme_node: rdflib.URIRef
    ) -> bool:
        """Return whether the file places a subject in some other vocabulary.

        Args:
            graph: The parsed graph.
            node: The subject.
            scheme_node: The vocabulary being imported.

        Returns:
            True when the subject names a vocabulary other than ``scheme_node`` with
            ``skos:inScheme`` or ``skos:topConceptOf``, or another vocabulary lists it
            with ``skos:hasTopConcept``.
        """
        schemes = set(graph.objects(node, SKOS.inScheme))
        schemes |= set(graph.objects(node, SKOS.topConceptOf))
        schemes |= set(graph.subjects(SKOS.hasTopConcept, node))
        return bool(schemes - {scheme_node})

    def identifiable(self, node: rdflib.term.Node) -> TypeGuard[rdflib.URIRef]:
        """Return whether a subject's URI can be stored, or record a fatal finding.

        A blank node cannot be identified again on a re-import. A ``javascript:``,
        ``data:`` or ``vbscript:`` URI is refused because the pages render a record's
        URI as a link, and one longer than the ``uri`` column because the database would
        refuse it partway through the run.

        Args:
            node: The subject.

        Returns:
            Whether the subject is a usable URI.
        """
        if not isinstance(node, rdflib.URIRef):
            self.report.add_fatal(FatalReason.MISSING_IDENTITY, str(node))
            return False
        if urllib.parse.urlsplit(str(node)).scheme.lower() in UNSAFE_SCHEMES:
            self.report.add_fatal(FatalReason.REFUSED_IDENTITY, str(node))
            return False
        limit = Record._meta.get_field("uri").max_length
        if limit is not None and len(node) > limit:
            self.report.add_fatal(
                FatalReason.IDENTIFIER_TOO_LONG, str(node), limit=str(limit)
            )
            return False
        return True

    def document(
        self,
        graph: rdflib.Graph,
        node: rdflib.term.Node,
        path: frozenset[rdflib.term.Node] = frozenset(),
    ) -> dict:
        """Gather every statement a subject makes into a document.

        Args:
            graph: The parsed graph.
            node: The subject.
            path: The blank nodes being described around this one, so a cycle of them
                ends instead of recursing forever.

        Returns:
            The document: CURIE (or full URI) to a list of entries. Entries are sorted
            so a re-import of the same file stores the same text; ``skos:memberList``
            keeps its sequence.

        Raises:
            SkosImportError: A ``skos:memberList`` loops back on itself.
        """
        document: dict[str, list[dict]] = {}
        for predicate, obj in graph.predicate_objects(node):
            if predicate != SKOS.memberList:
                key = Namespaces.compact(str(predicate))
                document.setdefault(key, []).append(
                    self.entry(graph, obj, path | {node})
                )
        for entries in document.values():
            entries.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
        for head in graph.objects(node, SKOS.memberList):
            try:
                members = list(RdfList(graph, head))
            except ValueError as exc:
                raise SkosImportError(
                    _(
                        "'%(subject)s' has a skos:memberList that does not terminate "
                        "(its rdf:rest chain loops back on itself); the import was "
                        "refused."
                    ),
                    params={"subject": str(node)},
                    code="skos_cyclic_member_list",
                ) from exc
            document["skos:memberList"] = [{"@id": str(member)} for member in members]
        return document

    def entry(
        self,
        graph: rdflib.Graph,
        obj: rdflib.term.Node,
        path: frozenset[rdflib.term.Node],
    ) -> dict:
        """Write one object as the entry JSON-LD would.

        A blank node has no identifier that survives a re-import, so it is written as
        an embedded node holding its own statements, as JSON-LD embeds one.

        Args:
            graph: The parsed graph.
            obj: A URI, blank node or literal.
            path: The blank nodes being described around this one.

        Returns:
            ``{"@id": ...}`` for a link, the embedded statements for a blank node (empty
            when it is already being described, so a cycle ends), otherwise
            ``{"@value": ...}`` with its language or datatype.
        """
        if isinstance(obj, rdflib.URIRef):
            return {"@id": str(obj)}
        if not isinstance(obj, rdflib.Literal):
            return {} if obj in path else self.document(graph, obj, path)
        entry = {"@value": str(obj)}
        if obj.language:
            entry["@language"] = obj.language
        elif obj.datatype and obj.datatype != XSD.string:
            entry["@type"] = Namespaces.compact(str(obj.datatype))
        return entry

    def upsert_scheme(
        self,
        graph: rdflib.Graph,
        declared: rdflib.URIRef | None,
        documents: dict[rdflib.URIRef, dict],
    ) -> ConceptScheme:
        """Return the vocabulary the records go into, created or refreshed from file.

        A vocabulary the run creates takes the most common language of its records'
        preferred labels as its default. One passed in, or already held, keeps its own.

        Args:
            graph: The parsed graph.
            declared: The scheme node the file declares, if any.
            documents: Each record's document, read for the default language.

        Returns:
            The saved vocabulary.
        """
        if declared is None:
            return self.target  # type: ignore[return-value]
        scheme = self.target or ConceptScheme.objects.filter(uri=str(declared)).first()
        created = scheme is None
        if scheme is None:
            languages = Counter(
                entry["@language"]
                for document in documents.values()
                for entry in document.get("skos:prefLabel", [])
                if "@language" in entry
            )
            scheme = ConceptScheme(
                uri=str(declared),
                default_language=(
                    languages.most_common(1)[0][0]
                    if languages
                    else settings.LANGUAGE_CODE
                ),
            )
        scheme.data = self.document(graph, declared)
        scheme.save()
        (self.report.created if created else self.report.updated).append(scheme.uri)
        return scheme

    def upsert_record(
        self,
        scheme: ConceptScheme,
        node: rdflib.URIRef,
        record_type: str,
        document: dict,
        record: Record | None,
    ) -> None:
        """Create the record for ``node``, or replace the document of the URI's holder.

        Args:
            scheme: The vocabulary the record belongs to.
            node: The subject.
            record_type: The record's type.
            document: The record's statements.
            record: The record already holding the subject's URI, if any.
        """
        uri = str(node)
        if record is None:
            record = Record(uri=uri)
            self.report.created.append(uri)
        else:
            self.report.updated.append(uri)
        record.scheme = scheme
        record.type = record_type
        record.data = document
        record.save()


def import_skos(
    file: str | Path,
    *,
    serialization: str | None = None,
    scheme: ConceptScheme | None = None,
    base_uri: str | None = None,
) -> ImportReport:
    """Import a published SKOS file and return a structured report.

    Args:
        file: Path of the SKOS file to import.
        serialization: The file's serialization (``turtle``, ``xml`` or ``json-ld``), guessed
            from its extension when omitted.
        scheme: The vocabulary to import into, for a file that declares none of its own. A
            file that declares a different one fails the run and writes nothing.
        base_uri: The address a fetched document was published at, so its relative
            identifiers resolve against it (docs/adr/0006-a-document-identity-comes-from-where-it-was-published.md).

    Returns:
        The report of what the run created and updated.
    """
    return SkosImporter(
        file, serialization=serialization, scheme=scheme, base_uri=base_uri
    ).run()
