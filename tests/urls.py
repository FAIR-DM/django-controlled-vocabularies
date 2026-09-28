"""Root URL configuration for the test project."""

from django.contrib import admin
from django.urls import include, path

# Both apps mount under non-root prefixes, so a hard-coded path fails instead of
# matching by accident. The ui prefix is the path CONTROLLED_VOCABULARIES_BASE_URI
# names, or the controlled_vocabularies.ui.W001 check fires (FS-014).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("widget/", include("controlled_vocabularies.urls")),
    path("vocabularies/", include("controlled_vocabularies.ui.urls")),
]
