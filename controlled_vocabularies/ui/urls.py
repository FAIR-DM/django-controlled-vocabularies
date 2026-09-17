"""URL configuration for the opt-in vocabulary-browsing front end (013-find-a-vocabulary T006,
015-read-single-record T000).

``app_name`` is distinct from the core app's own ``controlled_vocabularies`` namespace, so a
project can mount both without either shadowing the other's reverses (plan.md Key design
decisions #4). Views are imported relatively, staying inside this app's own package.
"""

from django.urls import path

from .views import (
    CollectionDetailView,
    ConceptDetailView,
    VocabularyDetailView,
    VocabularyListView,
)

app_name = "controlled_vocabularies_ui"

urlpatterns = [
    path("", VocabularyListView.as_view(), name="vocabulary-list"),
    # <str:slug>, not <slug:slug>: the models slugify with allow_unicode=True, and Django's
    # slug converter matches ASCII only, so a record named in a non-Latin script would 404
    # on its own page under the obvious converter. The collection route is declared before
    # the concept route because it is the more specific pattern (three segments to two),
    # and both before the single-segment vocabulary route below — the three cannot in fact
    # collide, since each has a different segment count, but declaring the more specific
    # pattern first is the habit that stays correct when a fourth shape arrives (plan.md
    # Key design decision #2).
    path(
        "<str:slug>/collection/<str:collection_slug>/",
        CollectionDetailView.as_view(),
        name="collection-detail",
    ),
    path(
        "<str:slug>/<str:concept_slug>/",
        ConceptDetailView.as_view(),
        name="concept-detail",
    ),
    path("<str:slug>/", VocabularyDetailView.as_view(), name="vocabulary-detail"),
]
