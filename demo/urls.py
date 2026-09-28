"""URL configuration for the demo project."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("browse/", include("controlled_vocabularies.ui.urls")),
    # The endpoint behind the concept search control, which the package's system checks warn about
    # when a project never mounts it.
    path("vocabularies/", include("controlled_vocabularies.urls")),
    # django-mvp's footer menu links to a view named "home". Without one, django-flex-menus logs a
    # reversal failure on every render, and the root address returns 404.
    path(
        "",
        RedirectView.as_view(pattern_name="controlled_vocabularies_ui:vocabulary-list"),
        name="home",
    ),
]
