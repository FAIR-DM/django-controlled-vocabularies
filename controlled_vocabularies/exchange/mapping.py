"""SKOS predicate -> model mapping (research.md R4).

Fixed by what R1's models already define — no new modelling, just naming the
correspondence ``skos.py`` walks against. This grows one predicate at a time as
each story in ``tasks.md`` needs it, rather than being populated up front with
entries nothing yet reads (Article II — no speculative table). User Story 1
needs only the namespace itself, plus the identity and scheme-membership
predicates it reads directly (``skos:prefLabel``, ``skos:inScheme``,
``skos:topConceptOf``, ``skos:hasTopConcept``), all reachable as plain
attributes of :data:`SKOS` without a lookup table. Labels, notes, relations,
and collections are named here once their owning story (US-3/4/5) adds the
code that reads them.

User Story 2 adds :data:`DCTERMS` for exactly one predicate,
``dcterms:description`` — SKOS defines no description predicate for a
``skos:ConceptScheme``, so a vocabulary's description is read from the same
Dublin Core term CONTEXT.md already names as the import alias for a concept's
own ``definition`` (decisions.md D21). ``rdflib.namespace.DCTERMS`` is a
built-in namespace object, so nothing new is declared here beyond importing it.

User Story 3 (tasks.md T018/T019/T021) adds the label, note, and mapping
predicate tables below, exactly the growth this module's docstring already
anticipated.

015-read-single-record T001 adds the opposite direction: given a *stored*
kind, the CURIE to key a page's row on. :func:`skos_curie` moves here from
``exchange/skos.py`` — it is a namespace concern, not a graph one, and this
module is exactly where the namespace it depends on already lives.
:data:`LABEL_CURIES` and :data:`NOTE_CURIES` are derived by inverting
:data:`LABEL_PREDICATES` and :data:`NOTE_PREDICATES` and applying
:func:`skos_curie`, never hand-written, so a predicate added to either
forward table appears in its inverse with no second edit. The relation,
scheme-membership, collection-membership and type terms invert nothing that
exists, so they are written out directly instead.
"""

from __future__ import annotations

import rdflib
from rdflib.namespace import DCTERMS

from controlled_vocabularies.models import ConceptLabel, ConceptNote

#: The SKOS namespace every predicate and class this package reads belongs to.
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")


def skos_curie(predicate: rdflib.URIRef) -> str:
    """The ``skos:xxx`` CURIE for a predicate in the SKOS namespace.

    Used for report display (FIX 15, decisions.md D48) and, from T001 on, to key a
    record's page rows on (plan.md Key design decision #3). Refuses a predicate outside
    the SKOS namespace rather than mangling one — slicing the namespace off by length
    with no check would turn ``skos_curie(rdflib.RDF.type)`` into the nonsensical
    ``"skos:tax-ns#type"``. Its original scope (report display only) is why that never
    mattered before; keying a page's rows on it makes it matter.
    """
    predicate_str = str(predicate)
    namespace = str(SKOS)
    if not predicate_str.startswith(namespace):
        raise ValueError(f"'{predicate_str}' is not a predicate in the SKOS namespace.")
    return f"skos:{predicate_str[len(namespace) :]}"


#: Prefix -> namespace for every CURIE a record's page renders as a term
#: (015-read-single-record T031). :func:`skos_curie` goes one way, from a URI to its
#: short form; a page needs the other way too, because a reader hovering ``skos:member``
#: is asking what it abbreviates.
CURIE_NAMESPACES: dict[str, str] = {
    "skos": str(SKOS),
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}


def curie_uri(curie: str) -> str:
    """The full URI a ``prefix:local`` CURIE abbreviates.

    Refuses a prefix this package does not declare rather than concatenating whatever
    it was given — the same reason :func:`skos_curie` refuses a predicate outside SKOS,
    and the reason a term added to a namespace nobody declared fails at render rather
    than putting a fabricated identifier in front of a reader.
    """
    prefix, separator, local = curie.partition(":")
    if not separator or not local or prefix not in CURIE_NAMESPACES:
        raise ValueError(
            f"'{curie}' is not a CURIE in a namespace this package declares."
        )
    return f"{CURIE_NAMESPACES[prefix]}{local}"


#: SKOS label predicate -> :class:`~controlled_vocabularies.models.ConceptLabel.Kind`
#: (T018, FR-008). ``skos:prefLabel`` in the vocabulary's effective default
#: language is not looked up through this table at all — that value is
#: ``Concept.label`` itself (T009), and a ``ConceptLabel`` row would duplicate
#: the identity anchor, which ``ConceptLabel.clean()`` refuses.
LABEL_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.prefLabel: ConceptLabel.Kind.PREFERRED,
    SKOS.altLabel: ConceptLabel.Kind.ALTERNATIVE,
    SKOS.hiddenLabel: ConceptLabel.Kind.HIDDEN,
}

#: SKOS documentary-note predicate -> :class:`~controlled_vocabularies.models.ConceptNote.Kind`
#: (T019, FR-009). ``dcterms:description`` is a *separate*, concept-level
#: alias for :attr:`ConceptNote.Kind.DEFINITION` (CONTEXT.md, decisions.md
#: D21/D24), read only where the file carries no ``skos:definition`` of its
#: own in that language, and reported as a normalisation rather than applied
#: silently (FR-009) — so it is handled in ``skos.py`` directly rather than
#: listed here alongside the predicates that need no such reporting.
NOTE_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.definition: ConceptNote.Kind.DEFINITION,
    SKOS.scopeNote: ConceptNote.Kind.SCOPE,
    SKOS.example: ConceptNote.Kind.EXAMPLE,
    SKOS.editorialNote: ConceptNote.Kind.EDITORIAL,
    SKOS.historyNote: ConceptNote.Kind.HISTORY,
    SKOS.changeNote: ConceptNote.Kind.CHANGE,
    SKOS.note: ConceptNote.Kind.NOTE,
}

#: SKOS mapping predicates (T021, FR-014) — cross-vocabulary links to concepts
#: in *other* vocabularies. CONTEXT.md is explicit that these "live in the
#: JSON document, not the relation M2M", and the JSON document is exactly the
#: escrow store decisions.md D1 defers past this feature, so a mapping has no
#: model to write to yet: it is set aside and reported (FR-014) under its own
#: readable CURIE rather than a raw URI.
MAPPING_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.exactMatch: "skos:exactMatch",
    SKOS.closeMatch: "skos:closeMatch",
    SKOS.broadMatch: "skos:broadMatch",
    SKOS.narrowMatch: "skos:narrowMatch",
    SKOS.relatedMatch: "skos:relatedMatch",
    SKOS.mappingRelation: "skos:mappingRelation",
}

#: Stored :class:`~controlled_vocabularies.models.ConceptLabel.Kind` -> ``skos:xxx`` CURIE
#: (015-read-single-record T001, FR-003). The inverse of :data:`LABEL_PREDICATES`, derived
#: rather than hand-written, so a predicate added there appears here with no second edit.
LABEL_CURIES: dict[str, str] = {
    kind: skos_curie(predicate) for predicate, kind in LABEL_PREDICATES.items()
}

#: Stored :class:`~controlled_vocabularies.models.ConceptNote.Kind` -> ``skos:xxx`` CURIE
#: (015-read-single-record T001, FR-003). The inverse of :data:`NOTE_PREDICATES`, same
#: no-second-edit guarantee as :data:`LABEL_CURIES`.
NOTE_CURIES: dict[str, str] = {
    kind: skos_curie(predicate) for predicate, kind in NOTE_PREDICATES.items()
}

#: The relation, scheme-membership, collection-membership and type CURIEs a record's page
#: keys its remaining rows on (015-read-single-record T001, FR-010 to FR-013). None of
#: these invert a forward table this module already has — ``broader``/``narrower``/
#: ``related`` have no ``predicate -> stored kind`` table the way labels and notes do,
#: ``inScheme`` and the membership terms are never imported at all, and ``rdf:type`` is
#: not in the SKOS namespace in the first place, so :func:`skos_curie` would refuse it —
#: so each is written out directly rather than derived.
BROADER_CURIE = "skos:broader"
NARROWER_CURIE = "skos:narrower"
RELATED_CURIE = "skos:related"
IN_SCHEME_CURIE = "skos:inScheme"
MEMBER_CURIE = "skos:member"
MEMBER_LIST_CURIE = "skos:memberList"
TYPE_CURIE = "rdf:type"
CONCEPT_TYPE_CURIE = "skos:Concept"
COLLECTION_TYPE_CURIE = "skos:Collection"
ORDERED_COLLECTION_TYPE_CURIE = "skos:OrderedCollection"

#: Dublin Core Terms — currently used only for ``DCTERMS.description`` (D21).
__all__ = [
    "BROADER_CURIE",
    "COLLECTION_TYPE_CURIE",
    "CONCEPT_TYPE_CURIE",
    "CURIE_NAMESPACES",
    "DCTERMS",
    "IN_SCHEME_CURIE",
    "LABEL_CURIES",
    "LABEL_PREDICATES",
    "MAPPING_PREDICATES",
    "MEMBER_CURIE",
    "MEMBER_LIST_CURIE",
    "NARROWER_CURIE",
    "NOTE_CURIES",
    "NOTE_PREDICATES",
    "ORDERED_COLLECTION_TYPE_CURIE",
    "RELATED_CURIE",
    "SKOS",
    "TYPE_CURIE",
    "curie_uri",
    "skos_curie",
]
