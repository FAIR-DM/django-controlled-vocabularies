"""Configuration access for controlled_vocabularies.

A single read site for the base address used to compose concept and scheme URIs
(research decision R2). Keeping the read in one place stops the composition rule
from scattering across the models.
"""

from django.conf import settings

#: Default base address when the host project does not configure one. A localhost
#: placeholder that signals "configure me for real deployments" while keeping the
#: package usable standalone. Documented in the README.
DEFAULT_BASE_URI = "http://localhost:8000/vocabularies"

#: Default schemes accepted for an externally assigned static URI (FR-004,
#: decisions.md D5/D15, T035): a small, stable allowlist rather than an
#: unbounded denylist. ``http``/``https`` are the overwhelming common case;
#: ``urn``, ``doi``, ``info``, ``ark``, ``tag``, ``hdl``, and ``oai`` are the
#: non-http identifier schemes real SKOS vocabularies actually use (``tag``,
#: ``hdl``, and ``oai`` added in review round 4, decisions.md D15).
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
    """Return the configured base URI for vocabulary/concept URIs, without a trailing slash.

    Reads ``settings.CONTROLLED_VOCABULARIES_BASE_URI`` and falls back to
    :data:`DEFAULT_BASE_URI`. A trailing slash is stripped so callers can compose
    with ``f"{base}/{slug}"`` unconditionally.
    """
    base = getattr(settings, "CONTROLLED_VOCABULARIES_BASE_URI", DEFAULT_BASE_URI)
    return base.rstrip("/")


def get_allowed_uri_schemes() -> frozenset[str]:
    """Return the configured, lower-cased set of accepted static-URI schemes.

    Reads ``settings.CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES`` and falls
    back to :data:`DEFAULT_ALLOWED_URI_SCHEMES`, so a downstream project with
    an unusual scheme is not stuck with the defaults (T035).
    """
    schemes = getattr(
        settings,
        "CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES",
        DEFAULT_ALLOWED_URI_SCHEMES,
    )
    return frozenset(scheme.lower() for scheme in schemes)
