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


def get_declared_vocabularies() -> dict[str, dict]:
    """Return the vocabularies the site declares, keyed by the slug fields name them by.

    Reads ``settings.CONTROLLED_VOCABULARIES``. Each value holds a ``source``, a local path
    or an http(s) URL, and optionally the ``format`` it is serialized in.

    Returns:
        The declarations, or an empty dict when the setting is absent.
    """
    return getattr(settings, "CONTROLLED_VOCABULARIES", {})
