"""The structured outcome of one import run (FS-006)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db.models import TextChoices
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

# Entry values are text the source document chose, and a remote server can supply it, so
# escapes, carriage returns and newlines are stripped before an operator's terminal sees
# them (Article V). Newline and tab are included: an entry is one line by construction.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class FatalReason(TextChoices):
    """The closed vocabulary of reasons a run fails outright.

    Every reason refuses the whole run and rolls its transaction back: either a subject
    has no identifier that survives re-serialization, or the run cannot tell which
    vocabulary the records belong to.
    """

    MISSING_IDENTITY = "missing_identity", _("identifier missing or blank")
    VOCABULARY_UNDETERMINED = (
        "vocabulary_undetermined",
        _("vocabulary not declared and no target named"),
    )
    VOCABULARY_TARGET_MISMATCH = (
        "vocabulary_target_mismatch",
        _("declared vocabulary does not match the named target"),
    )
    VOCABULARY_AMBIGUOUS = (
        "vocabulary_ambiguous",
        _("the file declares more than one vocabulary and none was named"),
    )

    @property
    def template(self) -> Promise:
        """The translatable message template for this reason, keyed by named placeholders."""
        return _FATAL_TEMPLATES[self]


_FATAL_TEMPLATES: dict[FatalReason, Promise] = {
    FatalReason.MISSING_IDENTITY: _(
        "'%(subject)s' has no identifier that survives re-serialization (a blank node); the run was refused."
    ),
    FatalReason.VOCABULARY_UNDETERMINED: _(
        "'%(subject)s' declares no vocabulary of its own, and no target vocabulary was named; the run was refused."
    ),
    FatalReason.VOCABULARY_TARGET_MISMATCH: _(
        "'%(subject)s' is not the vocabulary named as the import's target ('%(target)s'); the run was refused."
    ),
    FatalReason.VOCABULARY_AMBIGUOUS: _(
        "'%(subject)s' declares more than one vocabulary (%(declared)s) and none was named as the import's "
        "target; the run was refused."
    ),
}


@dataclass(frozen=True)
class FatalFinding:
    """One reason a run failed outright, with what it was and why.

    Attributes:
        reason: Why the run was refused.
        subject: The record or file at fault.
        params: The named placeholders :attr:`FatalReason.template` needs beyond ``subject``.
    """

    reason: FatalReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Return this finding's message in the active language, safe to print."""
        merged = {"subject": self.subject, **self.params}
        return str(self.reason.template) % {
            key: _CONTROL_CHARACTERS.sub("", value) for key, value in merged.items()
        }


@dataclass
class ImportReport:
    """The structured outcome of one import run.

    Every bucket is a plain list a caller reads directly, never by parsing a message. On a
    successful run :attr:`fatal` is empty.

    Attributes:
        created: URIs of the records the run created.
        updated: URIs of the records the run updated.
        absent_from_source: URIs of records the file no longer mentions, left untouched.
        fatal: One finding per reason the whole run was refused.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    absent_from_source: list[str] = field(default_factory=list)
    fatal: list[FatalFinding] = field(default_factory=list)

    def add_fatal(self, reason: FatalReason, subject: str, **params: str) -> None:
        """Record that ``subject`` is why the whole run was refused.

        A run with anything in :attr:`fatal` raises instead of returning, so a caller reads
        this bucket from the raised exception.

        Args:
            reason: Why the run was refused.
            subject: The record or file at fault.
            **params: The named placeholders the reason's template needs.
        """
        self.fatal.append(FatalFinding(reason=reason, subject=subject, params=params))
