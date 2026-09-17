"""Resolving a published language tag to a configured language (FS-007 US0).

One class owns this subject (constitution Article XV) rather than a handful of
module-level functions beside ``skos.py``'s own ``configured_language_codes()`` —
the plan's "eight comparisons" all read through :class:`LanguageMatcher` once the
stories after this one wire them up. This module imports nothing from ``rdflib``:
the graph traversal that produces a predominance ranking stays behind
:class:`~controlled_vocabularies.exchange.skos.SkosGraph`, this codebase's RDF
boundary (``research.md`` R2), so a matcher here is testable from a plain dict.

Django's own ``django.utils.translation.get_supported_language_variant`` was
measured and rejected (``research.md`` R1): it refuses any language Django ships
no translation catalog for, including one the project explicitly declares in
``settings.LANGUAGES`` — which would make this feature silently useless for the
research vocabularies it exists to serve. Nothing here consults a translation
catalog; matching is plain string comparison against the configured codes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class LanguageResolution:
    """One published tag's resolution against the site's configured languages (T001).

    ``configured_language`` is ``None`` when ``published_tag`` shares no base
    language with any configured language (FR-001). Otherwise it is the winning
    code exactly as declared in ``settings.LANGUAGES`` — case folding is for
    comparison only, never for the returned value, because a project declaring
    ``en-GB`` that received the normalised ``en-gb`` back would raise
    ``ValidationError`` from ``ConceptLabel.clean`` on every write.

    ``is_exact`` is derived from ``published_tag`` and ``configured_language``
    rather than stored alongside them, so the pair can never disagree with
    itself.
    """

    published_tag: str
    configured_language: str | None

    @property
    def is_exact(self) -> bool:
        """Whether ``configured_language`` matches ``published_tag`` verbatim, case-insensitively."""
        return (
            self.configured_language is not None
            and self.configured_language.lower() == self.published_tag.lower()
        )


class LanguageMatcher:
    """Resolves published language tags against the site's configured languages
    (FR-001, FR-002, FR-003; decisions.md D3, D5, D15).

    Immutable once constructed: ``configured_languages`` is the deterministically
    ordered sequence of codes the site holds — never a ``set``, whose iteration
    order varies per process and would make :meth:`resolve` non-deterministic on
    the one ambiguous base Django's own 99-language default contains,
    ``zh-hans``/``zh-hant`` (D15). ``tag_counts`` is how often each published tag
    appears across the vocabulary's own concept nodes' ``skos:prefLabel`` values
    (``research.md`` R2) — the population :meth:`resolve_winner` settles a contest
    over.
    """

    def __init__(
        self, configured_languages: Sequence[str], tag_counts: Mapping[str, int]
    ) -> None:
        self._configured_languages: tuple[str, ...] = tuple(configured_languages)
        self._tag_counts: dict[str, int] = dict(tag_counts)

    @classmethod
    def from_settings(cls, tag_counts: Mapping[str, int]) -> LanguageMatcher:
        """Build a matcher for the site's own ``settings.LANGUAGES`` (research.md R2).

        Replaces ``skos.py``'s ``configured_language_codes()`` as the one place
        that reads the site's configured languages for this feature's purposes.
        """
        return cls([code for code, _label in settings.LANGUAGES], tag_counts)

    def resolve(self, published_tag: str) -> LanguageResolution:
        """Resolve ``published_tag`` to one configured language, or none (FR-001/FR-002).

        An exact match always wins and is never displaced by a variant (FR-002).
        Otherwise, among the configured languages sharing ``published_tag``'s base
        language, the least specific one receives it (D3); where several are
        equally specific, the lower code wins, ordered lexicographically over the
        deterministically ordered ``configured_languages`` sequence given at
        construction, never over a ``set`` (D15). Comparison is case-insensitive
        throughout.
        """
        tag_lower = published_tag.lower()
        base = tag_lower.split("-", 1)[0]
        candidates: list[str] = []
        for code in self._configured_languages:
            code_lower = code.lower()
            if code_lower == tag_lower:
                return LanguageResolution(published_tag, code)
            if code_lower.split("-", 1)[0] == base:
                candidates.append(code)
        if not candidates:
            return LanguageResolution(published_tag, None)
        candidates.sort(key=lambda code: (code.lower().count("-"), code.lower()))
        return LanguageResolution(published_tag, candidates[0])

    def resolve_winner(
        self, configured_language: str, candidates: Sequence[tuple[str, str]]
    ) -> tuple[tuple[str, str], list[tuple[str, str]]]:
        """The one winner among several published variants filling one configured
        language's slot, and everyone else (T021, FR-002, FR-003; S3R SPEC-001).

        ``candidates`` are the ``(published_tag, value)`` pairs a caller has
        already resolved to ``configured_language`` via :meth:`resolve`. Exact
        match wins first and always (FR-002); otherwise the tag this matcher's
        ``tag_counts`` shows publishing most often wins (FR-003); ties — equal
        predominance, or no predominance data at all — break lexicographically by
        tag (FR-003, D5). Lives here rather than in the importer because two call
        sites need the identical answer for the identical candidate set —
        ``preferred_label_in`` (``Concept.label``) and ``import_labels`` (the
        surplus report) — and today they agree only by the coincidence that both
        happen to sort the same way.
        """
        candidates = list(candidates)
        config_lower = configured_language.lower()

        def sort_key(pair: tuple[str, str]) -> tuple[bool, int, str, str]:
            tag, value = pair
            tag_lower = tag.lower()
            return (
                tag_lower != config_lower,
                -self._tag_counts.get(tag_lower, 0),
                tag_lower,
                value,
            )

        ranked = sorted(
            range(len(candidates)), key=lambda index: sort_key(candidates[index])
        )
        winner_index = ranked[0]
        winner = candidates[winner_index]
        losers = [
            pair for index, pair in enumerate(candidates) if index != winner_index
        ]
        return winner, losers
