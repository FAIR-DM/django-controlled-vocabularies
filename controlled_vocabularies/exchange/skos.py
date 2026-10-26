"""Import a published SKOS file into records and report what the run did (FS-006)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

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
_SUPPORTED_FORMATS = frozenset({"turtle", "xml", "json-ld"})

#: The classes that make a subject a record, lowest priority first: a subject typed with
#: several becomes the last one it matches.
_RECORD_CLASSES = (
    (SKOS.Concept, Record.Type.CONCEPT),
    (SKOS.Collection, Record.Type.COLLECTION),
    (SKOS.OrderedCollection, Record.Type.ORDERED_COLLECTION),
)


class SkosImporter:
    """Run one import: read the graph, then upsert the vocabulary and its records by URI.

    Every predicate on a subject is kept in its record's document, in every language, so
    nothing a file says is set aside. Re-running upserts: a record the file contains is
    matched by its URI, and a record it does not mention is left untouched and named in
    ``report.absent_from_source``.

    Args:
        file: Path of the SKOS file to import.
        serialization: The file's serialization (``turtle``, ``xml`` or ``json-ld``), guessed
            from its extension when omitted.
        scheme: The vocabulary to import into, for a file that declares none of its own.
        base_uri: The address a fetched document was published at, used as the parse base.
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

        The whole run is one transaction. Fatal findings are collected before anything is
        written, so a file with several problems reports all of them.

        Returns:
            The report of what the run created and updated.

        Raises:
            SkosImportFailed: The run recorded a fatal finding; nothing is written.
        """
        graph = self._read_graph()
        source_label = str(self.base_uri or self.file)

        with transaction.atomic():
            declared = self._declared_scheme(graph, source_label)
            scheme_node = declared or rdflib.URIRef(
                self.target.uri if self.target else ""
            )
            nodes = self._record_nodes(graph, scheme_node)
            if self.report.fatal:
                raise SkosImportFailed(self.report)

            documents = {node: self._document(graph, node) for node in nodes}
            scheme = self._upsert_scheme(graph, declared, documents)
            seen = set()
            for node, record_type in nodes.items():
                self._upsert_record(scheme, node, record_type, documents[node])
                seen.add(str(node))
            for uri in scheme.records.values_list("uri", flat=True):
                if uri not in seen:
                    self.report.absent_from_source.append(uri)
        return self.report

    def _read_graph(self) -> rdflib.Graph:
        """Read the file into a graph, scanning RDF/XML and JSON-LD first.

        The scan runs before rdflib sees the bytes (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).

        Returns:
            The parsed graph.

        Raises:
            SkosImportError: The file is missing, in an unsupported serialization, or cannot
                be parsed.
            UnsafeRdfXmlError: The RDF/XML document fails the safety scan.
            UnsafeJsonLdError: The JSON-LD document fails the safety scan.
        """
        path = Path(self.file)
        # A fetched document's temporary file is gone by the time an operator reads a message.
        source_name = str(self.base_uri or path)
        if not path.is_file():
            raise SkosImportError(
                _("'%(file)s' could not be found."),
                params={"file": source_name},
                code="skos_file_not_found",
            )
        resolved_format = self.serialization or rdflib.util.guess_format(str(path))
        if resolved_format not in _SUPPORTED_FORMATS:
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

    def _declared_scheme(
        self, graph: rdflib.Graph, source_label: str
    ) -> rdflib.URIRef | None:
        """Find the scheme node the file declares, recording a fatal finding when it is unusable.

        Args:
            graph: The parsed graph.
            source_label: How to name the file in a finding.

        Returns:
            The declared scheme, or None when the file declares none the run can use.
        """
        nodes = sorted(set(graph.subjects(RDF.type, SKOS.ConceptScheme)), key=str)
        for node in nodes:
            if isinstance(node, rdflib.BNode):
                self.report.add_fatal(FatalReason.MISSING_IDENTITY, str(node))
        declared = [node for node in nodes if isinstance(node, rdflib.URIRef)]

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

    def _record_nodes(
        self, graph: rdflib.Graph, scheme_node: rdflib.URIRef
    ) -> dict[rdflib.URIRef, str]:
        """Find the subjects that become records, and the type each becomes.

        Typed subjects are records, and so are untyped subjects that say they belong to the
        scheme. A blank node cannot be identified again on a re-import, so it is fatal.

        Args:
            graph: The parsed graph.
            scheme_node: The vocabulary the records belong to.

        Returns:
            The record type of each subject, in URI order.
        """
        found: dict[rdflib.term.Node, str] = {}
        for rdf_class, record_type in _RECORD_CLASSES:
            found.update(
                dict.fromkeys(graph.subjects(RDF.type, rdf_class), record_type)
            )
        for predicate in (SKOS.inScheme, SKOS.topConceptOf):
            for node in graph.subjects(predicate, scheme_node):
                found.setdefault(node, Record.Type.CONCEPT)

        nodes = {}
        for node in sorted(found, key=str):
            if isinstance(node, rdflib.URIRef):
                nodes[node] = found[node]
            else:
                self.report.add_fatal(FatalReason.MISSING_IDENTITY, str(node))
        return nodes

    def _document(self, graph: rdflib.Graph, node: rdflib.URIRef) -> dict:
        """Gather every statement a subject makes into a document.

        Args:
            graph: The parsed graph.
            node: The subject.

        Returns:
            The document: CURIE (or full URI) to a list of entries. Entries are sorted so a
            re-import of the same file stores the same text; ``skos:memberList`` keeps its sequence.
        """
        document: dict[str, list[dict]] = {}
        for predicate, obj in graph.predicate_objects(node):
            if predicate != SKOS.memberList:
                key = Namespaces.compact(str(predicate))
                document.setdefault(key, []).append(self._entry(obj))
        for entries in document.values():
            entries.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
        for head in graph.objects(node, SKOS.memberList):
            document["skos:memberList"] = [
                {"@id": str(member)} for member in RdfList(graph, head)
            ]
        return document

    @staticmethod
    def _entry(obj: rdflib.term.Node) -> dict:
        """Write one object as the entry JSON-LD would.

        Args:
            obj: A URI, blank node or literal.

        Returns:
            ``{"@id": ...}`` for a link, otherwise ``{"@value": ...}`` with its language or
            datatype.
        """
        if isinstance(obj, rdflib.URIRef):
            return {"@id": str(obj)}
        if not isinstance(obj, rdflib.Literal):
            return {"@id": f"_:{obj}"}
        entry = {"@value": str(obj)}
        if obj.language:
            entry["@language"] = obj.language
        elif obj.datatype and obj.datatype != XSD.string:
            entry["@type"] = Namespaces.compact(str(obj.datatype))
        return entry

    def _upsert_scheme(
        self,
        graph: rdflib.Graph,
        declared: rdflib.URIRef | None,
        documents: dict[rdflib.URIRef, dict],
    ) -> ConceptScheme:
        """Return the vocabulary the records go into, creating or refreshing it from the file.

        A vocabulary the run creates is not managed here. One passed in, or already held,
        keeps its flag and its default language.

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
                managed=False,
                default_language=(
                    languages.most_common(1)[0][0]
                    if languages
                    else settings.LANGUAGE_CODE
                ),
            )
        scheme.data = self._document(graph, declared)
        scheme.save()
        (self.report.created if created else self.report.updated).append(scheme.uri)
        return scheme

    def _upsert_record(
        self,
        scheme: ConceptScheme,
        node: rdflib.URIRef,
        record_type: str,
        document: dict,
    ) -> None:
        """Create the record for ``node``, or replace the document of the one holding its URI.

        A record already held by another vocabulary moves into this one with a fresh slug,
        because a URI is held once.

        Args:
            scheme: The vocabulary the record belongs to.
            node: The subject.
            record_type: The record's type.
            document: The record's statements.
        """
        uri = str(node)
        record = Record.objects.filter(uri=uri).first()
        if record is None:
            record = Record(uri=uri)
            self.report.created.append(uri)
        else:
            if record.scheme_id != scheme.pk:
                record.slug = ""
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
