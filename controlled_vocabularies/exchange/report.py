"""The structured outcome of one import run (FR-015, decisions.md D7).

``ImportReport`` is the feature's public contract alongside the import itself: #51
groups and counts what was set aside for a curator, and #52 renders a command-line
summary and a dry-run preview from it, neither re-reading the file nor parsing
prose (spec Acceptance Scenario US1-11). Four buckets, each inspectable as data:
what was created, what was updated, what was set aside with a reason, and what the
source no longer mentions.

A set-aside reason is drawn from the closed :class:`SetAsideReason` vocabulary,
never freeform text (Article XII, FR-016). An entry stores its reason, its
subject, and any reason-specific parameters as plain data — the same shape
:class:`~django.core.exceptions.ValidationError` uses — so the message renders in
the caller's active language at display time rather than being baked into one
language at creation time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db.models import TextChoices
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: SEC-406, decisions.md D64 (fix cycle 5): SkosGraph.first_literal_with_language reports "" for
#: an untagged literal (D52) — a caller naming that value in a %(language)s placeholder would
#: otherwise render "...in ''...", which leaks nothing but tells a curator nothing either. Every
#: render() below substitutes this phrase for an empty language, at the one boundary all of a
#: report's messages pass through, rather than each call site guarding its own params.
_NO_LANGUAGE_TAG = _("no language tag")


#: SEC-702, decisions.md D22 (review, security lens) — the C0 and C1 control ranges, minus
#: nothing: no label, URI, language tag or predicate name in a vocabulary has any business
#: carrying an escape, a carriage return or a backspace. Every value in a report entry is
#: text the *source document* chose, and since #52 a source document can be a file a remote
#: server hands over, rendered straight to an operator's terminal. `\x1b[2K\r` erases the
#: line being written and `\x1b[1A` moves the cursor over the one above it, so a document
#: could overwrite the account of itself — worst on ``--dry-run``, whose entire product is
#: the text an operator reads before deciding to commit.
#:
#: The range includes newline and tab, which the usual "control characters" carve-out keeps.
#: A report entry is one line by construction, so an embedded newline breaks the format
#: whatever its intent, and lets a document fake a whole additional line of the account —
#: the same failure as the escape sequence, reached with a character nobody screens for.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _render_params(subject: str, params: dict[str, str]) -> dict[str, str]:
    """``params`` merged with ``subject``, substituting :data:`_NO_LANGUAGE_TAG` for an empty
    ``language`` value (SEC-406, decisions.md D64) and stripping control characters from every
    document-supplied value (SEC-702, decisions.md D22) — shared by every entry's ``render()``.

    Both guards live here rather than at each call site for the same reason: this is the one
    boundary every fatal, set-aside and normalized message passes through on its way to a
    person.
    """
    merged = {"subject": subject, **params}
    if merged.get("language") == "":
        merged["language"] = str(_NO_LANGUAGE_TAG)
    return {
        key: _CONTROL_CHARACTERS.sub("", value) if isinstance(value, str) else value
        for key, value in merged.items()
    }


class SetAsideReason(TextChoices):
    """The closed vocabulary of reasons an import cannot store something (FR-014).

    Covers what the spec's Key Entities and FR-014 name: a language the site is
    not configured for, a predicate or construct the models have no place for, a
    relationship or membership end missing from both the file and the database, a
    concept with no usable preferred label, and a record claiming a vocabulary
    other than the one being imported. Not "fatal" findings (a missing or blank-node
    identity) — those fail the whole run rather than being set aside (D3, D8) and
    are not part of this vocabulary.

    ``DEFAULT_LANGUAGE_FROZEN`` (US-2, decisions.md D18/D22) is the one member
    naming a conflict at the vocabulary level rather than a value that could
    not be stored: a re-imported file's declared default language differing
    from the one already frozen on an existing, concept-bearing scheme.
    ``RELATION_DISJOINTNESS`` (review fix, decisions.md D37) names a pair
    stated, in one file or split across two runs, as both a hierarchical
    (broader/narrower) and a related relation — SKOS declares the two
    mutually exclusive (models.py ``ConceptRelation._reject_disjointness_violation``);
    the hierarchical relation always wins and the related statement is the
    one set aside. ``SURPLUS_PREFERRED_LABEL`` (review fix, decisions.md D38)
    names a preferred label beyond the first a concept carries in one
    language — the model allows only one ``PREFERRED`` row per (concept,
    language) — whichever value is not the deterministically-kept one is
    the one set aside, in the vocabulary's default language exactly as much
    as in any other configured language. ``EMPTY_SLUG`` (review fix,
    decisions.md D39; reworded fix cycle 8, S6 CORR-701, decisions.md D72)
    names a concept or collection this run could not give a usable URL slug,
    which the model refuses to store; the record is set aside rather than
    crashing the run on that refusal. Its message names that outcome and not
    a cause, because the causes differ by call site and no longer include the
    preferred label at all: since T029/decisions.md D35 the slug derives from
    the published identifier's own segment, so what can slugify to nothing is
    that segment — or, on the paths T060 added, nothing is wrong with the
    published values and the collision loop simply ran out of candidates.
    ``ALREADY_IN_ANOTHER_VOCABULARY`` (review fix 8/9, decisions.md D42) names
    a concept or collection whose identity is already held by a *different*
    vocabulary than the one being imported: moving a record between
    vocabularies is a curatorial act, never a side effect of reading a file,
    so the existing record is left exactly where it is rather than
    reassigned. ``URI_HELD_BY_DIFFERENT_KIND`` (review fix 10, decisions.md
    D43) names a URI already held by a record of a different kind — a
    collection where this file asserts a concept, or the reverse — a
    contradictory source reported while reading rather than surfacing as a
    database constraint violation (spec Edge Cases). ``NO_LANGUAGE_TAG``
    (review fix 15, decisions.md D48) names a label or note value that is
    either a plain literal with no language tag, or not a literal at all
    (e.g. ``skos:definition`` pointing at a URI) — FR-008/FR-009 both require
    a label or note to be stored "with its language", which a value carrying
    none cannot meet; the value is set aside rather than guessed into the
    vocabulary's default language, a language the file itself never asserted.
    ``VARIANT_NOT_KEPT`` (T022, FR-005, decisions.md D14) names a preferred
    label beaten by a *sibling variant* in a language contest (FR-003) —
    never ``SURPLUS_PREFERRED_LABEL``, whose message means more than one
    preferred label in one and the same language and is false for a value
    whose file carries exactly one preferred label in its own published tag.
    The two have different remedies: nothing recovers a same-language
    duplicate, while configuring the published tag recovers a contest loser,
    which is what FR-008's account exists to tell apart.
    ``VALUE_TOO_LONG`` (fix cycle 1, S6 SEC-002, decisions.md D34) names a
    label or note value the model's own field refuses on length — variant
    matching newly routes values that were previously unreachable into
    ``Concept.add_label``/``add_note``, and a single verbose alternative
    label in a hostile or merely careless file must not abort an entire
    import; the value is set aside rather than crashing the run on
    ``ValidationError`` (the same discipline ``EMPTY_SLUG`` already applies
    to the slug). ``STORED_SLUG_INVALID`` (fix cycle 4, S6 SEC-301,
    decisions.md D50) names a matched record whose already-stored slug was
    written out of band (``.update()``, ``loaddata``, ``bulk_create``, a data
    migration) and no longer passes the model's own manual-slug validation —
    T041's read-back means that value now reaches the write path unchanged,
    and the record is set aside rather than letting ``ValidationError``
    escape ``import_skos`` outside its own exception hierarchy.
    ``COLLECTION_NOT_CREATED`` (fix cycle 5, CORR-404, decisions.md D60) names
    the record-level outcome when a *created* collection's name is unusable —
    over-long with nothing storable to fall back to, or absent altogether —
    distinct from ``VALUE_TOO_LONG``, which names a value lost from a record
    that still exists. Without this, both a matched collection keeping its old
    name and a created collection dropped in full rendered the identical
    ``VALUE_TOO_LONG`` entry, distinguishable only by querying the database
    the report exists to describe.
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
        """The translatable, named-placeholder message template for this reason.

        Every template declares ``%(subject)s`` (the record or value at fault);
        reasons that need more context declare their own named placeholders
        alongside it (Article XII) — supplied via :attr:`SetAsideEntry.params`.
        """
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
    """One value the import could not store, with what it was and why (FR-014/FR-015).

    ``subject`` names the record or value at fault — typically a URI. ``params``
    carries whatever else :attr:`SetAsideReason.template` needs (a language, a
    predicate CURIE, the other end of a relationship), keyed by name, the same
    shape :class:`~django.core.exceptions.ValidationError` uses. Both are read
    directly by a caller that groups or counts (spec US1-11); :meth:`render` is
    for display only.
    """

    reason: SetAsideReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """This entry's message in the caller's active language (Article XII)."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


class FatalReason(TextChoices):
    """The closed vocabulary of reasons a run fails outright (FR-004, decisions.md D3/D8).

    Deliberately separate from :class:`SetAsideReason`: everything in that
    vocabulary lets the rest of the file still import; everything here means
    the whole run fails and the transaction rolls back (T011,
    ``research.md`` R7). Covers the small fatal set decisions.md D8 names —
    a missing or refused record identity — plus the two ways the vocabulary
    itself cannot be resolved (FR-005): the file names none and the caller
    named no target, or the caller's named target contradicts the file's own.
    ``DEFAULT_LANGUAGE_UNCONFIGURED`` (fix cycle 1, S6 SEC-001, decisions.md D34)
    names a vocabulary whose ``effective_default_language`` is not itself one
    of the site's configured languages — ``settings.LANGUAGE_CODE`` falls back
    unvalidated against ``settings.LANGUAGES``, and no published tag can ever
    resolve to a value that is not itself a configured code, so every concept
    would otherwise be silently set aside for want of a preferred label. Failing
    the whole run early, naming the one misconfiguration, replaces what would
    otherwise be one ``NO_PREFERRED_LABEL`` per concept for no gain to a curator.
    ``VOCABULARY_SLUG_UNUSABLE`` (fix cycle 2, FR-018, decisions.md D35) names a
    vocabulary whose published identifier's own segment (T030's
    ``identifier_slug_segment``) is made up only of characters ``slugify()``
    strips, so no local address can be derived from it. Fatal rather than set
    aside like a concept's own ``EMPTY_SLUG``: a concept missing its slug is one
    record the rest of the file can still import around, but without a
    resolvable vocabulary there is nothing for the rest of the file to import
    into. ``VOCABULARY_NAME_UNUSABLE`` (fix cycle 4, FR-014, decisions.md D49)
    names a vocabulary this run is *creating* whose only published name is
    longer than the field can store: a matched scheme keeps whatever name it
    already held (``VALUE_TOO_LONG``, a set-aside), but a created one has no
    earlier name to fall back to, and writing it anyway leaves a row
    ``full_clean()`` immediately refuses — the same reasoning
    ``VOCABULARY_SLUG_UNUSABLE`` already gives for an unusable identifier,
    applied to the other field nothing else in the file can supply on the
    vocabulary's behalf. ``VOCABULARY_RECORD_INVALID`` (fix cycle 5, CORR-401/
    SEC-402, decisions.md D57) names a *matched* scheme whose write itself
    fails the model's own validation for a reason the published file did not
    cause — a stored value written out of band, or a configured language later
    dropped from ``settings.LANGUAGES``. Without a resolved vocabulary the rest
    of the file has nothing to import into, the same reasoning
    ``VOCABULARY_SLUG_UNUSABLE`` gives when a slug cannot even be minted;
    unlike that reason, the specific field named — a slug or something else —
    is reported separately, as a :class:`SetAsideReason` where one exists
    (``STORED_SLUG_INVALID``) rather than folded into this fatal's own message.
    ``VOCABULARY_NAME_UNPUBLISHED`` (fix cycle 6, CORR-504, decisions.md D68)
    names a *created* scheme with no ``skos:prefLabel`` this application can
    store, in any language — distinct from ``VOCABULARY_NAME_UNUSABLE``, whose
    own message names a published value that is too long, which is false both
    when nothing was published at all and when everything published in every
    language was empty or whitespace-only (T059/T061, SEC-603/CORR-603,
    decisions.md D69/D71: the empty-literal case is this same reason, not a
    second one, because T059's own rule already makes the two indistinguishable
    at the point a name is selected).
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
        """The translatable, named-placeholder message template for this reason.

        Every template declares ``%(subject)s``, the same shape
        :class:`SetAsideReason.template` uses (Article XII).
        """
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
    """One reason a run failed outright, with what it was and why (FR-004/FR-015).

    The fatal counterpart of :class:`SetAsideEntry`, with the same shape —
    ``subject`` names the record or file at fault, ``params`` carries whatever
    else the reason's template needs — kept as a distinct type because a
    fatal finding is never one of :class:`SetAsideReason`'s reasons
    (decisions.md's report.py docstring: fatal findings "are not part of
    this vocabulary").
    """

    reason: FatalReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """This entry's message in the caller's active language (Article XII)."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


class NormalizedReason(TextChoices):
    """The closed vocabulary of predicates this import stores under a different
    model field than the one the file itself asserted (T021, FR-009, decisions.md D24).

    Deliberately separate from :class:`SetAsideReason`: every set-aside entry
    names a value that was *not* stored; every entry here names one that
    *was*, just not verbatim under the source's own predicate. Article XI's
    "never applied silently" reaches both — a value that made it in under a
    different name still needs to be visible as a normalisation, not only a
    value that did not make it in at all.

    ``LANGUAGE_SUBSTITUTION`` (T003, FR-006, decisions.md D8/research.md R4)
    names a value stored under a configured language other than the tag it
    was published under — a variant match one axis over from
    ``FOREIGN_DEFINITION``'s predicate substitution: ``%(language)s`` carries
    the published tag, identically to :attr:`SetAsideReason.UNCONFIGURED_LANGUAGE`,
    and ``%(kept_as)s`` the configured language it was stored under.
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
        """The translatable, named-placeholder message template for this reason.

        Every template declares ``%(subject)s``, the same shape
        :class:`SetAsideReason.template` uses (Article XII).
        """
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
    """One value this import stored under a predicate other than the one the file asserted
    (FR-009/FR-015), with what it was and why. The normalised counterpart of
    :class:`SetAsideEntry`, with the same shape — ``subject`` names the record at
    fault, ``params`` carries whatever else the reason's template needs — but kept as
    a distinct type because a normalised value is never one of :class:`SetAsideReason`'s
    reasons: it *was* stored.
    """

    reason: NormalizedReason
    subject: str
    params: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """This entry's message in the caller's active language (Article XII)."""
        return str(self.reason.template) % _render_params(self.subject, self.params)


@dataclass
class ImportReport:
    """The structured outcome of one import run (FR-015, decisions.md D7).

    Six buckets, each a plain list a caller reads directly rather than parsing:
    :attr:`created` and :attr:`updated` hold the URIs of records the run wrote,
    :attr:`set_aside` holds a :class:`SetAsideEntry` per value the run could not
    store, :attr:`absent_from_source` holds the URIs of records the file no
    longer mentions (FR-013) — left untouched, only named — :attr:`normalized`
    holds a :class:`NormalizedEntry` per value the run *did* store, but under a
    different predicate than the one the file asserted (T021, FR-009), and
    :attr:`fatal` holds a :class:`FatalFinding` per reason the whole run was
    refused (FR-004): non-empty only on a failed run, and always empty on one
    that returned successfully.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    set_aside: list[SetAsideEntry] = field(default_factory=list)
    absent_from_source: list[str] = field(default_factory=list)
    normalized: list[NormalizedEntry] = field(default_factory=list)
    fatal: list[FatalFinding] = field(default_factory=list)

    def add_created(self, subject: str) -> None:
        """Record that ``subject`` was created by this run."""
        self.created.append(subject)

    def add_updated(self, subject: str) -> None:
        """Record that ``subject`` was updated by this run."""
        self.updated.append(subject)

    def add_absent_from_source(self, subject: str) -> None:
        """Record that ``subject`` exists here but is no longer in the source (FR-013)."""
        self.absent_from_source.append(subject)

    def add_set_aside(
        self, reason: SetAsideReason, subject: str, **params: str
    ) -> None:
        """Record that ``subject`` was not stored, for ``reason``, with any extra ``params``
        its message template needs."""
        self.set_aside.append(
            SetAsideEntry(reason=reason, subject=subject, params=params)
        )

    def add_normalized(
        self, reason: NormalizedReason, subject: str, **params: str
    ) -> None:
        """Record that ``subject`` was stored under a predicate other than the one the
        file asserted, for ``reason``, with any extra ``params`` its message template
        needs (T021, FR-009). The value *is* stored — this is visibility, not a refusal,
        so it is tracked apart from :attr:`set_aside`."""
        self.normalized.append(
            NormalizedEntry(reason=reason, subject=subject, params=params)
        )

    def add_fatal(self, reason: FatalReason, subject: str, **params: str) -> None:
        """Record that ``subject`` is why the whole run was refused, for ``reason``, with any
        extra ``params`` its message template needs (FR-004). A run with anything in
        :attr:`fatal` raises rather than returning; the caller reads this bucket from the
        raised exception, not from a normal return value."""
        self.fatal.append(FatalFinding(reason=reason, subject=subject, params=params))

    def set_aside_by_reason(self) -> dict[SetAsideReason, list[SetAsideEntry]]:
        """Group :attr:`set_aside` entries by reason, for a curator-facing count per reason
        (#51) without parsing any rendered message."""
        grouped: dict[SetAsideReason, list[SetAsideEntry]] = {}
        for entry in self.set_aside:
            grouped.setdefault(entry.reason, []).append(entry)
        return grouped

    #: The :class:`SetAsideReason` members :meth:`language_account` folds over
    #: (T004, FR-008, decisions.md D14) — explicit, not "carries a ``language``
    #: param": :attr:`SetAsideReason.SURPLUS_PREFERRED_LABEL` carries one too,
    #: and its language is a configured code the site already holds, not a
    #: published tag configuring something would recover.
    _LANGUAGE_ACCOUNT_REASONS = frozenset(
        {SetAsideReason.UNCONFIGURED_LANGUAGE, SetAsideReason.VARIANT_NOT_KEPT}
    )

    def language_account(self) -> dict[str, int]:
        """How many values were not stored for a language reason, broken down by
        the published language they carried (FR-008, research.md R3).

        A fold over :attr:`set_aside`, not a field accumulated beside it, so it
        can never disagree with the entries a caller reads directly. Both
        reasons folded here put the *published* tag under ``params["language"]``
        (T022), so a contest loser published ``en-us`` is counted under
        ``en-us``, never under the configured language it lost to. Present and
        empty — never absent — after a run that left nothing behind, so a
        caller never has to distinguish "clean run" from "feature absent".

        Folded case-insensitively (CORR-003/SEC-003, decisions.md D34): FR-001
        makes matching case-insensitive throughout, so ``PT-br`` and ``pt-BR``
        are one recoverable language, not two — a curator ranking by what
        configuring a language would recover must not have its vote split by
        a spelling difference RFC 5646 itself calls meaningless. The first
        published spelling seen (a run's :attr:`set_aside` order is
        deterministic) is kept as the display key.
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
