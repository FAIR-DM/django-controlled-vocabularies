"""URL configuration for the demo project."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from mvp.mounted import mount

from demo.mounted import docs

urlpatterns = [
    path("admin/", admin.site.urls),
    path("browse/", include("controlled_vocabularies.ui.urls")),
    # The endpoint behind the concept search control, which the package's system checks warn about
    # when a project never mounts it.
    path("vocabularies/", include("controlled_vocabularies.urls")),
    # The endpoint the open page listens on to reload itself after a change.
    path("__reload__/", include("django_browser_reload.urls")),
    # The package's documentation, as the demo's main app: its contents are the sidebar on every
    # page, the browsing pages included.
    mount("docs/", docs, main=True),
    # django-mvp's footer menu links to a view named "home". Without one, django-flex-menus logs a
    # reversal failure on every render, and the root address returns 404.
    path("", RedirectView.as_view(pattern_name="docs:front_page"), name="home"),
]
