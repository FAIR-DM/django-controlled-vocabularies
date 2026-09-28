"""The structured outcome of one import run (FS-006)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db.models import TextChoices
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

# An untagged literal reports an empty language, which would render as "in ''"; every
# render() substitutes this phrase at the one boundary all report messages pass through.
_NO_LANGUAGE_TAG = _("no language tag")


# Entry values are text the source document chose, and a remote server can supply it, so
# escapes, carriage returns and newlines are stripped before an operator's terminal sees
# them (Article V). Newline and tab are included: an entry is one line by construction.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _render_params(subject: str, params: dict[str, str]) -> dict[str, str]:
    """Merge ``subject`` into ``params`` and make the values safe to display.

    Every entry's ``render()`` passes through here: an empty ``language`` becomes a
    readable phrase and control characters are stripped from every value.

    Args:
        subject: The record or value at fault.
        params: The entry's reason-specific parameters.

    Returns:
        The placeholders for the reason's message template.
    """
    merged = {"subject": subject, **params}
    if merged.get("language") == "":
        merged["language"] = str(_NO_LANGUAGE_TAG)
    return {
        key: _CONTROL_CHARACTERS.sub("", value) if isinstance(value, str) else value
        for key, value in merged.items()
    }


class SetAsideReason(TextChoices):
    """The closed vocabulary of reasons an import cannot store something.

    A reason names an outcome, not a cause (docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md).
    Fatal findings are not part of this vocabulary. A few members are easy to confuse:

    - ``VARIANT_NOT_KEPT`` is a preferred label that lost a language contest, and
      configuring its published tag recovers it. ``SURPLUS_PREFERRED_LABEL`` is a second
      preferred label in one and the same language, which nothing recovers.
    - ``VALUE_TOO_LONG`` is a value lost from a record that still exists.
      ``COLLECTION_NOT_CREATED`` is a created collection dropped for want of a usable name.
    - ``EMPTY_SLUG`` names the outcome, not a cause: the identifier's segment may slugify to
      nothing, or the collision loop may have run out of candidates.
    - ``DEFAULT_LANGUAGE_FROZEN`` is a conflict at the vocabulary level: a re-imported file
      declares a default language that differs from the frozen one.
    - ``RELATION_DISJOINTNESS`` sets aside the related statement when a pair is also
      broader/narrower, because SKOS makes the two mutually exclusive.
    """

    UNCONFIGURED_LANGUAGE = "unconfigured_language", _("language not configured")
    UNMODELLED_PREDICATE = "unmodelled_predicate", _("predicate not modelled")
    NOTATION = "notation", _("notation")
    MAPPING = "mapping", _("mapping to another vocabulary")
    MISSING_RELATION_END = "missing_relation_end", _("relationship end not found")
    MISSING_MEMBER = "missing_member", _("collection member not found")
    NO_PREFERRED_LABEL = (
        "no_preferred_label",
        _("no preferred label in default language"),
    )
    VOCABULARY_MISMATCH = "vocabulary_mismatch", _("belongs to a different vocabulary")
    DEFAULT_LANGUAGE_FROZEN = (
        "default_language_frozen",
        _("default language already fixed"),
    )
    RELATION_DISJOINTNESS = (
        "relation_disjointness",
        _("broader/narrower and related both claimed for a pair"),
    )
    SURPLUS_PREFERRED_LABEL = (
        "surplus_preferred_label",
        _("surplus preferred label in a language"),
    )
    EMPTY_SLUG = "empty_slug", _("no usable URL slug could be derived")
    ALREADY_IN_ANOTHER_VOCABULARY = (
        "already_in_another_vocabulary",
        _("already belongs to another vocabulary"),
    )
    URI_HELD_BY_DIFFERENT_KIND = (
        "uri_held_by_different_kind",
        _("identifier held by a different kind of record"),
    )
    NO_LANGUAGE_TAG = "no_language_tag", _("no language tag")
    VARIANT_NOT_KEPT = "variant_not_kept", _("language variant not kept")
    VALUE_TOO_LONG = (
        "value_too_long",
        _("value exceeds the maximum length this application can store"),
    )
    STORED_SLUG_INVALID = (
        "stored_slug_invalid",
        _("stored slug no longer passes validation"),
    )
    COLLECTION_NOT_CREATED = (
        "collection_not_created",
        _("collection was not created for want of a usable name"),
    )

    @property
    def template(self) -> Promise:
        """The translatable message template for this reason, keyed by named placeholders."""
        return _REASON_TEMPLATES[self]


_REASON_TEMPLATES: dict[SetAsideReason, Promise] = {
    SetAsideReason.UNCONFIGURED_LANGUAGE: _(
        "'%(subject)s' carries a value in the language '%(language)s', which the site "
        "is not configured for; it was not stored."
    ),
    SetAsideReason.UNMODELLED_PREDICATE: _(
        "'%(subject)s' carries the predicate '%(predicate)s', which the models have no place for; it was not stored."
    ),
    SetAsideReason.NOTATION: _(
        "'%(subject)s' carries a notation, which the models have no place for; it was not stored."
    ),
    SetAsideReason.MAPPING: _(
        "'%(subject)s' carries a mapping to another vocabulary ('%(predicate)s'), which the "
        "models have no place for; it was not stored."
    ),
    SetAsideReason.MISSING_RELATION_END: _(
        "The relationship between '%(subject)s' and '%(other)s' was not stored because "
        "'%(other)s' is neither in this file nor already in the database."
    ),
    SetAsideReason.MISSING_MEMBER: _(
        "'%(subject)s' was not added to the collection '%(collection)s' because it is neither "
        "in this file nor already in the database."
    ),
    SetAsideReason.NO_PREFERRED_LABEL: _(
        "'%(subject)s' has no preferred label in the vocabulary's default language '%(language)s' and was set aside."
    ),
    SetAsideReason.VOCABULARY_MISMATCH: _(
        "'%(subject)s' claims the vocabulary '%(other)s', not the one being imported, and was set aside."
    ),
    SetAsideReason.DEFAULT_LANGUAGE_FROZEN: _(
        "'%(subject)s' declares its default language as '%(declared)s', but this vocabulary's default "
        "language is already fixed to '%(frozen)s' because it already has concepts; the declared value "
        "was not applied."
    ),
    SetAsideReason.RELATION_DISJOINTNESS: _(
        "'%(subject)s' and '%(other)s' are joined as broader/narrower, so the related statement between "
        "them was set aside; a broader/narrower pair and a related pair are mutually exclusive."
    ),
    SetAsideReason.SURPLUS_PREFERRED_LABEL: _(
        "'%(subject)s' carries more than one preferred label in the language '%(language)s'; only one is "
        "kept and the surplus value was set aside."
    ),
    SetAsideReason.EMPTY_SLUG: _(
        "'%(subject)s' could not be given a usable URL slug, so it was set aside."
    ),
    SetAsideReason.ALREADY_IN_ANOTHER_VOCABULARY: _(
        "'%(subject)s' already belongs to the vocabulary '%(current)s'; importing it into '%(target)s' "
        "would move it between vocabularies, so it was left where it is."
    ),
    SetAsideReason.URI_HELD_BY_DIFFERENT_KIND: _(
        "'%(subject)s' is already held by a record of a different kind in this application; a second "
        "record was not created for it."
    ),
    SetAsideReason.NO_LANGUAGE_TAG: _(
        "'%(subject)s' carries a '%(predicate)s' value with no language tag (or one that is not text "
        "at all); it was not stored."
    ),
    SetAsideReason.VARIANT_NOT_KEPT: _(
        "'%(subject)s' carries a value in the language '%(language)s'; another variant was kept for "
        "the site's '%(kept_as)s' instead, and this one was not stored."
    ),
    SetAsideReason.VALUE_TOO_LONG: _(
        "'%(subject)s' carries a value in the language '%(language)s' longer than this application "
        "can store; it was not stored."
    ),
    SetAsideReason.STORED_SLUG_INVALID: _(
        "'%(subject)s' has a stored slug that no longer passes this application's own validation; "
        "it was left exactly as stored, and nothing else about it was imported this run."
    ),
    SetAsideReason.COLLECTION_NOT_CREATED: _(
        "'%(subject)s' was not created because it has no name this application can store."
    ),
}


@dataclass(frozen=True)
class SetAsideEntry:
    """One value the import could not store, with what it was and why.

    Attributes:
        reason: Why the value was not stored.
        subject: The record or value at fault, typically a URI.
        params: The named placeholders :attr:`SetAsideReason.template` needs beyond
            ``subject``.
    """

    reason: SetAsideReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Return this entry's message in the active language."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


class FatalReason(TextChoices):
    """The closed vocabulary of reasons a run fails outright.

    Separate from :class:`SetAsideReason`: everything there lets the rest of the file
    import, while every reason here refuses the whole run and rolls its transaction back.
    Two name a missing or refused record identity and the rest a vocabulary the run cannot
    resolve or create, because without one there is nothing for the rest of the file to
    import into. ``VOCABULARY_NAME_UNPUBLISHED`` covers both a scheme with no
    ``skos:prefLabel`` at all and one whose labels are all empty.
    """

    MISSING_IDENTITY = "missing_identity", _("identifier missing or blank")
    REFUSED_IDENTITY = "refused_identity", _("identifier refused by the identity rules")
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
    DEFAULT_LANGUAGE_UNCONFIGURED = (
        "default_language_unconfigured",
        _("default language not configured"),
    )
    VOCABULARY_SLUG_UNUSABLE = (
        "vocabulary_slug_unusable",
        _("vocabulary's identifier produces no usable slug"),
    )
    VOCABULARY_NAME_UNUSABLE = (
        "vocabulary_name_unusable",
        _("vocabulary's name is longer than this application can store"),
    )
    VOCABULARY_RECORD_INVALID = (
        "vocabulary_record_invalid",
        _(
            "vocabulary's stored record fails its own validation and could not be written"
        ),
    )
    VOCABULARY_NAME_UNPUBLISHED = (
        "vocabulary_name_unpublished",
        _("vocabulary publishes no preferred label in any language"),
    )

    @property
    def template(self) -> Promise:
        """The translatable message template for this reason, keyed by named placeholders."""
        return _FATAL_TEMPLATES[self]


_FATAL_TEMPLATES: dict[FatalReason, Promise] = {
    FatalReason.MISSING_IDENTITY: _(
        "'%(subject)s' has no identifier that survives re-serialization (a blank node); the run was refused."
    ),
    FatalReason.REFUSED_IDENTITY: _(
        "'%(subject)s' is not an identifier the application accepts; the run was refused."
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
    FatalReason.DEFAULT_LANGUAGE_UNCONFIGURED: _(
        "'%(subject)s' has an effective default language of '%(language)s', which this site is not "
        "configured for; the run was refused."
    ),
    FatalReason.VOCABULARY_SLUG_UNUSABLE: _(
        "'%(subject)s' produces no usable slug from its own identifier; the run was refused."
    ),
    FatalReason.VOCABULARY_NAME_UNUSABLE: _(
        "'%(subject)s' has no name this application can store — its published name in "
        "'%(language)s' is longer than this application can store, and there is no earlier "
        "name to keep; the run was refused."
    ),
    FatalReason.VOCABULARY_RECORD_INVALID: _(
        "'%(subject)s' has a stored record that fails this application's own validation and "
        "could not be written; the run was refused."
    ),
    FatalReason.VOCABULARY_NAME_UNPUBLISHED: _(
        "'%(subject)s' has no name this application can store — no skos:prefLabel with a "
        "usable value was published for it in any language; the run was refused."
    ),
}


@dataclass(frozen=True)
class FatalFinding:
    """One reason a run failed outright, with what it was and why.

    The fatal counterpart of :class:`SetAsideEntry`, kept as its own type because a fatal
    reason is never one of :class:`SetAsideReason`'s.

    Attributes:
        reason: Why the run was refused.
        subject: The record or file at fault.
        params: The named placeholders :attr:`FatalReason.template` needs beyond ``subject``.
    """

    reason: FatalReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Return this entry's message in the active language."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


class NormalizedReason(TextChoices):
    """The closed vocabulary of reasons a value is stored under something other than published.

    Separate from :class:`SetAsideReason`: a set-aside value was not stored, whereas a
    normalized one was, just not verbatim. Both are reported so nothing is applied silently
    (Article XI). ``LANGUAGE_SUBSTITUTION`` reads ``%(language)s`` as the published tag and
    ``%(kept_as)s`` as the configured language it was stored under.
    """

    FOREIGN_DEFINITION = (
        "foreign_definition",
        _("definition read from a foreign predicate"),
    )
    LANGUAGE_SUBSTITUTION = (
        "language_substitution",
        _("value stored under a different language than published"),
    )

    @property
    def template(self) -> Promise:
        """The translatable message template for this reason, keyed by named placeholders."""
        return _NORMALIZED_TEMPLATES[self]


_NORMALIZED_TEMPLATES: dict[NormalizedReason, Promise] = {
    NormalizedReason.FOREIGN_DEFINITION: _(
        "'%(subject)s' has no '%(language)s' definition of its own; its '%(predicate)s' value in "
        "that language was stored as its definition instead."
    ),
    NormalizedReason.LANGUAGE_SUBSTITUTION: _(
        "'%(subject)s' was published in the language '%(language)s' and was stored under "
        "'%(kept_as)s', the site's matching configured language."
    ),
}


@dataclass(frozen=True)
class NormalizedEntry:
    """One value stored under a predicate other than the one the file asserted.

    The normalized counterpart of :class:`SetAsideEntry`, kept as its own type because the
    value was stored.

    Attributes:
        reason: Why the value was stored differently.
        subject: The record at fault.
        params: The named placeholders :attr:`NormalizedReason.template` needs beyond
            ``subject``.
    """

    reason: NormalizedReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Return this entry's message in the active language."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


@dataclass
class ImportReport:
    """The structured outcome of one import run.

    Every bucket is a plain list a caller reads directly, never by parsing a message. On a
    successful run :attr:`fatal` is empty.

    Attributes:
        created: URIs of the records the run created.
        updated: URIs of the records the run updated.
        set_aside: One entry per value the run could not store.
        absent_from_source: URIs of records the file no longer mentions, left untouched.
        normalized: One entry per value stored under a different predicate than published.
        fatal: One finding per reason the whole run was refused.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    set_aside: list[SetAsideEntry] = field(default_factory=list)
    absent_from_source: list[str] = field(default_factory=list)
    normalized: list[NormalizedEntry] = field(default_factory=list)
    fatal: list[FatalFinding] = field(default_factory=list)

    def add_created(self, subject: str) -> None:
        """Record that ``subject`` was created by this run.

        Args:
            subject: The URI of the created record.
        """
        self.created.append(subject)

    def add_updated(self, subject: str) -> None:
        """Record that ``subject`` was updated by this run.

        Args:
            subject: The URI of the updated record.
        """
        self.updated.append(subject)

    def add_absent_from_source(self, subject: str) -> None:
        """Record that ``subject`` exists here but is no longer in the source.

        Args:
            subject: The URI of the record the file no longer mentions.
        """
        self.absent_from_source.append(subject)

    def add_set_aside(
        self, reason: SetAsideReason, subject: str, **params: str
    ) -> None:
        """Record that ``subject`` was not stored.

        Args:
            reason: Why it was not stored.
            subject: The record or value at fault.
            **params: The named placeholders the reason's template needs.
        """
        self.set_aside.append(
            SetAsideEntry(reason=reason, subject=subject, params=params)
        )

    def add_normalized(
        self, reason: NormalizedReason, subject: str, **params: str
    ) -> None:
        """Record that ``subject`` was stored under a predicate other than the published one.

        The value is stored, so this is visibility rather than a refusal and is kept apart
        from :attr:`set_aside`.

        Args:
            reason: Why it was stored differently.
            subject: The record at fault.
            **params: The named placeholders the reason's template needs.
        """
        self.normalized.append(
            NormalizedEntry(reason=reason, subject=subject, params=params)
        )

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

    def set_aside_by_reason(self) -> dict[SetAsideReason, list[SetAsideEntry]]:
        """Group :attr:`set_aside` by reason, without parsing any rendered message.

        Returns:
            The entries under each reason that
            has any.
        """
        grouped: dict[SetAsideReason, list[SetAsideEntry]] = {}
        for entry in self.set_aside:
            grouped.setdefault(entry.reason, []).append(entry)
        return grouped

    # Explicit rather than "carries a language param": SURPLUS_PREFERRED_LABEL carries one
    # too, but its language is already configured, so configuring something recovers nothing.
    _LANGUAGE_ACCOUNT_REASONS = frozenset(
        {SetAsideReason.UNCONFIGURED_LANGUAGE, SetAsideReason.VARIANT_NOT_KEPT}
    )

    def language_account(self) -> dict[str, int]:
        """Count the values not stored for a language reason, by published language.

        A fold over :attr:`set_aside`, so it cannot disagree with the entries. Counts are
        under the published tag, never the configured language a contest loser lost to.
        Tags fold case-insensitively, because ``PT-br`` and ``pt-BR`` are one recoverable
        language, and the first spelling seen is the display key.

        Returns:
            Count per published language, empty after a run that left
            nothing behind.
        """
        account: dict[str, int] = {}
        display: dict[str, str] = {}
        for entry in self.set_aside:
            if entry.reason in self._LANGUAGE_ACCOUNT_REASONS:
                language = entry.params["language"]
                key = language.lower()
                display.setdefault(key, language)
                account[key] = account.get(key, 0) + 1
        return {display[key]: count for key, count in account.items()}
