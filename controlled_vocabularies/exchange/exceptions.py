"""The exceptions raised when reading a published SKOS file (FS-006)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from controlled_vocabularies.exchange.report import ImportReport

__all__ = [
    "SkosImportError",
    "SkosImportFailed",
    "UnsafeJsonLdError",
    "UnsafeRdfXmlError",
]


# Siblings, not parent and child: catching an unreadable file must not also catch a readable
# file whose content was rejected. Callers catch the pair (SkosImportError, SkosImportFailed).
class SkosImportError(ValidationError):
    """Raise when a file cannot be turned into usable SKOS at all.

    Covers a missing file, an undeterminable or unsupported serialization, a file that
    fails to parse, and (through its subclasses) a file the pre-flight safety scan refuses.
    """


class UnsafeRdfXmlError(SkosImportError):
    """Raise when an RDF/XML document fails the pre-flight safety scan.

    The underlying ``defusedxml`` exception is chained as ``__cause__``.
    """


class UnsafeJsonLdError(SkosImportError):
    """Raise when a JSON-LD document has a remote ``@context`` or an ``@import``."""


class SkosImportFailed(ValidationError):
    """Raise when a run collects one or more fatal findings.

    The run is all-or-nothing, so the transaction it was raised in has already rolled
    back. The report still names every problem.

    Args:
        report: The run's partial report, kept as :attr:`report`.
    """

    def __init__(self, report: ImportReport) -> None:
        self.report = report
        super().__init__(
            _(
                "The import was refused: %(count)s problem(s) were found. See the report for details."
            ),
            params={"count": len(report.fatal)},
            code="skos_import_failed",
        )
