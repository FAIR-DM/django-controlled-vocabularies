"""URL configuration for the demo project."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from demo.views import TermPickerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Sign-in for the curator's pages. The package adds none of its own; a project provides it.
    path("accounts/", include("django.contrib.auth.urls")),
    path("browse/", include("controlled_vocabularies.ui.urls")),
    # The endpoint behind the concept search control, which the package's system checks warn about
    # when a project never mounts it.
    path("vocabularies/", include("controlled_vocabularies.urls")),
    # django-mvp's footer menu links to a view named "home". Without one, django-flex-menus logs a
    # reversal failure on every render, and the root address returns 404.
    # The endpoint the open page listens on to reload itself after a change.
    path("__reload__/", include("django_browser_reload.urls")),
    path("term-picker/", TermPickerView.as_view(), name="term-picker"),
    path(
        "",
        RedirectView.as_view(pattern_name="controlled_vocabularies_ui:vocabulary-list"),
        name="home",
    ),
]
