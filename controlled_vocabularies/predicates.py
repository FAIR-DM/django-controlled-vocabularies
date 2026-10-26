"""The predicates the pages know about and the CURIE prefixes a stored document uses."""

import re

from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

#: The prefixes a stored key may use. A key outside these namespaces is stored as a full URI.
#: Fixed rather than configurable, because the keys of every stored document are written with it.
PREFIXES: dict[str, str] = {
    "skos": str(SKOS),
    "dcterms": str(DCTERMS),
    "owl": str(OWL),
    "rdf": str(RDF),
    "rdfs": str(RDFS),
    "xsd": str(XSD),
}

#: Known predicates in the order the pages show them. Any other predicate is shown after these.
PREDICATE_ORDER: tuple[str, ...] = (
    "skos:prefLabel",
    "skos:altLabel",
    "skos:hiddenLabel",
    "skos:notation",
    "skos:definition",
    "skos:scopeNote",
    "skos:example",
    "skos:editorialNote",
    "skos:historyNote",
    "skos:changeNote",
    "skos:note",
    "skos:broader",
    "skos:narrower",
    "skos:related",
    "skos:exactMatch",
    "skos:closeMatch",
    "skos:broadMatch",
    "skos:narrowMatch",
    "skos:relatedMatch",
    "skos:member",
    "skos:memberList",
    "skos:inScheme",
    "skos:topConceptOf",
    "dcterms:title",
    "dcterms:description",
    "dcterms:publisher",
    "dcterms:creator",
    "dcterms:license",
    "dcterms:modified",
    "owl:versionInfo",
)

#: Predicates a page shows in one language: the reader's, else the vocabulary's default.
TRANSLATED_PREDICATES = frozenset(
    {
        "skos:prefLabel",
        "skos:altLabel",
        "skos:hiddenLabel",
        "skos:definition",
        "skos:scopeNote",
        "skos:example",
        "skos:editorialNote",
        "skos:historyNote",
        "skos:changeNote",
        "skos:note",
        "dcterms:title",
        "dcterms:description",
    }
)


class Namespaces:
    """Translate between full URIs and the CURIEs the stored documents use."""

    #: What may follow a prefix's namespace for the result to count as a CURIE.
    LOCAL_NAME = re.compile(r"[\w.-]+")

    @classmethod
    def compact(cls, uri: str) -> str:
        """Abbreviate a URI to a CURIE when its namespace has a known prefix.

        Args:
            uri: A full URI.

        Returns:
            ``prefix:local`` for a known namespace, otherwise ``uri`` unchanged.
        """
        for prefix, namespace in PREFIXES.items():
            local = uri.removeprefix(namespace)
            if local != uri and cls.LOCAL_NAME.fullmatch(local):
                return f"{prefix}:{local}"
        return uri

    @staticmethod
    def expand(curie: str) -> str:
        """Return the full URI a CURIE abbreviates.

        Args:
            curie: A ``prefix:local`` CURIE, or a full URI.

        Returns:
            The full URI; ``curie`` unchanged when its prefix is unknown.
        """
        prefix, _, local = curie.partition(":")
        return PREFIXES[prefix] + local if prefix in PREFIXES else curie
