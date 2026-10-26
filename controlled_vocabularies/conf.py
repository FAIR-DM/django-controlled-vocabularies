"""Readers for the package's settings and their defaults."""

from django.conf import settings

#: A localhost placeholder that signals "configure me" while keeping the package usable standalone.
DEFAULT_BASE_URI = "http://localhost:8000/vocabularies"

#: The ``rdflib.namespace`` classes whose terms the statement editor offers and whose prefixes it accepts.
DEFAULT_NAMESPACES = ["SKOS", "DCTERMS", "OWL", "RDF", "RDFS"]


def get_base_uri() -> str:
    """Return the base address for composed URIs, without a trailing slash.

    Reads ``settings.CONTROLLED_VOCABULARIES_BASE_URI``, falling back to
    :data:`DEFAULT_BASE_URI`.

    Returns:
        The base address.
    """
    base = getattr(settings, "CONTROLLED_VOCABULARIES_BASE_URI", DEFAULT_BASE_URI)
    return base.rstrip("/")


def get_namespaces() -> list[str]:
    """Return the names of the ``rdflib.namespace`` classes the package works with.

    Reads ``settings.CONTROLLED_VOCABULARIES_NAMESPACES``, falling back to
    :data:`DEFAULT_NAMESPACES`.

    Returns:
        Class names such as ``"SKOS"``.
    """
    return list(
        getattr(settings, "CONTROLLED_VOCABULARIES_NAMESPACES", DEFAULT_NAMESPACES)
    )
