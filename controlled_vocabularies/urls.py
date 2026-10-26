"""URL configuration for the concept and predicate autocomplete endpoints."""

from django.urls import path

from .views import ConceptAutocompleteView, PredicateAutocompleteView

app_name = "controlled_vocabularies"

urlpatterns = [
    path("concepts/", ConceptAutocompleteView.as_view(), name="concept-autocomplete"),
    path(
        "predicates/",
        PredicateAutocompleteView.as_view(),
        name="predicate-autocomplete",
    ),
]
