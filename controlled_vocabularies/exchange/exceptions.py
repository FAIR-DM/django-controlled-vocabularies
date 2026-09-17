"""The exception hierarchy for reading a published SKOS file (FS-006).

Two unrelated ways an import ends badly, which callers are documented to catch
as the pair ``(SkosImportError, SkosImportFailed)``:

- :class:`SkosImportError` — the file could not be turned into usable SKOS at
  all. Missing, an undeterminable or unsupported serialization, unparseable, or
  refused outright by the pre-flight safety scan through one of its two
  subclasses.
- :class:`SkosImportFailed` — the file parsed fine and its *content* was
  refused. Carries the run's :class:`~controlled_vocabularies.exchange.report.ImportReport`.

They are siblings rather than one subclassing the other, deliberately: catching
"unreadable file" should not also catch "readable file, rejected content".

These lived in ``safety.py`` and ``skos.py`` respectively. ``SkosImportError``
was moved into ``safety.py`` by review fix 19 (decisions.md D52) only so the
two ``Unsafe*`` subclasses could reach it without a circular import, which left
the base of the whole hierarchy — covering a missing file and an undeterminable
serialization, neither of them a safety concern — living in the safety scanner.
Collecting them here removes the cycle as the reason for a module's contents.
Both names remain importable from their original modules, so no caller moves.
"""

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


class SkosImportError(ValidationError):
    """Raised when a candidate file cannot be turned into usable SKOS at all (FR-002).

    Covers a missing file, a serialization that cannot be determined or is not
    one of the three this feature reads, and a file that fails to parse as the
    serialization it is read as — plus, through its two subclasses, a file the
    pre-flight safety scan refuses. A
    :class:`~django.core.exceptions.ValidationError` subclass so it carries the
    same translatable, named-placeholder message shape as the rest of the
    package (Article XII).
    """


class UnsafeRdfXmlError(SkosImportError):
    """Raised when a candidate RDF/XML document fails the pre-flight safety scan.

    A :class:`SkosImportError` subclass (review fix 19, decisions.md D52) so a
    consumer catching the package's documented pair still catches a hostile
    file without needing to know the scan exists. The underlying `defusedxml`
    exception is chained via ``__cause__`` for developer diagnostics, which are
    exempt from translation (Article XII).
    """


class UnsafeJsonLdError(SkosImportError):
    """Raised for a JSON-LD document carrying a remote ``@context`` reference (decisions.md D36)
    or an ``@import`` inside any context (decisions.md D47).

    Same shape and same reasoning as :class:`UnsafeRdfXmlError` (review fix 19,
    decisions.md D52, Article XII).
    """


class SkosImportFailed(ValidationError):
    """Raised when a run collects one or more fatal findings (FR-004, decisions.md D3/D8).

    Carries the run's partial :class:`~controlled_vocabularies.exchange.report.ImportReport`
    so a caller can see what was wrong, even though the transaction this is
    raised inside has already rolled back everything the run wrote — the run is
    all-or-nothing, but the report still names every problem (T011, research.md
    R7, FR-004).
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
