"""Readers for the package's settings and their defaults."""

from django.conf import settings

#: A localhost placeholder that signals "configure me" while keeping the package usable standalone.
DEFAULT_BASE_URI = "http://localhost:8000/vocabularies"

#: An allowlist rather than a denylist: ``http``/``https`` plus the non-http identifier
#: schemes real SKOS vocabularies use.
DEFAULT_ALLOWED_URI_SCHEMES = (
    "http",
    "https",
    "urn",
    "doi",
    "info",
    "ark",
    "tag",
    "hdl",
    "oai",
)


def get_base_uri() -> str:
    """Return the base address for composed URIs, without a trailing slash.

    Reads ``settings.CONTROLLED_VOCABULARIES_BASE_URI``, falling back to
    :data:`DEFAULT_BASE_URI`.

    Returns:
        The base address.
    """
    base = getattr(settings, "CONTROLLED_VOCABULARIES_BASE_URI", DEFAULT_BASE_URI)
    return base.rstrip("/")


def get_allowed_uri_schemes() -> frozenset[str]:
    """Return the lower-cased schemes accepted for a static URI.

    Reads ``settings.CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES``, falling back to
    :data:`DEFAULT_ALLOWED_URI_SCHEMES`.

    Returns:
        The accepted schemes.
    """
    schemes = getattr(
        settings,
        "CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES",
        DEFAULT_ALLOWED_URI_SCHEMES,
    )
    return frozenset(scheme.lower() for scheme in schemes)
