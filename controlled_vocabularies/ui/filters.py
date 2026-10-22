"""Filtersets carrying the search, sort and facets of the browsing front end's list pages."""

import django_filters
from django import forms
from django.conf import settings
from django.db.models import Count, F, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.utils.translation import get_language_info
from django.utils.translation import gettext_lazy as _
from mvp.filters import SearchFilter, SortFilter

from controlled_vocabularies.models import Concept, ConceptScheme

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
FACETS = ("publisher", "license", "language", "source")


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


def language_expression():
    """Return the expression for a vocabulary's effective default language.

    Returns:
        The vocabulary's own default language, or ``LANGUAGE_CODE`` when it gives none.
    """
    return Coalesce(
        NullIf("default_language", Value("")), Value(settings.LANGUAGE_CODE)
    )


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


class VocabularyFilter(django_filters.FilterSet):
    """The search, sort and facets of the list of vocabularies.

    Each facet offers the values the site's vocabularies carry, and is left out when
    fewer than two vocabularies differ on it. The view annotates ``concept_count`` and
    ``language`` onto the queryset.
    """

    q = SearchFilter(fields=["name", "description"], max_words=MAX_SEARCH_WORDS)
    publisher = django_filters.MultipleChoiceFilter(
        label=_("Publisher"), widget=CountedCheckboxes
    )
    license = django_filters.MultipleChoiceFilter(
        label=_("Licence"), widget=CountedCheckboxes
    )
    language = django_filters.MultipleChoiceFilter(
        label=_("Language"), widget=CountedCheckboxes
    )
    source = django_filters.MultipleChoiceFilter(
        label=_("Source"),
        widget=CountedCheckboxes,
        method="filter_source",
        choices=[("imported", _("Imported")), ("here", _("Held here"))],
    )
    # The option keys are the ones the address has always carried, so bookmarked sorts keep
    # working. `pk` makes each order total, so equal names cannot swap between pages.
    o = SortFilter(
        options=[
            ("name_asc", _("Name (A-Z)"), [Lower("name"), "pk"]),
            ("name_desc", _("Name (Z-A)"), [Lower("name").desc(), "-pk"]),
            (
                "concepts_desc",
                _("Most concepts"),
                [F("concept_count").desc(), Lower("name"), "pk"],
            ),
            (
                "modified_desc",
                _("Recently updated"),
                [F("modified").desc(nulls_last=True), Lower("name"), "pk"],
            ),
        ]
    )

    class Meta:
        model = ConceptScheme
        fields: list[str] = []

    def __init__(self, *args, request=None, **kwargs):
        """Offer each facet the values vocabularies carry, and drop those that cannot narrow."""
        super().__init__(*args, request=request, **kwargs)
        every = ConceptScheme.objects.annotate(language=language_expression())
        self.offer_values("publisher", every, str)
        self.offer_values("license", every, licence_name)
        self.offer_values("language", every, language_name)
        # Whether a vocabulary was imported decides whether it may be edited here, which is an
        # editor's concern only, as on the vocabulary's own page.
        user = getattr(request, "user", None)
        if user is None or not user.has_perm(
            "controlled_vocabularies.change_conceptscheme"
        ):
            del self.filters["source"]

    def offer_values(self, name: str, every, label) -> None:
        """Make a facet's choices the values vocabularies carry, most common first.

        A facet with fewer than two values is removed, because it cannot narrow the list.

        Args:
            name: The facet, which is also the field it reads.
            every: Every vocabulary, annotated as the facet needs.
            label: Turns a value into the text its option shows.
        """
        values = (
            every.exclude(**{name: ""})
            .order_by()
            .values(name)
            .annotate(vocabularies=Count("pk"))
            .order_by("-vocabularies", name)
            .values_list(name, flat=True)
        )
        choices = [(value, label(value)) for value in values]
        if len(choices) < 2:
            del self.filters[name]
        else:
            self.filters[name].extra["choices"] = choices

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
            remaining = ConceptScheme.objects.filter(
                pk__in=queryset.values("pk")
            ).annotate(language=language_expression())
            self.form.fields[name].widget.counts = (
                self.count_sources(remaining)
                if name == "source"
                else dict(
                    remaining.order_by()
                    .values(name)
                    .annotate(vocabularies=Count("pk"))
                    .values_list(name, "vocabularies")
                )
            )

    @staticmethod
    def count_sources(remaining) -> dict[str, int]:
        """Count the imported vocabularies and those held here.

        Args:
            remaining: The vocabularies to count.

        Returns:
            The count for each of the source facet's options.
        """
        imported = remaining.filter(static_uri__isnull=False).count()
        return {"imported": imported, "here": remaining.count() - imported}

    def filter_source(self, queryset, name, value):
        """Keep the imported vocabularies, those held here, or both.

        Args:
            queryset: The vocabularies to narrow.
            name: The facet's name.
            value: The chosen options.

        Returns:
            The vocabularies matching any chosen option.
        """
        if not value or set(value) == {"imported", "here"}:
            return queryset
        return queryset.filter(static_uri__isnull="imported" not in value)


class ConceptFilter(django_filters.FilterSet):
    """The search and sort of the concepts on a vocabulary's page.

    Sorts by ``resolved_label``, the label shown, which the view annotates onto its queryset.
    """

    # `labels__text` reaches every label: other languages, alternative and hidden. Notes are left out
    # on purpose. A hidden label is matched but never shown, since display reads only preferred labels.
    q = SearchFilter(fields=["label", "labels__text"])
    o = SortFilter(
        options=[
            ("label_asc", _("Label (A-Z)"), [Lower("resolved_label"), "pk"]),
            ("label_desc", _("Label (Z-A)"), [Lower("resolved_label").desc(), "-pk"]),
        ]
    )

    class Meta:
        model = Concept
        fields: list[str] = []
