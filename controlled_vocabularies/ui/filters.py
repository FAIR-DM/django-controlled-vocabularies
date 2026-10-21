"""Filtersets carrying the search and sort of the browsing front end's list pages."""

import django_filters
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from mvp.filters import SearchFilter, SortFilter

from controlled_vocabularies.models import Concept, ConceptScheme

# Far above any real search, because dropping words from an OR search drops matches. The bound
# exists because the search builds one condition per word, and past roughly 400 words the
# expression exceeds SQLite's parser depth limit (django-mvp#281).
MAX_SEARCH_WORDS = 100


class VocabularyFilter(django_filters.FilterSet):
    """The search and sort of the list of vocabularies."""

    q = SearchFilter(fields=["name", "description"], max_words=MAX_SEARCH_WORDS)
    # The option keys are the ones the address has always carried, so bookmarked sorts keep
    # working. `pk` makes each order total, so equal names cannot swap between pages.
    o = SortFilter(
        options=[
            ("name_asc", _("Name (A-Z)"), [Lower("name"), "pk"]),
            ("name_desc", _("Name (Z-A)"), [Lower("name").desc(), "-pk"]),
        ]
    )

    class Meta:
        model = ConceptScheme
        fields: list[str] = []


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
