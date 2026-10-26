"""Readers for the package's settings and their defaults."""

from django.conf import settings

#: A localhost placeholder that signals "configure me" while keeping the package usable standalone.
DEFAULT_BASE_URI = "http://localhost:8000/vocabularies"


def get_base_uri() -> str:
    """Return the base address for composed URIs, without a trailing slash.

    Reads ``settings.CONTROLLED_VOCABULARIES_BASE_URI``, falling back to
    :data:`DEFAULT_BASE_URI`.

    Returns:
        The base address.
    """
    base = getattr(settings, "CONTROLLED_VOCABULARIES_BASE_URI", DEFAULT_BASE_URI)
    return base.rstrip("/")
