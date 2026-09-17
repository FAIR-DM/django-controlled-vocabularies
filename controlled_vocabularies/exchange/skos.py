"""Reading a published SKOS file into records (FS-006).

The RDF boundary: a file becomes an ``rdflib`` graph (:meth:`SkosGraph.from_file`), the graph is
walked into the models R1 built, and the run returns a structured
:class:`~controlled_vocabularies.exchange.report.ImportReport` of what it did (Article X: RDF is
read only at this boundary, never stored as a graph).

:func:`import_skos` is the module's one public entry point, a thin wrapper over
:class:`SkosImporter`. It resolves or creates the vocabulary a file declares, then imports each
concept — identity, labels, notes, relationships, and collection membership — setting aside
anything the models have no place for rather than dropping it (Article XI). The whole run is one
transaction: a fatal finding rolls the run back entirely, after every problem has been collected,
not only the first.
"""

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

#: The three serializations FR-002 requires this feature to read. Anything
#: else — an unrecognised extension with no explicit ``format``, or an
#: explicit ``format`` naming a serialization outside this set — fails the
#: run rather than being handed to rdflib on the chance it understands it:
#: FR-002 names exactly these three, not "whatever rdflib happens to parse".
_SUPPORTED_FORMATS = frozenset({"turtle", "xml", "json-ld"})


def identifier_slug_segment(uri: str) -> str:
    """The part of a published identifier that anchors a local address (FR-017/FR-018,
    decisions.md D35): the fragment, where the identifier has one, otherwise the last
    segment of its path. Shared by :class:`ConceptImporter` and :class:`SchemeResolver`,
    the two callers that turn a ``static_uri`` into a slug — both segments of a local
    address are identifier-derived by the same rule.

    Not itself guaranteed to be a valid slug (an identifier's segment can carry
    characters a :class:`~django.db.models.SlugField` refuses); every caller runs the
    result through ``slugify()`` before storing or comparing it.
    """
    parsed = urllib.parse.urlsplit(uri)
    if parsed.fragment:
        return parsed.fragment
    return parsed.path.rstrip("/").rsplit("/", 1)[-1]


def identifier_slug_base(uri: str) -> str:
    """The slugified identifier segment (FR-017/FR-018/FR-020) — ``""`` when the segment is made
    up only of characters ``slugify()`` strips (ARCH-305, fix cycle 4, decisions.md D55).

    One definition of "this identifier has no usable base", shared by :func:`unique_slug_for_identifier`
    (which suffixes it on a collision) and the pre-write ``EMPTY_SLUG`` guards in
    :meth:`ConceptImporter.import_concepts` and :meth:`CollectionImporter.import_collections`
    (which run for a *matched* record too, so they can never simply call
    :func:`unique_slug_for_identifier` itself — see that function's own note about matched
    records never being re-minted).
    """
    return slugify(identifier_slug_segment(uri), allow_unicode=True)


def unique_slug_for_identifier(
    static_uri: str, taken_slugs: dict[str, str | None], max_length: int
) -> str:
    """The deterministic, collision-resolved slug for ``static_uri`` (FR-017/FR-018/FR-020,
    decisions.md D35): the same identifier-derived base (:func:`identifier_slug_segment`), with a
    numeric suffix appended only when the candidate already belongs to a *different* record. An
    unusable base (an identifier segment made up only of characters ``slugify()`` strips) is
    returned as ``""`` rather than suffixed — a caller decides what that means for its own record
    kind (a concept is set aside, decisions.md D39; a vocabulary is fatal, decisions.md D35 fix
    cycle 2, since nothing else in the file has anywhere to import into).

    Shared by :meth:`ConceptImporter.assign_unique_slug`, :meth:`SchemeResolver.resolve_scheme`
    and :meth:`CollectionImporter.import_collections` — a collision in any of the three record
    kinds is the same computation (Article XV), so the shape is not duplicated three times.

    ``taken_slugs`` maps every claimed slug to its claimant's ``static_uri``, mutated in place so a
    caller resolving more than one record in the same run sees each prior assignment as taken.
    Because ``static_uri`` never changes once assigned, a record's own previously-stored slug is
    always read back to itself rather than suffixed (FR-020's "same file yields the same slugs
    however it is traversed").

    ``max_length`` (T042, SEC-002-shaped, decisions.md D35 fix cycle 3) bounds the returned value
    to the calling model's own ``SlugField.max_length`` — never a literal ``255`` written a second
    time here. A published identifier segment can be arbitrarily long; nothing on this write path
    calls ``full_clean()``, so an unbounded slug lands unchecked on SQLite and raises a bare
    ``DataError`` on PostgreSQL. The *base* is truncated, leaving room for the numeric suffix, and
    the assembled candidate is itself clamped to ``max_length`` (SEC-405, decisions.md D63, fix
    cycle 5), so the returned candidate never exceeds ``max_length`` however many collisions it
    resolves — true even at ``max_length < len(suffix_text) + 1``, where keeping one base
    character and the whole suffix would otherwise still overrun the field.

    Returns ``""`` — the same "unusable" signal an empty base already gives — rather than looping
    forever when no further collision retry can produce a candidate distinct from one already
    tried (T056, CORR-503, decisions.md D66, fix cycle 6): once ``max_length`` is small enough
    relative to the suffix text, the clamp above can make two *different* suffixes render as the
    identical truncated string, and a candidate that keeps re-colliding with the same taken slug
    would otherwise never terminate.

    ``tried`` (T060, CORR-601/SEC-604, decisions.md D70, fix cycle 7) records only candidates this
    loop has itself *generated*, never ``base`` — the ``while`` condition above has already tested
    ``base`` on its own. Seeding it with ``base`` made the give-up fire on a collision's very
    first retry whenever ``len(base) == max_length`` and ``base`` ends in ``-2``: the clamp above
    then renders that retry's candidate as ``base`` itself (``base[:253] + "-2" == base`` at
    ``max_length=255``), which looked like a repeat of a *tried* candidate rather than what it
    actually was — the first and only attempt so far, resolvable by the very next suffix.
    """
    base = identifier_slug_base(static_uri)[:max_length]
    if not base:
        return ""
    candidate = base
    suffix = 1
    tried: set[str] = set()
    while taken_slugs.get(candidate, static_uri) != static_uri:
        suffix += 1
        suffix_text = f"-{suffix}"
        # T046, SEC-303 (fix cycle 4): a bare `max_length - len(suffix_text)` goes to zero or
        # negative once the suffix is as long as (or longer than) max_length, and Python slices
        # from the *end* of the string instead of raising — the candidate then loses its
        # relationship to the base entirely (at equality, the bare suffix). Unreachable at any
        # of the three current call sites (all pass 255), fixed by construction anyway: always
        # keep at least one base character.
        #
        # SEC-405 (fix cycle 5): keeping one base character plus the whole suffix can still
        # exceed max_length when the suffix alone is longer than max_length - 1 — the docstring's
        # own "never exceeds max_length" claim was false in that case. The final `[:max_length]`
        # clamps the assembled candidate, not only the base.
        candidate = (base[: max(max_length - len(suffix_text), 1)] + suffix_text)[
            :max_length
        ]
        if candidate in tried:
            # CORR-503 (fix cycle 6): the clamp above can render two different suffixes as the
            # same truncated string once max_length is small relative to suffix_text — a repeat
            # proves this call cannot resolve the collision within the field's own width, not
            # merely that this one candidate is taken. Every one of the three current call sites
            # passes max_length=255, so this is unreached in practice (D51/D63 already put the
            # collision count needed at roughly 10^250); a direct caller of this module-level
            # helper with a small max_length is the only way to reach it.
            return ""
        tried.add(candidate)
    taken_slugs[candidate] = static_uri
    return candidate


class FatalIdentity(Exception):
    """Internal signal that a node's identity is fatal (D3/FR-004); carries the finding to record."""

    def __init__(self, reason: FatalReason, subject: str, **params: str) -> None:
        self.reason = reason
        self.subject = subject
        self.params = params
        super().__init__(subject)


class SkosGraph:
    """Wraps the parsed ``rdflib.Graph`` and the pure, read-only queries the importer runs
    against it — the RDF boundary itself.
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
        """Read ``file`` into a :class:`SkosGraph` (research.md R1, FR-002).

        ``serialization`` is the caller-stated format; when omitted it is guessed from the file's
        extension. Either way the result must be one of :data:`_SUPPORTED_FORMATS`, or the run
        fails naming the file (FR-002).

        RDF/XML and JSON-LD are scanned by :mod:`~controlled_vocabularies.exchange.safety` before
        rdflib ever sees them (research.md R3, D9, D36) — either way rdflib then reads the file a
        second time from ``path`` itself, deliberately: its file-based parse establishes its base
        URI from the file's own location (D13), which pre-read ``data=`` bytes would silently
        change.

        ``base_uri``, when given, is passed to rdflib as ``publicID`` (FR-003, decisions.md D10):
        a fetched document's relative identifiers resolve against the address it was published
        at, not the temporary file it was written to for the parse. Omitted, this is exactly
        today's behaviour — the parse takes its base from ``path`` itself (D13). ``base_uri`` also
        settles what a refusal below calls the source, since a fetched document's temporary file
        no longer exists by the time an operator reads the message.

        A file that cannot be found or parsed raises :class:`SkosImportError` rather than letting
        rdflib's own exception escape. The pre-flight scan itself is wrapped the same way (review
        fix 18, D51): a malformed document can make the scan raise a bare exception outside this
        try/except otherwise. The *deliberate* refusals,
        :class:`~controlled_vocabularies.exchange.exceptions.UnsafeRdfXmlError` and
        :class:`~controlled_vocabularies.exchange.exceptions.UnsafeJsonLdError`, are excluded from that
        wrapping and propagate as themselves (D36).
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
                # Pre-flight only — the bytes read here are not what gets parsed (see the base-URI
                # note above), so a second, larger read is a deliberate, small cost on RDF/XML input.
                scan_rdf_xml(path.read_bytes())
            elif resolved_format == "json-ld":
                # Same pre-flight discipline, closing the equivalent hole D36 found in JSON-LD's own
                # remote-`@context` route.
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
        """Return ``node``'s usable identifier, or raise :class:`FatalIdentity` (FR-004, D3).

        A blank node supplies no identifier that survives re-serialization and is always fatal —
        an ordered collection's own member list is read as a list, never as a candidate record, so
        it never reaches this function. A ``URIRef`` is checked through
        :func:`~controlled_vocabularies.models.validate_static_uri`, the same identity rule the
        models enforce on a stored ``static_uri`` (research.md R6).

        ``hint`` — typically the node's own preferred label, when one could be read before the
        identity check ran — gives the fatal message something recognisable to point a curator at
        when the node itself has no URI to show.
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
        """Whether ``literal`` is a published value this application can store as a name (T059,
        SEC-601/CORR-602, decisions.md D69): an :class:`rdflib.Literal` whose text survives
        stripping surrounding whitespace.

        The one predicate every literal-to-name-candidate read shares (:meth:`first_literal`,
        :meth:`first_literal_with_language`, :meth:`label_languages`, :meth:`preferred_label_in`,
        and :class:`ConceptImporter`'s own read of the same label predicates for a concept's
        non-default-language labels), rather than each repeating an equivalent check — which is
        exactly how T055 (D65, fix cycle 6) applied an equivalent test inline in only the first
        two of those and left the others, most notably a concept's own preferred label, still
        treating an empty literal as a usable name. A :class:`~typing.TypeGuard` rather than a
        plain ``bool`` so a caller's own ``isinstance`` narrowing (``literal.language`` below) is
        not lost behind the method call.
        """
        return isinstance(literal, rdflib.Literal) and bool(str(literal).strip())

    def first_literal(
        self,
        node: rdflib.term.Node,
        predicate: rdflib.URIRef,
        *,
        language: str | None = None,
    ) -> str | None:
        """The lexicographically-first *usable* literal value of ``predicate`` on ``node``, or
        ``None``.

        Deterministic rather than "whichever rdflib happens to yield first" — the graph's own
        iteration order is not something to depend on for a value that ends up in a stored record
        (T010). ``language``, when given, restricts to literals tagged with that language.

        An empty or whitespace-only literal is excluded from selection entirely (T055, SEC-501/
        SEC-504, decisions.md D65; :meth:`is_usable_literal`, T059, decisions.md D69) — it is not
        a name or description any caller can actually store, and sorting on the raw string alone
        let it win over a real value published alongside it in the same file.
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
        """The lexicographically-first literal value of ``predicate`` on ``node``, paired with the
        published language tag it actually carried (``""`` for an untagged literal), or ``None``.

        The any-language counterpart of :meth:`first_literal` (T047, decisions.md D52, fix cycle
        4): a caller reporting a value this fallback selected needs to name the language that
        value was published in, not the target language the fallback exists because nothing
        resolved to. With no ``max_length``, selects the identical value :meth:`first_literal`
        (called with no ``language``) would — same sort key — so the two never disagree about
        *which* literal.

        ``max_length`` (T051, SEC-401, decisions.md D56) restricts the selection to literals a
        caller can actually store: an any-language fallback exists so a record is not left with
        no name at all, and picking the lexicographically first literal regardless of length
        defeated that purpose whenever it happened to sort ahead of a shorter, storable one in
        the same file. Returns ``None`` when no literal exists at all, or (with ``max_length``
        given) when none of them fit — a caller distinguishes the two only when it needs to,
        by calling again with no ``max_length`` to get a representative value for a message.

        An empty or whitespace-only literal is excluded unconditionally, with or without
        ``max_length`` (T055, SEC-501/SEC-502/SEC-504, decisions.md D65; :meth:`is_usable_literal`,
        T059, decisions.md D69) — it always satisfies a length filter and always sorts first, so
        without this it wins the fallback over any real value published alongside it, in both
        branches this fallback is called from (nothing published in the target language at all,
        and the target-language value itself being unusable).
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
        """The language tags of ``predicate``'s usable literal values on ``node`` (empty-tag
        values excluded, T059/SEC-602, decisions.md D69: an empty or whitespace-only literal is
        excluded here too, the same as every other name-candidate read — otherwise it could not
        itself win a name slot, yet it still tipped :meth:`preferred_label_tag_counts`'
        predominance vote between two real variants that could).
        """
        return [
            literal.language
            for literal in self.graph.objects(node, predicate)
            if self.is_usable_literal(literal) and literal.language
        ]

    def preferred_label_in(self, node: rdflib.term.Node) -> list[tuple[str, str]]:
        """Every ``(published tag, value)`` pair ``node`` carries a usable ``skos:prefLabel`` in
        (T007; :meth:`is_usable_literal`, T059, SEC-601/CORR-602, decisions.md D69).

        Unfiltered by language: which pair fills a configured language's slot is decided by
        :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner`, and that
        policy does not belong on this RDF boundary (Article XV) — the caller, which already holds
        the matcher, resolves and picks a winner from what this returns.
        """
        return sorted(
            (str(literal.language), str(literal))
            for literal in self.graph.objects(node, SKOS.prefLabel)
            if self.is_usable_literal(literal) and literal.language
        )

    def preferred_label_tag_counts(
        self, concept_nodes: Iterable[rdflib.term.Node]
    ) -> dict[str, int]:
        """How often each published language tag appears across ``concept_nodes``'
        own ``skos:prefLabel`` values (T002, research.md R2, decisions.md D4/D5).

        That predicate and that node set, and no other: the vocabulary's own
        ``skos:prefLabel`` and every collection's are excluded, because
        :meth:`SchemeResolver.determine_default_language` already counts exactly
        this population (``skos.py:327``) and a contest can only ever turn on it
        (D4). A caller passing a wider node set would silently change that
        already-shipped rule.

        Keyed case-folded (CORR-003/SEC-003, decisions.md D34): ``rdflib``
        preserves a literal's published case, but FR-001 makes matching
        case-insensitive throughout — ``pt-BR`` and ``pt-br`` are one
        published tag, not two, so :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner`
        (which looks this tally up case-folded too) never splits one
        population's vote across cases.
        """
        counts: dict[str, int] = {}
        for node in concept_nodes:
            for language in self.label_languages(node, SKOS.prefLabel):
                key = language.lower()
                counts[key] = counts.get(key, 0) + 1
        return counts

    def scheme_refs(self, concept_node: rdflib.term.Node) -> set[str]:
        """Every vocabulary URI this concept declares membership of, by any of the three predicates."""
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
        """The URI of a *different* vocabulary this concept claims, if any (T009, FR-006).

        A concept with no scheme reference at all is not a conflict — it is read as belonging to
        the vocabulary being imported — so this returns ``None`` both when every reference agrees
        with ``target_scheme_uri`` and when there is no reference to check.
        """
        others = self.scheme_refs(concept_node) - {target_scheme_uri}
        return sorted(others)[0] if others else None

    def implied_concept_nodes(self) -> set[rdflib.term.Node]:
        """Nodes the file identifies as concepts through a scheme-membership predicate, but never
        types with ``rdf:type skos:Concept`` at all (review fix 17, decisions.md D50).

        Restricted to a node carrying **no** ``rdf:type`` whatsoever — one the file does type, as
        something other than ``skos:Concept``, is left entirely to whatever that type already
        makes of it, never reclassified.
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
    """The value of ``predicate`` on ``node`` whose published tag resolves to ``target_language``
    through ``matcher`` (T008, call sites 6/7/8), paired with the winning published tag, or
    ``None``.

    ``SkosGraph.first_literal``'s own ``language=`` filter is an exact match; resolving a variant
    tag to ``target_language`` is configured-language policy, which stays off ``SkosGraph``
    (Article XV), so it happens here, reading only the graph's public, read-only queries. Without
    this, a site importing a vocabulary declared in a variant of its default language names every
    concept correctly and then falls through to :meth:`SkosGraph.first_literal`'s own any-language
    fallback — ``sorted(...)[0]`` across every language in the file — for the record's own name.

    The winning tag is returned rather than discarded (CORR-002, decisions.md D34) so each of this
    function's three callers can report a :attr:`~controlled_vocabularies.exchange.report.NormalizedReason.LANGUAGE_SUBSTITUTION`
    when it differs from ``target_language`` — the same guard :meth:`ConceptImporter.import_concepts`
    already applies to ``Concept.label`` over an identical candidate computation, so a vocabulary's
    name and description and a collection's name are held to the one rule everywhere it applies,
    not silently exempted at three of its four sites.
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
    """Set aside and report a predicate ``node`` carries that is neither in ``handled`` — already
    accounted for elsewhere, for whatever kind of node this is — nor itself a SKOS predicate
    this module has no read path for *yet* (FIX 12, D45; generalises D27's own concept-only
    rule past the single node kind it was written for). A SKOS predicate with no read path is
    deliberately not reported: the models do have a place for it, only "not yet built" applies.
    Called once per node this module treats as a record with its own identity — a concept, the
    vocabulary's own scheme node, and a collection — each with its own ``handled`` set naming
    what it already reads.
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
    """Resolves which vocabulary a file belongs to: the one it declares, or a caller-named target
    (FR-005).
    """

    #: Predicates the vocabulary's own scheme node carries that :meth:`resolve_scheme` already
    #: reads and accounts for (FIX 12, decisions.md D45): its own identity, name
    #: (``skos:prefLabel``), top concepts, and description. ``skos:hasTopConcept`` is read *about*
    #: a concept, not held for the concept, so it is not shared with :class:`ConceptImporter`'s
    #: own handled set.
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
        """Return the :class:`ConceptScheme` matching ``uri``, or a new unsaved one (research.md R6)."""
        try:
            return ConceptScheme.objects.get_by_uri(uri)
        except ConceptScheme.DoesNotExist:
            return ConceptScheme(static_uri=uri)

    def determine_default_language(
        self, declared_node: rdflib.term.Node, concept_nodes: list[rdflib.term.Node]
    ) -> str:
        """The imported vocabulary's default language, per FR-005 (T008, decisions.md D4).

        Taken from the file where the file says: the vocabulary's own ``skos:prefLabel``, when
        tagged with exactly one language, else the language most of ``concept_nodes``' own
        preferred labels use, tied deterministically by language code. Either way the resolved
        language is found through :attr:`matcher` (T006, FR-007, decisions.md D9) rather than
        exact set membership — a vocabulary declaring itself in a variant of a configured language
        (``de-at`` on a ``de`` site) resolves to that configured language rather than falling
        through to the site's own default. When no configured language shares a base with either
        candidate, this returns ``""``, which :attr:`ConceptScheme.default_language` already
        treats as "fall back to the site's own default" (``effective_default_language``) — the
        mechanism R1 built, reused rather than duplicated.
        """
        declared_languages = set(
            self.skos_graph.label_languages(declared_node, SKOS.prefLabel)
        )
        if len(declared_languages) == 1:
            (declared_language,) = declared_languages
            resolved = self.matcher.resolve(declared_language).configured_language
            if resolved:
                return resolved

        # T040, decisions.md D34/D35 (fix cycle 3): reuses SkosGraph.preferred_label_tag_counts
        # (Article XV) rather than keeping its own unfolded copy of the identical walk — that
        # copy counted 'EN-GB' and 'en-gb' as two tags instead of the one FR-001 says they are.
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
        """Pick the one vocabulary a file is declaring, or fail saying it cannot (FR-005).

        A file routinely types more than one ``skos:ConceptScheme`` without being about more than
        one: a second is merely a vocabulary some concept claims membership of, set aside rather
        than refused (spec Edge Cases §1) — so multiplicity itself is not fatal. What decides is
        which declared vocabulary the file's own concepts belong to, by the same three membership
        predicates :meth:`SkosGraph.scheme_refs` reads; the one with the most members wins, never
        any property of the identifier itself such as sorted order (D5 makes the file authoritative
        for what it writes, not the alphabet). A genuine tie with no caller-named target to resolve
        it is refused. A named target always decides; one matching none of the declared
        vocabularies falls through to :meth:`resolve_scheme`'s own mismatch check.
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
        """Resolve, create or update the vocabulary being imported into (FR-005, T007).

        The file is authoritative for which vocabulary is being imported: when it declares none, a
        caller-named target is required; when it declares one, a given target must agree with it (a
        mismatch is fatal, nothing is written). Matches an existing record via ``get_by_uri``
        (research.md R6); otherwise creates one holding the file's identifier.

        Returns ``(scheme, declared_uri)`` — ``declared_uri`` is what concepts are later checked
        against for "belongs to a different vocabulary" (T009) — or ``(None, None)`` when
        resolution itself is fatal, in which case ``report.fatal`` already carries why.
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
            # ConceptScheme.save() itself refuses to change default_language once the scheme has
            # concepts (R1 — it is the anchor every concept's identity is built against, D4); only
            # a freshly created scheme has no concepts yet to protect.
            row.default_language = declared_default_language
        elif (
            declared_default_language
            and declared_default_language != row.effective_default_language
        ):
            # D18 froze this value once the scheme has concepts; D22 requires the conflict be
            # reported rather than silently kept. Compared against effective_default_language, not
            # the raw stored field, so a scheme relying on the site default that agrees with the
            # file in the same effective language is not a conflict.
            self.report.add_set_aside(
                SetAsideReason.DEFAULT_LANGUAGE_FROZEN,
                subject=declared_uri,
                declared=declared_default_language,
                frozen=row.effective_default_language,
            )
        # ARCH-306, fix cycle 4, decisions.md D55: cast rather than an `is not None` runtime
        # check, the same narrowing unique_slug_for_identifier's own max_length reads already
        # use (skos.py above) — Django's field metadata always supplies this for a CharField
        # the model itself declares, so the two Optional[int] narrowings were one computation
        # handled two different ways. Read ahead of the name resolution below (T051, decisions.md
        # D56): the any-language fallback needs it to pick a literal it can actually store.
        name_max_length = cast(int, ConceptScheme._meta.get_field("name").max_length)
        name_match = _localized_literal(
            self.skos_graph,
            self.matcher,
            declared_node,
            SKOS.prefLabel,
            row.effective_default_language,
        )
        if name_match is None:
            # The declared default language (or the site's, on fallback) carries no prefLabel on
            # the scheme itself — fall back to any language rather than leaving name unset.
            # T047, CORR-305, decisions.md D52 (fix cycle 4): the tag reported alongside this
            # fallback value is the one it was actually published in, not the target language
            # the fallback exists because nothing matched — the two can differ.
            # T051, SEC-401, decisions.md D56: prefer a literal this record can actually store —
            # the plain (unfiltered) lexicographically-first pick only stands in when nothing
            # published fits, so the length check below still has a representative name for its
            # fatal/set-aside message.
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
                # CORR-002, decisions.md D34: the same guard Concept.label's own write already
                # applies — a name that made it in under a different language than published is a
                # normalisation, not a silent substitution (FR-006, Article XI).
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=declared_uri,
                    language=winning_tag,
                    kept_as=row.effective_default_language,
                )
        if name and len(name) > name_max_length:
            if created:
                # T044, decisions.md D49 (fix cycle 4, ARCH-301/CORR-303/SEC-302): a scheme is
                # what the rest of the file imports into, so a *created* scheme with no usable
                # name has nothing to fall back to — row.name would stay '', and a row
                # full_clean() then refuses is exactly what D47's guard exists to prevent.
                # Fatal, the same reasoning VOCABULARY_SLUG_UNUSABLE already gives an unusable
                # identifier: without a resolvable, storable vocabulary there is nothing for
                # the rest of the file to import into.
                #
                # CORR-402, decisions.md D56 (fix cycle 5): the value above came straight from
                # the default-language match, which T051's fallback never runs for — a *different*
                # configured language may still publish a storable name in the same file. Try
                # that before refusing the run; its own message already promises this fatal is
                # reserved for "no name this application can store," which is false when another
                # published language has one.
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
                # T042, SEC-002-shaped, decisions.md D35 (fix cycle 3): row.save() never calls
                # full_clean(), so an over-long name would otherwise reach the database unchecked
                # on SQLite and raise a bare DataError on PostgreSQL — the same hole
                # Concept.label's own pre-write VALUE_TOO_LONG guard closes. A *matched* scheme
                # already has a name, so this leaves it exactly as held rather than losing it to
                # an unusable replacement.
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG,
                    subject=declared_uri,
                    language=winning_tag,
                )
        elif name:
            row.name = name
        elif created:
            # SEC-404, decisions.md D56 (fix cycle 5): the guard above only fires for an
            # over-long name; a scheme with no skos:prefLabel published at all reaches here with
            # name still None, which would otherwise leave row.name at the field default '' — the
            # exact state D49 already declares impossible for a created record, reached by a
            # different route.
            #
            # T058, CORR-504, decisions.md D68 (fix cycle 6): VOCABULARY_NAME_UNUSABLE's own
            # message names a published value that is "longer than this application can store" —
            # false on this path, since nothing was published at all. VOCABULARY_NAME_UNPUBLISHED
            # names what actually happened; no language param, since there is no language the
            # value was published in.
            self.report.add_fatal(
                FatalReason.VOCABULARY_NAME_UNPUBLISHED, subject=declared_uri
            )
            return None, None
        # SKOS defines no description predicate for a skos:ConceptScheme; dcterms:description is
        # the source (D21), the same alias CONTEXT.md establishes for a concept's own definition.
        # Unlike name, description is written unconditionally, including to empty when the file no
        # longer carries one — nothing anchors identity to it the way default_language is anchored.
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
        # T030, FR-018, decisions.md D35: the vocabulary's own slug is identifier-derived,
        # exactly like a concept's (T029, assign_unique_slug).
        # T035, FR-020, decisions.md D35 (fix cycle 2): two published vocabularies can end in the
        # same identifier segment, so the importer resolves that collision itself, the same shape
        # assign_unique_slug already resolves a concept's — ConceptScheme.save() keeps refusing
        # (never auto-suffixing) a colliding slug (research R4), which is a different case: a
        # curator setting two vocabularies' slugs equal by hand.
        # T041, FR-020, decisions.md D35 (fix cycle 3): minted through unique_slug_for_identifier
        # only for a scheme this run is creating — a matched row already holds a slug, which is
        # read back exactly as stored rather than recomputed, so no change in what else currently
        # occupies the table (a sibling vocabulary deleted, a slot vacated) can move an address
        # that has nothing to do with this scheme's own identifier (the "however many times it is
        # imported" reading of FR-020's "same file yields the same slugs however it is traversed").
        if created:
            taken_slugs: dict[str, str | None] = dict(
                ConceptScheme.objects.values_list("slug", "static_uri")
            )
            # ConceptScheme.slug declares max_length explicitly; cast rather than assert
            # narrows the type without a runtime check ruff's bandit rules refuse in production
            # code (S101), for a value Django's own field metadata always supplies here.
            max_length = cast(int, ConceptScheme._meta.get_field("slug").max_length)
            slug = unique_slug_for_identifier(declared_uri, taken_slugs, max_length)
            if not slug:
                # T036, decisions.md D35 (fix cycle 2): an identifier segment made up only of
                # characters slugify() strips is fatal, not set aside like a concept's EMPTY_SLUG —
                # without a resolvable vocabulary there is nothing for the rest of the file to
                # import into. Checked ahead of the write (the same discipline EMPTY_SLUG already
                # applies) rather than letting ConceptScheme.save()'s own refusal raise. Falling
                # back to row.name here would reinstate the exact defect FR-018 exists to remove.
                self.report.add_fatal(
                    FatalReason.VOCABULARY_SLUG_UNUSABLE, subject=declared_uri
                )
                return None, None
            row.slug = slug
        # T041: this is resolve_scheme's only write of the row — every field assigned above
        # (default_language, name, description, static_uri) is persisted here too, not by a
        # separate row.save() (ARCH-304, fix cycle 4). slug_is_manual is pinned True for both a
        # freshly minted slug and a matched row's own unchanged one, so a locally-authored
        # scheme the importer is matching for the first time also gets pinned.
        row.slug_is_manual = True
        try:
            row.save()
        except ValidationError as exc:
            # T045, SEC-301, decisions.md D50 (fix cycle 4): a matched row's slug is now read
            # back unchanged (T041) rather than recomputed, so a value written out of band
            # (.update(), loaddata, bulk_create, a data migration) reaches this validation
            # exactly as stored. Set aside rather than letting ValidationError escape
            # import_skos outside its own exception hierarchy — the same discipline
            # import_labels/_import_notes already apply to a value's own save().
            #
            # T052, CORR-401/SEC-403, decisions.md D57 (fix cycle 5): ConceptScheme.save() also
            # raises ValidationError for its frozen- and configured-default-language checks
            # (models.py), neither of which is a slug problem — a matched row's default_language
            # is never reassigned here (D46), so a language later dropped from
            # settings.LANGUAGES reaches this exact path with the slug untouched. Only report
            # STORED_SLUG_INVALID when the exception actually names the slug; anything else keeps
            # its own field name out of a message that would otherwise misdiagnose it.
            #
            # T057, CORR-505/SEC-503, decisions.md D67 (fix cycle 6): exc.message_dict is a
            # property that raises AttributeError for a ValidationError built from a bare message
            # or a list rather than a field dict — every raise this package's own save() chain
            # produces is dict-form, but a consumer's pre_save receiver or a subclass override is
            # not obliged to be. error_dict is the attribute message_dict itself guards on, and
            # its keys are the same field names; reading it with a default keeps this refusal
            # inside SkosImportFailed for every shape of ValidationError, not only the dict one.
            if "slug" in getattr(exc, "error_dict", {}):
                self.report.add_set_aside(
                    SetAsideReason.STORED_SLUG_INVALID, subject=declared_uri
                )
            # T052, CORR-401/SEC-402, decisions.md D57 (fix cycle 5): whichever field failed, the
            # scheme was not written, so nothing else in the file has a resolved vocabulary to
            # import into — every other `return None, None` in this method is preceded by
            # add_fatal; this one was not, and a run that imports nothing must never report
            # `fatal == []` (the precedent VOCABULARY_SLUG_UNUSABLE already sets for a vocabulary
            # that cannot be written at all).
            self.report.add_fatal(
                FatalReason.VOCABULARY_RECORD_INVALID, subject=declared_uri
            )
            return None, None
        if created:
            self.report.add_created(row.uri)
        else:
            self.report.add_updated(row.uri)
        # FIX 12 (D45): the scheme node itself can carry a non-SKOS predicate this module has no
        # place for, exactly as a concept or a collection can.
        report_unmodelled_predicates(
            self.skos_graph,
            declared_node,
            declared_uri,
            self._HANDLED_PREDICATES,
            self.report,
        )
        return row, declared_uri


class ConceptImporter:
    """Creates or updates each concept in the target vocabulary, and everything about it beyond
    identity (FR-006 onward).
    """

    #: Every predicate a concept node carries that this module already reads and accounts for
    #: elsewhere (T021): the identity/scheme predicates T009 reads, every label and note predicate
    #: (:data:`LABEL_PREDICATES`/`NOTE_PREDICATES`), the mapping predicates, and
    #: ``dcterms:description`` (the definition alias).
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
        """Store ``concept``'s labels other than its own default-language preferred one (T018, FR-008).

        Replaces whatever labels this concept already held: a label carries no identifier to upsert
        by, and the file is authoritative for what it contains (FR-013). :data:`LABEL_PREDICATES`
        covers ``skos:prefLabel``/``altLabel``/``hiddenLabel``; a preferred label whose *resolved*
        language is ``default_language`` (T008: compared through the matcher, not the raw published
        tag) is skipped — that slot is already ``concept.label`` (T009), and the model refuses a
        second preferred row in that language.

        A value sharing no base language with any configured one is set aside and reported by its
        own published tag, checked ahead of the write rather than letting ``ConceptLabel.clean()``'s
        own refusal raise (T020, FR-014, D25) — that exception protects a direct, out-of-band write,
        not this importer's control flow.

        A second ``skos:prefLabel`` resolving to one configured language — default or not — is the
        same shape of problem for a cardinality reason: the model allows only one ``PREFERRED`` row
        per (concept, language), so the contest is keyed on the *resolved* language and settled once
        per language by :meth:`~controlled_vocabularies.exchange.languages.LanguageMatcher.resolve_winner`
        (T013/T021) — not by grouping on the raw published tag, which let two *different* tags
        resolving to one non-default language both reach ``add_label()`` and crash the run on the
        model's own refusal, because each tag was its own singleton group and neither ever saw the
        other. This is the identical computation ``import_concepts`` already runs for
        ``Concept.label`` over the identical ``preferred_label_in`` candidates, so the two agree by
        construction rather than by coincidence (decisions.md D13). In every configured language's
        slot, default or not, a loser is discriminated by its own published tag against the tag the
        winner computation chose (T014): the same tag is a same-language duplicate and keeps
        ``SURPLUS_PREFERRED_LABEL`` (FIX 4, D38); a different tag is a losing variant and takes
        ``VARIANT_NOT_KEPT`` (T022, decisions.md D14) — the two populations have different remedies,
        which is what :meth:`~controlled_vocabularies.exchange.report.ImportReport.language_account`
        exists to tell apart.
        """
        concept.labels.all().delete()

        # One winner per resolved configured language this concept carries a skos:prefLabel
        # candidate for (T013/T021), read once here rather than grouped by raw published tag.
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
                    # FIX 15 (D48): a plain literal with no language tag, or an object that is not
                    # even a Literal (e.g. skos:altLabel pointing at a URI), used to be dropped
                    # with no report entry.
                    self.report.add_set_aside(
                        SetAsideReason.NO_LANGUAGE_TAG,
                        subject=uri,
                        predicate=skos_curie(predicate),
                    )
                    continue
                if not SkosGraph.is_usable_literal(literal):
                    # T059, decisions.md D69 (fix cycle 7): this loop reads the raw graph
                    # directly rather than through preferred_label_in, so it is the "fifth call
                    # site" the structural fix exists to keep from missing this rule — an empty
                    # or whitespace-only literal is never a usable name. Treated exactly as
                    # SkosGraph's own accessors treat one: silently excluded, not reported, a
                    # real value in this same predicate/language (if the file published one)
                    # still wins undisturbed. Also what keeps a non-default-language preferred
                    # label whose only candidate is unusable from reaching the
                    # preferred_winner_by_language lookup below with no entry to find — an
                    # unusable literal never becomes a candidate there either (D69), so it must
                    # never reach that lookup as a literal instead.
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
                        # FIX 4 (D38): the winner already lives as concept.label; a same-tag loser
                        # in this language must still be named, not merely skipped.
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
                        # T014: the same discriminator the default-language branch already applies
                        # (D24) — a same-tag loser is a same-language duplicate, a different-tag
                        # loser is a contest loser recoverable by configuring its published tag.
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
                    # SEC-002, decisions.md D34: variant matching now routes values that were
                    # previously unreachable into add_label's own full_clean() — a single
                    # over-long value must not abort the whole run (Article V: imported RDF is
                    # untrusted), the same discipline EMPTY_SLUG already applies to the slug.
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                if resolved_language.lower() != published_tag.lower():
                    # T009, FR-006: a value stored under a resolved language other than its
                    # published tag is a normalisation, never applied silently (decisions.md D8).
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=published_tag,
                        kept_as=resolved_language,
                    )

    def _import_notes(self, node: rdflib.term.Node, concept: Concept, uri: str) -> None:
        """Store ``concept``'s documentary notes — the definition and the six SKOS note kinds
        (T019, FR-009) — through :meth:`~controlled_vocabularies.models.Concept.add_note`.

        Replaces whatever notes this concept already held, the same full-replace rule and reason as
        :meth:`import_labels`. :data:`NOTE_PREDICATES` covers the native SKOS predicates only;
        ``dcterms:description`` is a separate, concept-level definition alias (T021, FR-009,
        D24/D21) — read only in a language with no ``skos:definition`` of its own, and reported as a
        normalisation rather than applied silently. A tag sharing no base language with any
        configured one is set aside the same way :meth:`import_labels` filters one (T020, FR-014,
        D25). Notes carry no per-language cardinality limit (decisions.md D4), so — unlike
        :meth:`import_labels` — there is no contest here and no per-tag winner to compute: every
        variant value resolves and is stored.
        """
        concept.concept_notes.all().delete()
        definition_languages: set[str] = set()
        for predicate, kind in NOTE_PREDICATES.items():
            for literal in self.skos_graph.graph.objects(node, predicate):
                if not isinstance(literal, rdflib.Literal) or not literal.language:
                    # FIX 15 (D48): same defect as import_labels's identical branch.
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
                    # SEC-002, decisions.md D34: same discipline as import_labels's own guard.
                    # Checked after the write attempt, not before: not counted into
                    # definition_languages below either, since it was never actually stored.
                    self.report.add_set_aside(
                        SetAsideReason.VALUE_TOO_LONG,
                        subject=uri,
                        language=published_tag,
                    )
                    continue
                if kind == ConceptNote.Kind.DEFINITION:
                    definition_languages.add(resolved_language)
                if resolved_language.lower() != published_tag.lower():
                    # T009, FR-006 (decisions.md D8).
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=published_tag,
                        kept_as=resolved_language,
                    )

        for literal in self.skos_graph.graph.objects(node, DCTERMS.description):
            if not isinstance(literal, rdflib.Literal) or not literal.language:
                # FIX 15 (D48): the dcterms:description alias carries the identical defect.
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
                # The concept already carries its own skos:definition in this language.
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
                # SEC-002, decisions.md D34: same discipline as import_labels's own guard.
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
                # T009, FR-006: a second, independent axis of normalisation from the predicate
                # substitution just reported — the language changed too (decisions.md D8).
                self.report.add_normalized(
                    NormalizedReason.LANGUAGE_SUBSTITUTION,
                    subject=uri,
                    language=published_tag,
                    kept_as=resolved_language,
                )

    def _import_unheld_values(self, node: rdflib.term.Node, uri: str) -> None:
        """Set aside and report the values on ``concept`` the models have no place for (T021, FR-014).

        Three kinds, each named under the reason that fits it, one entry per value: a
        ``skos:notation``; a cross-vocabulary mapping (:data:`MAPPING_PREDICATES`); and any
        predicate this concept carries that is neither handled elsewhere in this module nor itself
        a SKOS predicate (:func:`report_unmodelled_predicates`). A SKOS predicate this module
        simply does not read *yet* (``skos:broader``/``narrower``/``related``,
        ``skos:member``/``memberList``) is deliberately not reported here — the models do have a
        place for it, just not built yet.
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
        """Import everything about ``concept`` beyond its identity and default-language label.

        Called once per created-or-updated concept, after it has a primary key (label replacement
        needs one).
        """
        self.import_labels(
            node, concept, self.target_scheme.effective_default_language, uri
        )
        self._import_notes(node, concept, uri)
        self._import_unheld_values(node, uri)

    def import_concepts(
        self, concept_nodes: list[rdflib.term.Node]
    ) -> dict[str, Concept]:
        """Create or update each of ``concept_nodes`` inside the target vocabulary (T009, FR-006).

        For each node, in order: identity is checked (a blank node or refused URI is fatal, D3); a
        concept claiming a *different* vocabulary is set aside (spec Edge Cases §1); a concept with
        no preferred label in the target's effective default language is set aside (FR-006) rather
        than crashing the run. A matched or created :class:`Concept` gets a deterministic,
        scheme-unique slug (:meth:`assign_unique_slug`, FR-007). A URI already belonging to a
        different vocabulary is left there, set aside naming both (review fix 8, D42); a URI already
        held by a :class:`Collection` is set aside rather than made to identify two records at once
        (review fix 10, D43).

        Returns the concepts created or updated, keyed by URI — what :class:`RelationImporter` and
        :class:`CollectionImporter` resolve references against, and what
        :meth:`report_absent_concepts` compares against afterwards.

        ``taken_slugs`` (FIX 16, D49) is fetched once rather than once per concept: a scheme-wide
        slug collision check that used to cost one query per suffix attempt (quadratic across a
        shared-label group, D6) now costs nothing per concept beyond the one shared lookup.
        """
        concepts_by_uri: dict[str, Concept] = {}
        # slug -> the static_uri of the concept currently holding it, seeded from every concept
        # already in target_scheme and kept current as each concept below is assigned its own
        # final slug (FIX 16, D49).
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
                # SC-025, S6 CORR-001, decisions.md D34: this concept is about to be skipped
                # entirely, so import_labels never runs for it and none of its own languages
                # would otherwise enter language_account() — precisely the concept a curator
                # most needs visibility into. Accounted under its own published tag(s), never
                # under the configured default it lacks (D14's failure mode).
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

            # ARCH-306, fix cycle 4, decisions.md D55: cast, not an `is not None` check — see
            # the identical note on resolve_scheme's own name-length read.
            label_max_length = cast(int, Concept._meta.get_field("label").max_length)
            if len(label) > label_max_length:
                # SEC-002, decisions.md D34: Concept.save() never calls full_clean() (it derives
                # the slug and refuses a collision, nothing more), so an over-long label would
                # otherwise reach the database unchecked on SQLite and raise a bare DataError on
                # PostgreSQL. Checked ahead of the write, the same discipline EMPTY_SLUG already
                # applies just below — the reason names the value, not the slug it never reaches.
                self.report.add_set_aside(
                    SetAsideReason.VALUE_TOO_LONG, subject=uri, language=winning_tag
                )
                continue

            if not identifier_slug_base(uri):
                # T029, decisions.md D35: the slug now derives from the identifier's own
                # segment, not the label, so this is what can slugify to nothing — a
                # publisher-assigned fragment or path segment made up only of characters
                # slugify() strips. Checked ahead of the write (D25, FIX 5/D39) rather than
                # letting Concept.save()'s own refusal raise. The label itself is unaffected.
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue

            try:
                concept = Concept.objects.get_by_uri(uri)
                created = False
            except Concept.DoesNotExist:
                # FIX 10 (D43): before minting a new record for this URI, check the *other*
                # identity space — a Collection may already hold it.
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
                # FIX 8 (D42): a concept matched here already belongs to a *different* vocabulary.
                # Moving a record between vocabularies is a curatorial act, never a side effect of
                # reading a file.
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
                # T060, SEC-604, decisions.md D70 (fix cycle 7): unique_slug_for_identifier's
                # give-up (D66) is a genuine "this collision could not be resolved" outcome, not
                # yet checked here the way SchemeResolver.resolve_scheme's own call already is.
                # Left unguarded, this empty slug reached save() and was caught only by the
                # model's own manual-slug validation below, reported as STORED_SLUG_INVALID — a
                # reason whose message says a *stored* slug fails validation, which is false for
                # a slug that was never written. EMPTY_SLUG is the same reason the identifier's
                # own unusable base already gets just above; the two are the same outcome for a
                # curator (no address for this concept) even though the identifier itself was
                # perfectly usable here.
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue
            try:
                concept.save()
            except ValidationError:
                # T045, SEC-301, decisions.md D50 (fix cycle 4): the same escape as
                # SchemeResolver's own row.save() call, one record kind over — a matched
                # concept's slug is read back unchanged (T041), so a value written out of band
                # reaches Concept.save()'s manual-slug validation exactly as stored.
                self.report.add_set_aside(
                    SetAsideReason.STORED_SLUG_INVALID, subject=uri
                )
                continue
            if winning_tag.lower() != default_language.lower():
                # T009, FR-006: concept.label is stored content too — a value that made it in
                # under a different language than published is a normalisation, not a silent
                # substitution (decisions.md D8).
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
        """Report every existing concept of the target vocabulary that :meth:`import_concepts`
        never saw mentioned (T013, FR-013) — left completely untouched. A concept set aside for
        claiming a *different* vocabulary is not "absent from source": the file does mention it.

        Called by the orchestrator after relations and collections have been reconciled (FIX 7/20,
        D41/D53: filtered and sorted in Python by ``.uri`` rather than a database ``__in`` clause
        sized by the file's own concept count).
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
        """Give ``concept`` a deterministic, scheme-unique slug derived from its published
        identifier (T029, FR-017, decisions.md D35).

        Nothing is derived from ``concept.label`` — identity's slug and the label a curator reads
        are deliberately independent, so a publisher renaming a concept never moves its address.
        ``Concept.save()`` only *refuses* a collision rather than resolving one (research R4,
        written for curator-authored content where two identifiers colliding on their own final
        segment is rare); a published file is not so well-behaved (D35), so the importer resolves
        it itself via :func:`unique_slug_for_identifier` — the same computation
        :meth:`SchemeResolver.resolve_scheme` reuses for a vocabulary's own collision (Article XV).

        ``created`` (T041, FR-020, decisions.md D35 fix cycle 3) decides whether a slug is minted
        at all: a slug is computed through :func:`unique_slug_for_identifier` only for a concept
        this run is creating. A concept :meth:`import_concepts` *matched* to an existing row
        already holds a slug — it is read back exactly as stored, never recomputed, so no change
        in what else currently occupies the scheme (a sibling deleted, a slot vacated) can move an
        address that has nothing to do with this concept's own identifier. Recomputing
        unconditionally used to be *safe* (the base is a pure function of ``concept.static_uri``,
        invariant once assigned) but not *stable*: ``taken_slugs`` is reseeded fresh from the
        database on every run, so a collision this concept was once suffixed against can vanish
        between two imports of the identical file, silently moving its address (FR-020's "same
        file yields the same slugs however it is traversed" — reread here as "however many times
        it is imported").

        ``taken_slugs`` (FIX 16, D49) maps every claimed slug to its claimant's ``static_uri`` —
        fetched once by :meth:`import_concepts` from every concept currently in the scheme
        (matched rows included), mutated in place by :func:`unique_slug_for_identifier` so the
        next *newly created* concept in the run sees a just-minted sibling's slug as taken. Because
        ``concept_nodes`` is always processed in URI-sorted order (never the order a file happens
        to declare them in), a collision between two identifiers created in the same run resolves
        identically whichever order the file is read in.

        ``slug_is_manual`` is always set ``True``, matched or created alike: it stops
        ``Concept.save()`` from re-deriving this value on a later, unrelated save — including for a
        concept the importer is touching for the first time after it was authored locally (no prior
        ``static_uri``), which otherwise keeps deriving its slug from its label (FR-019) forever.
        The caller (:meth:`import_concepts`) already sets aside a concept whose identifier segment
        slugifies to nothing (``EMPTY_SLUG``) before this method ever runs, so the base is never
        empty for a concept actually being created here.
        """
        if created:
            max_length = cast(int, Concept._meta.get_field("slug").max_length)
            concept.slug = unique_slug_for_identifier(
                concept.static_uri, taken_slugs, max_length
            )
        concept.slug_is_manual = True


class ConceptReferenceResolverMixin:
    """Shared by :class:`RelationImporter` and :class:`CollectionImporter`, both of which resolve a
    URI back to the :class:`Concept` it identifies (D30 treats a membership as the same shape of
    problem a relationship already is) — a small shared base rather than duplicating the method,
    since neither importer is a more natural home for it than the other.

    A subclass must set ``self.target_scheme`` before calling :meth:`_resolve_concept_reference`.
    """

    target_scheme: ConceptScheme

    def _resolve_concept_reference(
        self, uri: str, successful_concepts: dict[str, Concept]
    ) -> Concept | None:
        """Return the :class:`Concept` ``uri`` names, or ``None`` when it cannot back a relation or
        a collection membership (FR-011).

        Tries this run's own writes first (``successful_concepts``, keyed by URI); otherwise falls
        back to :meth:`~controlled_vocabularies.models.ConceptManager.get_by_uri` for a concept an
        earlier import already created (spec Acceptance Scenario US4-6). A match belonging to a
        *different* vocabulary than the one being imported is treated as no match at all
        (research.md R4, D29) — the same "collect, don't crash" discipline every other set-aside
        reason follows.
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
    """Reconciles ``skos:broader``/``skos:narrower``/``skos:related`` into stored
    :class:`~controlled_vocabularies.models.ConceptRelation` rows (FR-010/FR-011).
    """

    def __init__(
        self, skos_graph: SkosGraph, report: ImportReport, target_scheme: ConceptScheme
    ) -> None:
        self.skos_graph = skos_graph
        self.report = report
        self.target_scheme = target_scheme

    def import_relations(self, successful_concepts: dict[str, Concept]) -> None:
        """Reconcile ``skos:broader``/``skos:narrower``/``skos:related`` into the single canonical
        BROADER/RELATED row research.md R4 defines for each pair, for every concept this run
        created or updated (T023/T024, FR-010/FR-011/FR-013).

        Read only from ``successful_concepts`` — a concept set aside for another reason has no row
        to attach a relation to. ``skos:narrower`` resolves to the same stored BROADER row as
        ``skos:broader`` with its ends swapped
        (:meth:`~controlled_vocabularies.models.Concept.add_broader`'s contract: ``source`` is the
        narrower end); ``skos:related`` is symmetric, keyed by an unordered pair — either direction
        for the same pair collapses to the same dict key, so which one the file states first never
        matters.

        An existing row is only ever a *deletion* candidate when **both** its ends were created or
        updated this run (D30): only then has the file had the opportunity to speak about it at
        all. This is computed as one whole pass over every concept touched, not incrementally per
        concept, because a relation is commonly asserted from only one of its two ends — an
        incremental delete-and-recreate would delete a row a sibling's own pass had only just
        written.

        A broader/narrower pair always wins over the same pair resolved as related (review fix 2,
        D37): SKOS declares the two disjoint, and the model refuses to store both
        (:meth:`~controlled_vocabularies.models.ConceptRelation._reject_disjointness_violation`).
        Broader/narrower rows are written first, each clearing any conflicting stored RELATED row
        for the same pair — not only one the bulk deletion pass above would catch, since that pass
        only considers a row when *both* ends were rewritten this run (D30), and the far end of a
        newly-stated broader edge may instead be a concept only referenced this run (D29's
        ``get_by_uri`` fallback). Related rows are written after, checked the same way against a
        conflicting BROADER row, and set aside rather than attempted when one is found.
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
                # FIX 6 (D40): a concept stating skos:broader/skos:narrower about itself is not a
                # real hierarchy edge (the model's own _reject_self would refuse it); nothing
                # meaningful to reconcile.
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
                # A concept stating skos:related about itself — the model's own _reject_self would
                # refuse it; nothing meaningful to reconcile.
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

        # Both ends in successful_ids, not either (D30): a row with one end outside this run's own
        # writes is only half spoken about by the file.
        #
        # FIX 20 (D53): scoped by source__scheme=target_scheme — one bind parameter — rather than
        # source_id__in=successful_ids, target_id__in=successful_ids (2N parameters together).
        # Django does not chunk an `__in` clause for PostgreSQL, whose 65,535-bind-parameter limit
        # this reaches around 33k concepts, inside the "tens of thousands" the spec targets. Every
        # ConceptRelation row already has both ends in the same scheme
        # (ConceptRelation._reject_cross_scheme), so scoping by source's scheme alone already scopes
        # target's too; "both ends in successful_ids" is then checked in Python against the
        # in-memory set, reproducing the original SQL-level condition exactly.
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
            # FIX 2, route 2 (D37): an existing RELATED row for this exact pair may not have been a
            # candidate for the bulk deletion pass above — that pass only considers a row when
            # *both* its ends were rewritten by this run (D30), and the far end of a newly-stated
            # broader edge may instead be a concept only referenced this run (D29). Checked directly
            # and unconditionally, so a stale RELATED row from an earlier run can never survive to
            # make add_broader raise the model's own disjointness ValidationError.
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
            # FIX 2, the symmetric route (D37): the mirror image of the broader-side check just
            # above — a BROADER row surviving from an earlier run for the same D30 reason must be
            # checked before add_related too, or the model's own guard raises here instead.
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
    """Creates or updates every ``skos:Collection``/``skos:OrderedCollection`` in the target
    vocabulary, with its membership (T027/T028, FR-012).
    """

    #: Predicates a collection node carries that :meth:`import_collections` already reads and
    #: accounts for (FIX 12, D45): its own identity, name, and membership (both ``skos:member`` and
    #: ``skos:memberList``, per FIX 11).
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
        """Create or update every ``skos:Collection``/``skos:OrderedCollection`` in the graph inside
        the target vocabulary, with its membership (T027/T028, FR-012).

        Run after every concept this run created or updated already has a primary key — membership
        needs :meth:`_resolve_concept_reference` exactly as a relationship end does. A collection's
        identity is checked with the same :meth:`SkosGraph.identify` a concept or the vocabulary
        itself uses (D3): a blank-node collection is fatal, collected, and the run continues (FR-003).
        The structural exception is ``skos:memberList`` itself — an RDF list, made of blank nodes by
        construction (research.md R2) — read through ``graph.items()``, which yields the member
        *URIs*, never the list's own cells, so those blank nodes never reach ``identify``. A URI
        matching an existing collection already in a different vocabulary is left untouched, set
        aside naming both (review fix 9, D42); a URI matching no collection but already held by a
        :class:`Concept` is set aside rather than made to identify two records at once (fix 10, D43).

        ``skos:member`` (unordered) or ``skos:memberList`` (ordered, in file order) name the desired
        membership. An ordered collection with no ``memberList`` falls back to ``member``, sorted;
        when both are present, ``memberList`` governs order and any ``member`` it omits is appended
        after, sorted (review fix 11, D44 — ``memberList`` narrows ``member`` rather than replacing
        it). Each member URI is resolved through :meth:`_resolve_concept_reference`; one that
        resolves to nothing is set aside (:data:`SetAsideReason.MISSING_MEMBER`) rather than failing
        the run (FR-011), and the collection is still created holding whatever did resolve.

        Membership is written only through the model's own API (``Collection.add``/``remove``/
        ``set_member_order``), never a :class:`~controlled_vocabularies.models.CollectionMember` row
        constructed directly, so the model's cross-scheme check always runs. An existing membership
        is only ever a *removal* candidate when its member belongs to ``successful_concepts`` (D30,
        the same rule relationship reconciliation follows, applied to a second model).

        Finally (T034, FR-013), every existing collection of the target vocabulary never seen among
        ``collection_nodes`` is left completely untouched and named in ``report.absent_from_source``.
        """
        graph = self.skos_graph.graph
        collection_nodes = sorted(
            set(graph.subjects(rdflib.RDF.type, SKOS.Collection))
            | set(graph.subjects(rdflib.RDF.type, SKOS.OrderedCollection)),
            key=str,
        )
        successful_ids = {concept.pk for concept in successful_concepts.values()}
        mentioned_uris: set[str] = set()
        # slug -> the static_uri of the collection currently holding it, seeded from every
        # collection already in target_scheme (T038, FR-017/FR-020, decisions.md D35) — the
        # same shape ConceptImporter.import_concepts already seeds for concepts.
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
                # FIX 10 (D43): the mirror image of the same check in
                # ConceptImporter.import_concepts — this URI may already be held by a Concept
                # instead. The two identity spaces are checked independently of each other.
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
                # FIX 9 (D42): the same rule FIX 8 gives a concept, applied to a collection.
                # Reassigning it (and its membership) to target_scheme is exactly the state
                # CollectionMember._reject_cross_scheme exists to prevent.
                self.report.add_set_aside(
                    SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY,
                    subject=uri,
                    current=row.scheme.uri,
                    target=self.target_scheme.uri,
                )
                continue

            if not identifier_slug_base(uri):
                # T039, decisions.md D35 (fix cycle 3): the same guard import_concepts
                # already applies for EMPTY_SLUG — a publisher-assigned fragment or path
                # segment made up only of characters slugify() strips. Checked ahead of the
                # write rather than letting Collection.save()'s own refusal raise. Unlike a
                # vocabulary, a collection is not something the rest of the file needs in
                # order to import, so this is set aside rather than fatal.
                self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                continue

            row.scheme = self.target_scheme
            row.static_uri = uri
            default_language = self.target_scheme.effective_default_language
            # ARCH-306, fix cycle 4, decisions.md D55: cast, not an `is not None` check — see
            # the identical note on resolve_scheme's own name-length read. Read ahead of the name
            # resolution below (T051, decisions.md D56), the same reordering resolve_scheme's own
            # copy needed.
            name_max_length = cast(int, Collection._meta.get_field("name").max_length)
            name_match = _localized_literal(
                self.skos_graph, self.matcher, node, SKOS.prefLabel, default_language
            )
            if name_match is None:
                # T047, CORR-305, decisions.md D52 (fix cycle 4): report the language this
                # any-language fallback actually found the value in, not the default it fell
                # back from — resolve_scheme's own name fallback has the identical fix.
                # T051, SEC-401, decisions.md D56: prefer a literal this record can actually
                # store — the identical fix resolve_scheme's own fallback needed.
                any_literal = self.skos_graph.first_literal_with_language(
                    node, SKOS.prefLabel, max_length=name_max_length
                ) or self.skos_graph.first_literal_with_language(node, SKOS.prefLabel)
                name, winning_tag = (
                    any_literal if any_literal is not None else (None, default_language)
                )
            else:
                name, winning_tag = name_match
                if winning_tag.lower() != default_language.lower():
                    # CORR-002, decisions.md D34: the same guard resolve_scheme's own name/
                    # description writes already apply.
                    self.report.add_normalized(
                        NormalizedReason.LANGUAGE_SUBSTITUTION,
                        subject=uri,
                        language=winning_tag,
                        kept_as=default_language,
                    )
            if name and len(name) > name_max_length:
                # T042, SEC-002-shaped, decisions.md D35 (fix cycle 3): the same pre-write guard
                # resolve_scheme's own name write applies — row.save() never calls full_clean(),
                # so an over-long name would otherwise reach the database unchecked on SQLite and
                # raise a bare DataError on PostgreSQL.
                if created:
                    # T044, decisions.md D49 (fix cycle 4, ARCH-301/CORR-303/SEC-302): unlike a
                    # vocabulary, a collection is not something the rest of the file needs in
                    # order to import — but a *created* collection still has no earlier name to
                    # fall back to, so the whole collection is set aside rather than persisted
                    # with a blank name a row full_clean() would then refuse. A *matched*
                    # collection already has a name and keeps it exactly as held.
                    #
                    # CORR-402, decisions.md D56 (fix cycle 5): the same second-chance fallback
                    # resolve_scheme's own copy needed — the value above came straight from the
                    # default-language match, and a different configured language may still
                    # publish a storable name in the same file.
                    fallback = self.skos_graph.first_literal_with_language(
                        node, SKOS.prefLabel, max_length=name_max_length
                    )
                    if fallback is None:
                        self.report.add_set_aside(
                            SetAsideReason.VALUE_TOO_LONG,
                            subject=uri,
                            language=winning_tag,
                        )
                        # CORR-404, decisions.md D60 (fix cycle 5): VALUE_TOO_LONG alone leaves
                        # this indistinguishable, from the report, from a *matched* collection's
                        # identical set-aside two lines below — one keeps its old name, the other
                        # is dropped whole. This second entry names the record-level outcome.
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
                # SEC-404, decisions.md D56 (fix cycle 5): the guard above only fires for an
                # over-long name; a collection with no skos:prefLabel published at all reaches
                # here with name still None, which would otherwise leave row.name at the field
                # default '' — the exact state D49 already declares impossible for a created
                # record, reached by a different route. CORR-404, decisions.md D60: reports
                # COLLECTION_NOT_CREATED rather than reusing VALUE_TOO_LONG — there is no
                # over-long value to name here, only the record-level outcome.
                self.report.add_set_aside(
                    SetAsideReason.COLLECTION_NOT_CREATED, subject=uri
                )
                continue
            row.ordered = ordered
            # T038, FR-017, decisions.md D35: a collection's own slug is identifier-derived,
            # exactly like a concept's (assign_unique_slug) and a scheme's (resolve_scheme) —
            # nothing is derived from row.name, so a publisher rename never moves it.
            # T041, FR-020, decisions.md D35 (fix cycle 3): minted only when this collection is
            # being created; a matched row already holds a slug and keeps it exactly as stored,
            # the same read-back-don't-recompute rule assign_unique_slug and resolve_scheme
            # apply, so no change in what else currently occupies the scheme can move it.
            if created:
                max_length = cast(int, Collection._meta.get_field("slug").max_length)
                row.slug = unique_slug_for_identifier(uri, taken_slugs, max_length)
                if not row.slug:
                    # T060, SEC-604, decisions.md D70 (fix cycle 7): the same guard
                    # ConceptImporter.import_concepts now applies — a give-up here reached
                    # row.save() unchecked and was caught only by the model's own manual-slug
                    # validation, reported as STORED_SLUG_INVALID even though nothing was ever
                    # stored. EMPTY_SLUG is the identifier-unusable reason this collection's own
                    # pre-write guard above already gives; the give-up is the same outcome for a
                    # curator even though the identifier itself was perfectly usable here.
                    self.report.add_set_aside(SetAsideReason.EMPTY_SLUG, subject=uri)
                    continue
            row.slug_is_manual = True
            try:
                row.save()
            except ValidationError:
                # T045, SEC-301, decisions.md D50 (fix cycle 4): the same escape as
                # ConceptImporter.import_concepts and SchemeResolver.resolve_scheme, the third
                # record kind — a matched collection's slug is read back unchanged (T041), so a
                # value written out of band reaches Collection.save()'s manual-slug validation
                # exactly as stored.
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
                        # FIX 18 (D51): a malformed skos:memberList whose rdf:rest chain loops back
                        # on itself instead of terminating in rdf:nil makes graph.items() raise a
                        # bare ValueError. Not collected as a per-record set-aside: an infinite list
                        # has no well-defined membership to import "the rest of", so the whole run
                        # is refused rather than silently importing a partial one.
                        raise SkosImportError(
                            _(
                                "'%(subject)s' has a skos:memberList that does not terminate (its rdf:rest "
                                "chain loops back on itself); the import was refused."
                            ),
                            params={"subject": uri},
                            code="skos_cyclic_member_list",
                        ) from exc
                    # FIX 11 (D44): skos:memberList narrows skos:member rather than replacing it —
                    # a skos:member the memberList omits is still an explicit membership assertion
                    # and must not disappear (Article XI). Appended after memberList's own order, in
                    # the same deterministic sorted order the unordered branch below already uses.
                    member_only = sorted(
                        {str(obj) for obj in graph.objects(node, SKOS.member)}
                        - set(ordered_uris)
                    )
                    member_uris = ordered_uris + member_only
                else:
                    # FIX 11 (D44): an ordered collection asserted only with skos:member — no
                    # memberList at all — still has real, explicit membership to import; read the
                    # same deterministic sorted way the unordered branch already reads skos:member.
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

        # FIX 7 (D41): a row whose static_uri is NULL — a locally authored collection the file
        # could never mention, since it carries no external identifier — is reported by its own
        # .uri, never the raw column, which for such a row would be None; sorted in Python since
        # .uri is not a database column .order_by() can reach.
        #
        # FIX 20 (D53): filtered in Python against the in-memory mentioned_uris set rather than
        # .exclude(static_uri__in=mentioned_uris) — the same __in-sized-by-file concern
        # RelationImporter's own fix addresses, here for a string __in rather than an integer one.
        absent = [
            collection
            for collection in Collection.objects.filter(scheme=self.target_scheme)
            if collection.static_uri not in mentioned_uris
        ]
        for collection in sorted(absent, key=lambda row: row.uri):
            self.report.add_absent_from_source(collection.uri)


class SkosImporter:
    """Orchestrates one run of :func:`import_skos`: holds the graph, report, target vocabulary, and
    the transaction, and drives :class:`SchemeResolver`, :class:`ConceptImporter`,
    :class:`RelationImporter` and :class:`CollectionImporter` in sequence (FR-001, FR-003).
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
        """Import :attr:`file` and return the run's :class:`ImportReport` (FR-001).

        Re-running an import upserts rather than deleting and recreating: a record the file still
        contains has its content matched to the file exactly, including removing a value the file
        no longer carries, while a record the file simply does not mention is left completely
        untouched and named in ``report.absent_from_source`` (FR-013). Anything the file carries
        that the models have no place for is set aside and named in the report rather than dropped
        in silence (FR-014, Article XI).

        The whole run sits inside one transaction (research.md R7): a fatal finding is collected
        rather than raised immediately, so a file with more than one problem reports all of them;
        only once nothing further can be checked does :class:`SkosImportFailed` actually raise,
        which is what triggers the rollback. A successful run's ``report.fatal`` is always empty.
        """
        skos_graph = SkosGraph.from_file(
            self.file, serialization=self.serialization, base_uri=self.base_uri
        )
        source_label = str(self.base_uri or self.file)

        with transaction.atomic():
            declared_nodes = sorted(
                skos_graph.graph.subjects(rdflib.RDF.type, SKOS.ConceptScheme), key=str
            )
            # FIX 17 (D50): a node the file identifies as a concept only through
            # skos:inScheme/topConceptOf/hasTopConcept — never through rdf:type skos:Concept — is
            # folded in here, before scheme disambiguation runs, so it is neither invisible to the
            # import nor to choose_declared_scheme's own membership count.
            concept_nodes = sorted(
                set(skos_graph.graph.subjects(rdflib.RDF.type, SKOS.Concept))
                | skos_graph.implied_concept_nodes(),
                key=str,
            )
            # The matcher is built once per run, before any concept is written, from
            # the whole file's predominance counts (research.md R2) — settling a
            # variant contest needs the whole file counted first. Passed as a
            # constructor argument rather than let each collaborator build its own
            # (plan.md "One winner, one computation").
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
                # SEC-001, decisions.md D34: effective_default_language falls back to
                # settings.LANGUAGE_CODE unvalidated against settings.LANGUAGES — Django's own
                # shipped defaults are exactly this shape. resolve() can only ever return a code
                # taken verbatim from LANGUAGES, so if this value is not itself an exact member
                # (is_exact), no candidate could ever match it and every concept would be set
                # aside one at a time for no gain to a curator. Caught once, here, naming the
                # misconfiguration instead.
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
    """Import a published SKOS file and return a structured report (FR-001).

    A thin wrapper over :class:`SkosImporter` — see :meth:`SkosImporter.run` for the transaction,
    upsert, and set-aside semantics. ``scheme`` names a target vocabulary for a file that declares
    none of its own, or is checked against one the file does declare — a mismatch fails the run
    and writes nothing (FR-005). ``base_uri``, when given, is the address a fetched document was
    published at (FR-003, decisions.md D10); omitted, this is exactly today's behaviour.
    """
    return SkosImporter(
        file, serialization=serialization, scheme=scheme, base_uri=base_uri
    ).run()
