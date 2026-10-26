"""Filtersets carrying the search, sort and facets of the browsing front end's list pages."""

from collections import Counter
from dataclasses import dataclass

import django_filters
from django import forms
from django.db.models import F
from django.db.models.functions import Lower
from django.utils.translation import get_language, get_language_info
from django.utils.translation import gettext_lazy as _
from mvp.filters import SearchFilter, SortFilter

from controlled_vocabularies.models import ConceptScheme, Record
from controlled_vocabularies.ui.rows import PropertyRows, PublicationDetails

__all__ = [
    "FACETS",
    "LICENCE_NAMES",
    "MAX_SEARCH_WORDS",
    "ConceptFilter",
    "CountedCheckboxes",
    "Profile",
    "VocabularyFilter",
    "language_name",
    "licence_name",
]

# Far above any real search, because dropping words from an OR search drops matches. The bound
# exists because the search builds one condition per word, and past roughly 400 words the
# expression exceeds SQLite's parser depth limit (django-mvp#281).
MAX_SEARCH_WORDS = 100


#: Short names for the licences vocabularies most often give, keyed by their address.
LICENCE_NAMES = {
    "https://creativecommons.org/licenses/by/4.0/": "CC BY 4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/": "CC BY-SA 4.0",
    "https://creativecommons.org/licenses/by-nd/4.0/": "CC BY-ND 4.0",
    "https://creativecommons.org/licenses/by-nc/4.0/": "CC BY-NC 4.0",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/": "CC BY-NC-SA 4.0",
    "https://creativecommons.org/licenses/by-nc-nd/4.0/": "CC BY-NC-ND 4.0",
    "https://creativecommons.org/publicdomain/zero/1.0/": "CC0 1.0",
}

#: The facets of the list of vocabularies, in the order the filter panel draws them.
FACETS = ("publisher", "license", "language")


def licence_name(value: str) -> str:
    """Return a licence's short name, or the value itself when it has none.

    The address is matched over either scheme and with or without its trailing slash, the
    forms a publisher is likely to give.

    Args:
        value: The licence as the vocabulary gives it.

    Returns:
        The short name, or ``value`` unchanged.
    """
    address = value.strip().replace("http://", "https://", 1).rstrip("/") + "/"
    return LICENCE_NAMES.get(address, value)


def language_name(code: str) -> str:
    """Return a language's name in the reading language.

    Args:
        code: The language code.

    Returns:
        The language's name, or the code when Django does not know it.
    """
    try:
        return str(get_language_info(code)["name_translated"])
    except KeyError:
        return code


class CountedCheckboxes(forms.CheckboxSelectMultiple):
    """Checkboxes that show beside each option how many records it would match.

    The count is added when the option is drawn and is not part of the choice's label, so an
    applied filter elsewhere on the page is named without it.
    """

    def __init__(self, *args, **kwargs):
        """Start with no counts, which draws each option without one."""
        super().__init__(*args, **kwargs)
        self.counts: dict[str, int] | None = None

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        """Add the option's count to its label.

        Args:
            name: The field's name.
            value: The option's value.
            label: The option's label.
            selected: Whether the option is chosen.
            index: The option's position.
            subindex: The option's position within its group.
            attrs: The option's attributes.

        Returns:
            The option's context.
        """
        if self.counts is not None:
            label = f"{label} ({self.counts.get(value, 0)})"
        return super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )


@dataclass(frozen=True)
class Profile:
    """What the list of vocabularies searches and facets on, read from one vocabulary.

    Attributes:
        publisher: The publisher, or an empty string.
        license: The licence, or an empty string.
        language: The default language.
        text: The lower-cased name and description searched for words.
    """

    publisher: str
    license: str
    language: str
    text: str

    @classmethod
    def of(cls, scheme: ConceptScheme) -> "Profile":
        """Read a vocabulary's profile.

        Args:
            scheme: The vocabulary.

        Returns:
            Its profile.
        """
        details = PublicationDetails.of(scheme)
        descriptions = PropertyRows.in_reading_language(
            scheme.values("dcterms:description"),
            get_language() or "",
            scheme.default_language,
        )
        words = [scheme.display_label(), *(str(d["@value"]) for d in descriptions)]
        return cls(
            publisher=scheme.first_value("dcterms:publisher"),
            license=details.license,
            language=scheme.default_language,
            text=" ".join(words).lower(),
        )


class VocabularySearch(SearchFilter):
    """Match any word of the term against a vocabulary's name and description."""

    def filter(self, qs, value):
        """Keep the vocabularies whose profile text holds some word of ``value``.

        Args:
            qs: The vocabularies to narrow.
            value: The search term.

        Returns:
            The matching vocabularies, or ``qs`` unchanged for an empty term.
        """
        words = (value or "").lower().split()[: self.max_words]
        if not words:
            return qs
        profiles = self.parent.profiles
        return qs.filter(
            pk__in=[
                pk
                for pk, profile in profiles.items()
                if any(word in profile.text for word in words)
            ]
        )


class VocabularyFilter(django_filters.FilterSet):
    """The search, sort and facets of the list of vocabularies.

    A site holds few vocabularies, so every facet is computed in Python over all of
    them. Each facet offers the values the site's vocabularies carry, and is left out
    when fewer than two vocabularies differ on it. The view annotates ``concept_count``
    and ``modified`` onto the queryset.
    """

    q = VocabularySearch(fields=[], max_words=MAX_SEARCH_WORDS)
    publisher = django_filters.MultipleChoiceFilter(
        label=_("Publisher"), widget=CountedCheckboxes, method="filter_facet"
    )
    license = django_filters.MultipleChoiceFilter(
        label=_("Licence"), widget=CountedCheckboxes, method="filter_facet"
    )
    language = django_filters.MultipleChoiceFilter(
        label=_("Language"), widget=CountedCheckboxes, method="filter_facet"
    )
    # The option keys are the ones the address has always carried, so bookmarked sorts keep
    # working. `pk` makes each order total, so equal names cannot swap between pages.
    o = SortFilter(
        options=[
            ("name_asc", _("Name (A-Z)"), [Lower("pref_label"), "pk"]),
            ("name_desc", _("Name (Z-A)"), [Lower("pref_label").desc(), "-pk"]),
            (
                "concepts_desc",
                _("Most concepts"),
                [F("concept_count").desc(), Lower("pref_label"), "pk"],
            ),
            (
                "modified_desc",
                _("Recently updated"),
                [F("modified").desc(nulls_last=True), Lower("pref_label"), "pk"],
            ),
        ]
    )

    class Meta:
        model = ConceptScheme
        fields: list[str] = []

    def __init__(self, *args, request=None, **kwargs):
        """Offer each facet the values vocabularies carry, and drop those that cannot narrow."""
        super().__init__(*args, request=request, **kwargs)
        self.profiles = {
            scheme.pk: Profile.of(scheme) for scheme in ConceptScheme.objects.all()
        }
        self.offer_values("publisher", str)
        self.offer_values("license", licence_name)
        self.offer_values("language", language_name)

    def offer_values(self, name: str, label) -> None:
        """Make a facet's choices the values vocabularies carry, most common first.

        A facet with fewer than two values is removed, because it cannot narrow the list.

        Args:
            name: The facet, which is also the profile field it reads.
            label: Turns a value into the text its option shows.
        """
        counts = Counter(
            getattr(profile, name)
            for profile in self.profiles.values()
            if getattr(profile, name)
        )
        values = sorted(counts, key=lambda value: (-counts[value], value))
        if len(values) < 2:
            del self.filters[name]
        else:
            self.filters[name].extra["choices"] = [
                (value, label(value)) for value in values
            ]

    def count_facets(self) -> None:
        """Set beside each facet option how many vocabularies choosing it would leave.

        Each facet is counted over what the search and the other facets leave, and not over
        its own choice, so ticking a second option shows what it would add. Call it once
        the filterset has filtered, so the form's values are known.
        """
        chosen = getattr(self.form, "cleaned_data", {})
        for name in FACETS:
            if name not in self.filters:
                continue
            queryset = self.queryset
            for other, a_filter in self.filters.items():
                if other not in (name, "o") and other in chosen:
                    queryset = a_filter.filter(queryset, chosen[other])
            remaining = set(queryset.values_list("pk", flat=True))
            self.form.fields[name].widget.counts = dict(
                Counter(
                    getattr(profile, name)
                    for pk, profile in self.profiles.items()
                    if pk in remaining
                )
            )

    def filter_facet(self, queryset, name, value):
        """Keep the vocabularies whose value for the facet is any of the chosen ones.

        Args:
            queryset: The vocabularies to narrow.
            name: The facet's name.
            value: The chosen options.

        Returns:
            The vocabularies matching any chosen option.
        """
        return queryset.filter(
            pk__in=[
                pk
                for pk, profile in self.profiles.items()
                if getattr(profile, name) in value
            ]
        )


class ConceptFilter(django_filters.FilterSet):
    """The search and sort of the concepts on a vocabulary's page."""

    # `search_text` reaches every label: other languages, alternative and hidden. Notes
    # are left out on purpose. A hidden label is matched but never shown.
    q = SearchFilter(fields=["pref_label", "search_text"])
    o = SortFilter(
        options=[
            ("label_asc", _("Label (A-Z)"), [Lower("pref_label"), "pk"]),
            ("label_desc", _("Label (Z-A)"), [Lower("pref_label").desc(), "-pk"]),
        ]
    )

    class Meta:
        model = Record
        fields: list[str] = []
