"""SKOS predicates, CURIEs and their mapping to the concept models."""

from __future__ import annotations

import rdflib
from rdflib.namespace import DCTERMS

from controlled_vocabularies.models import ConceptLabel, ConceptNote

SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")


def skos_curie(predicate: rdflib.URIRef) -> str:
    """Return the ``skos:xxx`` CURIE for a predicate in the SKOS namespace.

    Refuses a predicate outside the namespace rather than slicing it by length, which
    would turn ``rdf:type`` into ``"skos:tax-ns#type"``.

    Args:
        predicate: A predicate URI in the SKOS namespace.

    Returns:
        The predicate's CURIE, such as ``skos:broader``.

    Raises:
        ValueError: The predicate is not in the SKOS namespace.
    """
    predicate_str = str(predicate)
    namespace = str(SKOS)
    if not predicate_str.startswith(namespace):
        raise ValueError(f"'{predicate_str}' is not a predicate in the SKOS namespace.")
    return f"skos:{predicate_str[len(namespace) :]}"


CURIE_NAMESPACES: dict[str, str] = {
    "skos": str(SKOS),
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}


def curie_uri(curie: str) -> str:
    """Return the full URI a ``prefix:local`` CURIE abbreviates.

    Refuses a prefix this package does not declare rather than concatenating whatever it
    was given, so a term in an undeclared namespace fails at render time.

    Args:
        curie: A ``prefix:local`` CURIE in one of :data:`CURIE_NAMESPACES`.

    Returns:
        The namespace URI followed by the local part.

    Raises:
        ValueError: The CURIE has no local part or its prefix is not declared.
    """
    prefix, separator, local = curie.partition(":")
    if not separator or not local or prefix not in CURIE_NAMESPACES:
        raise ValueError(
            f"'{curie}' is not a CURIE in a namespace this package declares."
        )
    return f"{CURIE_NAMESPACES[prefix]}{local}"


# The default-language preferred label is Concept.label itself, and ConceptLabel.clean()
# refuses a row that duplicates it, so it is never looked up through this table.
LABEL_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.prefLabel: ConceptLabel.Kind.PREFERRED,
    SKOS.altLabel: ConceptLabel.Kind.ALTERNATIVE,
    SKOS.hiddenLabel: ConceptLabel.Kind.HIDDEN,
}

# dcterms:description is handled in skos.py instead, because it is stored as a definition
# only when the file has no skos:definition and is reported as a normalisation.
NOTE_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.definition: ConceptNote.Kind.DEFINITION,
    SKOS.scopeNote: ConceptNote.Kind.SCOPE,
    SKOS.example: ConceptNote.Kind.EXAMPLE,
    SKOS.editorialNote: ConceptNote.Kind.EDITORIAL,
    SKOS.historyNote: ConceptNote.Kind.HISTORY,
    SKOS.changeNote: ConceptNote.Kind.CHANGE,
    SKOS.note: ConceptNote.Kind.NOTE,
}

# Mappings to other vocabularies live in the JSON document, which does not exist yet, so
# they are set aside and reported under these CURIEs.
MAPPING_PREDICATES: dict[rdflib.URIRef, str] = {
    SKOS.exactMatch: "skos:exactMatch",
    SKOS.closeMatch: "skos:closeMatch",
    SKOS.broadMatch: "skos:broadMatch",
    SKOS.narrowMatch: "skos:narrowMatch",
    SKOS.relatedMatch: "skos:relatedMatch",
    SKOS.mappingRelation: "skos:mappingRelation",
}

# Derived by inverting the forward table, so a predicate added there needs no second edit.
LABEL_CURIES: dict[str, str] = {
    kind: skos_curie(predicate) for predicate, kind in LABEL_PREDICATES.items()
}

NOTE_CURIES: dict[str, str] = {
    kind: skos_curie(predicate) for predicate, kind in NOTE_PREDICATES.items()
}

# Written out rather than derived: none of these inverts a forward table, and rdf:type is
# outside the SKOS namespace, so skos_curie would refuse it.
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
