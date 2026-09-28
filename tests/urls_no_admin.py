"""Root URL configuration for tests.settings_no_admin."""

from django.urls import include, path

# tests/urls.py mounts admin.site.urls, and resolving any route walks it, importing
# django.contrib.admin and defeating the no-admin proof (FS-012).
urlpatterns = [
    path("vocabularies/", include("controlled_vocabularies.urls")),
]
