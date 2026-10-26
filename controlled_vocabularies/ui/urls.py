"""URL configuration for the opt-in vocabulary-browsing front end."""

from django.urls import path

from .views import (
    CollectionDetailView,
    ConceptDetailView,
    VocabularyDetailView,
    VocabularyListView,
)

# Distinct from the core app's namespace, so a project can mount both without shadowed reverses.
app_name = "controlled_vocabularies_ui"

urlpatterns = [
    path("", VocabularyListView.as_view(), name="vocabulary-list"),
    # <str:slug>, not <slug:slug>: slugs allow unicode and Django's slug converter is ASCII-only, so a
    # record named in a non-Latin script would 404 on its own page.
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
