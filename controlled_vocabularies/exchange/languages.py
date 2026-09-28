"""Resolving a published language tag to a configured language (FS-007)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class LanguageResolution:
    """One published tag's resolution against the site's configured languages.

    ``configured_language`` is returned exactly as declared in ``settings.LANGUAGES``.
    Case folding is only for comparison, because a project declaring ``en-GB`` that
    received ``en-gb`` back would fail ``ConceptLabel.clean`` on every write.

    Attributes:
        published_tag: The language tag as the file published it.
        configured_language: The configured language it resolved to, or ``None`` when
            it shares a base language with none of them.
    """

    published_tag: str
    configured_language: str | None

    @property
    def is_exact(self) -> bool:
        """Whether ``configured_language`` equals ``published_tag``, ignoring case."""
        return (
            self.configured_language is not None
            and self.configured_language.lower() == self.published_tag.lower()
        )


class LanguageMatcher:
    """Resolve published language tags against the site's configured languages.

    Immutable once constructed.

    Args:
        configured_languages: The configured language codes, in a deterministic order.
            Never a ``set``: its iteration order varies per process and would make
            :meth:`resolve` non-deterministic for ``zh-hans``/``zh-hant``, which Django's
            default languages both contain.
        tag_counts: How often each published tag appears across the vocabulary's concept
            ``skos:prefLabel`` values, the population :meth:`resolve_winner` ranks by.
    """

    def __init__(
        self, configured_languages: Sequence[str], tag_counts: Mapping[str, int]
    ) -> None:
        self._configured_languages: tuple[str, ...] = tuple(configured_languages)
        self._tag_counts: dict[str, int] = dict(tag_counts)

    @classmethod
    def from_settings(cls, tag_counts: Mapping[str, int]) -> LanguageMatcher:
        """Build a matcher for the site's own ``settings.LANGUAGES``.

        Args:
            tag_counts: How often each published tag appears in the vocabulary.

        Returns:
            A matcher over the codes in ``settings.LANGUAGES``.
        """
        return cls([code for code, _label in settings.LANGUAGES], tag_counts)

    # Matching is plain string comparison, not django's get_supported_language_variant:
    # that refuses any language Django ships no catalog for, even one in settings.LANGUAGES.
    def resolve(self, published_tag: str) -> LanguageResolution:
        """Resolve ``published_tag`` to one configured language, or none.

        An exact match always wins. Otherwise, among the configured languages sharing the
        tag's base language, the least specific one wins, and equally specific ones
        resolve to the lowest code. Comparison is case-insensitive throughout.

        Args:
            published_tag: The language tag as the file published it.

        Returns:
            The resolution, whose ``configured_language`` is ``None``
            when no configured language shares the tag's base language.
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
        """Pick the one variant that fills a configured language's slot.

        An exact match wins first. Otherwise the tag published most often wins, and ties
        (including no predominance data at all) break lexicographically by tag. It lives
        here so ``Concept.label`` and the importer's surplus report get the same answer
        for the same candidates.

        Args:
            configured_language: The configured language the candidates compete for.
            candidates: The ``(published_tag, value)`` pairs already resolved to
                ``configured_language`` through :meth:`resolve`.

        Returns:
            The winning pair, then every
            other candidate.
        """
        candidates = list(candidates)
        config_lower = configured_language.lower()

        def sort_key(pair: tuple[str, str]) -> tuple[bool, int, str, str]:
            """Rank a candidate: exact match first, then predominance, then tag, then value."""
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
