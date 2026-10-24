"""URL configuration for the opt-in vocabulary-browsing front end."""

from django.urls import path

from .views import (
    CollectionDetailView,
    ConceptDetailView,
    VocabularyCreateView,
    VocabularyDeleteView,
    VocabularyDetailView,
    VocabularyListView,
    VocabularyUpdateView,
)

# Distinct from the core app's namespace, so a project can mount both without shadowed reverses.
app_name = "controlled_vocabularies_ui"

urlpatterns = [
    path("", VocabularyListView.as_view(), name="vocabulary-list"),
    # The curator's pages sit behind a "-" segment, which no generated slug can be, so they never
    # shadow a vocabulary or a concept whose slug is "new", "edit" or "delete".
    path("-/new/", VocabularyCreateView.as_view(), name="vocabulary-create"),
    path(
        "<str:slug>/-/edit/", VocabularyUpdateView.as_view(), name="vocabulary-update"
    ),
    path(
        "<str:slug>/-/delete/", VocabularyDeleteView.as_view(), name="vocabulary-delete"
    ),
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
