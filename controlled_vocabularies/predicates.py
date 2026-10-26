"""The predicates the package knows about and the CURIE prefixes that abbreviate them."""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

import rdflib.namespace

from controlled_vocabularies.conf import get_namespaces


class Kind(StrEnum):
    """What a predicate's values are, which decides how an export types them."""

    LITERAL = "literal"
    URI = "uri"
    TYPED = "typed"


@dataclass(frozen=True)
class Predicate:
    """What the package knows about one predicate.

    Attributes:
        kind: Whether the values are plain literals, links, or literals with a datatype.
        many: Whether more than one value is allowed (per language when translatable).
        translatable: Whether a value may be given once per language.
    """

    kind: Kind
    many: bool = True
    translatable: bool = False


class _Prefixes(Mapping[str, str]):
    """The prefix to namespace map, built from the configured ``rdflib`` namespace classes.

    Read on every access rather than at import, so it follows the project's settings.
    ``xsd`` is always present because typed values use ``xsd:date``.
    """

    @staticmethod
    def _build() -> dict[str, str]:
        """Return the map for the namespaces now configured."""
        names = dict.fromkeys([*get_namespaces(), "XSD"])
        return {name.lower(): str(getattr(rdflib.namespace, name)) for name in names}

    def __getitem__(self, prefix: str) -> str:
        """Return the namespace a prefix abbreviates."""
        return self._build()[prefix]

    def __iter__(self) -> Iterator[str]:
        """Iterate the prefixes in configured order."""
        return iter(self._build())

    def __len__(self) -> int:
        """Return how many prefixes there are."""
        return len(self._build())


#: The prefixes a stored key may use. A key outside these namespaces is stored as a full URI.
PREFIXES = _Prefixes()

_LITERAL = Predicate(Kind.LITERAL, many=False)
_NOTE = Predicate(Kind.LITERAL, translatable=True)
_LINKS = Predicate(Kind.URI)

#: Known predicates in the order the pages show them. An unlisted predicate is stored and
#: shown verbatim after these.
PREDICATES: dict[str, Predicate] = {
    "skos:prefLabel": Predicate(Kind.LITERAL, many=False, translatable=True),
    "skos:altLabel": _NOTE,
    "skos:hiddenLabel": _NOTE,
    "skos:notation": Predicate(Kind.TYPED),
    "skos:definition": _NOTE,
    "skos:scopeNote": _NOTE,
    "skos:example": _NOTE,
    "skos:editorialNote": _NOTE,
    "skos:historyNote": _NOTE,
    "skos:changeNote": _NOTE,
    "skos:note": _NOTE,
    "skos:broader": _LINKS,
    "skos:narrower": _LINKS,
    "skos:related": _LINKS,
    "skos:exactMatch": _LINKS,
    "skos:closeMatch": _LINKS,
    "skos:broadMatch": _LINKS,
    "skos:narrowMatch": _LINKS,
    "skos:relatedMatch": _LINKS,
    "skos:member": _LINKS,
    "skos:memberList": _LINKS,
    "skos:inScheme": _LINKS,
    "skos:topConceptOf": _LINKS,
    "dcterms:title": Predicate(Kind.LITERAL, many=False, translatable=True),
    "dcterms:description": Predicate(Kind.LITERAL, many=False, translatable=True),
    "dcterms:publisher": Predicate(Kind.LITERAL),
    "dcterms:creator": Predicate(Kind.LITERAL),
    "dcterms:license": _LINKS,
    "dcterms:modified": Predicate(Kind.TYPED, many=False),
    "owl:versionInfo": _LITERAL,
}


class Namespaces:
    """Translate between full URIs and the CURIEs the stored documents use."""

    #: What may follow a prefix's namespace for the result to count as a CURIE.
    _LOCAL_NAME = re.compile(r"[\w.-]+")

    @classmethod
    def terms(cls) -> list[str]:
        """Return the properties of the configured namespaces, as CURIEs.

        Returns:
            The CURIEs in ``PREDICATES`` first, in table order, then the rest alphabetically.
        """
        return cls._terms(tuple(get_namespaces()))

    @staticmethod
    @cache
    def _terms(names: tuple[str, ...]) -> list[str]:
        """Collect the properties of the named ``rdflib`` classes once per process."""
        # A DefinedNamespace lists its terms as class annotations, and by RDF's convention a
        # property starts in lower case where a class does not.
        found = {
            f"{name.lower()}:{term}"
            for name in names
            for term in getattr(rdflib.namespace, name).__annotations__
            if term[0].islower()
        }
        known = [curie for curie in PREDICATES if curie in found]
        return known + sorted(found - set(known))

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
            if local != uri and cls._LOCAL_NAME.fullmatch(local):
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
