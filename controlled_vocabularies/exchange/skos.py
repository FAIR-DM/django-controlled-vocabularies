"""Import a published SKOS file into records and report what the run did (FS-006)."""

from __future__ import annotations

import urllib.parse
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import TypeGuard, cast

import rdflib
import rdflib.util
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.exchange.exceptions import (
    SkosImportError,
    SkosImportFailed,
    UnsafeJsonLdError,
    UnsafeRdfXmlError,
)
from controlled_vocabularies.exchange.languages import LanguageMatcher
from controlled_vocabularies.exchange.mapping import (
    DCTERMS,
    LABEL_PREDICATES,
    MAPPING_PREDICATES,
    NOTE_PREDICATES,
    SKOS,
    skos_curie,
)
from controlled_vocabularies.exchange.report import (
    FatalReason,
    ImportReport,
    NormalizedReason,
    SetAsideReason,
)
from controlled_vocabularies.exchange.safety import scan_json_ld, scan_rdf_xml
from controlled_vocabularies.models import (
    Collection,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
    validate_static_uri,
)

# The serializations this importer reads. Anything else fails the run instead of reaching rdflib.
_SUPPORTED_FORMATS = frozenset({"turtle", "xml", "json-ld"})


def identifier_slug_segment(uri: str) -> str:
    """Return the part of a published identifier that anchors a local address.

    That is the fragment where the identifier has one, otherwise the last path segment. The
    result may not be a valid slug, so callers pass it through ``slugify()``.

    Args:
        uri: The published identifier.

    Returns:
        The fragment or last path segment.
    """
    parsed = urllib.parse.urlsplit(uri)
    if parsed.fragment:
        return parsed.fragment
    return parsed.path.rstrip("/").rsplit("/", 1)[-1]


def identifier_slug_base(uri: str) -> str:
    """Return the slugified identifier segment, or ``""`` when it slugifies to nothing.

    One definition of "this identifier has no usable base", shared by
    :func:`unique_slug_for_identifier` and the pre-write ``EMPTY_SLUG`` guards, which also run
    for matched records that are never re-minted.

    Args:
        uri: The published identifier.

    Returns:
        The slug base, empty when the segment holds only characters ``slugify()`` strips.
    """
    return slugify(identifier_slug_segment(uri), allow_unicode=True)


def unique_slug_for_identifier(
    static_uri: str, taken_slugs: dict[str, str | None], max_length: int
) -> str:
    """Return the deterministic, collision-resolved slug for ``static_uri``.

    The identifier-derived base gets a numeric suffix only when the candidate already belongs
    to a different record, and a record's own stored slug is read back to itself, so the same
    file yields the same slugs in any traversal order (docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md).
    Shared by :meth:`ConceptImporter.assign_unique_slug`, :meth:`SchemeResolver.resolve_scheme`
    and :meth:`CollectionImporter.import_collections`.

    Nothing on the write path calls ``full_clean()``, so an unbounded slug would reach the
    database unchecked and raise a bare ``DataError`` on PostgreSQL. The base is truncated to
    leave room for the suffix and the assembled candidate is clamped to ``max_length``.

    Args:
        static_uri: The published identifier the slug derives from.
        taken_slugs: Every claimed slug mapped to its claimant's ``static_uri``. Updated in
            place so a caller resolving several records sees each earlier assignment as taken.
        max_length: The calling model's ``SlugField.max_length``.

    Returns:
        The slug, or ``""`` when the base is unusable or no further suffix can produce a
        candidate not already tried. The caller decides what that means for its record kind.
    """
    base = identifier_slug_base(static_uri)[:max_length]
    if not base:
        return ""
    candidate = base
    suffix = 1
    # Holds only candidates generated here, never `base`: seeded with it, the give-up misfires
    # when a clamped first retry renders as `base` itself.
    tried: set[str] = set()
    while taken_slugs.get(candidate, static_uri) != static_uri:
        suffix += 1
        suffix_text = f"-{suffix}"
        # Keep at least one base character: a non-positive slice length would cut from the end
        # of the string. The final clamp stops a suffix longer than max_length overrunning the
        # field.
        candidate = (base[: max(max_length - len(suffix_text), 1)] + suffix_text)[
            :max_length
        ]
        if candidate in tried:
            # The clamp can render two different suffixes as one string once max_length is small.
            # A repeat means no candidate can resolve the collision within the field's width.
            return ""
        tried.add(candidate)
    taken_slugs[candidate] = static_uri
    return candidate


class FatalIdentity(Exception):
    """Signal that a node's identity is fatal, carrying the finding to record.

    Args:
        reason: The fatal reason to record.
        subject: What the finding names, the node's URI or a recognisable label.
        **params: Further message parameters for the finding.
    """

    def __init__(self, reason: FatalReason, subject: str, **params: str) -> None:
        self.reason = reason
        self.subject = subject
        self.params = params
        super().__init__(subject)


class SkosGraph:
    """Wrap the parsed ``rdflib.Graph`` with the read-only queries the importer runs against it.

    This is the RDF boundary itself: RDF is read here and never stored (Article X).

    Args:
        graph: The parsed graph.
    """

    def __init__(self, graph: rdflib.Graph) -> None:
        self.graph = graph

    @classmethod
    def from_file(
        cls,
        file: str | Path,
        *,
        serialization: str | None = None,
        base_uri: str | None = None,
    ) -> SkosGraph:
        """Read a file into a :class:`SkosGraph`.

        The serialization must be one of :data:`_SUPPORTED_FORMATS`, or the run fails naming the
        file. RDF/XML and JSON-LD are scanned by
        :mod:`~controlled_vocabularies.exchange.safety` before rdflib sees them (docs/adr/0007-outbound-fetches-are-restricted-by-removing-handlers.md).
        The scan is wrapped like the parse, so a malformed document cannot raise a bare
        exception. Only the two deliberate refusals propagate as themselves.

        Args:
            file: Path of the file to read.
            serialization: The caller-stated format, guessed from the file's extension when
                omitted.
            base_uri: The address the document was published at, passed to rdflib as
                ``publicID`` so relative identifiers resolve against it (docs/adr/0006-a-document-identity-comes-from-where-it-was-published.md).
                It also names the source in a refusal, since a fetched document's temporary
                file is gone by the time an operator reads the message.

        Returns:
            The graph wrapper.

        Raises:
            SkosImportError: The file is missing, in an unsupported serialization, or cannot
                be parsed.
            UnsafeRdfXmlError: The RDF/XML document fails the safety scan.
            UnsafeJsonLdError: The JSON-LD document fails the safety scan.
        """
        path = Path(file)
        source_name = str(base_uri or path)
        if not path.is_file():
            raise SkosImportError(
                _("'%(file)s' could not be found."),
                params={"file": source_name},
                code="skos_file_not_found",
            )
        resolved_format = serialization or rdflib.util.guess_format(str(path))
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
            if base_uri is not None:
                graph.parse(str(path), format=resolved_format, publicID=base_uri)
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
        return cls(graph)

    @staticmethod
    def identify(node: rdflib.term.Node, *, hint: str | None = None) -> str:
        """Return ``node``'s usable identifier, or raise :class:`FatalIdentity`.

        A blank node has no identifier that survives re-serialization and is always fatal. A
        ``URIRef`` is checked by :func:`~controlled_vocabularies.models.validate_static_uri`, the
        rule the models enforce on a stored ``static_uri``.

        Args:
            node: The node to identify.
            hint: Typically the node's preferred label, so a fatal message has something
                recognisable to point at when the node has no URI to show.

        Returns:
            The node's URI.

        Raises:
            FatalIdentity: The node is a blank node, or its URI is refused.
        """
        subject = hint or str(node)
        if isinstance(node, rdflib.BNode):
            raise FatalIdentity(FatalReason.MISSING_IDENTITY, subject=subject)
        uri = str(node)
        try:
            validate_static_uri(uri)
        except ValidationError as exc:
            raise FatalIdentity(FatalReason.REFUSED_IDENTITY, subject=uri) from exc
        return uri

    @staticmethod
    def is_usable_literal(literal: object) -> TypeGuard[rdflib.Literal]:
        """Return whether ``literal`` is a published value this application can store as a name.

        True for an :class:`rdflib.Literal` whose text survives stripping whitespace. Every
        literal-to-name read shares this predicate, so no read can treat an empty literal as a
        usable name. A ``TypeGuard`` so the caller keeps its ``isinstance`` narrowing.

        Args:
            literal: The object to test.

        Returns:
            Whether it is a usable literal.
        """
        return isinstance(literal, rdflib.Literal) and bool(str(literal).strip())

    def first_literal(
        self,
        node: rdflib.term.Node,
        predicate: rdflib.URIRef,
        *,
        language: str | None = None,
    ) -> str | None:
        """Return the lexicographically-first usable literal of ``predicate`` on ``node``.

        Deterministic rather than whichever rdflib yields first, since the value ends up in a
        stored record. An empty or whitespace-only literal is excluded, so it cannot win over a
        real value published alongside it.

        Args:
            node: The node to read.
            predicate: The predicate whose values are read.
            language: Restrict to literals tagged with exactly this language.

        Returns:
            The value, or ``None`` when there is none.
        """
        values = sorted(
            str(literal)
            for literal in self.graph.objects(node, predicate)
            if (language is None or getattr(literal, "language", None) == language)
            and self.is_usable_literal(literal)
        )
        return values[0] if values else None

    def first_literal_with_language(
        self,
        node: rdflib.term.Node,
        predicate: rdflib.URIRef,
        *,
        max_length: int | None = None,
    ) -> tuple[str, str] | None:
        """Return the first usable literal of ``predicate`` on ``node`` with its published tag.

        The any-language counterpart of :meth:`first_literal`: a caller reporting a fallback
        value needs the language it was published in. With no ``max_length`` it selects the
        value :meth:`first_literal` would. An empty or whitespace-only literal is excluded
        either way, since it would always sort first and satisfy any length filter.

        Args:
            node: The node to read.
            predicate: The predicate whose values are read.
            max_length: Restrict to literals short enough to store, so the fallback does not
                pick a literal that sorts first but cannot be kept.

        Returns:
            The ``(value, language tag)`` pair, the tag being ``""`` for an untagged literal.
            ``None`` when no literal exists or, with ``max_length``, none fits.
        """
        pairs = sorted(
            (str(literal), getattr(literal, "language", None) or "")
            for literal in self.graph.objects(node, predicate)
            if self.is_usable_literal(literal)
            and (max_length is None or len(str(literal)) <= max_length)
        )
        return pairs[0] if pairs else None

    def label_languages(
        self, node: rdflib.term.Node, predicate: rdflib.URIRef
    ) -> list[str]:
        """Return the language tags of ``predicate``'s usable literals on ``node``.

        An empty literal is excluded like every other name-candidate read, so it cannot tip the
        vote in :meth:`preferred_label_tag_counts`.

        Args:
            node: The node to read.
            predicate: The predicate whose values are read.

        Returns:
            The published tag of each tagged, usable literal.
        """
        return [
            literal.language
            for literal in self.graph.objects(node, predicate)
            if self.is_usable_literal(literal) and literal.language
        ]

    def preferred_label_in(self, node: rdflib.term.Node) -> list[tuple[str, str]]:
        """Return every ``(published tag, value)`` pair of ``node``'s usable ``skos:prefLabel``.

        Unfiltered by language: which pair fills a configured language's slot is decided by the
        caller, with :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner`.

        Args:
            node: The node to read.

        Returns:
            The pairs, sorted.
        """
        return sorted(
            (str(literal.language), str(literal))
            for literal in self.graph.objects(node, SKOS.prefLabel)
            if self.is_usable_literal(literal) and literal.language
        )

    def preferred_label_tag_counts(
        self, concept_nodes: Iterable[rdflib.term.Node]
    ) -> dict[str, int]:
        """Count how often each published language tag appears in the concepts' preferred labels.

        Only concept nodes count: the vocabulary's own and every collection's ``skos:prefLabel``
        are excluded, which is the population
        :meth:`SchemeResolver.determine_default_language` counts. Keys are case-folded because
        matching is case-insensitive, so ``pt-BR`` and ``pt-br`` are one tag.

        Args:
            concept_nodes: The concept nodes to count over.

        Returns:
            Each case-folded tag mapped to its number of occurrences.
        """
        counts: dict[str, int] = {}
        for node in concept_nodes:
            for language in self.label_languages(node, SKOS.prefLabel):
                key = language.lower()
                counts[key] = counts.get(key, 0) + 1
        return counts

    def scheme_refs(self, concept_node: rdflib.term.Node) -> set[str]:
        """Return every vocabulary URI a concept declares membership of.

        Args:
            concept_node: The concept's node.

        Returns:
            The URIs named by ``skos:inScheme``, ``skos:topConceptOf`` and
            ``skos:hasTopConcept``.
        """
        refs = {str(obj) for obj in self.graph.objects(concept_node, SKOS.inScheme)}
        refs |= {
            str(obj) for obj in self.graph.objects(concept_node, SKOS.topConceptOf)
        }
        refs |= {
            str(subj) for subj in self.graph.subjects(SKOS.hasTopConcept, concept_node)
        }
        return refs

    def conflicting_scheme_ref(
        self, concept_node: rdflib.term.Node, target_scheme_uri: str
    ) -> str | None:
        """Return the URI of a different vocabulary the concept claims, if any.

        A concept with no scheme reference is read as belonging to the vocabulary being
        imported, so that is not a conflict.

        Args:
            concept_node: The concept's node.
            target_scheme_uri: The URI of the vocabulary being imported.

        Returns:
            The first conflicting vocabulary URI in sorted order, or ``None``.
        """
        others = self.scheme_refs(concept_node) - {target_scheme_uri}
        return sorted(others)[0] if others else None

    def implied_concept_nodes(self) -> set[rdflib.term.Node]:
        """Return nodes the file places in a vocabulary but never types as ``skos:Concept``.

        Restricted to a node carrying no ``rdf:type`` at all. One the file types as something
        else is left to whatever that type makes of it.

        Returns:
            The implied concept nodes.
        """
        candidates: set[rdflib.term.Node] = set(
            self.graph.subjects(SKOS.inScheme, None)
        )
        candidates |= set(self.graph.subjects(SKOS.topConceptOf, None))
        candidates |= set(self.graph.objects(None, SKOS.hasTopConcept))
        return {
            node
            for node in candidates
            if next(self.graph.objects(node, rdflib.RDF.type), None) is None
        }


def _localized_literal(
    skos_graph: SkosGraph,
    matcher: LanguageMatcher,
    node: rdflib.term.Node,
    predicate: rdflib.URIRef,
    target_language: str,
) -> tuple[str, str] | None:
    """Return the value of ``predicate`` on ``node`` in ``target_language``, with its published tag.

    :meth:`SkosGraph.first_literal` matches a tag exactly. Resolving a variant tag to a
    configured language is language policy and stays off :class:`SkosGraph`. Without it, a
    vocabulary declared in a variant of its default language would fall through to the
    any-language fallback for its own name. The winning tag is returned so each caller can
    report a ``LANGUAGE_SUBSTITUTION`` when it differs from ``target_language``.

    Args:
        skos_graph: The graph to read.
        matcher: Resolves a published tag to a configured language.
        node: The node to read.
        predicate: The predicate whose values are read.
        target_language: The configured language the value must resolve to.

    Returns:
        The value and the published tag it won under, or ``None`` when no tag resolves.
    """
    candidates = [
        (tag, value)
        for tag in sorted(set(skos_graph.label_languages(node, predicate)))
        if (value := skos_graph.first_literal(node, predicate, language=tag))
        is not None
        if matcher.resolve(tag).configured_language == target_language
    ]
    if not candidates:
        return None
    (winning_tag, value), _losers = matcher.resolve_winner(target_language, candidates)
    return value, winning_tag


def report_unmodelled_predicates(
    skos_graph: SkosGraph,
    node: rdflib.term.Node,
    uri: str,
    handled: frozenset[rdflib.URIRef],
    report: ImportReport,
) -> None:
    """Set aside and report each predicate a node carries that nothing here reads.

    A predicate is skipped when it is in ``handled`` or is a SKOS predicate with no read path
    yet, which the models do have a place for. Called once per record with its own identity: a
    concept, the vocabulary's scheme node and a collection.

    Args:
        skos_graph: The graph to read.
        node: The record's node.
        uri: The record's identifier, the subject of each report entry.
        handled: The predicates already accounted for on this kind of node.
        report: The report each set-aside is recorded on.
    """
    for other_predicate, _obj in skos_graph.graph.predicate_objects(node):
        if other_predicate in handled:
            continue
        if str(other_predicate).startswith(str(SKOS)):
            continue
        report.add_set_aside(
            SetAsideReason.UNMODELLED_PREDICATE,
            subject=uri,
            predicate=str(other_predicate),
        )


class SchemeResolver:
    """Resolve which vocabulary a file belongs to: the one it declares or a caller-named target.

    Args:
        skos_graph: The parsed graph.
        report: The report each finding is recorded on.
        target: The vocabulary the caller named, or ``None``.
        source_label: What a finding calls the file being imported.
        matcher: Resolves a published language tag to a configured language.
    """

    # skos:hasTopConcept is read about a concept, not held for it, so ConceptImporter omits it.
    _HANDLED_PREDICATES = frozenset(
        {
            rdflib.RDF.type,
            SKOS.prefLabel,
            SKOS.hasTopConcept,
            DCTERMS.description,
        }
    )

    def __init__(
        self,
        skos_graph: SkosGraph,
        report: ImportReport,
        *,
        target: ConceptScheme | None,
        source_label: str,
        matcher: LanguageMatcher,
    ) -> None:
        self.skos_graph = skos_graph
        self.report = report
        self.target = target
        self.source_label = source_label
        self.matcher = matcher

    @staticmethod
    def _get_or_create_scheme(uri: str) -> ConceptScheme:
        """Return the scheme matching ``uri``, or a new unsaved one.

        Args:
            uri: The vocabulary's published identifier.

        Returns:
            The stored scheme, or an unsaved scheme holding ``uri``.
        """
        try:
            return ConceptScheme.objects.get_by_uri(uri)
        except ConceptScheme.DoesNotExist:
            return ConceptScheme(static_uri=uri)

    def determine_default_language(
        self, declared_node: rdflib.term.Node, concept_nodes: list[rdflib.term.Node]
    ) -> str:
        """Return the imported vocabulary's default language.

        Taken from the vocabulary's own ``skos:prefLabel`` when it is tagged with exactly one
        language, else from the language most concept preferred labels use, ties broken by
        language code. Either is resolved through :attr:`matcher`, so a variant of a configured
        language (``de-at`` on a ``de`` site) resolves to it. When none shares a base with a
        configured language this returns ``""``, which :attr:`ConceptScheme.default_language`
        treats as "use the site's default".

        Args:
            declared_node: The vocabulary node the file declares.
            concept_nodes: The file's concept nodes.

        Returns:
            A configured language code, or ``""``.
        """
        declared_languages = set(
            self.skos_graph.label_languages(declared_node, SKOS.prefLabel)
        )
        if len(declared_languages) == 1:
            (declared_language,) = declared_languages
            resolved = self.matcher.resolve(declared_language).configured_language
            if resolved:
                return resolved

        counts = self.skos_graph.preferred_label_tag_counts(concept_nodes)
        if counts:
            commonest = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][
                0
            ]
            resolved = self.matcher.resolve(commonest).configured_language
            if resolved:
                return resolved

        return ""

    def choose_declared_scheme(
        self,
        declared_nodes: list[rdflib.term.Node],
        concept_nodes: list[rdflib.term.Node],
    ) -> rdflib.term.Node | None:
        """Pick the one vocabulary a file declares, or record that it cannot.

        A file often types several ``skos:ConceptScheme`` nodes without being about several: a
        second is just a vocabulary some concept claims membership of, so multiplicity alone is
        not fatal. The declared vocabulary with the most member concepts (counted by
        :meth:`SkosGraph.scheme_refs`) wins, never an accident of identifier sort order. A tie
        with no caller-named target is fatal. A named target always decides, and one matching no
        declared vocabulary falls through to the mismatch check in :meth:`resolve_scheme`.

        Args:
            declared_nodes: Every node typed ``skos:ConceptScheme``.
            concept_nodes: The file's concept nodes.

        Returns:
            The chosen node, or ``None`` when there is none or the choice is ambiguous.
        """
        if len(declared_nodes) < 2:
            return declared_nodes[0] if declared_nodes else None
        if self.target is not None:
            named = [node for node in declared_nodes if str(node) == self.target.uri]
            if named:
                return named[0]
            return declared_nodes[0]

        members: Counter[str] = Counter()
        for concept_node in concept_nodes:
            for scheme_uri in self.skos_graph.scheme_refs(concept_node):
                members[scheme_uri] += 1
        ranked = sorted(
            declared_nodes, key=lambda node: (-members[str(node)], str(node))
        )
        best, runner_up = members[str(ranked[0])], members[str(ranked[1])]
        if best > runner_up:
            return ranked[0]

        self.report.add_fatal(
            FatalReason.VOCABULARY_AMBIGUOUS,
            subject=self.source_label,
            declared=", ".join(str(node) for node in declared_nodes),
        )
        return None

    def resolve_scheme(
        self,
        declared_node: rdflib.term.Node | None,
        concept_nodes: list[rdflib.term.Node],
    ) -> tuple[ConceptScheme | None, str | None]:
        """Resolve, create or update the vocabulary being imported into.

        The file is authoritative: when it declares none a caller-named target is required, and
        when it declares one a given target must agree with it. A mismatch is fatal and nothing
        is written. The vocabulary is matched by URI, else created holding the file's
        identifier.

        Args:
            declared_node: The vocabulary node the file declares, or ``None``.
            concept_nodes: The file's concept nodes, used to determine the default language.

        Returns:
            ``(scheme, declared_uri)``, where ``declared_uri`` is what concepts are later
            checked against, or ``(None, None)`` when resolution is fatal and the report says
            why.
        """
        if declared_node is None:
            if self.target is None:
                self.report.add_fatal(
                    FatalReason.VOCABULARY_UNDETERMINED, subject=self.source_label
                )
                return None, None
            return self.target, self.target.uri

        hint = self.skos_graph.first_literal(declared_node, SKOS.prefLabel)
        try:
            declared_uri = self.skos_graph.identify(declared_node, hint=hint)
        except FatalIdentity as exc:
            self.report.add_fatal(exc.reason, exc.subject, **exc.params)
            return None, None

        if self.target is not None and self.target.uri != declared_uri:
            self.report.add_fatal(
                FatalReason.VOCABULARY_TARGET_MISMATCH,
                subject=declared_uri,
                target=self.target.uri,
            )
            return None, None

        row = (
            self.target
            if self.target is not None
            else self._get_or_create_scheme(declared_uri)
        )
        created = row.pk is None
        declared_default_language = self.determine_default_language(
            declared_node, concept_nodes
        )
        if created:
            # ConceptScheme.save() refuses to change default_language once the scheme has concepts,
            # so only a freshly created scheme may set it.
            row.default_language = declared_default_language
        elif (
            declared_default_language
            and declared_default_language != row.effective_default_language
        ):
            # Compared with effective_default_language, not the stored field, so a scheme relying
            # on the site default that agrees in effect is not a conflict.
            self.report.add_set_aside(
                SetAsideReason.DEFAULT_LANGUAGE_FROZEN,
                subject=declared_uri,
                declared=declared_default_language,
                frozen=row.effective_default_language,
            )
        # max_length is always set on these fields: cast narrows the type without an assert
        # (S101). Read before the name resolution, since the any-language fallback needs it.
        name_max_length = cast(int, ConceptScheme._meta.get_field("name").max_length)
        name_match = _localized_literal(
            self.skos_graph,
            self.matcher,
            declared_node,
            SKOS.prefLabel,
            row.effective_default_language,
        )
        if name_match is None:
            # No prefLabel in the default language: fall back to any language, preferring a literal
            # that fits the field. The tag reported is the one the value was published in, not the
            # language sought.
            any_literal = self.skos_graph.first_literal_with_language(
                declared_node, SKOS.prefLabel, max_length=name_max_length
            ) or self.skos_graph.first_literal_with_language(
                declared_node, SKOS.prefLabel
            )
            name, winning_tag = (
                any_literal
                if any_literal is not None
                else (None, row.effective_default_language)
            )
        else:
            name, winning_tag = name_match
            if winning_tag.lower() != row.effective_default_language.lower():
                # A name stored under another language than published is a normalisation, never
                # silent (Article XI).
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=declared_uri,
                    language=winning_tag,
                    kept_as=row.effective_default_language,
                )
        if name and len(name) > name_max_length:
            if created:
                # A created scheme with no storable name has nothing to fall back to, and a blank
                # name fails full_clean(). Try another published language before refusing the run;
                # without a resolvable vocabulary nothing else in the file can be imported.
                fallback = self.skos_graph.first_literal_with_language(
                    declared_node, SKOS.prefLabel, max_length=name_max_length
                )
                if fallback is None:
                    self.report.add_fatal(
                        FatalReason.VOCABULARY_NAME_UNUSABLE,
                        subject=declared_uri,
                        language=winning_tag,
                    )
                    return None, None
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG,
                    subject=declared_uri,
                    language=winning_tag,
                )
                name, winning_tag = fallback
                row.name = name
            else:
                # save() never calls full_clean(), so an over-long name would reach the database
                # unchecked and raise a bare DataError on PostgreSQL. A matched scheme keeps the
                # name it holds.
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG,
                    subject=declared_uri,
                    language=winning_tag,
                )
        elif name:
            row.name = name
        elif created:
            # No prefLabel at all leaves name empty on a created row. Its own reason, since
            # VOCABULARY_NAME_UNUSABLE would claim a value was too long to store
            # (docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md).
            self.report.add_fatal(
                FatalReason.VOCABULARY_NAME_UNPUBLISHED, subject=declared_uri
            )
            return None, None
        # SKOS has no description predicate for a scheme, so dcterms:description is the source.
        # Written even when empty: nothing anchors identity to it the way it does default_language.
        description_match = _localized_literal(
            self.skos_graph,
            self.matcher,
            declared_node,
            DCTERMS.description,
            row.effective_default_language,
        )
        if description_match is None:
            description = self.skos_graph.first_literal(
                declared_node, DCTERMS.description
            )
        else:
            description, winning_tag = description_match
            if winning_tag.lower() != row.effective_default_language.lower():
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=declared_uri,
                    language=winning_tag,
                    kept_as=row.effective_default_language,
                )
        row.description = description or ""
        row.static_uri = declared_uri
        # A created scheme mints its slug from its identifier and a matched row keeps the one it holds
        # (docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md). Two vocabularies can end in the same
        # segment, so the importer resolves that collision itself: ConceptScheme.save() only refuses one.
        if created:
            taken_slugs: dict[str, str | None] = dict(
                ConceptScheme.objects.values_list("slug", "static_uri")
            )
            max_length = cast(int, ConceptScheme._meta.get_field("slug").max_length)
            slug = unique_slug_for_identifier(declared_uri, taken_slugs, max_length)
            if not slug:
                # Fatal, unlike a concept's EMPTY_SLUG: without a resolvable vocabulary nothing in
                # the file has anywhere to import into.
                self.report.add_fatal(
                    FatalReason.VOCABULARY_SLUG_UNUSABLE, subject=declared_uri
                )
                return None, None
            row.slug = slug
        # The only write of the row: every field assigned above is persisted here. slug_is_manual
        # is pinned for a matched row too, so a locally authored scheme is pinned on first import.
        row.slug_is_manual = True
        try:
            row.save()
        except ValidationError as exc:
            # A stored slug written out of band reaches validation as stored (docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md).
            # Report it only when the error names the slug: save() also raises for language checks.
            # Read error_dict, since message_dict raises for a ValidationError built from a message.
            if "slug" in getattr(exc, "error_dict", {}):
                self.report.add_set_aside(
                    SetAsideReason.STORED_SLUG_INVALID, subject=declared_uri
                )
            # Whichever field failed, nothing was written, and a run that imports nothing must not
            # report `fatal == []`.
            self.report.add_fatal(
                FatalReason.VOCABULARY_RECORD_INVALID, subject=declared_uri
            )
            return None, None
        if created:
            self.report.add_created(row.uri)
        else:
            self.report.add_updated(row.uri)
        report_unmodelled_predicates(
            self.skos_graph,
            declared_node,
            declared_uri,
            self._HANDLED_PREDICATES,
            self.report,
        )
        return row, declared_uri


class ConceptImporter:
    """Create or update each concept in the target vocabulary, with everything beyond identity.

    Args:
        skos_graph: The parsed graph to read concepts from.
        report: The report each finding is recorded on.
        target_scheme: The vocabulary being imported into.
        target_scheme_uri: The identifier the file declares for the vocabulary, which each
            concept's own scheme references are checked against.
        matcher: Resolves a published language tag to a configured language.
    """

    _HANDLED_PREDICATES = frozenset(
        {
            rdflib.RDF.type,
            SKOS.inScheme,
            SKOS.topConceptOf,
            SKOS.notation,
            DCTERMS.description,
            SKOS.broader,
            SKOS.narrower,
            SKOS.related,
        }
        | set(LABEL_PREDICATES)
        | set(NOTE_PREDICATES)
        | set(MAPPING_PREDICATES)
    )

    def __init__(
        self,
        skos_graph: SkosGraph,
        report: ImportReport,
        target_scheme: ConceptScheme,
        target_scheme_uri: str,
        *,
        matcher: LanguageMatcher,
    ) -> None:
        self.skos_graph = skos_graph
        self.report = report
        self.target_scheme = target_scheme
        self.target_scheme_uri = target_scheme_uri
        self.matcher = matcher
        self._mentioned_uris: set[str] = set()

    def import_labels(
        self, node: rdflib.term.Node, concept: Concept, default_language: str, uri: str
    ) -> None:
        """Store ``concept``'s labels other than its default-language preferred one.

        Replaces every label the concept held, since a label has no identifier to upsert by and
        the file is authoritative. A preferred label whose resolved language is
        ``default_language`` is skipped because that slot is ``concept.label``.

        A value in a language no configured language shares a base with is set aside under its
        published tag before the write, so the model's own refusal never fires. A concept keeps
        one preferred label per language, so competing ``skos:prefLabel`` values resolving to the
        same configured language are settled once per language by
        :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner`, the
        computation :meth:`import_concepts` runs for ``Concept.label``. A loser carrying the
        winner's published tag is a same-language duplicate (``SURPLUS_PREFERRED_LABEL``) and one
        with a different tag is a variant (``VARIANT_NOT_KEPT``). The remedies differ.

        Args:
            node: The concept's node in the graph.
            concept: The stored concept to attach labels to.
            default_language: The vocabulary's effective default language.
            uri: The concept's identifier, the subject of any report entry.
        """
        concept.labels.all().delete()

        preferred_candidates_by_language: dict[str, list[tuple[str, str]]] = {}
        for tag, value in self.skos_graph.preferred_label_in(node):
            resolved = self.matcher.resolve(tag).configured_language
            if resolved is not None:
                preferred_candidates_by_language.setdefault(resolved, []).append(
                    (tag, value)
                )
        preferred_winner_by_language: dict[str, tuple[str, str]] = {
            language: self.matcher.resolve_winner(language, candidates)[0]
            for language, candidates in preferred_candidates_by_language.items()
        }
        default_language_winner_tag = (
            preferred_winner_by_language[default_language][0]
            if default_language in preferred_winner_by_language
            else None
        )

        for predicate, kind in LABEL_PREDICATES.items():
            for literal in self.skos_graph.graph.objects(node, predicate):
                if not isinstance(literal, rdflib.Literal) or not literal.language:
                    self.report.add_set_aside(
                        SetAsideReason.NO_LANGUAGE_TAG,
                        subject=uri,
                        predicate=skos_curie(predicate),
                    )
                    continue
                if not SkosGraph.is_usable_literal(literal):
                    # An empty or whitespace-only literal is never a usable name. Skip it silently, as
                    # SkosGraph's accessors do, so it never reaches the winner lookup below.
                    continue
                published_tag = literal.language
                resolved_language = self.matcher.resolve(
                    published_tag
                ).configured_language
                if (
                    kind == ConceptLabel.Kind.PREFERRED
                    and resolved_language == default_language
                ):
                    if (
                        default_language_winner_tag is not None
                        and published_tag.lower() != default_language_winner_tag.lower()
                    ):
                        self.report.add_set_aside(
                            SetAsideReason.VARIANT_NOT_KEPT,
                            subject=uri,
                            language=published_tag,
                            kept_as=default_language,
                        )
                    elif (
                        str(literal)
                        != preferred_winner_by_language[default_language][1]
                    ):
                        self.report.add_set_aside(
                            SetAsideReason.SURPLUS_PREFERRED_LABEL,
                            subject=uri,
                            language=default_language,
                        )
                    continue
                if resolved_language is None:
                    self.report.add_set_aside(
                        SetAsideReason.UNCONFIGURED_LANGUAGE,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                if kind == ConceptLabel.Kind.PREFERRED:
                    winner_tag, winner_value = preferred_winner_by_language[
                        resolved_language
                    ]
                    if (
                        published_tag.lower() != winner_tag.lower()
                        or str(literal) != winner_value
                    ):
                        if published_tag.lower() == winner_tag.lower():
                            self.report.add_set_aside(
                                SetAsideReason.SURPLUS_PREFERRED_LABEL,
                                subject=uri,
                                language=resolved_language,
                            )
                        else:
                            self.report.add_set_aside(
                                SetAsideReason.VARIANT_NOT_KEPT,
                                subject=uri,
                                language=published_tag,
                                kept_as=resolved_language,
                            )
                        continue
                try:
                    concept.add_label(
                        language=resolved_language, kind=kind, text=str(literal)
                    )
                except ValidationError:
                    # One over-long value must not abort the run: imported RDF is untrusted (Article V).
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                if resolved_language.lower() != published_tag.lower():
                    # Stored under a language other than the published one: a normalisation, never silent.
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=published_tag,
                        kept_as=resolved_language,
                    )

    def _import_notes(self, node: rdflib.term.Node, concept: Concept, uri: str) -> None:
        """Store ``concept``'s definition and the six SKOS note kinds as notes.

        Replaces every note the concept held, for the same reason as :meth:`import_labels`. A
        tag sharing no base language with a configured one is set aside the same way. Notes have
        no per-language cardinality limit, so there is no contest and every variant is stored.
        ``dcterms:description`` is read as a definition only in a language with no
        ``skos:definition`` of its own, and is reported as a normalisation.

        Args:
            node: The concept's node in the graph.
            concept: The stored concept to attach notes to.
            uri: The concept's identifier, the subject of any report entry.
        """
        concept.concept_notes.all().delete()
        definition_languages: set[str] = set()
        for predicate, kind in NOTE_PREDICATES.items():
            for literal in self.skos_graph.graph.objects(node, predicate):
                if not isinstance(literal, rdflib.Literal) or not literal.language:
                    self.report.add_set_aside(
                        SetAsideReason.NO_LANGUAGE_TAG,
                        subject=uri,
                        predicate=skos_curie(predicate),
                    )
                    continue
                published_tag = literal.language
                resolved_language = self.matcher.resolve(
                    published_tag
                ).configured_language
                if resolved_language is None:
                    self.report.add_set_aside(
                        SetAsideReason.UNCONFIGURED_LANGUAGE,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                try:
                    concept.add_note(
                        language=resolved_language, kind=kind, value=str(literal)
                    )
                except ValidationError:
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                if kind == ConceptNote.Kind.DEFINITION:
                    definition_languages.add(resolved_language)
                if resolved_language.lower() != published_tag.lower():
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=published_tag,
                        kept_as=resolved_language,
                    )

        for literal in self.skos_graph.graph.objects(node, DCTERMS.description):
            if not isinstance(literal, rdflib.Literal) or not literal.language:
                self.report.add_set_aside(
                    SetAsideReason.NO_LANGUAGE_TAG,
                    subject=uri,
                    predicate="dcterms:description",
                )
                continue
            published_tag = literal.language
            resolved_language = self.matcher.resolve(published_tag).configured_language
            if (
                resolved_language is not None
                and resolved_language in definition_languages
            ):
                continue
            if resolved_language is None:
                self.report.add_set_aside(
                    SetAsideReason.UNCONFIGURED_LANGUAGE,
                    subject=uri,
                    language=published_tag,
                )
                continue
            try:
                concept.add_note(
                    language=resolved_language,
                    kind=ConceptNote.Kind.DEFINITION,
                    value=str(literal),
                )
            except ValidationError:
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG, subject=uri, language=published_tag
                )
                continue
            self.report.add_normalized(
                NormalizedReason.FOREIGN_DEFINITION,
                subject=uri,
                predicate="dcterms:description",
                language=resolved_language,
            )
            if resolved_language.lower() != published_tag.lower():
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=uri,
                    language=published_tag,
                    kept_as=resolved_language,
                )

    def _import_unheld_values(self, node: rdflib.term.Node, uri: str) -> None:
        """Set aside and report the values on a concept that the models have no place for.

        Covers each ``skos:notation``, each cross-vocabulary mapping and each predicate that is
        neither handled elsewhere nor a SKOS predicate. A SKOS predicate this module does not
        read (``skos:member``, ``skos:memberList``) is not reported, because the models do have a
        place for it.

        Args:
            node: The concept's node in the graph.
            uri: The concept's identifier, the subject of each report entry.
        """
        for _notation in self.skos_graph.graph.objects(node, SKOS.notation):
            self.report.add_set_aside(SetAsideReason.NOTATION, subject=uri)

        for mapping_predicate, name in MAPPING_PREDICATES.items():
            for _obj in self.skos_graph.graph.objects(node, mapping_predicate):
                self.report.add_set_aside(
                    SetAsideReason.MAPPING, subject=uri, predicate=name
                )

        report_unmodelled_predicates(
            self.skos_graph, node, uri, self._HANDLED_PREDICATES, self.report
        )

    def _import_concept_content(
        self, node: rdflib.term.Node, concept: Concept, uri: str
    ) -> None:
        """Import everything about a concept beyond its identity and default-language label.

        Runs once per created-or-updated concept, after it has a primary key, which replacing
        its labels needs.

        Args:
            node: The concept's node in the graph.
            concept: The stored concept to attach content to.
            uri: The concept's identifier, the subject of any report entry.
        """
        self.import_labels(
            node, concept, self.target_scheme.effective_default_language, uri
        )
        self._import_notes(node, concept, uri)
        self._import_unheld_values(node, uri)

    def import_concepts(
        self, concept_nodes: list[rdflib.term.Node]
    ) -> dict[str, Concept]:
        """Create or update each concept node inside the target vocabulary.

        A blank node or refused URI is fatal. A concept claiming a different vocabulary, or with
        no preferred label in the default language, is set aside. A concept whose URI is already
        held by a concept of another vocabulary, or by a collection, is left as it is and set
        aside rather than made to identify two records. A written concept gets an
        identifier-derived slug (:meth:`assign_unique_slug`). The slugs already taken are read
        once, not per concept, so a collision costs no query.

        Args:
            concept_nodes: The nodes to import, in URI-sorted order.

        Returns:
            The concepts created or updated, keyed by URI.
        """
        concepts_by_uri: dict[str, Concept] = {}
        taken_slugs: dict[str, str | None] = dict(
            Concept.objects.filter(scheme=self.target_scheme).values_list(
                "slug", "static_uri"
            )
        )
        for node in concept_nodes:
            hint = self.skos_graph.first_literal(node, SKOS.prefLabel)
            try:
                uri = self.skos_graph.identify(node, hint=hint)
            except FatalIdentity as exc:
                self.report.add_fatal(exc.reason, exc.subject, **exc.params)
                continue
            self._mentioned_uris.add(uri)

            other = self.skos_graph.conflicting_scheme_ref(node, self.target_scheme_uri)
            if other is not None:
                self.report.add_set_aside(
                    SetAsideReason.VOCABULARY_MISMATCH, subject=uri, other=other
                )
                continue

            default_language = self.target_scheme.effective_default_language
            preferred_pairs = self.skos_graph.preferred_label_in(node)
            candidates = [
                (tag, value)
                for tag, value in preferred_pairs
                if self.matcher.resolve(tag).configured_language == default_language
            ]
            if not candidates:
                # Skipped, so import_labels never runs: account for its languages here, under the
                # published tags rather than the default it lacks, so language_account() sees them.
                for tag, _value in preferred_pairs:
                    if self.matcher.resolve(tag).configured_language is None:
                        self.report.add_set_aside(
                            SetAsideReason.UNCONFIGURED_LANGUAGE,
                            subject=uri,
                            language=tag,
                        )
                self.report.add_set_aside(
                    SetAsideReason.NO_PREFERRED_LABEL,
                    subject=uri,
                    language=default_language,
                )
                continue
            (winning_tag, label), _losers = self.matcher.resolve_winner(
                default_language, candidates
            )

            label_max_length = cast(int, Concept._meta.get_field("label").max_length)
            if len(label) > label_max_length:
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG, subject=uri, language=winning_tag
                )
                continue

            if not identifier_slug_base(uri):
                # The slug comes from the identifier's own segment, which can slugify to nothing.
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue

            try:
                concept = Concept.objects.get_by_uri(uri)
                created = False
            except Concept.DoesNotExist:
                # A collection may already hold this URI; one URI never identifies two records.
                try:
                    Collection.objects.get_by_uri(uri)
                except Collection.DoesNotExist:
                    pass
                else:
                    self.report.add_set_aside(
                        SetAsideReason.URI_HELD_BY_DIFFERENT_KIND, subject=uri
                    )
                    continue
                concept = Concept(scheme=self.target_scheme)
                created = True

            if not created and concept.scheme_id != self.target_scheme.pk:
                # Moving a record between vocabularies is a curatorial act, never a side effect of
                # an import.
                self.report.add_set_aside(
                    SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY,
                    subject=uri,
                    current=concept.scheme.uri,
                    target=self.target_scheme.uri,
                )
                continue

            concept.scheme = self.target_scheme
            concept.static_uri = uri
            concept.label = label
            self.assign_unique_slug(concept, taken_slugs, created=created)
            if created and not concept.slug:
                # unique_slug_for_identifier gave up. STORED_SLUG_INVALID would claim a stored slug
                # failed validation when none was written, so report EMPTY_SLUG instead
                # (docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md).
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue
            try:
                concept.save()
            except ValidationError:
                self.report.add_set_aside(
                    SetAsideReason.STORED_SLUG_INVALID, subject=uri
                )
                continue
            if winning_tag.lower() != default_language.lower():
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=uri,
                    language=winning_tag,
                    kept_as=default_language,
                )
            concepts_by_uri[uri] = concept
            self._import_concept_content(node, concept, uri)
            if created:
                self.report.add_created(uri)
            else:
                self.report.add_updated(uri)

        return concepts_by_uri

    def report_absent_concepts(self) -> None:
        """Report each stored concept of the target vocabulary the file never mentioned.

        Those concepts are left untouched. A concept set aside for claiming a different
        vocabulary is not absent, since the file does mention it. Runs after relations and
        collections are reconciled.
        """
        absent = [
            concept
            for concept in Concept.objects.filter(scheme=self.target_scheme)
            if concept.static_uri not in self._mentioned_uris
        ]
        for concept in sorted(absent, key=lambda row: row.uri):
            self.report.add_absent_from_source(concept.uri)

    @staticmethod
    def assign_unique_slug(
        concept: Concept, taken_slugs: dict[str, str | None], *, created: bool
    ) -> None:
        """Give a concept a slug derived from its published identifier.

        Nothing derives from the label, so a publisher renaming a concept never moves its
        address. The slug is minted only for a concept this run creates. A matched concept keeps
        the slug it holds, read back as stored, so that what else occupies the vocabulary cannot
        move its address between two imports of the same file (docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md).

        ``slug_is_manual`` is set for a matched concept too, so a later unrelated save does not
        re-derive the slug from the label, which a concept authored locally before its first
        import would otherwise keep doing. The caller has already set aside a concept whose
        identifier segment slugifies to nothing.

        Args:
            concept: The concept to assign a slug to.
            taken_slugs: Every claimed slug in the vocabulary, mapped to its claimant's
                ``static_uri``. Updated in place so the next created concept sees this slug as
                taken. Concepts are processed in URI-sorted order so a collision between two
                identifiers in one run resolves the same whichever order the file declares them.
            created: Whether this run is creating the concept.
        """
        if created:
            max_length = cast(int, Concept._meta.get_field("slug").max_length)
            concept.slug = unique_slug_for_identifier(
                concept.static_uri, taken_slugs, max_length
            )
        concept.slug_is_manual = True


class ConceptReferenceResolverMixin:
    """Resolve a URI to the concept it identifies, for the relation and collection importers.

    A subclass sets ``self.target_scheme`` before calling :meth:`_resolve_concept_reference`.
    """

    target_scheme: ConceptScheme

    def _resolve_concept_reference(
        self, uri: str, successful_concepts: dict[str, Concept]
    ) -> Concept | None:
        """Return the concept ``uri`` names, or ``None`` when it cannot back a relation or membership.

        A concept belonging to a different vocabulary counts as no match.

        Args:
            uri: The published identifier to resolve.
            successful_concepts: The concepts this run created or updated, keyed by URI.
                Tried before the database.

        Returns:
            The concept, or ``None`` when ``uri`` names no concept of the target vocabulary.
        """
        concept = successful_concepts.get(uri)
        if concept is None:
            try:
                concept = Concept.objects.get_by_uri(uri)
            except Concept.DoesNotExist:
                return None
        if concept.scheme_id != self.target_scheme.pk:
            return None
        return concept


class RelationImporter(ConceptReferenceResolverMixin):
    """Reconcile ``skos:broader``, ``skos:narrower`` and ``skos:related`` into stored relations.

    Args:
        skos_graph: The parsed graph to read relations from.
        report: The report each set-aside is recorded on.
        target_scheme: The vocabulary being imported into.
    """

    def __init__(
        self, skos_graph: SkosGraph, report: ImportReport, target_scheme: ConceptScheme
    ) -> None:
        self.skos_graph = skos_graph
        self.report = report
        self.target_scheme = target_scheme

    def import_relations(self, successful_concepts: dict[str, Concept]) -> None:
        """Reconcile the file's relations with the stored ones for every concept this run wrote.

        ``skos:narrower`` resolves to the same stored broader row as ``skos:broader`` with its
        ends swapped, and ``skos:related`` is symmetric, so either direction of a pair gives the
        same result. A stored row is a deletion candidate only when both of its ends were
        written this run, because only then has the file spoken about it. Deletion is one pass
        over the whole run: a relation is often asserted from one end only, so per-concept
        deletion would remove rows a sibling had just written.

        A broader/narrower pair wins over the same pair stated as related, since SKOS declares
        the two disjoint and the model refuses to store both. A conflicting stored related row is
        deleted, and a related pair that conflicts with a stored broader row is set aside.

        Args:
            successful_concepts: The concepts this run created or updated, keyed by URI.
                Only these are read; a concept set aside has no row to attach a relation to.
        """
        graph = self.skos_graph.graph
        desired_broader: dict[tuple[str, str], None] = {}
        desired_related: dict[frozenset[str], None] = {}
        for uri in successful_concepts:
            node = rdflib.URIRef(uri)
            for other in graph.objects(node, SKOS.broader):
                desired_broader[(uri, str(other))] = None
            for other in graph.objects(node, SKOS.narrower):
                desired_broader[(str(other), uri)] = None
            for other in graph.objects(node, SKOS.related):
                desired_related[frozenset({uri, str(other)})] = None

        resolved_broader: set[tuple[int, int]] = set()
        resolved_related: set[frozenset[int]] = set()
        concepts_by_pk: dict[int, Concept] = {}

        for narrower_uri, broader_uri in desired_broader:
            if narrower_uri == broader_uri:
                # The model refuses a self-relation.
                continue
            narrower_concept = self._resolve_concept_reference(
                narrower_uri, successful_concepts
            )
            broader_concept = self._resolve_concept_reference(
                broader_uri, successful_concepts
            )
            if narrower_concept is None or broader_concept is None:
                subject_uri = (
                    narrower_uri if narrower_concept is not None else broader_uri
                )
                other_uri = (
                    broader_uri if narrower_concept is not None else narrower_uri
                )
                self.report.add_set_aside(
                    SetAsideReason.MISSING_RELATION_END,
                    subject=subject_uri,
                    other=other_uri,
                )
                continue
            resolved_broader.add((narrower_concept.pk, broader_concept.pk))
            concepts_by_pk[narrower_concept.pk] = narrower_concept
            concepts_by_pk[broader_concept.pk] = broader_concept

        for pair in desired_related:
            if len(pair) < 2:
                # A single-element pair is a self-relation, which the model refuses.
                continue
            a_uri, b_uri = tuple(pair)
            a_concept = self._resolve_concept_reference(a_uri, successful_concepts)
            b_concept = self._resolve_concept_reference(b_uri, successful_concepts)
            if a_concept is None or b_concept is None:
                subject_uri = a_uri if a_concept is not None else b_uri
                other_uri = b_uri if a_concept is not None else a_uri
                self.report.add_set_aside(
                    SetAsideReason.MISSING_RELATION_END,
                    subject=subject_uri,
                    other=other_uri,
                )
                continue
            resolved_related.add(frozenset({a_concept.pk, b_concept.pk}))
            concepts_by_pk[a_concept.pk] = a_concept
            concepts_by_pk[b_concept.pk] = b_concept

        successful_ids = {concept.pk for concept in successful_concepts.values()}

        # Scoped by scheme, not `__in` over every concept: PostgreSQL caps bind parameters at
        # 65,535, reached near 33k concepts. Both ends of a relation share a scheme.
        existing_broader = ConceptRelation.objects.filter(
            kind=ConceptRelation.Kind.BROADER, source__scheme=self.target_scheme
        )
        for row in existing_broader:
            if (
                row.source_id not in successful_ids
                or row.target_id not in successful_ids
            ):
                continue
            if (row.source_id, row.target_id) not in resolved_broader:
                row.delete()

        existing_related = ConceptRelation.objects.filter(
            kind=ConceptRelation.Kind.RELATED, source__scheme=self.target_scheme
        )
        for row in existing_related:
            if (
                row.source_id not in successful_ids
                or row.target_id not in successful_ids
            ):
                continue
            if frozenset({row.source_id, row.target_id}) not in resolved_related:
                row.delete()

        for narrower_pk, broader_pk in resolved_broader:
            already_stored = ConceptRelation.objects.filter(
                source_id=narrower_pk,
                target_id=broader_pk,
                kind=ConceptRelation.Kind.BROADER,
            ).exists()
            if already_stored:
                continue
            # Clear a stale related row first: the bulk pass above only sees rows whose ends were
            # both written this run, and add_broader raises on a disjoint pair.
            conflicting_related = ConceptRelation.objects.filter(
                kind=ConceptRelation.Kind.RELATED
            ).filter(
                Q(source_id=narrower_pk, target_id=broader_pk)
                | Q(source_id=broader_pk, target_id=narrower_pk)
            )
            for row in conflicting_related:
                self.report.add_set_aside(
                    SetAsideReason.RELATION_DISJOINTNESS,
                    subject=concepts_by_pk[narrower_pk].static_uri,
                    other=concepts_by_pk[broader_pk].static_uri,
                )
                row.delete()
            concepts_by_pk[narrower_pk].add_broader(concepts_by_pk[broader_pk])

        for pk_pair in resolved_related:
            a_pk, b_pk = tuple(pk_pair)
            already_stored = (
                ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED)
                .filter(
                    Q(source_id=a_pk, target_id=b_pk)
                    | Q(source_id=b_pk, target_id=a_pk)
                )
                .exists()
            )
            if already_stored:
                continue
            conflicting_broader = (
                ConceptRelation.objects.filter(kind=ConceptRelation.Kind.BROADER)
                .filter(
                    Q(source_id=a_pk, target_id=b_pk)
                    | Q(source_id=b_pk, target_id=a_pk)
                )
                .exists()
            )
            if conflicting_broader:
                self.report.add_set_aside(
                    SetAsideReason.RELATION_DISJOINTNESS,
                    subject=concepts_by_pk[a_pk].static_uri,
                    other=concepts_by_pk[b_pk].static_uri,
                )
                continue
            concepts_by_pk[a_pk].add_related(concepts_by_pk[b_pk])


class CollectionImporter(ConceptReferenceResolverMixin):
    """Create or update each ``skos:Collection`` and its membership in the target vocabulary.

    Args:
        skos_graph: The parsed graph to read collections from.
        report: The report each finding is recorded on.
        target_scheme: The vocabulary being imported into.
        matcher: Resolves a published language tag to a configured language.
    """

    _HANDLED_PREDICATES = frozenset(
        {
            rdflib.RDF.type,
            SKOS.prefLabel,
            SKOS.member,
            SKOS.memberList,
        }
    )

    def __init__(
        self,
        skos_graph: SkosGraph,
        report: ImportReport,
        target_scheme: ConceptScheme,
        *,
        matcher: LanguageMatcher,
    ) -> None:
        self.skos_graph = skos_graph
        self.report = report
        self.target_scheme = target_scheme
        self.matcher = matcher

    def import_collections(self, successful_concepts: dict[str, Concept]) -> None:
        """Create or update every collection in the graph, with its membership.

        Runs once every concept this run wrote has a primary key, since membership resolves
        concepts the way a relation end does. A blank-node collection is fatal and collected.
        The ``skos:memberList`` cells are blank nodes too, but ``graph.items()`` yields the
        member URIs and never the cells, so they never reach identification. A collection whose
        URI is already held by another vocabulary or by a concept is set aside.

        Membership comes from ``skos:member`` (sorted) or ``skos:memberList`` (file order). An
        ordered collection with both keeps the list order and appends any ``skos:member`` the
        list omits, sorted. A member that resolves to nothing is set aside and the collection
        keeps whatever did resolve. Membership is written only through the model's ``add``,
        ``remove`` and ``set_member_order`` so its cross-scheme check always runs. A stored
        membership is a removal candidate only when its concept was written this run.

        Every stored collection of the vocabulary that the file does not mention is left
        untouched and named in ``report.absent_from_source``.

        Args:
            successful_concepts: The concepts this run created or updated, keyed by URI.

        Raises:
            SkosImportError: A ``skos:memberList`` never terminates, so its membership is
                undefined and the whole run is refused.
        """
        graph = self.skos_graph.graph
        collection_nodes = sorted(
            set(graph.subjects(rdflib.RDF.type, SKOS.Collection))
            | set(graph.subjects(rdflib.RDF.type, SKOS.OrderedCollection)),
            key=str,
        )
        successful_ids = {concept.pk for concept in successful_concepts.values()}
        mentioned_uris: set[str] = set()
        taken_slugs: dict[str, str | None] = dict(
            Collection.objects.filter(scheme=self.target_scheme).values_list(
                "slug", "static_uri"
            )
        )

        for node in collection_nodes:
            hint = self.skos_graph.first_literal(node, SKOS.prefLabel)
            try:
                uri = self.skos_graph.identify(node, hint=hint)
            except FatalIdentity as exc:
                self.report.add_fatal(exc.reason, exc.subject, **exc.params)
                continue
            mentioned_uris.add(uri)

            ordered = (node, rdflib.RDF.type, SKOS.OrderedCollection) in graph

            try:
                row = Collection.objects.get_by_uri(uri)
                created = False
            except Collection.DoesNotExist:
                try:
                    Concept.objects.get_by_uri(uri)
                except Concept.DoesNotExist:
                    pass
                else:
                    self.report.add_set_aside(
                        SetAsideReason.URI_HELD_BY_DIFFERENT_KIND, subject=uri
                    )
                    continue
                row = Collection(scheme=self.target_scheme)
                created = True

            if not created and row.scheme_id != self.target_scheme.pk:
                self.report.add_set_aside(
                    SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY,
                    subject=uri,
                    current=row.scheme.uri,
                    target=self.target_scheme.uri,
                )
                continue

            if not identifier_slug_base(uri):
                # Unlike a vocabulary, a collection is not needed to import the rest of the
                # file, so this is set aside rather than fatal.
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue

            row.scheme = self.target_scheme
            row.static_uri = uri
            default_language = self.target_scheme.effective_default_language
            name_max_length = cast(int, Collection._meta.get_field("name").max_length)
            name_match = _localized_literal(
                self.skos_graph, self.matcher, node, SKOS.prefLabel, default_language
            )
            if name_match is None:
                any_literal = self.skos_graph.first_literal_with_language(
                    node, SKOS.prefLabel, max_length=name_max_length
                ) or self.skos_graph.first_literal_with_language(node, SKOS.prefLabel)
                name, winning_tag = (
                    any_literal if any_literal is not None else (None, default_language)
                )
            else:
                name, winning_tag = name_match
                if winning_tag.lower() != default_language.lower():
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=winning_tag,
                        kept_as=default_language,
                    )
            if name and len(name) > name_max_length:
                if created:
                    # A created collection has no earlier name to fall back on, so it is dropped
                    # whole. A matched one keeps the name it holds.
                    fallback = self.skos_graph.first_literal_with_language(
                        node, SKOS.prefLabel, max_length=name_max_length
                    )
                    if fallback is None:
                        self.report.add_set_aside(
                            SetAsideReason.VALUE_TOO_LONG,
                            subject=uri,
                            language=winning_tag,
                        )
                        # VALUE_TOO_LONG alone cannot tell a dropped collection from one that kept
                        # its name (docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md).
                        self.report.add_set_aside(
                            SetAsideReason.COLLECTION_NOT_CREATED, subject=uri
                        )
                        continue
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG, subject=uri, language=winning_tag
                    )
                    name, winning_tag = fallback
                    row.name = name
                else:
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG, subject=uri, language=winning_tag
                    )
            elif name:
                row.name = name
            elif created:
                # No prefLabel at all: nothing is over-long, so name the record outcome instead.
                self.report.add_set_aside(
                    SetAsideReason.COLLECTION_NOT_CREATED, subject=uri
                )
                continue
            row.ordered = ordered
            # Minted only for a created collection; a matched row keeps its stored slug (docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md).
            if created:
                max_length = cast(int, Collection._meta.get_field("slug").max_length)
                row.slug = unique_slug_for_identifier(uri, taken_slugs, max_length)
                if not row.slug:
                    self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                    continue
            row.slug_is_manual = True
            try:
                row.save()
            except ValidationError:
                self.report.add_set_aside(
                    SetAsideReason.STORED_SLUG_INVALID, subject=uri
                )
                continue
            if created:
                self.report.add_created(uri)
            else:
                self.report.add_updated(uri)
            report_unmodelled_predicates(
                self.skos_graph, node, uri, self._HANDLED_PREDICATES, self.report
            )

            if ordered:
                member_list_node = graph.value(node, SKOS.memberList)
                if member_list_node is not None:
                    try:
                        ordered_uris = [
                            str(item) for item in graph.items(member_list_node)
                        ]
                    except ValueError as exc:
                        # A memberList whose rdf:rest chain loops makes graph.items() raise, and it has
                        # no membership to import, so the whole run is refused.
                        raise SkosImportError(
                            _(
                                "'%(subject)s' has a skos:memberList that does not terminate (its rdf:rest "
                                "chain loops back on itself); the import was refused."
                            ),
                            params={"subject": uri},
                            code="skos_cyclic_member_list",
                        ) from exc
                    # memberList narrows member rather than replacing it: a member it omits is
                    # still asserted and must survive.
                    member_only = sorted(
                        {str(obj) for obj in graph.objects(node, SKOS.member)}
                        - set(ordered_uris)
                    )
                    member_uris = ordered_uris + member_only
                else:
                    member_uris = sorted(
                        {str(obj) for obj in graph.objects(node, SKOS.member)}
                    )
            else:
                member_uris = sorted(
                    {str(obj) for obj in graph.objects(node, SKOS.member)}
                )

            resolved: list[Concept] = []
            seen_pks: set[int] = set()
            for member_uri in member_uris:
                concept = self._resolve_concept_reference(
                    member_uri, successful_concepts
                )
                if concept is None:
                    self.report.add_set_aside(
                        SetAsideReason.MISSING_MEMBER,
                        subject=member_uri,
                        collection=uri,
                    )
                    continue
                if concept.pk in seen_pks:
                    continue
                seen_pks.add(concept.pk)
                resolved.append(concept)

            resolved_pks = {concept.pk for concept in resolved}
            for membership in list(row.memberships.select_related("concept")):
                if (
                    membership.concept_id in successful_ids
                    and membership.concept_id not in resolved_pks
                ):
                    row.remove(membership.concept)

            for concept in resolved:
                row.add(concept)

            if ordered:
                current = [
                    membership.concept
                    for membership in row.memberships.select_related(
                        "concept"
                    ).order_by("position", "id")
                ]
                survivors = [
                    concept for concept in current if concept.pk not in resolved_pks
                ]
                row.set_member_order(resolved + survivors)

        # Filtered and sorted in Python: `.uri` is not a column and covers rows whose static_uri
        # is NULL, and a file-sized `__in` would hit the PostgreSQL bind-parameter cap.
        absent = [
            collection
            for collection in Collection.objects.filter(scheme=self.target_scheme)
            if collection.static_uri not in mentioned_uris
        ]
        for collection in sorted(absent, key=lambda row: row.uri):
            self.report.add_absent_from_source(collection.uri)


class SkosImporter:
    """Run one import: hold the graph, report and transaction, and drive each importer in turn.

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

        Re-running upserts: a record the file contains is matched to it exactly, including
        dropping a value the file no longer carries, and a record it does not mention is left
        untouched and named in ``report.absent_from_source``. Anything the models have no place
        for is set aside and reported rather than dropped (Article XI).

        The whole run is one transaction. A fatal finding is collected rather than raised, so a
        file with several problems reports all of them, and the run raises once nothing further
        can be checked.

        Returns:
            The report of what the run created, updated, normalised and set aside.

        Raises:
            SkosImportFailed: The run recorded a fatal finding; nothing is written.
        """
        skos_graph = SkosGraph.from_file(
            self.file, serialization=self.serialization, base_uri=self.base_uri
        )
        source_label = str(self.base_uri or self.file)

        with transaction.atomic():
            declared_nodes = sorted(
                skos_graph.graph.subjects(rdflib.RDF.type, SKOS.ConceptScheme), key=str
            )
            # Nodes only implied to be concepts join before scheme disambiguation, so they count
            # towards which vocabulary the file is about.
            concept_nodes = sorted(
                set(skos_graph.graph.subjects(rdflib.RDF.type, SKOS.Concept))
                | skos_graph.implied_concept_nodes(),
                key=str,
            )
            # Built once, before any concept is written: settling a variant contest needs the
            # whole file's tag counts first.
            matcher = LanguageMatcher.from_settings(
                skos_graph.preferred_label_tag_counts(concept_nodes)
            )

            resolver = SchemeResolver(
                skos_graph,
                self.report,
                target=self.target,
                source_label=source_label,
                matcher=matcher,
            )
            declared_node = resolver.choose_declared_scheme(
                declared_nodes, concept_nodes
            )
            target_scheme, declared_uri = (
                (None, None)
                if self.report.fatal
                else resolver.resolve_scheme(declared_node, concept_nodes)
            )

            if target_scheme is not None and declared_uri is not None:
                # effective_default_language can fall back to settings.LANGUAGE_CODE without being
                # checked against LANGUAGES, so no candidate could match it. Report that once rather
                # than setting aside every concept.
                if not matcher.resolve(
                    target_scheme.effective_default_language
                ).is_exact:
                    self.report.add_fatal(
                        FatalReason.DEFAULT_LANGUAGE_UNCONFIGURED,
                        subject=declared_uri,
                        language=target_scheme.effective_default_language,
                    )
                else:
                    concept_importer = ConceptImporter(
                        skos_graph,
                        self.report,
                        target_scheme,
                        declared_uri,
                        matcher=matcher,
                    )
                    successful_concepts = concept_importer.import_concepts(
                        concept_nodes
                    )
                    RelationImporter(
                        skos_graph, self.report, target_scheme
                    ).import_relations(successful_concepts)
                    CollectionImporter(
                        skos_graph, self.report, target_scheme, matcher=matcher
                    ).import_collections(successful_concepts)
                    concept_importer.report_absent_concepts()

            if self.report.fatal:
                raise SkosImportFailed(self.report)

        return self.report


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
        The report of what the run created, updated, normalised and set aside.
    """
    return SkosImporter(
        file, serialization=serialization, scheme=scheme, base_uri=base_uri
    ).run()
