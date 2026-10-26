"""URL configuration for the concept autocomplete endpoint."""

from django.urls import path

from .views import ConceptAutocompleteView

app_name = "controlled_vocabularies"

urlpatterns = [
    path("concepts/", ConceptAutocompleteView.as_view(), name="concept-autocomplete"),
]
